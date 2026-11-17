"""Codebuddy（WorkBuddy CLI）LLM 适配器：把本机 codebuddy 无头模式包装为 LLMAdapter。

设置页 provider=codebuddy 时，全部 LLM 调用改走用户 codebuddy 账号的模型配额
（hy4flash / glm-5.3 等），无需单独的 OpenAI 兼容 API Key。

- 流式：`codebuddy -p --output-format stream-json --include-partial-messages`
  （anthropic 风格事件流：text_delta 为正文增量，thinking_delta 为思考内容跳过）
- 非流式：同一链路收集全量文本（单一解析路径，两模式共用一份解析器）
- chat_raw（OpenAI function calling 工具环）不支持：显式抛错，由 agent runner 既有
  降级逻辑回落为纯文本对话（已知边界；二期经 MCP 桥接回 43 工具能力）

安全边界：--permission-mode dontAsk 锁死 CLI 自带工具（Bash/Write/WebSearch 等），
纯 LLM 语义下不允许它在本机执行任何动作；提示词全文经 stdin 传入（避开 argv 长度上限）。
"""
import asyncio
import contextlib
import json
import logging
import subprocess
import sys
import time
from typing import AsyncIterator

from app.services.llm.base import LLMAdapter
from app.services.llm.errors import LLMError, LLMServiceError
from app.services.workbuddy import kill_proc_tree, resolve_cli

logger = logging.getLogger(__name__)

# 单次调用整体上限：章节级长文生成也足够；外部传短超时（设置页测试连接 15s）时
# 地板 30s，防 CLI 冷启动（node 进程 ~1-2s）误杀
DEFAULT_TIMEOUT = 600.0
MIN_TIMEOUT = 30.0
# --system-prompt 走 argv，Windows 单参数上限约 32k 字符；超长系统提示词回落拼进 stdin
MAX_SYSTEM_ARGV = 30000


class CodebuddyAdapter(LLMAdapter):
    """provider=codebuddy 时的 LLM 引擎。model = codebuddy 模型 ID（如 hy4flash）。"""

    def __init__(self, model: str, scene: str = "chat", request_timeout: float | None = None):
        self.model = model
        self.scene = scene
        self.request_timeout = request_timeout
        self.cli = resolve_cli()
        if self.cli is None:
            raise LLMError(
                "本机未找到 WorkBuddy CLI（codebuddy）：请先 npm install -g @tencent-ai/codebuddy-code "
                "并在终端运行 codebuddy 输入 /login 登录一次。",
            )
        self.timeout = max(self.request_timeout, MIN_TIMEOUT) if self.request_timeout else DEFAULT_TIMEOUT

    # ----- 提示词组装 -----

    @staticmethod
    def _split_messages(messages: list[dict]) -> tuple[str, str]:
        """拆出 system 提示词与对话负载。单条用户消息原样透传（生成类主路径，不污染
        prompt 结构）；多轮历史构建为带角色标记的转录。"""
        system_parts = [str(m.get("content") or "") for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        system = "\n\n".join(p for p in system_parts if p.strip())
        if len(rest) == 1 and rest[0].get("role") == "user":
            return system, str(rest[0].get("content") or "")
        lines = ["以下是此前对话记录（供上下文参考）：", ""]
        for m in rest:
            role = "用户" if m.get("role") == "user" else "助手"
            lines.append(f"【{role}】{str(m.get('content') or '').strip()}")
        lines += ["", "请直接以【助手】身份回复最后的用户消息。"]
        return system, "\n".join(lines)

    def _command(self, system: str) -> tuple[list[str], str]:
        """构建命令行与 stdin 负载；system 优先走 --system-prompt，超长回落拼进 stdin。"""
        cmd = [
            self.cli,
            "-p",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--permission-mode", "dontAsk",
        ]
        payload = ""
        if system:
            if len(system) <= MAX_SYSTEM_ARGV:
                cmd += ["--system-prompt", system]
            else:
                payload = f"<系统指令>\n{system}\n</系统指令>\n\n"
        if self.model:
            cmd += ["--model", self.model]
        return cmd, payload

    # ----- 核心执行 -----

    async def _iter_deltas(self, messages: list[dict], json_mode: bool) -> AsyncIterator[str]:
        """spawn codebuddy 并逐事件解析 text_delta；统一超时/未登录/空输出分类。"""
        system, payload = self._split_messages(messages)
        if json_mode:
            payload += "\n\n（本次回复只输出 JSON 本体，不要任何解释文字或代码块标记。）"
        cmd, prefix = self._command(system)
        payload = prefix + payload
        deadline = time.monotonic() + self.timeout
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        # stderr 并发收容：任务体量小（报错文案），但若只读 stdout 可能被 stderr 管道写满卡死
        stderr_task = asyncio.create_task(proc.stderr.read())
        produced = False
        try:
            proc.stdin.write(payload.encode("utf-8"))
            with contextlib.suppress(Exception):
                await proc.stdin.drain()
            proc.stdin.close()
            async for raw in proc.stdout:
                if time.monotonic() > deadline:
                    raise LLMError(f"WorkBuddy 引擎响应超时（{int(self.timeout)}s）已中止，请重试或拆小任务。")
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") != "stream_event":
                    continue
                ev = evt.get("event") or {}
                if ev.get("type") == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            produced = True
                            yield text
            await proc.wait()
            stderr_text = (await stderr_task).decode("utf-8", "replace").strip() if stderr_task else ""
            if proc.returncode != 0:
                raise LLMServiceError(self._explain_failure(stderr_text))
            if not produced:
                # 实测：未登录时 exit 0 + stdout 空 + stderr 报 auth——退出码不可信，按内容分类
                if "authentication required" in stderr_text.lower() or "please use /login" in stderr_text.lower():
                    raise LLMError(
                        "WorkBuddy 未登录：请在终端运行 codebuddy 进入交互界面输入 /login 完成一次登录后重试。"
                    )
                raise LLMServiceError(
                    f"WorkBuddy 引擎无文本输出（exit 0）；请检查模型 ID 是否有效。{stderr_text[:200]}"
                )
        except asyncio.CancelledError:
            raise
        finally:
            if proc.returncode is None:
                kill_proc_tree(proc)
            if stderr_task and not stderr_task.done():
                stderr_task.cancel()

    @staticmethod
    def _explain_failure(stderr_text: str) -> str:
        if "authentication required" in stderr_text.lower() or "please use /login" in stderr_text.lower():
            return "WorkBuddy 未登录：请在终端运行 codebuddy 输入 /login 登录后重试。"
        tail = stderr_text[:300] or "（无 stderr）"
        return f"WorkBuddy 引擎异常退出：{tail}"

    # ----- LLMAdapter 接口 -----

    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str | AsyncIterator[str]:
        if max_tokens is not None or temperature is not None:
            logger.debug("CodebuddyAdapter 忽略 max_tokens/temperature（CLI 不透传该参数）")
        if stream:
            return self._iter_deltas(messages, json_mode)
        parts: list[str] = []
        async for delta in self._iter_deltas(messages, json_mode):
            parts.append(delta)
        return "".join(parts)

    async def chat_raw(self, messages: list[dict], tools=None):
        """OpenAI function calling 工具环不受支持：runner 捕获后降级为纯文本对话。"""
        raise LLMServiceError("Codebuddy 引擎不支持 function calling 工具环")
