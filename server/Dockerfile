FROM python:3.12-slim

# 设置工作目录与 Python 环境变量
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVER_PORT=8421 \
    DATA_DIR=/app/data \
    STATIC_DIR=/app/static

# 安装依赖
COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制代码与创建数据目录
COPY server/ /app/server/
RUN mkdir -p /app/data /app/static

# 声明数据持久化卷与端口
VOLUME ["/app/data"]
EXPOSE 8421

# 启动服务
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8421"]
