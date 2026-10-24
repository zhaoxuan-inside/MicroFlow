/// Declarative node tree (§6): a pure structural description.
///
/// Nodes reference registered primitives/components by `type`, bind props
/// through structured references and only reach styling/interaction through
/// their declared surfaces. No executable logic is inlined (§2.9).
library;

import 'layout.dart';

class MFNode {
  const MFNode({
    required this.id,
    required this.type,
    this.props = const {},
    this.slotOf,
    this.children = const [],
    this.slots = const {},
    this.t,
    this.style,
    this.constraints,
    this.layer,
  });

  /// Node id, unique within its defining tree; used as binding event anchor
  /// and identity seed for `component_instance_id`.
  final String id;

  /// Registered primitive or component id (`mf.reg.unregistered-ref` when
  /// it cannot be resolved).
  final String type;

  /// Structured prop values: literal JSON or `{"ref": "scope.path"}`.
  final Map<String, Object?> props;

  /// When this node sits inside a parent's slot: parent slot name (§23.9).
  final String? slotOf;

  /// Mixed children (composed into the default/only slot).
  final List<MFNode> children;

  /// Named slots -> child nodes.
  final Map<String, List<MFNode>> slots;

  /// i18n message reference for text-bearing nodes (§42.2). `t` and a bound
  /// text value are mutually exclusive (§42.2 rule).
  final String? t;

  /// Style sheet reference (§36.4). Literal aspects never appear here;
  /// values resolve through the (§36.6) coverage chain.
  final String? style;

  /// Node self constraint (§7.2); `null` means hug both axes (default for
  /// simple nodes) with no extra bounds.
  final MFSelfConstraint? constraints;

  /// 显式图层归属（§7.1）：本节点落入页面 `layerRegions` 中 id 匹配的分区
  /// （header/footer/overlay/content）；未声明时顶层节点按 id 匹配分区，
  /// 其余进 ContentLayer。引用不存在的分区 id 是静态错误（mf.ref.dangling）。
  final String? layer;

  /// Depth-first search for a node by id within this subtree.
  MFNode? find(String nodeId) {
    if (id == nodeId) return this;
    final inChildren = children.fold<MFNode?>(null, (r, n) => r ?? n.find(nodeId));
    if (inChildren != null) return inChildren;
    return slots.values
        .fold<MFNode?>(null, (r, list) => r ?? _findInList(list, nodeId));
  }

  /// Collect all nodes in this subtree (depth-first, declaration order).
  List<MFNode> flatten() => [
        this,
        ...children.expand((n) => n.flatten()),
        ...slots.values.expand(_flattenList),
      ];

  static List<MFNode> _flattenList(Iterable<MFNode> list) =>
      list.expand((n) => n.flatten()).toList(growable: false);

  static MFNode? _findInList(Iterable<MFNode> list, String nodeId) =>
      list.fold<MFNode?>(null, (r, n) => r ?? n.find(nodeId));
}

/// Search across multiple roots.
MFNode? findNode(Iterable<MFNode> roots, String id) =>
    roots.fold<MFNode?>(null, (r, n) => r ?? n.find(id));
