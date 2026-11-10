# LearnFlow 云端中转服务端 (LearnFlow Relay Server)

> 专为 LearnFlow 打造的自建云端中转与独立学习服务端：内置 Web 静态页面托管、默认强安全 Token 鉴权、WebSocket 反向穿透隧道、SQLite 云端数据持久化、前后端一体化 Docker 容器与 Web/Desktop 双端在线热更新。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue?logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Docker-All--in--One-2496ED?logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
</p>

---

## 🌟 核心特性

- **📱 手机/平板纯 Web 独立学习**：预编译打包前端 Web SPA 界面（HTML/JS/CSS），在公网 VPS 部署后，外网任何手机、平板或浏览器直接访问即可看讲义、刷题与 AI 答疑，本地电脑无需常开。
- **🔐 默认强制 Token 安全鉴权**：
  - **默认强安全**：`RELAY_AUTH_REQUIRED` 默认为 `true`，防止公网端口被恶意扫描与未授权调用；
  - **多源比对**：自动支持从请求头 `x-server-token` / `x-access-token`、URL 参数 `?token=...` 或 Cookie 提取校验；
  - **优雅交互**：浏览器初次访问未鉴权时，自动呈现自适应深浅色的密码录入页，输入正确后自动植入持久化 Cookie。
- **🚀 零公网 IP 反向穿透（WebSocket Tunnel）**：本地电脑无需公网 IP 或路由器端口映射，本地 LearnFlow 桌面端启动后自动通过 `/ws/relay` 与本服务端建立双向反向长连接隧道。
- **💾 云端 SQLite 数据持久化与双向同步**：
  - 课程、Markdown 讲义正文、题库、错题本与思维导图一键持久化至云端 SQLite 数据库；
  - 本地电脑关机时，云端依旧支持离线查阅讲义与刷题；外出手机刷题产生的记录，回家打开桌面端秒级双向合并。
- **⚡ 三种 AI 算力执行模式**：
  - 🔄 **智能自动 (`auto`，默认推荐)**：本地电脑在线优先调用本地算力与本地模型；本地断开时自动平滑回退由 VPS 云端大模型直出接管，学习绝不中断；
  - ☁️ **云端服务端模式 (`cloud`)**：强制由服务端直连大模型生成，外出手机轻量学习专属；
  - 💻 **本地节点模式 (`local`)**：强制通过隧道穿透至本地电脑运行，调用本地显卡算力与代码沙箱，保护代码隐私。
- **⚙️ 云端大模型 API 在线修改与持久化**：
  - 告别繁琐的服务器配置文件编辑，直接在网页端或电脑桌面端「设置」页修改 VPS 的大模型 Base URL、API Key 与 Model 名称，支持一键点击测试网络延迟；
  - 配置自动写入挂载的 `data/server_config.json`，容器重启、升级新镜像配置永不丢失。
- **🛡️ 权限最小化双容器在线热更新**：
  - 业务容器 `learnflow-relay` 绝不挂载宿主机 `docker.sock`（彻底消除特权逃逸风险）；
  - 由 Docker 内部局域网专职运维的 `watchtower` 响应网页/桌面端点击触发，自动拉取新镜像并热重启，15 秒倒计时后页面自动重新载入。

---

## 🛠️ 快速部署 (Docker Compose 推荐)

在云服务器（VPS）上创建目录并编写 `docker-compose.yml`：

```yaml
version: "3.8"

services:
  # ========================================================
  # 1. LearnFlow 云端中转服务端 (对外 Web 界面与 API 业务容器)
  #    【安全设计】：不挂载宿主机 docker.sock，杜绝特权逃逸风险！
  # ========================================================
  learnflow-relay:
    image: ghcr.io/zxxhz/learnflow-server:latest
    container_name: learnflow-relay
    restart: unless-stopped
    pull_policy: always # 开机或重启时自动拉取最新一体化镜像
    ports:
      - "${SERVER_PORT:-8421}:${SERVER_PORT:-8421}"
    environment:
      # 服务监听端口（改动此处会同时生效于容器内部 Uvicorn 与端口映射）
      - SERVER_PORT=8421
      # 安全访问密码（建议配置复杂密码；留空且 RELAY_AUTH_REQUIRED=false 则免密开放）
      - RELAY_SERVER_TOKEN=your_secure_token_here
      # 默认强制开启 Token 鉴权（true / false）
      - RELAY_AUTH_REQUIRED=true
      # AI 执行模式: auto (智能推荐) | cloud (强制云端) | local (强制本地)
      - AI_MODE=auto
      # 内部更新通信：通过 Docker 内部虚拟网络向独立的 Watchtower 触发热更新
      - WATCHTOWER_URL=http://watchtower:8080/v1/update
      - WATCHTOWER_TOKEN=learnflow_update_secret
    volumes:
      # 持久化存储 SQLite 数据库、讲义缓存及云端大模型配置 (server_config.json)
      - ./data:/app/data
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    healthcheck:
      test: ["CMD", "python", "-c", "import os, urllib.request; p=os.getenv('SERVER_PORT','8421'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s

  # ========================================================
  # 2. Watchtower 安全更新运维容器 (内部专用，不暴露公网端口)
  #    【安全设计】：由专职运维容器持有 docker.sock，仅内网响应热更新触发
  # ========================================================
  watchtower:
    image: containrrr/watchtower:latest
    container_name: learnflow-watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - DOCKER_API_VERSION=1.44         # 解决高版本 Docker Daemon 握手协商
      - WATCHTOWER_CLEANUP=true         # 更新后自动清理无用旧镜像，释放磁盘空间
      - WATCHTOWER_LABEL_ENABLE=true    # 仅更新带有 enable=true 标签的容器
      - WATCHTOWER_HTTP_API_UPDATE=true # 开启内网 HTTP API 触发模式
      - WATCHTOWER_HTTP_API_TOKEN=learnflow_update_secret
      - WATCHTOWER_POLL_INTERVAL=86400  # 默认巡检间隔（主要依靠 Web 端点击触发更新）
```

启动服务：
```bash
docker compose up -d
```
查看运行日志：
```bash
docker compose logs -f learnflow-relay
```
停止服务：
```bash
docker compose down
```

---

## ⚙️ 环境变量配置

| 变量名 | 类型 | 默认值 | 说明 |
| :--- | :---: | :---: | :--- |
| `SERVER_HOST` | string | `0.0.0.0` | 服务端监听网络地址 |
| `SERVER_PORT` | int | `8421` | 服务端监听端口（动态生效于容器内部 Uvicorn 与端口映射） |
| `RELAY_AUTH_REQUIRED` | bool | `true` | **是否强制开启访问鉴权（默认 true 强制开启，保护公网安全）** |
| `RELAY_SERVER_TOKEN` | string | `""` | 访问安全令牌；若显式设为 `RELAY_AUTH_REQUIRED=false` 且留空才免密开放 |
| `AI_MODE` | string | `auto` | AI 执行模式：`auto` (智能平滑降级) / `cloud` (强制云端) / `local` (强制本地) |
| `DATA_DIR` | path | `/app/data` | 云端 SQLite 数据库与持久化数据存储目录（需挂载宿主机卷） |
| `STATIC_DIR` | path | `/app/static` | 前端打包静态资源目录（镜像内置，无需手动指定） |
| `WATCHTOWER_URL` | string | `http://watchtower:8080/v1/update` | Docker 内网 Watchtower HTTP API 更新端点 |
| `WATCHTOWER_TOKEN` | string | `learnflow_update_secret` | 内部更新触发鉴权密钥 |

> **提示**：大语言模型配置（Base URL、API Key 与 Model 名称）**无需在环境变量中硬编码**！直接在手机网页端或电脑桌面端「设置」页面下方的「⚡ 云端服务端大模型 API 配置」中随时在线修改与测速，会自动持久化存入 `./data/server_config.json`，即使升级镜像也永久保留。

---

## 🔄 在线热更新机制 (Web 界面一键更新 & 开机自拉取)

本系统支持无需 SSH 登录服务器的高频在线平滑热更新：

1. **开机自拉取最新镜像 (`pull_policy: always`)**：
   在 `docker-compose.yml` 中默认配置了 `pull_policy: always`，任何时候重启容器，Docker 都会自动检测并拉取 GitHub Packages 上的最新前后端一体化镜像。
2. **Web 页面一键更新 (Watchtower 安全隔离代理)**：
   在 LearnFlow 网页端或电脑桌面端「设置」页面下方的 **「云端服务端在线更新」** 卡片中：
   - 自动检测 GitHub 最新 Release 版本与更新日志；
   - 点击 **【🚀 立即在线更新服务端】**，业务容器向内部局域网专职运维的 Watchtower 发起安全调用；
   - 业务容器 `learnflow-relay` 绝不挂载宿主机 `docker.sock`，仅由隔离的 Watchtower 负责拉取新镜像并热重启，15 秒倒计时后页面自动刷新就绪。

---

## 📡 核心 API 与端点说明

| 端点 | 请求方法 | 认证 | 说明 |
| :--- | :---: | :---: | :--- |
| `/` | `GET` | 按配置 | 前端 SPA 页面（浏览器访问） |
| `/health` | `GET` | 免除 | 轻量探针与心跳检测接口 |
| `/api/relay/system/version` | `GET` | 免除 | 查询服务端当前版本、云端最新版本及发布说明 |
| `/api/relay/system/update` | `POST` | 需鉴权 | 触发服务端在线更新并优雅重启容器 |
| `/ws/relay` | `WebSocket` | 按配置 | 本地客户端反向隧道长连接接入点 |
| `/api/relay/status` | `GET` | 免除 | 查询中转服务状态、Worker 在线状态、统计信息 |
| `/api/relay/ai-mode` | `GET`/`POST` | 按配置 | 查询或动态切换 AI 模式及在线修改大模型配置 |
| `/api/relay/ai-mode/test` | `POST` | 需鉴权 | 在线测试服务端大模型的网络连通性与往返延迟 |
| `/api/relay/sync/push` | `POST` | 需鉴权 | 接收本地客户端推送的课程、讲义、题库等数据落库 |
| `/api/relay/sync/pull` | `GET` | 需鉴权 | 从云端拉取已存储的全部结构化数据快照（供本地双向合并） |
| `/api/courses` | `GET` | 需鉴权 | 云端优先返回已同步的课程列表（离线可看） |
| `/api/courses/{id}` | `GET` | 需鉴权 | 获取课程详情及目录（离线可看） |
| `/api/documents/{id}/content` | `GET` | 需鉴权 | 获取文档正文 Markdown（离线可看） |
| `/api/banks` | `GET` | 需鉴权 | 获取题库列表（离线可看） |
| `/api/banks/{id}/wrong` | `GET` | 需鉴权 | 获取错题列表（离线可看） |
| `/api/mindmaps` | `GET` | 需鉴权 | 获取思维导图列表（离线可看） |
| `/api/*` (AI / 执行类) | `ALL` | 需鉴权 | 智能分发：本地在线穿透至本地，本地离线服务端直连生成 |

---

## 🔒 Nginx / Caddy 反向代理与 HTTPS 配置示例

在生产环境中，强烈建议通过域名反向代理并开启 SSL 证书与 WebSocket 支持：

### Caddy 示例（自带自动 SSL）
```caddy
learnflow.yourdomain.com {
    reverse_proxy 127.0.0.1:8421
}
```

### Nginx 示例
```nginx
server {
    listen 80;
    server_name learnflow.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name learnflow.yourdomain.com;

    ssl_certificate /etc/nginx/ssl/yourdomain.crt;
    ssl_certificate_key /etc/nginx/ssl/yourdomain.key;

    location / {
        proxy_pass http://127.0.0.1:8421;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 核心：必须开启 WebSocket 反向穿透支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 延长超时时间，防止长连接中断
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```
