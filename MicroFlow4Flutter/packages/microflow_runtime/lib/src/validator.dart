/// Static validation (§18.1 subset) over the runtime module's model shape.
///
/// Checks are anchored on the §44.3 consistency baseline items a static
/// checker can decide: unregistered refs (13/15), binding existence &
/// event declaration, concurrency declaration (26), navigation reachability
/// and entry existence, container info consumption reachability
/// (§2.8 ghost dependency, baseline 16), i18n message references (§42),
/// text `t` vs bind exclusivity (§42.2) and action result references.
library;

import 'package:microflow_model/microflow_model.dart';

import 'registry.dart';

class MFValidationResult {
  MFValidationResult(this.diagnostics);
  final List<MFDiag> diagnostics;

  bool get ok => !diagnostics.any((d) => d.severity == Severity.error);

  /// §4.3 可追踪引用的反向索引：resource -> 影响对象（used_by）。
  final ReferenceIndex index = ReferenceIndex();
}

class MFValidator {
  const MFValidator({
    required this.project,
    required this.registry,
    this.developingLocale,
  });

  final MFProject project;
  final MFRegistry registry;
  final String? developingLocale;

  MFValidationResult validate() {
    final diags = <MFDiag>[];
    final result = MFValidationResult(diags);
    _validateRouting(diags);
    for (final page in project.pages) {
      _validatePage(page, diags, result);
    }
    for (final comp in project.components.values) {
      _validateTree(comp.tree, comp.id, diags, result);
    }
    for (final map in project.bindingMaps.values) {
      _validateBindingMap(map, diags);
    }
    diags.addAll(registry.deprecationWarnings());
    _validateConsumableDependencies(diags);
    return result;
  }

  void _validateRouting(List<MFDiag> diags) {
    if (project.manifest.entryPage == null) return; // 不声明入口时跳过
    bool entryFound = false;
    for (final page in project.pages) {
      if (page.id == project.manifest.entryPage) {
        entryFound = true;
        break;
      }
    }
    if (project.pages.isNotEmpty && !entryFound) {
      diags.add(MFDiag(MFCodes.navEntryMissing, '入口页面未在项目中注册'));
    }
    for (final page in project.pages) {
      if (page.id == project.manifest.entryPage) {
        continue;
      }
      if (!_followsFromEntry(page)) {
        diags.add(MFDiag(MFCodes.navIsolatedPage, '页面 ${page.id} 从入口不可达'));
      }
    }
  }

  bool _followsFromEntry(MFPage page) {
    final entry = project.manifest.entryPage;
    if (entry == null) return true;
    final visited = <String>{};
    bool walk(String from) {
      if (!visited.add(from)) return false;
      for (final edge in project.navigation.edges) {
        if (edge.from == from) {
          if (edge.to == page.id) return true;
          if (walk(edge.to)) return true;
        }
      }
      return false;
    }

    return walk(entry);
  }

  void _validatePage(MFPage page, List<MFDiag> diags, MFValidationResult result) {
    _validateTree(page.tree, page.id, diags, result);
    if (page.onEnter != null && project.findBinding(page.onEnter!) == null) {
      diags.add(MFDiag(MFCodes.refDangling, 'onEnter 引用的绑定 ${page.onEnter} 不存在（page=${page.id}）'));
    }
    if (page.onLeave != null && project.findBinding(page.onLeave!) == null) {
      diags.add(MFDiag(MFCodes.refDangling, 'onLeave 引用的绑定 ${page.onLeave} 不存在（page=${page.id}）'));
    }
    for (final node in page.tree.flatten()) {
      result.index.record(page.id, node.type);
    }
    _validateBindingsFor(page, diags);
  }

  void _validateTree(MFNode tree, String ownerId, List<MFDiag> diags, MFValidationResult result) {
    for (final node in tree.flatten()) {
      if (!registry.has(node.type) && !project.components.containsKey(node.type)) {
        diags.add(MFDiag(MFCodes.regUnregisteredRef, '未注册的节点类型 ${node.type}（owner=$ownerId）'));
      }
      if (node.t != null && node.props.containsKey('text')) {
        diags.add(MFDiag(MFCodes.i18nChannelConflict, '节点 ${node.id} 同时声明 t 与 text（§42.2）'));
      }
      result.index.record(ownerId, node.type);
    }
  }

  void _validateConsumableDependencies(List<MFDiag> diags) {
    // Provided/consumed dependency reachability across pages (baseline 16):
    // a page that requires to consume must resolve to its own provides or
    // registered i18n message ids; unresolvable required consumes are ghost
    // dependencies (static error).
    for (final page in project.pages) {
      page.info.consumes.forEach((infoId, required) {
        final resolvable = page.info.provides.containsKey(infoId) || project.i18n.messages.containsKey(infoId);
        if (!resolvable && required) {
          diags.add(MFDiag(MFCodes.stateGhostDependency, '页面 ${page.id} 消费的信息 $infoId 不可解析'));
        }
      });
    }
  }

  void _validateBindingsFor(MFPage page, List<MFDiag> diags) {
    for (final map in project.bindingMaps.values) {
      for (final binding in map.bindings) {
        final anchor = binding.on.split('.');
        if (anchor.length < 2) {
          diags.add(MFDiag(MFCodes.bindingEventUnknown, '绑定 ${binding.id} 的 on 形式非法'));
          continue;
        }
        final nodeId = anchor.sublist(0, anchor.length - 1).join('.');
        final event = anchor.last;
        final node = page.tree.find(nodeId);
        if (node == null) {
          diags.add(MFDiag(MFCodes.bindingEventUnknown, '绑定 ${binding.id} 的目标节点 $nodeId 不存在（page=${page.id}）'));
          continue;
        }
        final contract = _contractOf(node.type);
        if (contract != null && !contract.declaresEvent(event)) {
          diags.add(MFDiag(MFCodes.bindingEventUnknown, '事件 $event 未在 ${node.type} 契约中声明（binding=${binding.id}）'));
        }
        if (binding.policy == MFPolicy.undeclared) {
          diags.add(MFDiag(MFCodes.bindingNoConcurrency, '绑定 ${binding.id} 未声明并发策略，将拒绝重复触发（基线 26）'));
        }
        final refs = <String>[];
        if (binding.guard != null) {
          refs.addAll(binding.guard!.refPaths());
        }
        for (final action in binding.actions) {
          if (action is MFStateAction) {
            refs.addAll(action.value.refPaths());
          }
          if (action is MFNavigationAction) {
            for (final a in action.arguments.values) {
              refs.addAll(a.refPaths());
            }
            if (project.page(action.target) == null) {
              diags.add(MFDiag(MFCodes.navUnknownTarget, '绑定 ${binding.id} 导航目标 ${action.target} 不存在'));
            }
          }
          if (action is MFAdapterAction && !registry.has(action.call)) {
            diags.add(MFDiag(MFCodes.regUnregisteredRef, '绑定 ${binding.id} 调用未注册的 ${action.kind}：${action.call}'));
          }
        }
        for (final path in refs) {
          _checkRefPath(path, page, binding.id, diags);
        }
        // Result references must point at a declared `as` (§39.1).
        final declaredAs = {'last'};
        for (final action in binding.actions) {
          if (action is MFAdapterAction && action.as != null) {
            declaredAs.add(action.as!);
          }
        }
        for (final action in binding.actions) {
          if (action is! MFStateAction) continue;
          for (final path in action.value.refPaths()) {
            if (path.startsWith('prev.') && !path.startsWith('prev.last')) {
              final name = path.split('.')[1];
              if (!declaredAs.contains(name)) {
                diags.add(MFDiag(MFCodes.bindingResultUnknown, '绑定 ${binding.id} 引用了未声明的动作结果 $name'));
              }
            }
          }
        }
      }
    }
  }

  void _validateBindingMap(MFBindingMap map, List<MFDiag> diags) {
    final seenIds = <String>{};
    for (final b in map.bindings) {
      if (!seenIds.add(b.id)) {
        diags.add(MFDiag(MFCodes.unknownField, '绑定 id 重复：${b.id}（map=${map.id}）'));
      }
    }
  }

  void _checkRefPath(String path, MFPage page, String bindingId, List<MFDiag> diags) {
    final parts = path.split('.');
    final root = parts.first;
    if (root == 'state') {
      final member = parts.length > 1 ? parts[1] : null;
      if (member == null || member.isEmpty || !page.stateMembers.contains(member)) {
        diags.add(MFDiag(MFCodes.interactionUnknownMember, '页面状态未声明成员 $path（binding=$bindingId）'));
      }
      if (parts.length > 2) {
        diags.add(MFDiag(MFCodes.stateWritebackDenied, '状态路径过深引用 $path（binding=$bindingId）', severity: Severity.warning));
      }
    }
    if (root == 'session' && parts.length > 2) {
      diags.add(MFDiag(MFCodes.interactionUnknownMember, '会话状态引用过深 $path（binding=$bindingId）', severity: Severity.warning));
    }
  }

  ComponentContract? _contractOf(String typeId) {
    final registered = registry.entry(typeId);
    if (registered != null) return registered.contract;
    final comp = project.components[typeId];
    return comp?.contract;
  }
}
