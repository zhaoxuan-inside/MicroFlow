# 宿主参考实现镜像：依赖层与源码层分离——源码变更不再触发依赖重装。
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir "fastapi>=0.115" uvicorn
COPY . .
RUN pip install --no-cache-dir --no-deps .

EXPOSE 3000
