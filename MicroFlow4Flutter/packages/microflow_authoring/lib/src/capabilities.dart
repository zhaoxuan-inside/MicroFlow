/// 创作命令面的机器可读能力投影（frontend-framework-design §14；
/// CLI 命令体系设计 §2 兼容契约第 5 条「能力探测替代硬编码」）。
///
/// 编辑器、CLI 与 AI Agent 应先探测本投影再调用 [MFAuthoringSession] 的命令，
/// 不假设命令存在。投影只描述已实现的命令面，与实际命令一一对应：新增命令
/// 时同步修订本表，守卫测试断言命令集合，漏登即实现缺陷。
///
/// 本投影是操作化收敛，不引入新语义：门禁、审计与回滚语义以 §14、§2.7、
/// §32 为准，此处仅声明其存在。
library;

import 'authoring.dart';

/// 命令面的单条能力声明。
class MFAuthoringCommand {
  const MFAuthoringCommand({
    required this.name,
    required this.kind,
    required this.arguments,
    required this.returns,
    required this.description,
  });

  /// §14 结构化命令名（snake_case）。
  final String name;

  /// mutate：修改模型并产生可回滚修订；inspect：只读；rollback：回滚。
  final String kind;

  /// 命名参数清单（按 [MFAuthoringSession] 对应方法的实际签名）。
  final List<String> arguments;

  /// 返回类型及其关键字段。
  final String returns;

  final String description;
}

/// 已实现的创作命令面（与 [MFAuthoringSession] 公开方法一一对应）。
const List<MFAuthoringCommand> mfAuthoringCommands = [
  MFAuthoringCommand(
    name: 'create_page',
    kind: 'mutate',
    arguments: ['pageId', 'route', 'tree', 'stateMembers?', 'parameters?', 'onEnter?',
      'errorBoundary?', 'info?', 'navigationFrom?'],
    returns: 'MFCommandResult{command, targetId, ok, diagnostics, affected, actor, '
        'beforeSummary, afterSummary, revision}',
    description: '纯配置构造新页面；引用未注册资源是静态错误（基线 13）；'
        'navigationFrom 在同一修订内原子声明入边。',
  ),
  MFAuthoringCommand(
    name: 'connect_navigation',
    kind: 'mutate',
    arguments: ['from', 'to', 'kind?'],
    returns: 'MFCommandResult{command, targetId, ok, diagnostics, affected, actor, '
        'beforeSummary, afterSummary, revision}',
    description: '在既有页面间声明导航边（§9 有向图）；来源或目标不存在是静态错误。',
  ),
  MFAuthoringCommand(
    name: 'create_page_from_template',
    kind: 'mutate',
    arguments: ['templateId', 'pageId', 'route?', 'params?', 'navigationFrom?'],
    returns: 'MFCommandResult{command, targetId, ok, diagnostics, affected, actor, '
        'beforeSummary, afterSummary, revision}',
    description: '按参数实例化模板为独立页面（§2.7）；缺失声明参数或提供未声明参数'
        '都是静态错误；模板修订不追溯改写已创建页面。',
  ),
  MFAuthoringCommand(
    name: 'register_finding',
    kind: 'mutate',
    arguments: ['findingId', 'findingType', 'targetRef', 'summary?', 'sourceRef?',
      'checkRef?', 'schemaVersion?'],
    returns: 'MFCommandResult{command, targetId, ok, diagnostics, affected, actor, '
        'beforeSummary, afterSummary, revision}',
    description: 'findings 结构化回流（§43.3、基线 17）；按 finding_id 登记，'
        '重复登记是静态错误；回流不自动修改模型。',
  ),
  MFAuthoringCommand(
    name: 'validate_project',
    kind: 'inspect',
    arguments: [],
    returns: 'MFValidationResult（含 findingsReport 与引用索引）',
    description: '对当前项目执行与发布相同的静态校验门禁（§18.1）。',
  ),
  MFAuthoringCommand(
    name: 'inspect_impact',
    kind: 'inspect',
    arguments: ['resourceId'],
    returns: 'MFImpactReport{resourceId, usedBy, referencesOf}',
    description: '基于 §4.3 反向索引报告资源的引用与被引用面。',
  ),
  MFAuthoringCommand(
    name: 'undo',
    kind: 'rollback',
    arguments: [],
    returns: 'MFProject?（无可回滚修订时为 null）',
    description: '回滚最近一次修订：恢复修订前模型快照；审计记录保留（§32）。',
  ),
];

/// 能力投影的版本化 JSON（工具经 `jsonEncode` 消费；两次调用结果一致）。
Map<String, Object> mfAuthoringCapabilities() => {
      'protocol': 'mf-authoring-capabilities-v1',
      'commandFace': 'frontend-framework-design §14（阶段六最小闭环）',
      'gate': '全部 mutate 命令走与发布相同的静态校验门禁，失败时项目保持不变（§2.7）',
      'audit': '追加式修订审计：每次 mutate 产生前后摘要、影响对象与可回滚修订；'
          'undo 只移动指针，不删除记录（§14、§32）',
      'commands': [
        for (final c in mfAuthoringCommands)
          {'name': c.name, 'kind': c.kind, 'arguments': c.arguments,
           'returns': c.returns, 'description': c.description},
      ],
    };
