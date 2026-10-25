// 一致性基线覆盖率工具（P1，MicroFlow4Flutter/baselines.json 的消费方）。
//
// 扫描本仓库全部 Dart 测试文件中测试名称的「基线 N」标记
// （如「基线 13、15」；名称含「部分」时该条目标记为部分覆盖），
// 对照 MicroFlow4Flutter/baselines.json 输出 Markdown 覆盖表。
//
// 用法（仓库根或 MicroFlow4Flutter/ 下均可）：
//   dart run tool/baseline_coverage.dart
//
// 退出码：2 = baselines.json 缺失或格式非法；1 = 测试引用了不存在的基线条目。
import 'dart:convert';
import 'dart:io';

void main() {
  final baselineFile = _locate('MicroFlow4Flutter/baselines.json');
  if (baselineFile == null) {
    stderr.writeln('未找到 MicroFlow4Flutter/baselines.json（从当前目录向上回溯）');
    exit(2);
  }
  final Map<String, Object?> doc;
  try {
    doc = jsonDecode(baselineFile.readAsStringSync()) as Map<String, Object?>;
  } catch (e) {
    stderr.writeln('baselines.json 解析失败：$e');
    exit(2);
  }
  final baselines = (doc['baselines'] as List)
      .map((e) => e as Map<String, Object?>)
      .toList(growable: false);
  final byId = {for (final b in baselines) b['id'] as int: b};
  final expected = List<int>.generate(baselines.length, (i) => i + 1);
  if (!expected.every(byId.containsKey)) {
    stderr.writeln('baselines.json 条目 id 必须为 1..${baselines.length} 连续');
    exit(2);
  }

  // 收集测试文件：总包 test/ 与各子包 packages/*/test/。
  final testFiles = <File>{};
  for (final rel in const ['test', 'packages']) {
    final dir = Directory(rel);
    if (!dir.existsSync()) continue;
    testFiles.addAll(dir
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('_test.dart')));
  }

  // 标记语法：基线 13、15 / 基线 3（名称含「部分」→ partial）。
  final marker = RegExp(r'基线\s*(\d+(?:\s*[、,，]\s*\d+)*)');
  final testName = RegExp(r'''(?:test|testWidgets)\(\s*(['"])(.+?)\1''');
  final coverage = <int, List<String>>{}; // id -> test names
  final partial = <int>{};
  final errors = <String>[];

  for (final f in testFiles) {
    final text = f.readAsStringSync();
    for (final m in testName.allMatches(text)) {
      final name = m.group(2)!;
      final isPartial = name.contains('部分');
      for (final bm in marker.allMatches(name)) {
        for (final idStr in bm.group(1)!.split(RegExp(r'[、,，]'))) {
          final id = int.tryParse(idStr.trim());
          if (id == null || !byId.containsKey(id)) {
            errors.add('${f.path}："${name.trim()}" 引用了不存在的基线条目 $idStr');
            continue;
          }
          coverage.putIfAbsent(id, () => []).add(name.trim());
          if (isPartial) partial.add(id);
        }
      }
    }
  }

  if (errors.isNotEmpty) {
    for (final e in errors) {
      stderr.writeln(e);
    }
    exit(1);
  }

  final buffer = StringBuffer()
    ..writeln('| 基线 | 条目 | 覆盖状态 | 测试 |')
    ..writeln('|---|---|---|---|');
  var full = 0;
  for (final id in expected) {
    final tests = coverage[id] ?? const [];
    final status = tests.isEmpty ? '未覆盖' : (partial.contains(id) ? '部分覆盖' : '已覆盖');
    if (status == '已覆盖') full++;
    final label = tests.map((t) => '`$t`').join('<br>');
    buffer.writeln('| $id | ${byId[id]!['title']} | $status | ${label.isEmpty ? '—' : label} |');
  }
  buffer.writeln();
  buffer.writeln(
      '覆盖汇总：$full/${expected.length} 条已覆盖，${partial.length} 条部分覆盖'
      '（生成工具：`dart run tool/baseline_coverage.dart`，勿手工编辑本表）。');
  stdout.writeln(buffer);
}

File? _locate(String rel) {
  var dir = Directory.current.path;
  for (var i = 0; i < 4; i++) {
    final candidate = File('$dir/$rel');
    if (candidate.existsSync()) return candidate;
    final parent = File('$dir/..').resolveSymbolicLinksSync();
    if (parent == dir) break;
    dir = parent;
  }
  return null;
}
