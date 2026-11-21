/// 真实 OpcHub 模型门禁：导出的 opchub.model.json 必须通过 TS validator
/// （与 Dart 侧 MFValidator 同语义的双端一致门禁）。
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { MFValidator } from '../src/validator/validator.ts';
import { loadProject, MFStyleResolver } from '../src/model/loader.ts';
import type { MFProjectJson } from '../src/model/types.ts';

/// 模型定位：OPCHUB_MODEL 环境变量显式锚定；缺省回落仓库同级宿主项目。
/// 文件缺失时显式 skip（不伪造通过）——与 Orchestration 集成测试纪律一致。
const modelPath = process.env.OPCHUB_MODEL
  ? resolve(process.env.OPCHUB_MODEL)
  : resolve(process.cwd(), '../../OpcHub/frontend_web/src/model/opchub.model.json');
const modelExists = existsSync(modelPath);

if (!modelExists) {
  console.warn(`[skip] OpcHub 真实模型门禁：未找到 ${modelPath}（可用 OPCHUB_MODEL 显式指定）`);
}

/// 收集期不读文件（vitest 的 skip 套件工厂仍会执行）——统一走惰性读取。
const readModel = (): MFProjectJson => JSON.parse(readFileSync(modelPath, 'utf8')) as MFProjectJson;

describe.skipIf(!modelExists)('OpcHub 真实模型（32 页）', () => {
  it('manifest/页面/绑定面齐全', () => {
    const json = readModel();
    expect(json.manifest.project_id).toBe('opchub-web');
    expect(json.pages?.length).toBe(32);
    expect(Object.keys(json.bindingMaps ?? {}).length).toBeGreaterThanOrEqual(32);
    expect((json.registry ?? []).length).toBeGreaterThan(40);
  });

  it('通过 TS 静态门禁（无 error 级诊断）', () => {
    const json = readModel();
    const result = new MFValidator(json).validate();
    const errors = result.diags.filter((d) => d.severity === 'error');
    expect(errors, JSON.stringify(errors.slice(0, 8), null, 1)).toEqual([]);
  });

  it('亮暗主题都解析全部被引用 token（§36.3）', () => {
    const json = readModel();
    const parsed = loadProject(json);
    const resolver = new MFStyleResolver(parsed.tokens, parsed.styleSheets, parsed.themes, json.manifest.default_theme);
    expect(resolver.effectiveTokens('theme-light')['color.bg.canvas']).toBe('#F2F1EC');
    expect(resolver.effectiveTokens('theme-dark')['color.bg.canvas']).toBe('#0A0B0D');
    expect(resolver.effectiveTokens('theme-dark')['color.text.primary']).toBe('#F4F5F7');
  });

  it('入口页 onEnter 绑定存在并可解析', () => {
    const parsed = loadProject(readModel());
    const home = parsed.pageById.get('home-page')!;
    expect(home.onEnter).toBeTruthy();
    const binding = parsed.bindingById.get(home.onEnter!);
    expect(binding?.actions.length).toBeGreaterThan(3);
  });
});
