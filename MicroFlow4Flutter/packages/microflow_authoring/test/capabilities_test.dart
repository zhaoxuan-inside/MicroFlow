import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:microflow_authoring/microflow_authoring.dart';

void main() {
  group('authoring capabilities projection（CLI 命令体系设计 §2 契约 5）', () {
    final names = mfAuthoringCommands.map((c) => c.name).toSet();

    test('declares exactly the implemented command face', () {
      expect(names, {
        'create_page',
        'connect_navigation',
        'create_page_from_template',
        'register_finding',
        'validate_project',
        'inspect_impact',
        'undo',
      });
    });

    test('command names match the actual session methods（漏登即缺陷的守卫）', () {
      final source = File('lib/src/authoring.dart').readAsStringSync();
      final pattern = RegExp(
        r'^  (?:MFCommandResult|MFValidationResult|MFImpactReport|MFProject\?) (\w+)\(',
        multiLine: true,
      );
      String snake(String s) =>
          s.replaceAllMapped(RegExp(r'[A-Z]'), (m) => '_${m.group(0)!.toLowerCase()}');
      final methods = pattern.allMatches(source).map((m) => snake(m.group(1)!)).toSet()
        ..removeWhere((n) => n.startsWith('_'));
      expect(names, methods);
    });

    test('projection is deterministic and JSON-encodable', () {
      final first = mfAuthoringCapabilities();
      final second = mfAuthoringCapabilities();
      expect(jsonEncode(first), jsonEncode(second));
      expect((first['commands'] as List).length, mfAuthoringCommands.length);
      expect(first['protocol'], 'mf-authoring-capabilities-v1');
    });

    test('kinds and return declarations stay honest', () {
      for (final c in mfAuthoringCommands) {
        expect(const ['mutate', 'inspect', 'rollback'], contains(c.kind), reason: c.name);
        if (c.kind == 'mutate') {
          expect(c.returns, contains('MFCommandResult'), reason: c.name);
          expect(c.returns, contains('revision'), reason: c.name);
        }
        if (c.kind == 'rollback') {
          expect(c.name, 'undo');
          expect(c.returns, contains('MFProject'));
        }
      }
      expect(names.where((n) => n == 'undo'), hasLength(1));
    });
  });
}
