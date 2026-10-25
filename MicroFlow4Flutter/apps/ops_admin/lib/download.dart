/// 浏览器文件下载（Blob + object URL + 锚点点击）：导出的 JSONL 以真实
/// 文件形式交付给运营人员。
///
/// interop 类型名与浏览器全局名一致（extension type 的外部构造器按
/// Dart 名映射 JS 构造函数）。
library;

import 'dart:js_interop';

extension type Blob._(JSObject _) implements JSObject {
  external factory Blob(JSArray<JSAny?> parts);
}

extension type HTMLAnchorElement._(JSObject _) implements JSObject {
  external set href(String value);
  external set download(String value);
  external void click();
}

@JS('document.createElement')
external JSObject _createElement(String tagName);

@JS('URL.createObjectURL')
external JSString _createObjectURL(JSObject blob);

@JS('URL.revokeObjectURL')
external void _revokeObjectURL(JSString url);

void downloadText(String fileName, String text) {
  final blob = Blob([text.toJS].toJS);
  final url = _createObjectURL(blob);
  final anchor = _createElement('a') as HTMLAnchorElement;
  anchor
    ..href = url.toDart
    ..download = fileName
    ..click();
  _revokeObjectURL(url);
}
