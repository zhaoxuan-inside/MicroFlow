/// 证据合并：把 MicroFlow4Verify 的 microflow-verify-v1 信封对号入座到 ui_script 场景。
/// 每个ui_script 场景必须有 pass 证据才进交付门禁；诚实语义：pending 与 fail 都算未通过。
import { SPCodes, specDiag, type SpecDiag } from '../diagnostics.ts';
import { canonicalDigest } from './canonical.ts';
import type { SpecModel } from '../model/types.ts';

/** microflow-verify-v1 信封中 Spec 消费的最小面（完整信封由 MicroFlow4Verify 定义）。 */
export interface VerifyReport {
  envelope: 'microflow-verify-v1';
  script: string;
  verdict: 'pass' | 'fail';
  summary: { total: number; passed: number; failed: number };
}

export type EvidenceVerdict = 'pass' | 'fail' | 'pending';

export interface ScenarioEvidence {
  scenarioId: string;
  script: string;
  verdict: EvidenceVerdict;
  reportDigest?: string;
  summary?: VerifyReport['summary'];
}

export interface MergeResult {
  diagnostics: SpecDiag[];
  /** 按 scenarioId 确定性排序；每个 ui_script 场景恰好一条。 */
  evidence: ScenarioEvidence[];
}

function parseReport(raw: unknown, index: number, diags: SpecDiag[]): VerifyReport | undefined {
  const path = `reports[${index}]`;
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    diags.push(specDiag(SPCodes.badReport, '证据报告必须是 JSON 对象', { path }));
    return undefined;
  }
  const report = raw as Record<string, unknown>;
  if (report['envelope'] !== 'microflow-verify-v1') {
    diags.push(
      specDiag(SPCodes.badEnvelope, `信封必须是 "microflow-verify-v1"，收到 ${JSON.stringify(report['envelope'])}`, { path }),
    );
    return undefined;
  }
  if (typeof report['script'] !== 'string' || report['script'].length === 0) {
    diags.push(specDiag(SPCodes.badReport, '"script" 必须是非空字符串', { path }));
    return undefined;
  }
  if (report['verdict'] !== 'pass' && report['verdict'] !== 'fail') {
    diags.push(specDiag(SPCodes.badReport, `"verdict" 必须是 "pass" | "fail"，收到 ${JSON.stringify(report['verdict'])}`, { path }));
    return undefined;
  }
  const summary = report['summary'];
  const okSummary =
    typeof summary === 'object' &&
    summary !== null &&
    !Array.isArray(summary) &&
    Number.isInteger((summary as Record<string, unknown>)['total']) &&
    Number.isInteger((summary as Record<string, unknown>)['passed']) &&
    Number.isInteger((summary as Record<string, unknown>)['failed']);
  if (!okSummary) {
    diags.push(specDiag(SPCodes.badReport, '"summary" 必须含整数 total/passed/failed', { path }));
    return undefined;
  }
  const counts = summary as { total: number; passed: number; failed: number };
  // 诚实门禁：失败数 > 0 却声称 pass 的报告按坏报告拒绝——不允许证据自证。
  if (counts.failed > 0 && report['verdict'] === 'pass') {
    diags.push(specDiag(SPCodes.badReport, `"summary.failed"=${counts.failed} > 0 但 verdict 为 "pass"`, { path }));
    return undefined;
  }
  return { envelope: 'microflow-verify-v1', script: report['script'], verdict: report['verdict'], summary: counts };
}

/** 把 verify 报告对号入座到 ui_script 场景；其余场景类型的证据合并属后续切片（LIFECYCLE.md 边界）。 */
export function mergeVerify(model: SpecModel, reports: readonly unknown[]): MergeResult {
  const diagnostics: SpecDiag[] = [];
  const evidence = new Map<string, ScenarioEvidence>();

  for (const scenario of model.scenarios) {
    if (scenario.kind === 'ui_script') {
      evidence.set(scenario.id, {
        scenarioId: scenario.id,
        script: (scenario.expectation as { script: string }).script,
        verdict: 'pending',
      });
    }
  }

  const sortedReports = reports
    .map((raw, index) => ({ report: parseReport(raw, index, diagnostics), index }))
    .filter((item): item is { report: VerifyReport; index: number } => item.report !== undefined)
    .sort((a, b) => (a.report.script < b.report.script ? -1 : a.report.script > b.report.script ? 1 : a.index - b.index));

  for (const { report } of sortedReports) {
    const matched = model.scenarios.filter(
      (scenario) => scenario.kind === 'ui_script' && (scenario.expectation as { script: string }).script === report.script,
    );
    if (matched.length === 0) {
      diagnostics.push(
        specDiag(SPCodes.unmatchedReport, `报告 "${report.script}" 未匹配任何 ui_script 场景`, { severity: 'warning' }),
      );
      continue;
    }
    for (const scenario of matched) {
      evidence.set(scenario.id, {
        scenarioId: scenario.id,
        script: report.script,
        verdict: report.verdict,
        reportDigest: canonicalDigest(report),
        summary: report.summary,
      });
    }
  }

  const sortedEvidence = [...evidence.values()].sort((a, b) => (a.scenarioId < b.scenarioId ? -1 : 1));
  for (const item of sortedEvidence) {
    if (item.verdict === 'pending') {
      diagnostics.push(
        specDiag(SPCodes.pendingScenario, `场景 "${item.scenarioId}" 缺少 ${item.script} 的证据报告`, { severity: 'warning', path: `scenarios[${item.scenarioId}]` }),
      );
    } else if (item.verdict === 'fail') {
      diagnostics.push(
        specDiag(SPCodes.failedScenario, `场景 "${item.scenarioId}" 证据 ${item.script} 判定 fail`, { path: `scenarios[${item.scenarioId}]` }),
      );
    }
  }
  return { diagnostics, evidence: sortedEvidence };
}
