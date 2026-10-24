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
import 'layout_solver.dart';

class MFValidationResult {
  MFValidationResult(this.diagnostics);
  final List<MFDiag> diagnostics;

  bool get ok => !diagnostics.any((d) => d.severity == Severity.error);

  /// §4.3 可追踪引用的反向索引：resource -> 影响对象（used_by）。
  final ReferenceIndex index = ReferenceIndex();

  /// §43.3 findings 校验报告：本次校验显式列出全部 findings 注记及其目标，
  /// 供回归基线与下一版修订消费（基线 17）。
  final List<Map<String, String?>> findingsReport = [];
}

class MFValidator {
  const MFValidator({
    required this.project,
    required this.registry,
    this.developingLocale,
    this.variantRewrites = const [],
  });

  final MFProject project;
  final MFRegistry registry;
  final String? developingLocale;

  /// Variant rewrite surfaces declared by the config plane (experiments or
  /// ops-variants, §24.4). Each must be registered in the product-level
  /// controlled crossing list (§2.9, baseline 32) or validation fails.
  final List<MFCrossingEntry> variantRewrites;

  /// 样式静态检查（§36.4/§36.8）：字面量禁令、承接链、主题完整性。
  void _validateStyles(List<MFDiag> diags) {
    diags.addAll(validateStyleSheets(project.styleSheets.values));
    final referencedTokens = <String>{
      for (final sheet in project.styleSheets.values) ...sheet.base.values,
      for (final sheet in project.styleSheets.values)
        for (final v in sheet.variants) ...v.set.values,
    };
    defaultThemeResolver().completenessDiagnostics(referencedTokens: referencedTokens).forEach(diags.add);
  }

  MFStyleResolver defaultThemeResolver() => MFStyleResolver(
        tokenSets: Map.of(project.tokens),
        styleSheets: Map.of(project.styleSheets),
        themes: Map.of(project.themes),
        defaultThemeId: project.manifest.defaultTheme ??
            (project.tokens.keys.isEmpty ? 'theme-default' : project.tokens.keys.first),
      );

  /// 布局静态检查（§7.5，基线 19/20/21 静态面）并入启动门禁。
  void _validateLayout(List<MFDiag> diags) {    final constraints = <MFDeclaredConstraint>[];
    final conditionalLayouts = <MFConditionalLayout>[];
    for (final page in project.pages) {
      for (final r in page.layerRegions ?? const <MFRegionConstraint>[]) {
        constraints.add(MFDeclaredConstraint(
          ownerId: '${page.id}/${r.id}',
          constraint: r.constraint,
          capabilityId: r.region,
          overlies: r.overlies,
        ));
      }
      conditionalLayouts.addAll(page.conditionalLayouts);
    }
    diags.addAll(staticLayoutChecks(
      constraints: constraints,
      conditionalLayouts: conditionalLayouts,
      targetProfiles: const [mfDefaultPlatformProfile],
    ));
  }

  MFValidationResult validate() {
    final diags = <MFDiag>[];
    final result = MFValidationResult(diags);
    _validateTypeDialect(diags);
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
    _validateBindings(diags);
    diags.addAll(registry.deprecationWarnings());
    _validateConsumableDependencies(diags);
    _validateStyles(diags);
    _validateLayout(diags);
    _validateCrossing(diags);
    _validateRecovery(diags);
    _validateTelemetryAnnotations(diags);
    _validateFindings(diags, result);
    return result;
  }

  /// Recovery contract gate (§16.1): `unknown_side_effects.auto_retry` is
  /// pinned false (baseline 27); declaring true fails the build.
  void _validateRecovery(List<MFDiag> diags) {
    for (final c in project.recoveryContracts.values) {
      if (c.unknownSideEffectsAutoRetry) {
        diags.add(MFDiag(MFCodes.buildRecoveryAutoRetry, '恢复契约 ${c.id} 声明 auto_retry=true（§16.1 固定 false，基线 27）'));
      }
    }
  }

  /// 采集注记静态校验（§24.7）：引用的事件必须已登记（标准运营事件族或
  /// diag. 诊断命名），隐私分类与采样策略必须通过检查；违例是静态错误
  /// （基线 8 的静态面）。
  void _validateTelemetryAnnotations(List<MFDiag> diags) {
    for (final entry in registry.all()) {
      final a = entry.contract.telemetry;
      if (a == null) continue;
      for (final e in a.events.entries) {
        final event = e.value;
        // 已登记事件：标准运营事件族（§24.2）、ops./diag. 命名空间下的产品
        // 登记事件（§24.7 示例口径，§41.1 命名空间纪律）。
        final registered = MFStandardEvents.all.contains(event) ||
            event.startsWith('ops.') ||
            event.startsWith('diag.');
        if (!registered) {
          diags.add(MFDiag(MFCodes.teleAnnotationInvalid, '资源 ${entry.id} 注记触点 ${e.key} 引用未登记事件 $event（§24.7）'));
        }
      }
      if (!mfAllowedPrivacyClasses.contains(a.privacyClass)) {
        diags.add(MFDiag(MFCodes.teleAnnotationInvalid, '资源 ${entry.id} 注记隐私分类 ${a.privacyClass} 非法（§24.2）'));
      }
      final r = a.samplingRatio;
      if (r != null && (r <= 0 || r > 1)) {
        diags.add(MFDiag(MFCodes.teleAnnotationInvalid, '资源 ${entry.id} 注记采样比例 $r 非法（应为 (0,1]）'));
      }
    }
  }

  /// findings 回流门禁（§43.3，基线 17）：结构化登记、引用可解析、
  /// regression-key 必须绑定可执行校验；自由文本替代（未登记引用）是静态
  /// 错误。全部通过后在校验报告中显式列出（回归基线消费面）。
  void _validateFindings(List<MFDiag> diags, MFValidationResult result) {
    const findingTypes = {'bug-cluster', 'experiment-conclusion', 'ops-alert', 'regression-key'};
    final bindingIds = <String>{for (final m in project.bindingMaps.values) for (final b in m.bindings) b.id};
    void checkRefs(String owner, List<String> refs) {
      for (final id in refs) {
        if (!project.findings.containsKey(id)) {
          diags.add(MFDiag(MFCodes.refDangling, '$owner 携带的 findings 引用 $id 未登记（§43.3，自由文本替代非法）'));
        }
      }
    }

    for (final page in project.pages) {
      checkRefs('页面 ${page.id}', page.findings);
    }
    for (final comp in project.components.values) {
      checkRefs('组件 ${comp.id}', comp.findings);
    }
    for (final map in project.bindingMaps.values) {
      for (final b in map.bindings) {
        checkRefs('绑定 ${b.id}', b.findings);
      }
    }
    for (final f in project.findings.values) {
      if (!findingTypes.contains(f.findingType)) {
        diags.add(MFDiag(MFCodes.regFindingInvalid, 'finding ${f.findingId} 类型 ${f.findingType} 非法（§43.3）'));
      }
      if (f.findingType == 'regression-key' && (f.checkRef == null || f.checkRef!.isEmpty)) {
        diags.add(MFDiag(MFCodes.regFindingInvalid, 'finding ${f.findingId} 为 regression-key 但未绑定可执行校验（§43.3）'));
      }
      final resolvable = project.page(f.targetRef) != null ||
          project.components.containsKey(f.targetRef) ||
          bindingIds.contains(f.targetRef);
      if (!resolvable) {
        diags.add(MFDiag(MFCodes.refDangling, 'finding ${f.findingId} 的 target_ref ${f.targetRef} 不可解析（§43.3）'));
      }
      result.findingsReport.add({
        'finding': f.findingId,
        'finding_type': f.findingType,
        'target': f.targetRef,
        'check_ref': f.checkRef,
      });
    }
  }

  /// Type dialect (§4.6, baseline 14): the manifest dialect must be one this
  /// implementation can resolve; otherwise the build fails.
  void _validateTypeDialect(List<MFDiag> diags) {
    if (!mfSupportedTypeDialects.contains(project.manifest.typeDialectVersion)) {
      diags.add(MFDiag(
        MFCodes.schemaDialectUnsupported,
        '类型方言 ${project.manifest.typeDialectVersion} 不受支持（支持：${mfSupportedTypeDialects.join(', ')}）',
      ));
    }
  }

  /// Controlled crossing gate (§2.9, baseline 32, static part): every
  /// config-plane rewrite must be registered with the same surface and source.
  void _validateCrossing(List<MFDiag> diags) {
    for (final rewrite in variantRewrites) {
      if (rewrite.source != 'experiment' && rewrite.source != 'ops-variant') {
        diags.add(MFDiag(MFCodes.expVariantOutOfScope,
            '改写面 ${rewrite.surface} 的配置来源 ${rewrite.source} 非法（experiment | ops-variant）'));
        continue;
      }
      if (!project.crossingList.allows(rewrite.surface, rewrite.source)) {
        diags.add(MFDiag(MFCodes.expVariantOutOfScope,
            '改写面 ${rewrite.surface}（来源 ${rewrite.source}）未登记入受控交叉清单'));
      }
    }
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
  }

  void _validateTree(MFNode tree, String ownerId, List<MFDiag> diags, MFValidationResult result) {
    for (final node in tree.flatten()) {
      if (!registry.has(node.type) && !project.components.containsKey(node.type)) {
        diags.add(MFDiag(MFCodes.regUnregisteredRef, '未注册的节点类型 ${node.type}（owner=$ownerId）'));
      }
      if (node.t != null && node.props.containsKey('text')) {
        diags.add(MFDiag(MFCodes.i18nChannelConflict, '节点 ${node.id} 同时声明 t 与 text（§42.2）'));
      }
      // Three-plane separation (§2.9, baseline 31, static part): the structure
      // tree may only carry structural/style/binding resources — inline
      // executable logic in prop values is rejected.
      _rejectInlineLogic(node, ownerId, diags);
      result.index.record(ownerId, node.type);
    }
  }

  /// Structured prop values are literals or `{"ref": ...}` (tree.dart); any
  /// executable-logic shape (`call`/`eval`/`script`/`exec`) is a violation.
  void _rejectInlineLogic(MFNode node, String ownerId, List<MFDiag> diags) {
    void walk(Object? value) {
      if (value is Map) {
        for (final key in const ['call', 'eval', 'script', 'exec']) {
          if (value.containsKey(key)) {
            diags.add(MFDiag(MFCodes.schemaInlineLogic,
                '节点 ${node.id} 的属性内联可执行逻辑（$key）（owner=$ownerId，§2.9）'));
            return;
          }
        }
        value.values.forEach(walk);
      } else if (value is List) {
        value.forEach(walk);
      }
    }

    node.props.values.forEach(walk);
  }

  void _validateConsumableDependencies(List<MFDiag> diags) {
    // Provided/consumed dependency reachability (baseline 16): a required
    // consume must resolve to the page's own provides, an upstream container
    // provides declared in the page tree's component contracts (§2.8), or a
    // registered i18n message id; unresolvable required consumes are ghost
    // dependencies (static error).
    for (final page in project.pages) {
      final upstreamProvides = <String>{};
      for (final node in page.tree.flatten()) {
        upstreamProvides.addAll(_contractOf(node.type)?.info.provides.keys ?? const <String>{});
      }
      page.info.consumes.forEach((infoId, required) {
        final resolvable = page.info.provides.containsKey(infoId) ||
            upstreamProvides.contains(infoId) ||
            project.i18n.messages.containsKey(infoId);
        if (!resolvable && required) {
          diags.add(MFDiag(MFCodes.stateGhostDependency, '页面 ${page.id} 消费的信息 $infoId 不可解析'));
        }
      });
    }
  }

  /// 绑定图校验（§39.3）：绑定锚点是跨对象键（§39），解析范围是全项目
  /// 页面树与组件树——与运行时 dispatchEvent 的全局解析一致；不逐页重复
  /// 检查。状态成员引用按锚点所属页面校验。
  void _validateBindings(List<MFDiag> diags) {
    final nodes = <String, MFNode>{};
    final ownerPage = <String, String>{};
    for (final p in project.pages) {
      for (final n in p.tree.flatten()) {
        nodes[n.id] = n;
        ownerPage[n.id] = p.id;
      }
    }
    for (final c in project.components.values) {
      for (final n in c.tree.flatten()) {
        nodes.putIfAbsent(n.id, () => n);
      }
    }
    for (final map in project.bindingMaps.values) {
      for (final binding in map.bindings) {
        final anchor = binding.on.split('.');
        if (anchor.length < 2) {
          diags.add(MFDiag(MFCodes.bindingEventUnknown, '绑定 ${binding.id} 的 on 形式非法'));
          continue;
        }
        final nodeId = anchor.sublist(0, anchor.length - 1).join('.');
        final event = anchor.last;
        final node = nodes[nodeId];
        if (node == null) {
          diags.add(MFDiag(MFCodes.bindingEventUnknown, '绑定 ${binding.id} 的目标节点 $nodeId 不存在'));
          continue;
        }
        final contract = _contractOf(node.type);
        if (contract != null && !contract.declaresEvent(event)) {
          diags.add(MFDiag(MFCodes.bindingEventUnknown, '事件 $event 未在 ${node.type} 契约中声明（binding=${binding.id}）'));
        }
        if (binding.policy == MFPolicy.undeclared) {
          diags.add(MFDiag(MFCodes.bindingNoConcurrency, '绑定 ${binding.id} 未声明并发策略，将拒绝重复触发（基线 26）'));
        }
        final pageId = ownerPage[nodeId] ??
            project.manifest.entryPage ??
            (project.pages.isEmpty ? null : project.pages.first.id);
        final page = pageId == null ? null : project.page(pageId);
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

  void _checkRefPath(String path, MFPage? page, String bindingId, List<MFDiag> diags) {
    final parts = path.split('.');
    final root = parts.first;
    if (root == 'state') {
      final member = parts.length > 1 ? parts[1] : null;
      if (page != null && (member == null || member.isEmpty || !page.stateMembers.contains(member))) {
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
