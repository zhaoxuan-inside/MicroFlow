/// 覆盖矩阵：需求 → 场景 → 实现载体的传递闭包，机器可判定的"验收先行"基线。
/// 门禁语义：uncovered（无场景）与 orphan（场景不挂需求）是矩阵洞；manualOnly 如实标记不美化。
import { SPCodes, specDiag, type SpecDiag } from '../diagnostics.ts';
import { canonicalDigest } from './canonical.ts';
import type { SpecModel, SpecScenario } from '../model/types.ts';

export interface CoverageScenario {
  id: string;
  kind: SpecScenario['kind'];
}

export interface CoverageRow {
  id: string;
  title: string;
  status: SpecModel['requirements'][number]['status'];
  scenarios: CoverageScenario[];
  carriers: { kind: string; id: string }[];
  /** 至少一个场景（含 manual）挂接。 */
  covered: boolean;
  /** 全部场景都是 manual——无机器证据，如实披露。 */
  manualOnly: boolean;
}

export interface CoverageReport {
  digest: string;
  summary: {
    requirements: number;
    scenarios: number;
    covered: number;
    uncovered: number;
    manualOnly: number;
  };
  /** 按 id 确定性排序。 */
  rows: CoverageRow[];
  /** 未挂任何需求的场景（矩阵洞，同样确定性排序）。 */
  orphans: { id: string; title: string }[];
}

export function coverage(model: SpecModel): CoverageReport {
  const byRequirement = new Map<string, CoverageScenario[]>();
  for (const requirement of model.requirements) {
    byRequirement.set(requirement.id, []);
  }

  const orphans: { id: string; title: string }[] = [];
  for (const scenario of [...model.scenarios].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const linked = scenario.requirementRefs.filter((ref) => byRequirement.has(ref));
    if (linked.length === 0) {
      orphans.push({ id: scenario.id, title: scenario.title });
      continue;
    }
    for (const ref of linked) {
      byRequirement.get(ref)!.push({ id: scenario.id, kind: scenario.kind });
    }
  }

  const rows: CoverageRow[] = [...model.requirements]
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .map((requirement) => {
      const scenarios = byRequirement.get(requirement.id) ?? [];
      const carriers = model.scenarios
        .filter((scenario) => scenario.requirementRefs.includes(requirement.id))
        .flatMap((scenario) => scenario.carriers ?? []);
      return {
        id: requirement.id,
        title: requirement.title,
        status: requirement.status,
        scenarios,
        carriers,
        covered: scenarios.length > 0,
        manualOnly:
          scenarios.length > 0 && scenarios.every((scenario) => scenario.kind === 'manual'),
      };
    });

  const covered = rows.filter((row) => row.covered).length;
  return {
    digest: canonicalDigest(model),
    summary: {
      requirements: model.requirements.length,
      scenarios: model.scenarios.length,
      covered,
      uncovered: rows.length - covered,
      manualOnly: rows.filter((row) => row.manualOnly).length,
    },
    rows,
    orphans,
  };
}

/** 矩阵诊断（warning 级——矩阵洞不阻止 check，但阻止交付门禁）。 */
export function coverageDiagnostics(report: CoverageReport): SpecDiag[] {
  const diags: SpecDiag[] = [];
  for (const row of report.rows) {
    if (!row.covered) {
      diags.push(
        specDiag(SPCodes.uncoveredRequirement, `需求 "${row.id}" 没有任何验收场景`, {
          severity: 'warning',
          path: `requirements[${row.id}]`,
        }),
      );
    } else if (row.manualOnly) {
      diags.push(
        specDiag(SPCodes.manualOnlyRequirement, `需求 "${row.id}" 只有 manual 场景（无机器证据）`, {
          severity: 'info',
          path: `requirements[${row.id}]`,
        }),
      );
    }
  }
  for (const orphan of report.orphans) {
    diags.push(
      specDiag(SPCodes.orphanScenario, `场景 "${orphan.id}" 未挂接任何需求`, {
        severity: 'warning',
        path: `scenarios[${orphan.id}]`,
      }),
    );
  }
  return diags;
}