/// 结构化命令面：verify run。
/// 契约：统一信封 `microflow-verify-v1`（报告即信封）；退出码 0 pass / 1 断言否定 /
/// 2 请求失败（脚本或模型不可读、静态门禁不过）。
/// 确定性边界：verdict/assertions 确定性；meta.startedAt/durationMs 为时钟性字段，
/// 不作摘要基础（证据标识由 Spec 对报告整体摘要）。
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { VRFCodes, vrfDiag, type VrfDiag } from './diagnostics.ts';
import { validateScript, toVerifyScript } from './script/validate.ts';
import { extractFacts } from './script/facts.ts';
import { runVerifyScript, type VerifyReport } from './runner.ts';
import { createWebSurface, webStandardEvents } from './surface/web.ts';
import type { SurfaceImpls } from './surface/port.ts';

export interface CliRequest {
  scriptFile: string;
  modelFile: string;
  implsFile?: string;
  outFile?: string;
}

function loadJson(file: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(readFileSync(file, 'utf8')) };
  } catch (error) {
    return { error: `${file}: ${(error as Error).message}` };
  }
}

/** 代码平面装载：ESM default 导出对象（registry id → 函数）或具名函数导出。 */
async function loadImpls(file: string): Promise<{ impls?: SurfaceImpls; error?: string }> {
  try {
    const mod = (await import(pathToFileURL(file).href)) as Record<string, unknown>;
    if (typeof mod['default'] === 'object' && mod['default'] !== null) {
      return { impls: mod['default'] as SurfaceImpls };
    }
    const impls: SurfaceImpls = {};
    for (const [key, value] of Object.entries(mod)) {
      if (typeof value === 'function') impls[key] = value as SurfaceImpls[string];
    }
    return { impls };
  } catch (error) {
    return { error: `${file}: ${(error as Error).message}` };
  }
}

function failedRequest(scriptFile: string, exit: 2, diagnostics: VrfDiag[]): VerifyReport {
  return {
    envelope: 'microflow-verify-v1',
    script: scriptFile,
    verdict: 'fail',
    assertions: [],
    summary: { total: 0, passed: 0, failed: 0 },
    meta: { startedAt: new Date().toISOString(), durationMs: 0, surface: 'none', surfaceDiagnostics: [] },
    diagnostics,
    requestFailed: true,
    exit,
  } as VerifyReport & { diagnostics: VrfDiag[]; requestFailed: boolean };
}

export async function runVerifyCli(argv: readonly string[]): Promise<VerifyReport> {
  const request: Partial<CliRequest> = {};
  const rest = [...argv];
  while (rest.length > 0) {
    const flag = rest.shift();
    if (flag === '--script') request.scriptFile = rest.shift();
    else if (flag === '--model') request.modelFile = rest.shift();
    else if (flag === '--impls') request.implsFile = rest.shift();
    else if (flag === '--out') request.outFile = rest.shift();
    else if (flag !== undefined && flag.startsWith('--')) {
      return failedRequest(String(flag), 2, [vrfDiag(VRFCodes.badType, `未知参数 "${flag}"；用法: verify run --script <s.json> --model <m.json> [--impls <impls.mjs>] [--out <report.json>]`)]);
    }
  }
  if (!request.scriptFile || !request.modelFile) {
    return failedRequest(request.scriptFile ?? '', 2, [
      vrfDiag(VRFCodes.missingRequired, '用法: verify run --script <s.json> --model <m.json> [--impls <impls.mjs>] [--out <report.json>]'),
    ]);
  }

  const scriptLoaded = loadJson(request.scriptFile);
  if (scriptLoaded.error !== undefined) {
    return failedRequest(request.scriptFile, 2, [vrfDiag(VRFCodes.badType, `无法读取脚本 ${scriptLoaded.error}`)]);
  }
  const modelLoaded = loadJson(request.modelFile);
  if (modelLoaded.error !== undefined) {
    return failedRequest(request.scriptFile, 2, [vrfDiag(VRFCodes.badType, `无法读取模型 ${modelLoaded.error}`)]);
  }

  const facts = extractFacts(modelLoaded.value);
  if (facts === undefined) {
    return failedRequest(request.scriptFile, 2, [vrfDiag(VRFCodes.badType, '模型不是含 pages 数组的 JSON 对象')]);
  }

  // 模型先过 4Web 静态门禁（0 error 才跑）——verify 不消费未通过门禁的模型。
  const { MFValidator } = await import('../../MicroFlow4Web/src/validator/validator.ts');
  const modelDiags = new MFValidator(modelLoaded.value as never).validate().diags.filter((d) => d.severity === 'error');
  if (modelDiags.length > 0) {
    return failedRequest(request.scriptFile, 2, modelDiags.map((d) => ({ code: d.code, message: d.message, severity: 'error' as const })));
  }

  const scriptDiags = validateScript(scriptLoaded.value, facts, webStandardEvents);
  const script = toVerifyScript(scriptLoaded.value, scriptDiags);
  if (script === undefined) {
    return failedRequest(request.scriptFile, 2, scriptDiags);
  }

  let impls: SurfaceImpls | undefined;
  if (request.implsFile !== undefined) {
    const loaded = await loadImpls(request.implsFile);
    if (loaded.error !== undefined) {
      return failedRequest(request.scriptFile, 2, [vrfDiag(VRFCodes.badType, `无法装载实现 ${loaded.error}`)]);
    }
    impls = loaded.impls;
  }

  const surface = createWebSurface({ project: modelLoaded.value, impls });
  const report = await runVerifyScript({ script, surface, scriptPath: request.scriptFile, surfaceName: 'web' });
  if (request.outFile !== undefined) {
    writeFileSync(request.outFile, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  }
  return report;
}

function main(): void {
  void runVerifyCli(process.argv.slice(2)).then((report) => {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    process.exitCode = report.exit;
  });
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
