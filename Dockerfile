# ========================================================
# 阶段 1：前端编译构建 (Node.js 20)
# ========================================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

# 优先拷贝依赖清单利用层缓存
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

# 拷贝前端源码并执行全量打包，显式输出到 dist 目录供阶段 2 复制
COPY frontend/ ./
RUN npm run build -- --outDir dist

# ========================================================
# 阶段 2：服务端运行时 (Python 3.12-slim)
# ========================================================
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVER_PORT=8421 \
    DATA_DIR=/app/data \
    STATIC_DIR=/app/static

# 安装基础运维小工具 (curl 用于健康探针与容器内外通信)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装服务端 Python 依赖
COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 拷贝服务端源代码
COPY server/ /app/server/

# 从阶段 1 拷贝打包好的前端静态资源至 /app/static
COPY --from=frontend-builder /app/frontend/dist /app/static

# 创建持久化数据目录
RUN mkdir -p /app/data

# 声明持久化卷与暴露端口
VOLUME ["/app/data"]
EXPOSE 8421

# 启动服务 (默认监听 0.0.0.0:8421)
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8421"]
