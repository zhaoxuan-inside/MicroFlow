/// Style & theme model (§36.3–§36.7): themes are bounded token redirections;
/// style sheets are extendable named units whose values may only reference
/// tokens; override chain is explicit and statically decidable.
library;

import 'diagnostics.dart';
import 'project.dart';

/// A theme (§36.3): projects onto a token base by redirecting part of the
/// token resolution results. Only existing tokens may be redirected, only
/// to same-type resolvable values; redirection cycles are a static error.
class MFTheme {
  const MFTheme({
    required this.id,
    this.base,
    this.extendsId,
    this.overrides = const {},
  });

  final String id;

  /// Token-set id this theme projects onto (§36.3).
  final String? base;

  /// Base theme id for `extends` chains (single parent, no cycles).
  final String? extendsId;

  /// token -> redirect: `{"ref": "color.base.gray.900"}`.
  final Map<String, Object?> overrides;
}

/// Style sheet variants (§36.4): declarative conditional sets; selectors
/// limited to state/platform/breakpoint with declared enums; same-condition
/// sets require an explicit order, ambiguous hits are a static error.
class MFStyleVariant {
  const MFStyleVariant({required this.when, required this.set, this.order = 0});
  final Map<String, String> when; // e.g. {'state': 'hover'} / {'platform': 'mobile'}
  final Map<String, String> set; // aspect -> token name
  final int order;
}

/// Style sheet (§36.4): a named reusable unit; values reference tokens only.
/// Style sheets extend via `extends` (chain must not loop).
class MFStyleSheet {
  const MFStyleSheet({
    required this.id,
    this.extendsId,
    this.base = const {},
    this.variants = const [],
    this.schemaVersion = '1.0',
  });

  final String id;
  final String? extendsId;
  final Map<String, String> base; // aspect -> token name
  final List<MFStyleVariant> variants;
  final String schemaVersion;
}

/// The override chain (§36.6): `Token < 组件默认样式片 < 页面覆盖 < 产品主题`.
/// Overrides only happen at declared tiers on declared (公开) style slots;
/// the chain decides uniquely, undecided conflicts are static errors.
enum MFOverrideTier { token, componentDefault, pageOverride, productTheme }

/// Chain resolution result for one aspect at one node.
class MFResolvedStyle {
  const MFResolvedStyle(this.token, this.value, this.tier);
  final String token; // resolved token name
  final Object? value; // resolved raw value (from tokens)
  final MFOverrideTier tier;

  bool get resolved => value != null;
}

/// Pure theme / style resolver shared by validators and renderers.
class MFStyleResolver {
  MFStyleResolver({
    required this.tokenSets,
    required Map<String, MFStyleSheet> styleSheets,
    required this.themes,
    required this.defaultThemeId,
  }) : styleSheets = Map.of(styleSheets);

  final Map<String, MFTokenSet> tokenSets;
  final Map<String, MFStyleSheet> styleSheets;
  final Map<String, MFTheme> themes;
  final String defaultThemeId;

  /// Effective token map for a theme (walk extends chain, apply overrides
  /// only for existing tokens). Bounded depth cuts cycles (static checker
  /// also reports them).
  Map<String, Object?> effectiveTokens(String themeId, {Set<String> visiting = const {}}) {
    if (visiting.contains(themeId)) return const {}; // cycle cut
    final theme = themes[themeId];
    if (theme == null) return rawTokens(tokenSets[themeId]);
    final effective = <String, Object?>{};
    final next = {...visiting, themeId};
    if (theme.base != null) {
      effective.addAll(rawTokens(tokenSets[theme.base!]));
    }
    if (theme.extendsId != null) {
      effective.addAll(effectiveTokens(theme.extendsId!, visiting: next));
    }
    // Merge own token-set contents (themes project on an own token base too).
    effective.addAll(rawTokens(tokenSets[themeId]));
    for (final e in theme.overrides.entries) {
      if (effective.containsKey(e.key)) {
        final v = e.value;
        // Themes redirect (§36.3): only `{"ref": other-token}` allowed.
        if (v is Map && v['ref'] is String) {
          effective[e.key] = effective[v['ref'] as String];
        } else {
          effective[e.key] = v;
        }
      }
    }
    return effective;
  }

  Map<String, Object?> rawTokens(MFTokenSet? set) => set?.tokens ?? const {};

  /// Theme resolution completeness (§36.3): each declared theme must resolve
  /// every referenced token; default theme completeness is a hard error.
  List<MFDiag> completenessDiagnostics({required Iterable<String> referencedTokens}) {
    final diags = <MFDiag>[];
    for (final themeId in themes.keys) {
      for (final token in referencedTokens) {
        if (effectiveTokens(themeId)[token] == null) {
          diags.add(MFDiag(MFCodes.themeIncomplete,
              '主题 $themeId 无法解析被引用 token $token（§36.3）'));
        }
      }
    }
    for (final token in referencedTokens) {
      if (effectiveTokens(defaultThemeId)[token] == null) {
        diags.add(
          MFDiag(MFCodes.themeIncomplete, '默认主题 $defaultThemeId 无法解析被引用 token $token'),
        );
      }
    }
    return diags;
  }

  /// Style sheet aspect resolution (§36.4/§36.6): sheet chain composes
  /// base-first; matched variants apply in declared order (last wins).
  /// `themeId` selects the token view (instance frozen theme, §36.3);
  /// falls back to the default theme.
  MFResolvedStyle resolveSheet(
    String sheetId,
    String aspect, {
    MFStyleConditions conditions = const {},
    Set<String> visiting = const {},
    String? themeId,
  }) {
    if (visiting.contains(sheetId)) {
      return MFResolvedStyle(aspect, null, MFOverrideTier.componentDefault);
    }
    final sheet = styleSheets[sheetId];
    if (sheet == null) return MFResolvedStyle(aspect, null, MFOverrideTier.componentDefault);
    final next = {...visiting, sheetId};
    final matches = sheet.variants
        .where((v) => MapStyleConditions(v.when).satisfiedBy(conditions))
        .toList()
      ..sort((a, b) => a.order.compareTo(b.order));
    for (final variant in matches.reversed) {
      final token = variant.set[aspect];
      if (token != null) return aspectResolved(token, themeId: themeId);
    }
    final baseToken = sheet.base[aspect];
    if (baseToken != null) return aspectResolved(baseToken, themeId: themeId);
    if (sheet.extendsId != null) {
      return resolveSheet(sheet.extendsId!, aspect, conditions: conditions, visiting: next, themeId: themeId);
    }
    return MFResolvedStyle(aspect, null, MFOverrideTier.componentDefault);
  }

  MFResolvedStyle aspectResolved(String token, {String? themeId}) =>
      MFResolvedStyle(token, effectiveTokens(themeId ?? defaultThemeId)[token], MFOverrideTier.componentDefault);

  /// Override chain: page overrides take precedence over component-default
  /// style sheet results (§36.6); product theme wins on token values. The
  /// chain evaluates against the instance's frozen theme (baseline 7).
  MFResolvedStyle resolveNode(
    String aspect, {
    String? styleSheetId,
    Map<String, String>? pageOverrides,
    String? themeId,
  }) {
    final theme = themeId ?? defaultThemeId;
    final effective = effectiveTokens(theme);
    // token < 组件默认样式片 < 页面覆盖 < 产品主题
    final pageAspect = pageOverrides?[aspect];
    if (pageAspect != null && effective[pageAspect] != null) {
      return MFResolvedStyle(pageAspect, effective[pageAspect], MFOverrideTier.pageOverride);
    }
    if (styleSheetId != null) {
      final r = resolveSheet(styleSheetId, aspect, themeId: themeId);
      if (r.resolved) return r;
    }
    final themeValue = effective[aspect];
    return MFResolvedStyle(aspect, themeValue, MFOverrideTier.productTheme);
  }
}

/// Style conditions at a point in time (renderer evaluation context).
typedef MFStyleConditions = Map<String, String?>;

/// Selector matching helper (§36.4: 限定 state/platform/breakpoint).
class MapStyleConditions {
  const MapStyleConditions(this.when);
  final Map<String, String> when;

  bool satisfiedBy(Map<String, String?> conditions) =>
      when.entries.every((e) => conditions[e.key] == e.value);
}

/// Static validation of a style-sheet pack (§36.4/§36.8): literal ban,
/// extends-chain dangling/cycle, variant selector ambiguity.
List<MFDiag> validateStyleSheets(Iterable<MFStyleSheet> sheets) {
  final diags = <MFDiag>[];
  final ids = {for (final s in sheets) s.id: s};
  for (final sheet in sheets) {
    for (final e in sheet.base.entries) {
      if (_looksLiteral(e.value)) {
        diags.add(MFDiag(MFCodes.styleLiteralInSheet,
            '样式片 ${sheet.id} 的 ${e.key} 使用字面量而非 token 引用（§36.4）'));
      }
    }
    for (final v in sheet.variants) {
      for (final e in v.set.entries) {
        if (_looksLiteral(e.value)) {
          diags.add(MFDiag(MFCodes.styleLiteralInSheet,
              '样式片 ${sheet.id} 变体 ${e.key} 使用字面量（§36.4）'));
        }
      }
    }
    // 同一变体选择器多次出现且未声明顺序 → 歧义（§36.4）。
    final unsorted = sheet.variants.where((v) => v.order == 0).toList();
    if (unsorted.length > 1 && _sameSelector(unsorted)) {
      diags.add(MFDiag(MFCodes.styleVariantAmbiguous, '样式片 ${sheet.id} 同一选择器命中多个 set 且顺序未声明'));
    }
    // extends chain: dangling & cycle.
    var cur = sheet;
    var hops = 0;
    while (cur.extendsId != null && hops++ < 16) {
      final parent = ids[cur.extendsId!];
      if (parent == null) {
        diags.add(MFDiag(MFCodes.refDangling, '样式片 ${sheet.id} 承接链悬空：${cur.extendsId}'));
        break;
      }
      if (parent.id == sheet.id) {
        diags.add(MFDiag(MFCodes.styleCycle, '样式片承接链循环：${sheet.id}'));
        break;
      }
      cur = parent;
    }
  }
  return diags;
}

bool _sameSelector(List<MFStyleVariant> variants) {
  if (variants.length < 2) return false;
  final first = variants.first.when.toString();
  return variants.skip(1).every((v) => v.when.toString() == first);
}

bool _looksLiteral(String tokenValue) => !tokenValue.contains('.');
