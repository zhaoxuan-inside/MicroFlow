/// 键值存储门面：按目标平台选择真实实现（§27：数据承载在宿主侧）。
/// - VM/桌面（应用测试与本地运行）：目录内 JSON 文件；
/// - Web：同源 localStorage —— 打卡平台与管理平台同源部署时经此共享
///   遥测日志（§30.2 查询消费面的本地通道）。
library;

export 'store_io.dart' if (dart.library.html) 'store_web.dart';
