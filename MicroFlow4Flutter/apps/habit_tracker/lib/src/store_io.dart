/// VM/桌面实现（应用测试与本地运行）：目录内 JSON 文件存储。
library;

import 'dart:io';

class MFKeyValueStore {
  MFKeyValueStore._(this._dir);

  final String _dir;

  factory MFKeyValueStore.open([String? dir]) =>
      MFKeyValueStore._(dir ?? Directory.systemTemp.createTempSync('mf-habits').path);

  File _file(String key) => File('$_dir/$key.json');

  String? read(String key) {
    final f = _file(key);
    return f.existsSync() ? f.readAsStringSync() : null;
  }

  void write(String key, String value) {
    Directory(_dir).createSync(recursive: true);
    _file(key).writeAsStringSync(value, flush: true);
  }
}
