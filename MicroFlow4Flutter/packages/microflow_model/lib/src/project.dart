/// Project model (§4): the single source of truth for editors, AI and the
/// compiler/runtime. All resources carry stable ids (§4.2).
library;

import 'bindings.dart';
import 'contracts.dart';
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
  });

  final String projectId;
  final String modelVersion;
  final String syntaxVersion;
  final List<String> targets;
  final String? entryPage;
  final String? defaultTheme;
  final String defaultLocale;
  final List<String> supportedLocales;
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

/// Top-level project model: every tool and the runtime operate on this object.
class MFProject {
  const MFProject({
    required this.manifest,
    required this.pages,
    this.components = const {},
    this.bindingMaps = const {},
    this.i18n = const MFI18nCatalog(),
    this.tokens = const {},
    this.navigation = const MFNavigationSpec(),
  });

  final MFManifest manifest;
  final List<MFPage> pages;
  final Map<String, MFComponentDefinition> components;
  final Map<String, MFBindingMap> bindingMaps;
  final MFI18nCatalog i18n;
  final Map<String, MFTokenSet> tokens;
  final MFNavigationSpec navigation;

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
  });

  final String id;
  final MFNode tree;
  final ComponentContract contract;

  /// Model-composition components don't carry an implementation pointer;
  /// host-implementation components registered via `registerComponent`
  /// provide theirs through the implementation loader contract.
  final String version;
  final String description;

  Iterable<MFNode> walkRaw() => tree.flatten();
}

/// Static impact-collector: records model-object references (§4.3).
void collectTreeRefs(ReferenceIndex index, String owner, Iterable<MFNode> trees) {
  for (final node in trees.expand((t) => t.flatten())) {
    index.record(owner, node.type);
  }
}
