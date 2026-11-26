"""MicroFlow 业务容器适配器参考实现：把控制面↔容器↔宿主的全部悬空线接上。"""
from .control import ControlPlaneClient
from .runtime import ContainerRuntime, config_content_hash
from .wiring import ContainerServices, build_services, records_to_node_io, stable_request_id

__version__ = "0.1.0"
__all__ = ["ContainerRuntime", "ContainerServices", "ControlPlaneClient",
           "build_services", "records_to_node_io", "stable_request_id",
           "config_content_hash", "__version__"]
