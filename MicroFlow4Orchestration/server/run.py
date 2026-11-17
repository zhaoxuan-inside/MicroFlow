"""控制面服务入口：python run.py（或 uvicorn app.main:app --port 8200）。"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8200, reload=False)
