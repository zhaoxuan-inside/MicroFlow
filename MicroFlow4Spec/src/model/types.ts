/// SpecModel v1 的 JSON 形态。文件名约定 `spec.model.json`；
/// 未知字段一律拒绝（与 MFProject 同纪律：表达不了的逻辑答案是"修订模型"，不是加字段）。

export type SpecPriority = 'must' | 'should' | 'could';
export type SpecStatus = 'open' | 'accepted' | 'delivered';

/** 实现载体：场景所作用的真实实现物。存在性校验属跨项目门禁，v1 只做结构校验（边界随交付更新）。 */
export type CarrierKind = 'operator' | 'flow' | 'page' | 'component' | 'scene';

export interface SpecCarrier {
  kind: CarrierKind;
  id: string;
}

/** 场景类型决定期望面形态与证据执行器归属。 */
export type ScenarioKind = 'backend_run' | 'orch_scenario' | 'ui_script' | 'manual';

/** backend_run：4Python `test` 命令的期望输出对照（执行器对接见 LIFECYCLE.md §七.2）。 */
export interface BackendRunExpectation {
  flow: string;
  input?: unknown;
  expectOutput?: Record<string, unknown>;
  expectMetaStatus?: string;
}

/** orch_scenario：编排控制面场景执行（E2E 阶段门禁证据）。 */
export interface OrchScenarioExpectation {
  scenario: string;
  expectStatus: string;
}

/** ui_script：MicroFlow4Verify 声明式脚本（microflow-verify-v1 信封）。 */
export interface UiScriptExpectation {
  script: string;
}

/** manual：人审证据，不进机器门禁（coverage 如实标记，不美化）。 */
export interface ManualExpectation {
  note: string;
}

export type ScenarioExpectation =
  | BackendRunExpectation
  | OrchScenarioExpectation
  | UiScriptExpectation
  | ManualExpectation;

export interface SpecScenario {
  id: string;
  title: string;
  kind: ScenarioKind;
  /** 需求 ↔ 场景边：可为空（未挂接 = 矩阵洞，orphan 警告并拦门禁）；悬空引用是静态错误。 */
  requirementRefs: string[];
  /** 场景 ↔ 实现载体边：可选。 */
  carriers?: SpecCarrier[];
  expectation: ScenarioExpectation;
}

export interface SpecRequirement {
  id: string;
  title: string;
  statement: string;
  priority: SpecPriority;
  status: SpecStatus;
}

export interface SpecModel {
  specVersion: 1;
  project: string;
  requirements: SpecRequirement[];
  scenarios: SpecScenario[];
}
