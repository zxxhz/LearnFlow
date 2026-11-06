# LearnFlow 云端中转服务端 (LearnFlow Relay Server)

> 专为 LearnFlow 打造的轻量自建云端中转服务端：支持 Web 静态网页托管、可选 Token 鉴权、WebSocket 反向穿透隧道、SQLite 云端数据持久化与 AI 请求实时流式代理。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue?logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
</p>

---

## 🌟 核心特性

- **🚀 零公网 IP 反向穿透（WebSocket Tunnel）**：本地电脑无需公网 IP 或配置路由器端口映射，本地 LearnFlow 启动后自动通过 `/ws/relay` 与本服务端建立反向 WebSocket 长连接。
- **🌐 独立 Web SPA 静态托管**：直接托管前端打包产物（`/assets`、`index.html` 等），支持从外网任意手机、平板或浏览器直接访问完整的 LearnFlow 界面。
- **🔐 灵活的访问令牌鉴权（Token Auth）**：
  - **按需启用**：可设置 `RELAY_AUTH_REQUIRED=false` 且 Token 为空，实现免密开放访问；
  - **多源比对**：开启鉴权时，按优先级从 `x-server-token` / `x-access-token` Header、`?token=...` Query 参数或 Cookie 提取比对；
  - **友好交互**：HTML 页面未鉴权时自动展示美观的暗色/亮色自适应 Token 录入界面，验证通过后自动植入持久化 Cookie。
- **💾 云端 SQLite 数据持久化与离线查阅**：
  - 本地客户端一键/自动将课程、文档讲义、题库、错题本、思维导图同步至云端 SQLite 数据库；
  - **离线也能看**：即便本地电脑休眠或离线，外网用户依然可以秒级查阅讲义正文、复习题库与错题！
- **⚡ 实时 AI 流式响应反向代理（SSE Proxy）**：
  - 云端收到 AI 生成、阅读答疑、沙箱代码运行等请求时，通过隧道实时打包派发至本地 Worker 执行；
  - 本地 LLM 生成的 SSE 文本块即时流式回传并直通浏览器前端，低延迟无缓冲。

---

## 🛠️ 快速开始

### 方式一：Docker Compose（推荐，一键秒级启动）

在服务器上克隆仓库或将 `server/` 目录上传至云服务器，直接启动：

```bash
cd server
docker compose up -d
```

查看运行日志：
```bash
docker compose logs -f
```

停止服务：
```bash
docker compose down
```

### 方式二：Docker 纯容器部署

```bash
# 1. 构建镜像（在项目根目录下）
docker build -t learnflow-relay:latest -f server/Dockerfile .

# 2. 启动容器（映射 8421 端口并挂载数据目录）
docker run -d \
  --name learnflow-relay \
  --restart unless-stopped \
  -p 8421:8421 \
  -v $(pwd)/server/data:/app/data \
  -e SERVER_PORT=8421 \
  -e RELAY_AUTH_REQUIRED=false \
  learnflow-relay:latest
```

### 方式三：原生 Python 虚拟环境运行

```bash
# 1. 进入服务端目录
cd server

# 2. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows 用户运行: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务（默认监听 0.0.0.0:8421）
uvicorn server.main:app --host 0.0.0.0 --port 8421
```

---

## ⚙️ 环境变量配置

支持通过 `.env` 文件或容器环境变量进行配置：

| 变量名 | 类型 | 默认值 | 说明 |
| :--- | :---: | :---: | :--- |
| `SERVER_HOST` | string | `0.0.0.0` | 监听网络地址 |
| `SERVER_PORT` / `RELAY_PORT` | int | `8421` | 监听服务端口 |
| `RELAY_AUTH_REQUIRED` | bool | `false` | 是否强制开启访问鉴权（`true` / `false`） |
| `RELAY_SERVER_TOKEN` | string | `""` | 访问安全令牌；若留空且 `RELAY_AUTH_REQUIRED=false` 则免密开放 |
| `AI_MODE` | string | `auto` | AI 执行模式：`auto` (本地在线走本地，离线走云端) / `cloud` (强制云端) / `local` (强制本地) |
| `SERVER_LLM_BASE_URL` | string | `https://api.openai.com/v1` | 服务端内置大模型接口地址（兼容 OpenAI 格式） |
| `SERVER_LLM_API_KEY` | string | `""` | 服务端大模型 API Key（本地 Ollama 可留空） |
| `SERVER_LLM_MODEL` | string | `gpt-4o-mini` | 服务端大模型模型名称（如 `qwen-plus`, `deepseek-chat`） |
| `STATIC_DIR` | path | 自动探测 | 前端静态资源目录（默认自动查找 `../frontend/dist` 或 `../backend/app/static`） |
| `DATA_DIR` | path | `server/data/` | 云端 SQLite 数据库与持久化数据存储目录 |

> **提示**：若希望启用 Token 鉴权，只需设置 `RELAY_SERVER_TOKEN=你的强密码` 并根据需要设置 `RELAY_AUTH_REQUIRED=true`。

---

## 📡 核心 API 与端点说明

| 端点 | 请求方法 | 认证 | 说明 |
| :--- | :---: | :---: | :--- |
| `/` | `GET` | 按配置 | 前端 SPA 主页或服务在线说明页 |
| `/health` | `GET` | 免除 | 轻量探针与心跳检测接口 |
| `/ws/relay` | `WebSocket` | 按配置 | 本地客户端反向隧道长连接接入点 |
| `/api/relay/status` | `GET` | 免除 | 查询中转服务状态、Worker 在线状态、统计信息 |
| `/api/relay/ai-mode` | `GET`/`POST` | 按配置 | 查询或动态切换 AI 模式（cloud/local/auto）及热更新大模型配置 |
| `/api/relay/sync/push` | `POST` | 需鉴权 | 接收本地客户端推送的课程、讲义、题库等数据落库 |
| `/api/relay/sync/pull` | `GET` | 需鉴权 | 从云端拉取已存储的全部结构化数据快照（供本地双向合并） |
| `/api/courses` | `GET` | 需鉴权 | 云端优先返回已同步的课程列表（离线可看） |
| `/api/courses/{id}` | `GET` | 需鉴权 | 获取课程详情及目录（离线可看） |
| `/api/documents/{id}/content` | `GET` | 需鉴权 | 获取文档正文 Markdown（离线可看） |
| `/api/banks` | `GET` | 需鉴权 | 获取题库列表（离线可看） |
| `/api/banks/{id}/wrong` | `GET` | 需鉴权 | 获取错题列表（离线可看） |
| `/api/mindmaps` | `GET` | 需鉴权 | 获取思维导图列表（离线可看） |
| `/api/*` (AI / 执行类) | `ALL` | 需鉴权 | 自动通过隧道反向代理回本地执行并实时流式下发 |

---

## 🔒 Nginx / Caddy 反向代理与 HTTPS 配置示例

生产环境下，强烈建议通过 Nginx 或 Caddy 配置域名与 SSL 证书，并开启 WebSocket 支持：

### Nginx 配置片段

```nginx
server {
    listen 80;
    server_name relay.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name relay.yourdomain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # 客户端上传限制（如导入大题库/离线资料）
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8421;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 反向隧道必需配置
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 禁用缓冲以保证 AI SSE 流式实时推送
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
    }
}
```

### Caddyfile 配置片段

```caddy
relay.yourdomain.com {
    reverse_proxy 127.0.0.1:8421 {
        flush_interval -1
    }
}
```

---

## 💻 客户端连接指引

1. 部署完成后，在电脑端打开 **LearnFlow** 客户端；
2. 进入「**设置**」→「**自建中转服务**」卡片；
3. 填入你的云端中转服务器地址（如 `http://你的公网IP:8421` 或 `https://relay.yourdomain.com`）；
4. 若服务端配置了 Token，在此填入相同的 Token（若未开启可留空）；
5. 点击「**连接测试**」与「**开启中转**」，连接成功后状态指示灯将变为绿色；
6. 点击「**立即同步数据**」，本地的课程、文档、题库即可一键同步至云端。

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。
