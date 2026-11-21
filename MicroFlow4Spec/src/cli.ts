/// 结构化命令面：check / coverage / verify / diff。
/// 契约（与 CLI 八条兼容契约同纪律）：统一信封 `microflow-spec-v1`；退出码 0 肯定 / 1 对象否定 /
/// 2 请求失败；确定性输出（同输入字节一致）；只暴露已实现命令。
import { readFileSync } from 'node:fs';
import { specDiag, type SpecDiag } from './diagnostics.ts';
import { validateSpecModel, toSpecModel } from './model/validate.ts';
import { canonicalDigest } from './core/canonical.ts';
import { coverage, coverageDiagnostics } from './core/coverage.ts';
import { mergeVerify } from './core/merge.ts';
import { diffSpec } from './core/diff.ts';
import type { SpecModel } from './model/types.ts';

export interface SpecEnvelope extends Record<string, unknown> {
  envelope: 'microflow-spec-v1';
  command: string;
  ok: boolean;
  exit: 0 | 1 | 2;
}

interface LoadedSpec {
  model?: SpecModel;
  diagnostics: SpecDiag[];
  /** JSON 解析失败（与"解析成功但校验不过"区分退出码 2/1）。 */
  unreadable: boolean;
}

function loadSpec(file: string): LoadedSpec {
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(file, 'utf8'));
  } catch (error) {
    return {
      diagnostics: [specDiag('spec.schema.bad-type', `无法读取 ${file}: ${(error as Error).message}`, { path: '$' })],
      unreadable: true,
    };
  }
  const diagnostics = validateSpecModel(raw);
  return { model: toSpecModel(raw, diagnostics), diagnostics, unreadable: false };
}

function envelope(command: string, ok: boolean, exit: 0 | 1 | 2, extra: Record<string, unknown>): SpecEnvelope {
  return { envelope: 'microflow-spec-v1', command, ok, exit, ...extra };
}

/** 模型损坏时的统一响应：JSON 解析失败按 2（请求失败），校验不过按 1（对象否定）。 */
function invalidSpecResponse(command: string, loaded: LoadedSpec): SpecEnvelope | undefined {
  if (loaded.model !== undefined) return undefined;
  return envelope(command, false, loaded.unreadable ? 2 : 1, { diagnostics: loaded.diagnostics });
}

function specMeta(model: SpecModel): Record<string, unknown> {
  return {
    project: model.project,
    digest: canonicalDigest(model),
    counts: {
      requirements: model.requirements.length,
      scenarios: model.scenarios.length,
    },
  };
}

function runCheck(file: string): SpecEnvelope {
  const loaded = loadSpec(file);
  const invalid = invalidSpecResponse('check', loaded);
  if (invalid) return invalid;
  const model = loaded.model!;
  const errors = loaded.diagnostics.filter((d) => d.severity === 'error');
  return envelope('check', errors.length === 0, errors.length === 0 ? 0 : 1, {
    diagnostics: loaded.diagnostics,
    spec: specMeta(model),
  });
}

function runCoverage(file: string): SpecEnvelope {
  const loaded = loadSpec(file);
  const invalid = invalidSpecResponse('coverage', loaded);
  if (invalid) return invalid;
  const model = loaded.model!;
  const report = coverage(model);
  const diags = coverageDiagnostics(report);
  // 门禁语义：矩阵洞（uncovered/orphan）= 未全绿 = 对象否定；manualOnly 如实披露不拦截。
  const ok = report.summary.uncovered === 0 && report.orphans.length === 0;
  return envelope('coverage', ok, ok ? 0 : 1, {
    summary: report.summary,
    rows: report.rows,
    orphans: report.orphans,
    diagnostics: diags,
    spec: specMeta(model),
  });
}

function runVerify(file: string, reportFiles: string[]): SpecEnvelope {
  const loaded = loadSpec(file);
  const invalid = invalidSpecResponse('verify', loaded);
  if (invalid) return invalid;
  const model = loaded.model!;
  const reports: unknown[] = [];
  for (const reportFile of reportFiles) {
    try {
      reports.push(JSON.parse(readFileSync(reportFile, 'utf8')));
    } catch (error) {
      return envelope('verify', false, 2, {
        diagnostics: [specDiag('spec.verify.bad-report', `无法读取证据报告 ${reportFile}: ${(error as Error).message}`, { path: 'reports' })],
      });
    }
  }
  const merged = mergeVerify(model, reports);
  // 门禁语义：fail / pending / 坏报告都算未通过——诚实边界不允许"没跑 = 通过"。
  const blockingCodes = new Set(['spec.verify.failed-scenario', 'spec.verify.pending-scenario', 'spec.verify.bad-report', 'spec.verify.bad-envelope']);
  const blocking = merged.diagnostics.filter((d) => blockingCodes.has(d.code));
  const ok = blocking.length === 0;
  return envelope('verify', ok, ok ? 0 : 1, {
    evidence: merged.evidence,
    diagnostics: merged.diagnostics,
    spec: specMeta(model),
  });
}

function runDiff(oldFile: string, newFile: string): SpecEnvelope {
  const oldLoaded = loadSpec(oldFile);
  const newLoaded = loadSpec(newFile);
  if (oldLoaded.model === undefined || newLoaded.model === undefined) {
    return envelope('diff', false, 2, {
      diagnostics: [...oldLoaded.diagnostics, ...newLoaded.diagnostics],
    });
  }
  const diff = diffSpec(oldLoaded.model, newLoaded.model);
  return envelope('diff', true, 0, { diff });
}

export function runSpec(argv: readonly string[]): SpecEnvelope {
  const [command, ...args] = argv;
  switch (command) {
    case 'check':
      return args.length === 1 ? runCheck(args[0]!) : envelope('check', false, 2, { message: '用法: spec check <spec.json>' });
    case 'coverage':
      return args.length === 1 ? runCoverage(args[0]!) : envelope('coverage', false, 2, { message: '用法: spec coverage <spec.json>' });
    case 'verify':
      return args.length >= 1 ? runVerify(args[0]!, args.slice(1)) : envelope('verify', false, 2, { message: '用法: spec verify <spec.json> <report.json...>' });
    case 'diff':
      return args.length === 2 ? runDiff(args[0]!, args[1]!) : envelope('diff', false, 2, { message: '用法: spec diff <old.json> <new.json>' });
    default:
      return envelope(String(command ?? ''), false, 2, {
        message: `未知命令 "${String(command ?? '')}"；已实现: check | coverage | verify | diff`,
      });
  }
}

function main(): void {
  const result = runSpec(process.argv.slice(2));
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  process.exitCode = result.exit;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
