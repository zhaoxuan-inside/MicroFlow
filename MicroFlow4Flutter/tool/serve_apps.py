#!/usr/bin/env python3
"""同源托管打卡平台（/）与运营管理平台（/admin/）。

同源是两个应用共享 localStorage 遥测数据的前提（§30.2 查询消费面的本地
通道）：打卡平台 MFStorageSink 写入的运营日志由管理平台经同一键读取。

用法：python3 tool/serve_apps.py [port]
"""
import http.server
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER = os.path.join(ROOT, 'apps', 'habit_tracker', 'build', 'web')
ADMIN = os.path.join(ROOT, 'apps', 'habit_admin', 'build', 'web')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=TRACKER, **kwargs)

    def translate_path(self, path):
        if path == '/admin' or path.startswith('/admin/'):
            rel = path[len('/admin'):].lstrip('/') or 'index.html'
            return os.path.join(ADMIN, rel)
        return super().translate_path(path)

    def end_headers(self):
        # 开发托管：禁缓存，保证两应用always拿到最新构建。
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


Handler.extensions_map = {
    **http.server.SimpleHTTPRequestHandler.extensions_map,
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.wasm': 'application/wasm',
    '.json': 'application/json',
}


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'habit-tracker → http://127.0.0.1:{port}/')
    print(f'habit-admin   → http://127.0.0.1:{port}/admin/')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
