/// Project model (§4): the single source of truth for editors, AI and the
/// compiler/runtime. All resources carry stable ids (§4.2).
library;

import 'bindings.dart';
import 'contracts.dart';
import 'layout.dart';
import 'recovery.dart';
import 'styles.dart';
import 'tree.dart';

class MFManifest {
  const MFManifest({
    required this.projectId,
    this.modelVersion = '1.0',
    this.syntaxVersion = '1.0',
    this.targets = const ['web'],
    this.entryPage,
    this.defaultTheme,
    this.defaultLocale = 'zh-CN',
    this.supportedLocales = const ['zh-CN'],
    this.typeDialectVersion = '1.0',
  });

  final String projectId;
  final String modelVersion;
  final String syntaxVersion;
  final List<String> targets;
  final String? entryPage;
  final String? defaultTheme;
  final String defaultLocale;
  final List<String> supportedLocales;

  /// Unified type dialect version (§4.6): must resolve every Schema reference
  /// inside the release snapshot; an unsupported dialect fails the build.
  final String typeDialectVersion;
}

/// Dialect versions this implementation can resolve (§4.6). A manifest
/// declaring anything else fails static validation (baseline 14).
const List<String> mfSupportedTypeDialects = ['1.0'];

/// One controlled-crossing entry (§2.9): a config-rewrite surface an
/// experiment or ops-variant is allowed to touch.
class MFCrossingEntry {
  const MFCrossingEntry({required this.surface, required this.source});
  final String surface;

  /// Allowed config origin: `experiment` or `ops-variant` (§2.9).
  final String source;
}

/// Product-level controlled crossing list (§2.9): a versioned resource.
/// Rewrites not registered here are rejected statically
/// (`mf.exp.variant-out-of-scope`, baseline 32).
class MFControlledCrossingList {
  const MFControlledCrossingList({
    this.id = 'crossing-list',
    this.schemaVersion = '1.0',
    this.entries = const [],
  });

  final String id;
  final String schemaVersion;
  final List<MFCrossingEntry> entries;

  bool allows(String surface, String source) =>
      entries.any((e) => e.surface == surface && e.source == source);
}

/// Traceability of defined references (§4.3): component -> used_by, page ->
/// reachable_from, etc. The validator / back-reference index is built here.
class ReferenceIndex {
  final Map<String, Set<String>> _references = {};
  final Map<String, Set<String>> _usedBy = {};

  void record(String from, String to) {
    _references.putIfAbsent(from, () => {}).add(to);
    _usedBy.putIfAbsent(to, () => {}).add(from);
  }

  Set<String> usedBy(String id) => _usedBy[id] ?? const {};

  Set<String> referencesOf(String id) => _references[id] ?? const {};
}

/// A page definition: route, layer tree, page state, lifecycle event anchors,
/// platform variant and error boundary (§8).
class MFPage {
  const MFPage({
    required this.id,
    required this.route,
    required this.tree,
    this.stateMembers = const [],
    this.parameters = const {},
    this.onEnter,
    this.onLeave,
    this.errorBoundary,
    this.platformVariant = const {},
    this.info = const InfoContract(),
    this.pageOverrides = const {},
    this.layerRegions,
    this.conditionalLayouts = const [],
    this.findings = const [],
  });

  final String id;
  final String route;

  /// Page root node (layer tree is expressed through structural primitives;
  /// implicit ContentLayer, §7).
  final MFNode tree;

  /// Declared page-level state members; binding expressions referencing
  /// undeclared members are static errors (§37.2).
  final List<String> stateMembers;

  final Map<String, String> parameters; // param name -> type name
  final String? onEnter; // binding id executed on page enter
  final String? onLeave;
  final String? errorBoundary;
  final Map<String, String> platformVariant;
  final InfoContract info;

  /// Page-level style overrides (§36.6 页面覆盖层)。
  final Map<String, String> pageOverrides;

  /// Declared layer regions (§7.1/§12): region constraint + subcomponents.
  /// `null` = no explicit layer tree; the implicit ContentLayer rule
  /// applies (§7.5, baseline 12).
  final List<MFRegionConstraint>? layerRegions;

  /// Conditional layout schemes (§7.4) for targets within the page
  /// (baseline 20) — default plan is mandatory.
  final List<MFConditionalLayout> conditionalLayouts;

  /// findings 注记引用（§43.3）：本资源携带的 finding id 列表；引用必须
  /// 指向已登记的 finding 资源，自由文本替代是静态错误（基线 17）。
  final List<String> findings;

  /// Whether the implicit ContentLayer applies (§7.5 / baseline 12).
  bool get hasExplicitLayers => layerRegions != null && layerRegions!.isNotEmpty;

  /// 派生候选页面定义（findings 注记登记用，§43.3）。
  MFPage copyWith({List<String>? findings}) => MFPage(
        id: id,
        route: route,
        tree: tree,
        stateMembers: stateMembers,
        parameters: parameters,
        onEnter: onEnter,
        onLeave: onLeave,
        errorBoundary: errorBoundary,
        platformVariant: platformVariant,
        info: info,
        pageOverrides: pageOverrides,
        layerRegions: layerRegions,
        conditionalLayouts: conditionalLayouts,
        findings: findings ?? this.findings,
      );
}

/// Layer region constraint (§7): scroll/overlay relations and region banding
/// expressed as a declarative mount point; children resolve inside it.
class MFRegionConstraint {
  const MFRegionConstraint({
    required this.id,
    this.region = 'content',
    this.scroll = false,
    this.overlies = const [],
    this.constraint = const MFSelfConstraint(),
  });

  final String id;
  final String region; // content | header | footer | overlay
  final bool scroll;
  final List<String> overlies; // ids this layer overlays (declared)
  final MFSelfConstraint constraint;
}

/// Navigation graph (§9): nodes and edges derived from page routes; guards
/// and fallback declared here; checked statically (reachability etc).
class MFNavigationSpec {
  const MFNavigationSpec({this.edges = const [], this.fallback = const {}});
  final List<MFNavEdge> edges;
  final Map<String, String> fallback; // pageId -> fallback pageId
}

class MFNavEdge {
  const MFNavEdge({required this.from, required this.to, this.kind = 'push'});
  final String from;
  final String to;
  final String kind;
}

/// i18n catalog resource (§42.1): locale registry, fallback chain, messages.
class MFI18nCatalog {
  const MFI18nCatalog({
    this.defaultLocale = 'zh-CN',
    this.supportedLocales = const ['zh-CN'],
    this.fallback = const {},
    this.messages = const {},
  });

  final String defaultLocale;
  final List<String> supportedLocales;
  final Map<String, String> fallback;

  /// message id -> locale -> value (MessageFormat subset placeholders).
  final Map<String, Map<String, String>> messages;

  /// Compose message through the fallback chain; missing translation must be
  /// diagnosable (§42.5), returned as part of the result.
  ({String? text, bool fellBack}) resolve(String id, String locale, [Map<String, Object?> args = const {}]) {
    final variants = messages[id];
    if (variants == null) return (text: null, fellBack: false);
    var current = locale;
    final visited = <String>{};
    while (visited.add(current)) {
      final value = variants[current];
      if (value != null) {
        return (text: _interpolate(value, args), fellBack: current != locale);
      }
      if (current == defaultLocale) {
        final fallbackValue = variants[defaultLocale];
        return (
          text: fallbackValue != null ? _interpolate(fallbackValue, args) : null,
          fellBack: locale != defaultLocale,
        );
      }
      final next = fallback[current] ?? defaultLocale;
      if (next == current) break;
      current = next;
    }
    return (text: null, fellBack: false);
  }

  static String _interpolate(String template, Map<String, Object?> args) {
    var out = template;
    for (final e in args.entries) {
      out = out.replaceAll('{$e.key}', '${e.value}');
    }
    return out;
  }
}

/// Minimal token set (§36.2): named platform-neutral semantic values.
class MFTokenSet {
  const MFTokenSet({required this.id, this.tokens = const {}});
  final String id;

  /// token -> raw value; token refs use "ref" key.
  final Map<String, Object?> tokens;

  Object? resolve(String token, [int depth = 0]) {
    if (depth > 8) return null; // ref cycle -> unresolved
    final v = tokens[token];
    if (v is Map && v.containsKey('ref')) {
      return resolve(v['ref'] as String, depth + 1);
    }
    return v;
  }
}

/// 页面模板（§4、§2.7）：项目模型中的版本化资源，记录一组带参数的图层树、
/// 状态与绑定骨架。`create_page_from_template` 按参数实例化生成独立页面定义；
/// 模板修订不追溯改写已创建页面。节点 id 与字符串属性值中的 `{{param}}`
/// 在实例化时被参数值替换。
class MFPageTemplate {
  const MFPageTemplate({
    required this.id,
    required this.tree,
    this.routePrefix = '/',
    this.stateMembers = const [],
    this.parameters = const {},
    this.version = '1.0.0',
  });

  final String id;
  final MFNode tree;
  final String routePrefix;
  final List<String> stateMembers;

  /// 模板参数：参数名 -> 描述。实例化时必须提供全部声明参数，
  /// 未声明的参数是错误（配置构造封闭集合，§2.7）。
  final Map<String, String> parameters;
  final String version;
}

/// findings 注记资源（§43.3 数据回流闭环）：外部结论以结构化 Schema 登记，
/// 不得以自由文本替代；`regression-key` 类型必须绑定可执行的校验命令或
/// 用例引用，防止同类问题回归。findings 是版本化资源：修订产生新版本，
/// 历史 finding 保留墓碑（§22.3）。
class MFFinding {
  const MFFinding({
    required this.findingId,
    required this.findingType,
    required this.targetRef,
    this.schemaVersion = '1.0',
    this.sourceRef = '',
    this.summary = '',
    this.createdBy = '',
    this.checkRef,
  });

  /// 稳定 id（§4.2）。
  final String findingId;

  /// bug-cluster | experiment-conclusion | ops-alert | regression-key。
  final String findingType;
  final String schemaVersion;

  /// 来源分析系统、方法与时间（§43.3）。
  final String sourceRef;
  final String summary;

  /// 被注记的资源 id（页面、组件或交互绑定）。
  final String targetRef;
  final String createdBy;

  /// regression-key 必填：可执行校验命令或用例引用。
  final String? checkRef;
}

/// Top-level project model: every tool and the runtime operate on this object.
class MFProject {
  const MFProject({
    required this.manifest,
    required this.pages,
    this.components = const {},
    this.bindingMaps = const {},
    this.i18n = const MFI18nCatalog(),
    this.tokens = const {},
    this.styleSheets = const {},
    this.themes = const {},
    this.navigation = const MFNavigationSpec(),
    this.crossingList = const MFControlledCrossingList(),
    this.pageTemplates = const {},
    this.findings = const {},
    this.recoveryContracts = const {},
  });

  final MFManifest manifest;
  final List<MFPage> pages;
  final Map<String, MFComponentDefinition> components;
  final Map<String, MFBindingMap> bindingMaps;
  final MFI18nCatalog i18n;
  final Map<String, MFTokenSet> tokens;
  final Map<String, MFStyleSheet> styleSheets;
  final Map<String, MFTheme> themes;
  final MFNavigationSpec navigation;

  /// Product-level controlled crossing list (§2.9, baseline 32).
  final MFControlledCrossingList crossingList;

  /// Page templates (§4、§2.7): versioned resources for config construction.
  final Map<String, MFPageTemplate> pageTemplates;

  /// findings 注记资源（§43.3，基线 17）：finding_id -> 资源。
  final Map<String, MFFinding> findings;

  /// Recovery Contract（§16.1）：id -> 契约资源；运行时按契约执行恢复，
  /// 契约缺失时禁止恢复（§22.1）。
  final Map<String, MFRecoveryContract> recoveryContracts;

  /// 派生候选项目（§14 结构化命令的构造路径）：未给出的字段保持原引用
  /// （不可变对象共享），给出则替换。
  MFProject copyWith({
    MFManifest? manifest,
    List<MFPage>? pages,
    Map<String, MFComponentDefinition>? components,
    Map<String, MFBindingMap>? bindingMaps,
    MFI18nCatalog? i18n,
    Map<String, MFTokenSet>? tokens,
    Map<String, MFStyleSheet>? styleSheets,
    Map<String, MFTheme>? themes,
    MFNavigationSpec? navigation,
    MFControlledCrossingList? crossingList,
    Map<String, MFPageTemplate>? pageTemplates,
    Map<String, MFFinding>? findings,
    Map<String, MFRecoveryContract>? recoveryContracts,
  }) =>
      MFProject(
        manifest: manifest ?? this.manifest,
        pages: pages ?? this.pages,
        components: components ?? this.components,
        bindingMaps: bindingMaps ?? this.bindingMaps,
        i18n: i18n ?? this.i18n,
        tokens: tokens ?? this.tokens,
        styleSheets: styleSheets ?? this.styleSheets,
        themes: themes ?? this.themes,
        navigation: navigation ?? this.navigation,
        crossingList: crossingList ?? this.crossingList,
        pageTemplates: pageTemplates ?? this.pageTemplates,
        findings: findings ?? this.findings,
        recoveryContracts: recoveryContracts ?? this.recoveryContracts,
      );

  MFPage? page(String id) => pages.fold(null, (r, p) => r == null && p.id == id ? p : r);

  MFBinding? findBinding(String bindingId) {
    for (final map in bindingMaps.values) {
      for (final b in map.bindings) {
        if (b.id == bindingId) return b;
      }
    }
    return null;
  }

  List<MFBinding> bindingsFor(String eventKey) {
    final result = <MFBinding>[];
    for (final map in bindingMaps.values) {
      for (final b in map.bindings) {
        if (b.on == eventKey) result.add(b);
      }
    }
    return result;
  }
}

/// Model-composition component definition (§6) built from the node tree.
class MFComponentDefinition {
  const MFComponentDefinition({
    required this.id,
    required this.tree,
    required this.contract,
    this.version = '1.0.0',
    this.description = '',
    this.findings = const [],
  });

  final String id;
  final MFNode tree;
  final ComponentContract contract;

  /// Model-composition components don't carry an implementation pointer;
  /// host-implementation components registered via `registerComponent`
  /// provide theirs through the implementation loader contract.
  final String version;
  final String description;

  /// findings 注记引用（§43.3）：见 [MFPage.findings]。
  final List<String> findings;

  Iterable<MFNode> walkRaw() => tree.flatten();

  /// 派生候选组件定义（findings 注记登记用，§43.3）。
  MFComponentDefinition copyWith({List<String>? findings}) => MFComponentDefinition(
        id: id,
        tree: tree,
        contract: contract,
        version: version,
        description: description,
        findings: findings ?? this.findings,
      );
}

/// Static impact-collector: records model-object references (§4.3).
void collectTreeRefs(ReferenceIndex index, String owner, Iterable<MFNode> trees) {
  for (final node in trees.expand((t) => t.flatten())) {
    index.record(owner, node.type);
  }
}
