"""服务端内置轻量 OpenAI 兼容大模型客户端与统一 AI 调度器。

支持功能：
1. 轻量异步 HTTPX 客户端，兼容所有 OpenAI 规范大模型接口（DeepSeek, Qwen, Moonshot, OpenAI, Ollama, vLLM 等）。
2. 支持打字机 SSE 流式调用与普通请求。
3. 统一调度器 dispatch_ai_request：
   - cloud 模式：直接在服务端调用配置的云端大模型，流式下发打字机数据；
   - local 模式：通过反向隧道穿透到本地电脑的 Ollama/沙箱/本地模型执行；
   - auto 模式：本地在线优先跑本地，本地离线平滑自动切换到云端模型，保障随时随地可用！
"""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx

from server.config import settings
from server.tunnel import WorkerOfflineError, WorkerRequestTimeoutError, tunnel_manager

logger = logging.getLogger("server.llm")


class ServerLLMService:
    """服务端内置大模型服务。"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str = "你是一个专业、耐心的 AI 助教与智能导师 LearnFlow Tutor，回答生动、清晰、循序渐进。",
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """向服务端配置的 OpenAI 兼容接口发起流式对话请求，逐 chunk yield 文本。"""
        base_url = settings.server_llm_base_url.rstrip("/")
        api_key = settings.server_llm_api_key
        target_model = model or settings.server_llm_model

        url = f"{base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        payload = {
            "model": target_model,
            "messages": payload_messages,
            "stream": True,
            "temperature": temperature,
        }

        client = self._get_client()
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    raise RuntimeError(f"上游 LLM 返回错误 HTTP {response.status_code}: {err_body.decode('utf-8', errors='ignore')}")

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data_json = json.loads(data_str)
                            choices = data_json.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except Exception:
                            continue
        except Exception as e:
            logger.error("云端服务端大模型请求异常: %s", e)
            raise e

    def extract_prompt_from_request(self, path: str, body: Any) -> tuple[str, list[dict[str, str]]]:
        """根据不同的前端请求路径解析用户提问与上下文。"""
        data = {}
        if isinstance(body, (bytes, bytearray)):
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                data = {}
        elif isinstance(body, str):
            try:
                data = json.loads(body)
            except Exception:
                data = {"message": body}
        elif isinstance(body, dict):
            data = body

        system_prompt = "你是 LearnFlow 智能学习导师。用生动通俗的语言讲解，支持 LaTeX 格式公式与 Markdown 排版。"
        messages = []

        # 1. 助教答疑 /api/courses/{id}/ask 或 /api/tutor/chat
        if "ask" in path or "chat" in path or "tutor" in path:
            question = data.get("question") or data.get("message") or data.get("content") or ""
            history = data.get("history") or []
            for h in history:
                if isinstance(h, dict) and "role" in h and "content" in h:
                    messages.append({"role": h["role"], "content": str(h["content"])})
            if question:
                messages.append({"role": "user", "content": str(question)})
            if not messages:
                messages.append({"role": "user", "content": "你好，请作为助教为我讲解当前知识点。"})

        # 2. 大纲生成 /api/courses/generate-outline 或 /api/courses/{id}/generate
        elif "generate" in path or "outline" in path:
            topic = data.get("topic") or "计算机与编程基础"
            level = data.get("level") or "初学者"
            chapter_count = data.get("chapter_count") or 5
            system_prompt = "你是一个资深教育专家与课程架构师，善于将复杂的知识体系拆解为层层递进、逻辑清晰的教学大纲。"
            messages.append({
                "role": "user",
                "content": f"请为主题为「{topic}」、面向难度「{level}」的学习者规划一门包含约 {chapter_count} 个章节的系统课程大纲，要求结构严密、通俗易懂。",
            })

        # 3. 错题解析 / 拍照答疑 /api/solve/snap 或 /api/banks/questions/{id}/ai-explain
        elif "solve" in path or "explain" in path:
            title = data.get("title") or data.get("question") or data.get("hint") or ""
            picked = data.get("picked") or []
            system_prompt = "你是一位擅长归纳总结解题技巧的特级名师，对各类经典考题提供循循善诱、直击要害的深度解析与思路拆解。"
            messages.append({
                "role": "user",
                "content": f"题目内容：{title}\n用户所选选项或疑问：{picked}\n请给出详尽透彻的题目剖析、正确答案推导过程与核心考点巩固。",
            })

        # 4. 思维导图 Agent / 章节修订
        elif "agent" in path or "revise" in path:
            instruction = data.get("instruction") or data.get("message") or "请根据上下文润色和补充内容。"
            content = data.get("content") or ""
            messages.append({
                "role": "user",
                "content": f"需要修改/扩充的内容：\n{content}\n\n修改要求：{instruction}",
            })

        else:
            msg_str = data.get("message") or data.get("content") or json.dumps(data, ensure_ascii=False)
            messages.append({"role": "user", "content": str(msg_str)})

        return system_prompt, messages

    async def stream_sse_response(self, path: str, body: Any) -> AsyncIterator[bytes]:
        """将云端大模型生成的流式内容包装为前端可直接消费的 LearnFlow 标准 SSE 格式。"""
        system_prompt, messages = self.extract_prompt_from_request(path, body)

        try:
            async for delta_text in self.stream_chat(messages, system_prompt=system_prompt):
                sse_frame = f"data: {json.dumps({'type': 'delta', 'text': delta_text}, ensure_ascii=False)}\n\n"
                yield sse_frame.encode("utf-8")

            # 正常完成帧
            yield b"data: {\"type\": \"done\"}\n\n"
        except Exception as e:
            err_msg = f"云端大模型服务调用失败: {e}"
            logger.error(err_msg)
            err_frame = f"data: {json.dumps({'type': 'error', 'detail': err_msg}, ensure_ascii=False)}\n\n"
            yield err_frame.encode("utf-8")


server_llm_service = ServerLLMService()


async def dispatch_ai_request(
    method: str,
    path: str,
    headers: Optional[dict[str, str]] = None,
    query_params: Optional[dict[str, Any]] = None,
    body: Any = None,
    timeout: float = 180.0,
) -> AsyncIterator[bytes]:
    """统一 AI 请求调度器。

    根据 settings.ai_mode（"cloud" | "local" | "auto"）进行智能分流：
    1. cloud 模式：直接在服务端调用服务端大模型流式直出；
    2. local 模式：通过反向隧道穿透到本地电脑执行；
    3. auto 模式：
       - 若本地 Worker 在线，优先反向代理至本地（保护隐私与离线算力）；
       - 若本地 Worker 离线，自动无缝平滑回退至云端服务端大模型！
    """
    mode = (settings.ai_mode or "auto").lower()

    # 1. 强制走云端模式
    if mode == "cloud":
        if not settings.is_server_llm_configured():
            err = "当前设置为「云端 AI 模式」，但服务端尚未配置大模型（可在设置中配置或指定 SERVER_LLM_API_KEY）。"
            yield f"data: {json.dumps({'type': 'error', 'detail': err}, ensure_ascii=False)}\n\n".encode("utf-8")
            return

        logger.info("[AI Dispatch] 使用云端内置 LLM 模式执行: %s", path)
        async for chunk in server_llm_service.stream_sse_response(path, body):
            yield chunk
        return

    # 2. 强制走本地模式
    elif mode == "local":
        if not tunnel_manager.is_worker_online():
            raise WorkerOfflineError("本地 AI 节点未连接，当前设置为「强制本地模式 (local)」，请启动本地客户端。")
        logger.info("[AI Dispatch] 强制使用本地 Worker 反向隧道执行: %s", path)
        async for chunk in tunnel_manager.dispatch_request(
            method=method, path=path, headers=headers, query_params=query_params, body=body, timeout=timeout
        ):
            yield chunk
        return

    # 3. 自动模式 (auto)
    else:
        if tunnel_manager.is_worker_online():
            logger.info("[AI Dispatch] [Auto] 本地 Worker 在线，优先派发到本地: %s", path)
            try:
                async for chunk in tunnel_manager.dispatch_request(
                    method=method, path=path, headers=headers, query_params=query_params, body=body, timeout=timeout
                ):
                    yield chunk
                return
            except (WorkerOfflineError, WorkerRequestTimeoutError) as e:
                logger.warning("[AI Dispatch] 本地 Worker 派发异常 (%s)，平滑回退到云端 LLM...", e)
                # 本地派发失败时尝试平滑回退到云端

        # 本地离线或异常，回退至云端
        if settings.is_server_llm_configured():
            logger.info("[AI Dispatch] [Auto] 本地离线，自动无缝回退到云端内置 LLM 驱动: %s", path)
            async for chunk in server_llm_service.stream_sse_response(path, body):
                yield chunk
        else:
            err = "本地 AI 节点未连接，且服务端未配置内置大模型。请启动本地客户端或在服务端配置 SERVER_LLM_API_KEY。"
            yield f"data: {json.dumps({'type': 'error', 'detail': err}, ensure_ascii=False)}\n\n".encode("utf-8")
