# 编排控制面镜像：PostgreSQL 客户端 + FastAPI。
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8200
