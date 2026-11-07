/// Web 实现：同源 localStorage（键统一带 `mf.` 前缀）。
/// 打卡平台与管理平台同源部署时，管理平台经同一键读取打卡平台的
/// 遥测日志——这是 §30.2 查询消费面的本地承载通道。
library;

import 'package:web/web.dart' as web;

class MFKeyValueStore {
  MFKeyValueStore._();

  factory MFKeyValueStore.open([String? _]) => MFKeyValueStore._();

  String? read(String key) => web.window.localStorage.getItem('mf.$key');

  void write(String key, String value) {
    web.window.localStorage.setItem('mf.$key', value);
  }
}
