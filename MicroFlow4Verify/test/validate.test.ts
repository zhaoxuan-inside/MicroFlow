/// 脚本静态门禁：合法脚本 0 诊断；锚点/事件/标准事件/页面/未实现 op 逐项挂账。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { VRFCodes } from '../src/diagnostics.ts';
import { extractFacts } from '../src/script/facts.ts';
import { validateScript, toVerifyScript } from '../src/script/validate.ts';
import { webStandardEvents } from '../src/surface/web.ts';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

const project: unknown = JSON.parse(readFileSync(fixture('demo.project.json'), 'utf8'));
const facts = extractFacts(project)!;

function codes(diags: { code: string }[]): string[] {
  return diags.map((d) => d.code);
}

describe('extractFacts', () => {
  it('页/节点/契约事件面齐全', () => {
    expect([...facts.pageIds].sort()).toEqual(['home-page', 'login-page']);
    expect(facts.nodeTypeById.get('submit')).toBe('Button');
    expect(facts.nodeTypeById.get('username')).toBe('Input');
    expect([...(facts.eventsByType.get('Button') ?? [])]).toEqual(['press']);
    expect([...(facts.eventsByType.get('Input') ?? [])].sort()).toEqual(['change', 'input']);
    expect(facts.entryPage).toBe('login-page');
  });

  it('非 JSON 对象拒绝', () => {
    expect(extractFacts('x')).toBeUndefined();
    expect(extractFacts({})).toBeUndefined();
  });
});

describe('validateScript', () => {
  it('合法脚本 0 诊断', () => {
    const raw = JSON.parse(readFileSync(fixture('login.script.json'), 'utf8'));
    const diags = validateScript(raw, facts, webStandardEvents);
    expect(diags).toEqual([]);
    expect(toVerifyScript(raw, diags)).toBeDefined();
  });

  it('负例集逐项命中预期码', () => {
    const raw = JSON.parse(readFileSync(fixture('invalid.script.json'), 'utf8'));
    const diags = validateScript(raw, facts, webStandardEvents);
    expect(codes(diags)).toEqual([
      VRFCodes.unknownPage,        // open nope-page
      VRFCodes.unknownNode,        // tap ghost
      VRFCodes.unknownEvent,       // tap submit explode
      VRFCodes.unknownEvent,       // fill submit（Button 无 change）
      VRFCodes.missingRequired,    // expect_binding 缺 equals
      VRFCodes.unknownStandardEvent, // biz.custom
      VRFCodes.opUnimplemented,    // screenshot
      VRFCodes.unknownField,       // expect_route extra
      VRFCodes.unknownPage,        // expect_route ghost-page
    ]);
    expect(toVerifyScript(raw, diags)).toBeUndefined();
  });

  it('根非对象与方言不支持', () => {
    expect(codes(validateScript([1], facts, webStandardEvents))).toEqual([VRFCodes.badType]);
    const diags = validateScript({ scriptVersion: 2, title: 't', steps: [{ op: 'back' }] }, facts, webStandardEvents);
    expect(codes(diags)).toEqual([VRFCodes.dialectUnsupported]);
  });

  it('空 steps 与缺 title', () => {
    const diags = validateScript({ scriptVersion: 1, steps: [] }, facts, webStandardEvents);
    expect(codes(diags)).toEqual([VRFCodes.missingRequired, VRFCodes.badType]);
  });

  it('未知 op 拒绝并列出允许集', () => {
    const diags = validateScript({ scriptVersion: 1, title: 't', steps: [{ op: 'drag' }] }, facts, webStandardEvents);
    expect(codes(diags)).toEqual([VRFCodes.badEnum]);
    expect(diags[0]!.message).toContain('"open"');
  });
});
