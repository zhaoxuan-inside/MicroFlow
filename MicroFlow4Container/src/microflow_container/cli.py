"""microflow-container CLI：一条命令起业务容器（接入编排控制面与宿主网关）。"""
import argparse
import os
import sys

import uvicorn

from .http import create_app
from .wiring import build_services

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="microflow-container",
        description="MicroFlow 业务容器参考实现：装载本地项目、接收控制面下发、"
                    "耐久执行、记录流与事件投递泵一次接成")
    parser.add_argument("--project", required=True, help="容器本地项目 project.json 路径")
    parser.add_argument("--env", default="dev", help="环境键（dev/test/staging/online）")
    parser.add_argument("--store", default="container-data", help="状态与发件箱根目录")
    parser.add_argument("--binding", default=None,
                        help="介质绑定 id（默认 container-<env>；项目 defaults 会被它覆盖）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host-endpoint", default="http://127.0.0.1:3000/api/v1/dispatch",
                        help="宿主网关 dispatch 端点（记录流/快照上行）")
    parser.add_argument("--host-token", default=os.getenv("MF_HOST_TOKEN", ""),
                        help="宿主令牌（需要 registry:write）")
    parser.add_argument("--control-url", default="http://127.0.0.1:8200",
                        help="编排控制面基址")
    parser.add_argument("--control-token", default=os.getenv("MF_CONTROL_TOKEN", ""),
                        help="控制面服务令牌（X-Service-Token）")
    parser.add_argument("--namespace", default="opchub", help="注册面命名空间")
    parser.add_argument("--group", default=None, help="注册面分组（默认等于 --env）")
    args = parser.parse_args(argv)

    services = build_services(
        project_path=args.project, store_dir=args.store, env=args.env,
        binding_id=args.binding or f"container-{args.env}",
        host_endpoint=args.host_endpoint, host_token=args.host_token,
        control_url=args.control_url, control_token=args.control_token,
        namespace=args.namespace, group=args.group or args.env)
    services.start()
    print(f"[microflow-container] env={args.env} release={services.runtime.release_id[:12]}"
          f" flows={sorted(services.runtime.flow_ids)} operators={sorted(services.runtime.operator_catalog)}"
          f" announced={services.announced['ok']}", flush=True)
    try:
        uvicorn.run(create_app(services), host=args.host, port=args.port, log_level="warning")
    finally:
        services.stop()
    return 0

if __name__ == "__main__":
    sys.exit(main())
