"""宿主参考实现 CLI：bootstrap / serve / scaffold。

bootstrap：创建管理员账号并**只打印一次**随机口令（与编排控制面同纪律）。
scaffold：生成宿主骨架文件，只写显式 --into 目录、永不覆盖（对齐 scaffold 纪律）。
"""
import argparse
import json
import secrets
import sys
from pathlib import Path

from .database import HostDatabase
from .scenarios import PERMISSION_CATALOG
from .security import hash_password

# 管理员角色持全目录权限——单一来源（与契约测试的装配同构）；
# 手工列举曾漏掉 registry:write 等 9 项，属于典型的第二真相漂移。
_ADMIN_ROLE_PERMISSIONS = sorted({entry["permission"] for entry in PERMISSION_CATALOG})

_SCAFFOLD_APP = '''"""宿主应用骨架 —— 由 `microflow-host scaffold` 生成（microflow-host 参考实现）。

[fill] 宿主关切归部署方：在 extend() 里接线真实业务端口（持久化提供者、
遥测投递、事件投递）。参考实现验证协议正确性，不冒充生产部署证据。
"""
from pathlib import Path

from microflow_host import HostDatabase, create_app

STORE = Path(__file__).resolve().parent / "host.sqlite3"
APPS_DIR = Path(__file__).resolve().parent / "apps"


def extend(app):
    """[fill] 宿主扩展点：追加自定义路由 / 中间件 / 代理（编排控制面 :8200 等）。"""
    return app


app = extend(create_app(HostDatabase(STORE), apps_dir=APPS_DIR))
'''

_SCAFFOLD_README = '''# 宿主骨架（microflow-host 参考）

1. `pip install microflow4host`
2. `microflow-host bootstrap --store host.sqlite3 --admin <name>`（口令只打印一次）
3. `uvicorn host_app:app --port 3000`
4. 平台 SPA 构建产物放入 `apps/ops`、`apps/bizops`、`apps/orchestration`（各含 index.html）
5. 完整场景清单与权限点目录见 `MicroFlow4Kit/HOST_CONTRACT.md`
'''


def bootstrap(store: Path, admin: str, password: str | None) -> int:
    db = HostDatabase(store)
    try:
        if db.query_one("SELECT 1 FROM users WHERE name = ?", (admin,)) is not None:
            print(json.dumps({"ok": False, "message": f"admin {admin!r} already exists"}))
            return 2
        generated = password is None
        password = password or secrets.token_urlsafe(18)
        digest, salt = hash_password(password)
        db.execute(
            "INSERT INTO users (name, password_hash, password_salt, created_at)"
            " VALUES (?,?,?, datetime('now'))", (admin, digest, salt))
        user = db.query_one("SELECT id FROM users WHERE name = ?", (admin,))
        db.execute("INSERT INTO roles (name, permissions) VALUES (?,?)",
                   ("admin", json.dumps(_ADMIN_ROLE_PERMISSIONS, sort_keys=True)))
        role = db.query_one("SELECT id FROM roles WHERE name = 'admin'")
        db.execute("INSERT INTO platform_roles (user_id, role_id) VALUES (?,?)", (user["id"], role["id"]))
        print(json.dumps({"ok": True, "admin": admin,
                          "password": password if generated else "(from --password)",
                          "note": "口令只显示这一次（与编排控制面同纪律）"}, ensure_ascii=True))
        return 0
    finally:
        db.close()


def scaffold(into: Path) -> int:
    into = Path(into)
    if into.exists() and not into.is_dir():
        print(json.dumps({"ok": False, "message": "target is not a directory"}))
        return 2
    targets = [(into / "host_app.py", _SCAFFOLD_APP), (into / "README.md", _SCAFFOLD_README)]
    for path, _ in targets:
        if path.exists():
            print(json.dumps({"ok": False, "message": f"scaffold never overwrites: {path}"}))
            return 2
    into.mkdir(parents=True, exist_ok=True)
    for path, content in targets:
        path.write_text(content, encoding="utf-8")
    print(json.dumps({"ok": True, "into": str(into),
                      "files": [str(p) for p, _ in targets]}, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="microflow-host")
    commands = parser.add_subparsers(dest="command", required=True)
    boot = commands.add_parser("bootstrap", help="Create the admin account (password printed once)")
    boot.add_argument("--store", required=True, type=Path)
    boot.add_argument("--admin", required=True)
    boot.add_argument("--password", default=None, help="Omit to generate a random one (printed once)")
    scaffold_cmd = commands.add_parser("scaffold", help="Generate a host skeleton; writes only into --into")
    scaffold_cmd.add_argument("--into", required=True, type=Path)
    serve = commands.add_parser("serve", help="Run the gateway (uvicorn)")
    serve.add_argument("--store", required=True, type=Path)
    serve.add_argument("--host", default="127.0.0.1",
                       help="bind address (containers pass 0.0.0.0)")
    serve.add_argument("--port", type=int, default=3000)
    serve.add_argument("--apps-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "bootstrap":
        return bootstrap(args.store, args.admin, args.password)
    if args.command == "scaffold":
        return scaffold(args.into)
    if args.command == "serve":
        import uvicorn  # 参考实现运行面；scaffold 骨架同样经 uvicorn 启动
        from .app import create_app
        from .database import HostDatabase as DB

        uvicorn.run(create_app(DB(args.store), apps_dir=args.apps_dir),
                    host=args.host, port=args.port, log_level="warning")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
