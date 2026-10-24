/// 结构化命令面（frontend-framework-design §14、§19 阶段六）。
///
/// Vibe Coding 的第一类对象不是文件，而是项目模型中的资源：编辑器、CLI 与
/// AI Agent 必须通过本会话的结构化命令修改模型，每次命令产生修改目标、
/// 前后摘要、影响对象、验证结果与可回滚修订（§14）。命令落地的候选项目
/// 先走与发布相同的静态校验门禁（§2.7「纯配置创建不降低任何门禁」），
/// 含静态错误时项目保持原样 —— 不存在免门禁的通道。
library;

import 'package:microflow_model/microflow_model.dart';
import 'package:microflow_runtime/microflow_runtime.dart';

/// 一次修订的审计记录（§14）。快照以不可变对象引用保存：回滚即恢复引用，
/// 审计记录本身不删除（§32）。
class MFRevision {
  MFRevision({
    required this.id,
    required this.command,
    required this.actor,
    required this.beforeSummary,
    required this.afterSummary,
    required this.snapshotBefore,
    required this.at,
  });

  final int id;
  final String command;
  final String actor;
  final String beforeSummary;
  final String afterSummary;

  /// 回滚锚点：修订前的完整项目模型（不可变对象）。
  final MFProject snapshotBefore;
  final DateTime at;
}

/// 结构化命令的执行结果（§14 的修改回执）。
class MFCommandResult {
  const MFCommandResult({
    required this.command,
    required this.ok,
    required this.diagnostics,
    required this.affected,
    required this.actor,
    this.targetId,
    this.beforeSummary,
    this.afterSummary,
    this.revision,
  });

  /// create_page | create_page_from_template | validate_project |
  /// inspect_impact（§14 命令面子集）。
  final String command;
  final String? targetId;
  final bool ok;

  /// ok=false 时为阻断性静态错误；ok=true 时为 warning 级诊断。
  final List<MFDiag> diagnostics;

  /// 反向索引命中的影响对象（§4.3）：引用了 target 的容器。
  final Set<String> affected;
  final String actor;
  final String? beforeSummary;
  final String? afterSummary;
  final MFRevision? revision;
}

/// 影响分析报告（§14 `inspect_impact`，§4.3 反向索引）。
class MFImpactReport {
  const MFImpactReport({
    required this.resourceId,
    required this.usedBy,
    required this.referencesOf,
  });

  final String resourceId;
  final Set<String> usedBy;
  final Set<String> referencesOf;
}

/// 候选项目构造器：从当前模型派生修改后的候选模型。
typedef MFProjectMutator = MFProject Function(MFProject base);

/// 提交前预检：返回的诊断含 error 时命令直接失败，不构造候选项目。
typedef MFPrecheck = List<MFDiag> Function(MFProject base);

/// 结构化命令执行会话。
///
/// 会话持有当前项目模型与资源注册表；全部修改走「候选项目 → 校验门禁 →
/// 提交修订」的同一通道。会话不接触运行实例：运行中的实例固定其发布时的
/// 模型（§13.2），模型修订只影响新建实例。
class MFAuthoringSession {
  MFAuthoringSession({
    required MFProject project,
    required this.registry,
    this.actor = 'authoring-client',
  }) : _current = project;

  MFProject _current;
  final MFRegistry registry;

  /// 操作主体，进入修订审计（§32）。
  final String actor;

  /// 追加式修订审计：回滚只移动指针，不删除记录（§32）。
  final List<MFRevision> _revisions = [];
  int _undoDepth = 0;

  MFProject get project => _current;

  /// 已提交的修订审计（回滚不删除记录）。
  List<MFRevision> get revisions => List.unmodifiable(_revisions);
  bool get canUndo => _undoDepth > 0;

  /// `create_page`（§14）：纯配置构造新页面定义，引用未注册资源是静态错误
  /// （§2.7、基线 13）。重复的页面 id 或路由是静态错误（§9）。
  /// `navigationFrom` 在同一修订内原子声明入边；不声明且页面非入口时，
  /// 孤立页面门禁（§9）会拒绝该命令。
  MFCommandResult createPage({
    required String pageId,
    required String route,
    required MFNode tree,
    List<String> stateMembers = const [],
    Map<String, String> parameters = const {},
    String? onEnter,
    String? errorBoundary,
    InfoContract info = const InfoContract(),
    String? navigationFrom,
  }) {
    return _execute(
      command: 'create_page',
      targetId: pageId,
      mutate: (base) {
        final page = MFPage(
          id: pageId,
          route: route,
          tree: tree,
          stateMembers: stateMembers,
          parameters: parameters,
          onEnter: onEnter,
          errorBoundary: errorBoundary,
          info: info,
        );
        return MFProject(
          manifest: base.manifest,
          pages: [...base.pages, page],
          components: base.components,
          bindingMaps: base.bindingMaps,
          i18n: base.i18n,
          tokens: base.tokens,
          navigation: navigationFrom == null
              ? base.navigation
              : MFNavigationSpec(
                  edges: [...base.navigation.edges, MFNavEdge(from: navigationFrom, to: pageId)],
                  fallback: base.navigation.fallback,
                ),
          crossingList: base.crossingList,
          pageTemplates: base.pageTemplates,
        );
      },
      precheck: (base) => [
        ..._duplicatePageDiags(base, pageId, route),
        if (navigationFrom != null && base.page(navigationFrom) == null)
          MFDiag(MFCodes.refDangling, '导航来源页面 $navigationFrom 不存在'),
      ],
    );
  }

  /// `connect_navigation`（§14）：在既有页面间声明导航边（§9 有向图）。
  MFCommandResult connectNavigation({
    required String from,
    required String to,
    String kind = 'push',
  }) {
    return _execute(
      command: 'connect_navigation',
      targetId: '$from->$to',
      mutate: (base) => MFProject(
        manifest: base.manifest,
        pages: base.pages,
        components: base.components,
        bindingMaps: base.bindingMaps,
        i18n: base.i18n,
        tokens: base.tokens,
        navigation: MFNavigationSpec(
          edges: [...base.navigation.edges, MFNavEdge(from: from, to: to, kind: kind)],
          fallback: base.navigation.fallback,
        ),
        crossingList: base.crossingList,
        pageTemplates: base.pageTemplates,
      ),
      precheck: (base) => [
        if (base.page(from) == null) MFDiag(MFCodes.refDangling, '导航来源页面 $from 不存在'),
        if (base.page(to) == null) MFDiag(MFCodes.refDangling, '导航目标页面 $to 不存在'),
      ],
    );
  }

  /// `create_page_from_template`（§14、§2.7）：按参数实例化模板为独立页面
  /// 定义；模板修订不追溯改写已创建页面。缺失声明参数或提供未声明参数
  /// 都是静态错误。
  MFCommandResult createPageFromTemplate({
    required String templateId,
    required String pageId,
    String? route,
    Map<String, String> params = const {},
    String? navigationFrom,
  }) {
    final template = _current.pageTemplates[templateId];
    if (template == null) {
      return MFCommandResult(
        command: 'create_page_from_template',
        targetId: pageId,
        ok: false,
        diagnostics: [MFDiag(MFCodes.refDangling, '模板 $templateId 不存在')],
        affected: const {},
        actor: actor,
      );
    }
    final paramDiags = <MFDiag>[];
    for (final p in params.keys) {
      if (!template.parameters.containsKey(p)) {
        paramDiags.add(MFDiag(MFCodes.unknownField, '模板 $templateId 未声明参数 $p（§2.7）'));
      }
    }
    for (final p in template.parameters.keys) {
      if (!params.containsKey(p)) {
        paramDiags.add(MFDiag(MFCodes.schemaTemplateParamInvalid,
            '模板 $templateId 缺少声明参数 $p（§2.7）'));
      }
    }
    if (paramDiags.isNotEmpty) {
      return MFCommandResult(
        command: 'create_page_from_template',
        targetId: pageId,
        ok: false,
        diagnostics: paramDiags,
        affected: const {},
        actor: actor,
      );
    }
    final tree = _instantiateTree(template.tree, params);
    final resolvedRoute = route ?? '${template.routePrefix}$pageId';
    return createPage(
      pageId: pageId,
      route: resolvedRoute,
      tree: tree,
      stateMembers: template.stateMembers,
      navigationFrom: navigationFrom,
    );
  }

  /// `validate_project`（§14）：对当前项目执行同一静态校验门禁。
  MFValidationResult validateProject() =>
      MFValidator(project: _current, registry: registry).validate();

  /// `inspect_impact`（§14）：基于 §4.3 反向索引报告资源的引用与被引用面。
  MFImpactReport inspectImpact(String resourceId) {
    final validation = validateProject();
    return MFImpactReport(
      resourceId: resourceId,
      usedBy: validation.index.usedBy(resourceId),
      referencesOf: validation.index.referencesOf(resourceId),
    );
  }

  /// 回滚最近一次修订（§14 可回滚修订）：恢复修订前的项目模型；
  /// 审计记录保留，继续追加新修订时旧审计仍在。
  MFProject? undo() {
    if (_undoDepth == 0) return null;
    final last = _revisions[_revisions.length - _undoDepth];
    _undoDepth--;
    _current = last.snapshotBefore;
    return _current;
  }

  MFCommandResult _execute({
    required String command,
    String? targetId,
    required MFProjectMutator mutate,
    MFPrecheck? precheck,
  }) {
    final before = _current;
    final preDiags = precheck?.call(before) ?? const <MFDiag>[];
    if (preDiags.any((d) => d.severity == Severity.error)) {
      return MFCommandResult(
        command: command,
        targetId: targetId,
        ok: false,
        diagnostics: preDiags,
        affected: const {},
        actor: actor,
        beforeSummary: _summary(before),
        afterSummary: _summary(before),
      );
    }
    final candidate = mutate(before);
    final validation = MFValidator(project: candidate, registry: registry).validate();
    final errors = validation.diagnostics.where((d) => d.severity == Severity.error).toList();
    if (errors.isNotEmpty) {
      // 门禁失败：项目保持不变，无隐式状态（§2.7、§14）。
      return MFCommandResult(
        command: command,
        targetId: targetId,
        ok: false,
        diagnostics: errors,
        affected: const {},
        actor: actor,
        beforeSummary: _summary(before),
        afterSummary: _summary(before),
      );
    }
    final revision = MFRevision(
      id: _revisions.length + 1,
      command: command,
      actor: actor,
      beforeSummary: _summary(before),
      afterSummary: _summary(candidate),
      snapshotBefore: before,
      at: DateTime.now().toUtc(),
    );
    _revisions.add(revision);
    _undoDepth++;
    _current = candidate;
    return MFCommandResult(
      command: command,
      targetId: targetId,
      ok: true,
      diagnostics: validation.diagnostics.where((d) => d.severity != Severity.error).toList(),
      affected: targetId == null ? const {} : validation.index.usedBy(targetId),
      actor: actor,
      beforeSummary: revision.beforeSummary,
      afterSummary: revision.afterSummary,
      revision: revision,
    );
  }

  List<MFDiag> _duplicatePageDiags(MFProject base, String pageId, String route) {
    final diags = <MFDiag>[];
    if (base.page(pageId) != null) {
      diags.add(MFDiag(MFCodes.routeDuplicate, '页面 id $pageId 已存在（§9 路由唯一）'));
    }
    if (base.pages.any((p) => p.route == route)) {
      diags.add(MFDiag(MFCodes.routeDuplicate, '路由 $route 已被页面 ${base.pages.firstWhere((p) => p.route == route).id} 占用'));
    }
    return diags;
  }

  /// 模板实例化：节点 id 与字符串属性值中的 `{{param}}` 替换为参数值；
  /// 其余值递归处理，保持结构不变（§2.6：实例不反向修改定义）。
  MFNode _instantiateTree(MFNode node, Map<String, String> params) => MFNode(
        id: _subst(node.id, params),
        type: node.type,
        props: node.props.map((k, v) => MapEntry(k, _substValue(v, params))),
        slotOf: node.slotOf,
        children: [for (final c in node.children) _instantiateTree(c, params)],
        slots: {
          for (final e in node.slots.entries)
            e.key: [for (final c in e.value) _instantiateTree(c, params)],
        },
        t: node.t,
      );

  static final RegExp _paramPattern = RegExp(r'\{\{(\w+)\}\}');

  String _subst(String s, Map<String, String> params) =>
      s.replaceAllMapped(_paramPattern, (m) => params[m.group(1)] ?? m.group(0)!);

  Object? _substValue(Object? value, Map<String, String> params) {
    if (value is String) return _subst(value, params);
    if (value is Map) return {for (final e in value.entries) '${e.key}': _substValue(e.value, params)};
    if (value is List) return [for (final v in value) _substValue(v, params)];
    return value;
  }

  /// 修订前后摘要（§14）：确定性资源清单，不含时间与主体（审计字段单独保存）。
  static String _summary(MFProject p) =>
      'pages=[${p.pages.map((e) => e.id).join(',')}]'
      '|components=[${(p.components.keys.toList()..sort()).join(',')}]'
      '|bindings=[${(p.bindingMaps.keys.toList()..sort()).join(',')}]'
      '|templates=[${(p.pageTemplates.keys.toList()..sort()).join(',')}]';
}
