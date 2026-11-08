import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 0.9.0 动效面（§36.5/§36.7）可执行判据：
/// - 基线 22：动效只出现在已声明动效面；动效值只解析到 motion Token；
/// - 基线 23：减少动效偏好命中替代组时应用替代 Token 并记录。

MFTokenSet _tokens() => const MFTokenSet(id: 'tokens-motion', tokens: {
      'motion.liquid': {
        'duration': 250,
        'curve': [0.16, 1, 0.3, 1],
      },
      'motion.liquid.reduced': {
        'duration': 0,
        'curve': [0, 0, 1, 1],
      },
      'motion.entrance': {
        'duration': 360,
        'curve': [0.16, 1, 0.3, 1],
      },
    });

void main() {
  group('基线 22：动效只出现在已声明动效面；动效值只解析到 motion Token（§36.5）', () {
    test('基线 22：motion token 解析——duration/curve 四点成形，值只解析到 token', () {
      final resolver = MFStyleResolver(
        tokenSets: {'t': _tokens()},
        styleSheets: const {},
        themes: const {},
        defaultThemeId: 't',
      );
      final res = resolver.resolveMotion('motion.liquid');
      expect(res.viaAlternative, isFalse);
      expect(res.spec?.durationMs, 250);
      expect(res.spec?.curve, [0.16, 1, 0.3, 1]);
      // 非 motion 值形状 → null（调用方报 token-invalid，不静默）。
      expect(resolver.resolveMotion('motion.missing').spec, isNull);
    });

    test('基线 22：形状不符的 motion token 是静态错误（mf.motion.token-invalid）', () {
      final bad = const MFTokenSet(id: 'bad', tokens: {
        'motion.bad': {'duration': 'fast'},
        'motion.bad2': {
          'duration': 100,
          'curve': [0.1, 0.2],
        },
      });
      final diags = validateMotionTokens([bad]);
      expect(diags.length, 2, reason: 'duration 类型与 curve 点数两条均报');
      expect(diags.every((d) => d.code == MFCodes.motionTokenInvalid), isTrue);
    });

    testWidgets('基线 22：未声明动效面的入场请求被拒绝并记录；已声明面正常生效', (tester) async {
      final diags = <MFDiag>[];
      MFRenderContext ctxFor(Set<String> surfaces) => MFRenderContext(
            props: const {},
            onEvent: (_, _, [_]) {},
            tokenColor: (_) => const Color(0xFF0071E3),
            motionSurfaces: surfaces,
            resolveMotion: (token) => MFMotionResolution(
              spec: const MFMotionSpec(durationMs: 360, curve: [0.16, 1, 0.3, 1]),
              viaAlternative: false,
            ),
            recordMotionDiag: diags.add,
          );

      // 未声明 entrance 面：原样返回 + 记录。
      final denied = mfMotionEntrance(ctxFor(const {}), const Text('X'));
      expect(denied, isA<Text>(), reason: '未声明面不产生动效包装');
      expect(diags.map((d) => d.code), contains(MFCodes.motionSurfaceUndeclared));

      // 已声明 entrance 面：透明度动效包装生效。
      diags.clear();
      final applied = mfMotionEntrance(ctxFor(const {'entrance'}), const Text('Y'));
      expect(applied, isNot(isA<Text>()), reason: '声明面生成动效包装');
      expect(diags, isEmpty);
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: applied)));
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Y'), findsOneWidget);
    });
  });

  group('基线 23：减少动效偏好命中替代组时应用替代 Token 并记录（§36.7）', () {
    test('基线 23：resolveMotion 命中 .reduced 替代组——替代 Token 应用 + viaAlternative 标记', () {
      final resolver = MFStyleResolver(
        tokenSets: {'t': _tokens()},
        styleSheets: const {},
        themes: const {},
        defaultThemeId: 't',
      );
      final res = resolver.resolveMotion('motion.liquid', reduceMotion: true);
      expect(res.viaAlternative, isTrue, reason: '替代组命中须如实标记（供渲染侧记录）');
      expect(res.spec?.durationMs, 0);
      // 无替代组的 token：回落基础值，不虚报。
      final plain = resolver.resolveMotion('motion.entrance', reduceMotion: true);
      expect(plain.viaAlternative, isFalse);
      expect(plain.spec?.durationMs, 360);
    });

    test('基线 23：悬空替代组（缺同名基础 token）是静态错误（mf.motion.alternative-dangling）', () {
      final dangling = const MFTokenSet(id: 'dangling', tokens: {
        'motion.gone.reduced': {
          'duration': 0,
          'curve': [0, 0, 1, 1],
        },
      });
      final diags = validateMotionTokens([dangling]);
      expect(diags.single.code, MFCodes.motionAlternativeDangling);
    });

    test('基线 23：替代组命中经由渲染通道记录（mf.motion.alternative-applied）', () {
      final diags = <MFDiag>[];
      final ctx = MFRenderContext(
        props: const {},
        onEvent: (_, _, [_]) {},
        tokenColor: (_) => const Color(0xFF0071E3),
        motionSurfaces: const {'entrance'},
        resolveMotion: (token) => MFMotionResolution(
          spec: const MFMotionSpec(durationMs: 0, curve: [0, 0, 1, 1]),
          viaAlternative: true,
        ),
        recordMotionDiag: diags.add,
      );
      final out = mfMotionEntrance(ctx, const Text('Z'));
      expect(out, isA<Text>(), reason: '替代组 duration 0：无动画直出');
      expect(diags.map((d) => d.code), contains(MFCodes.motionAlternativeApplied),
          reason: '基线 23「并记录」');
    });
  });
}
