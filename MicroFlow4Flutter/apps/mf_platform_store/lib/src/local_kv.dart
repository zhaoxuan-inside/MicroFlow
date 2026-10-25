/// localStorage 访问与跨标签页通知（frontend-framework-design §27 业务承载）。
///
/// 两个前端（habit_tracker / ops_admin）同源部署，共享同一 localStorage 面：
/// 打卡数据、遥测 JSONL 日志与采集控制开关都以这里的 KV 为介质。
library;

import 'dart:js_interop';

extension type _Storage._(JSObject _) implements JSObject {
  external String? getItem(String key);
  external void setItem(String key, String value);
  external void removeItem(String key);
}

@JS('localStorage')
external _Storage get _localStorage;

/// 同源 KV 读写。存储异常不进入业务路径（读返回 null，写静默失败）。
class MFLocalKV {
  const MFLocalKV();

  String? read(String key) {
    try {
      return _localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  void write(String key, String value) {
    try {
      _localStorage.setItem(key, value);
    } catch (_) {}
  }

  void remove(String key) {
    try {
      _localStorage.removeItem(key);
    } catch (_) {}
  }
}

@JS('addEventListener')
external void _addEventListener(String type, JSFunction handler);

/// 其他标签页写入共享键时收到通知（管理平台的日志实时收集面）。
void onStorageChanged(void Function() onChange) {
  final handler = ((JSAny? _) {
    onChange();
  }).toJS;
  _addEventListener('storage', handler);
}
