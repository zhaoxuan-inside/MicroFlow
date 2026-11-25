# 部署壳镜像：静态面 + 反向代理（server.py 单文件）。
FROM python:3.12-slim

WORKDIR /app
COPY server.py .
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.28" "httpx>=0.27"

EXPOSE 4601 4602 4603
CMD ["python", "server.py"]
