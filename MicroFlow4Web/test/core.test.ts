import { describe, expect, it } from 'vitest';
import { MFValidator, asMotionSpec, exprRefPaths } from '../src/validator/validator.ts';
import { MFExpressionEvaluator } from '../src/runtime/evaluator.ts';
import { MFStateStore } from '../src/runtime/state-store.ts';
import { MFStyleResolver, loadProject } from '../src/model/loader.ts';
import { miniProject } from './fixtures/mini.ts';

describe('求值器（§37.2 白名单子集）', () => {
  const evaluator = new MFExpressionEvaluator((id: string) =>
    id === 'add' ? (args: Record<string, unknown>) => (args.a as number) + (args.b as number) : undefined,
  );

  it('字面量与骨架保持', () => {
    expect(evaluator.eval(42, {})).toBe(42);
    expect(evaluator.eval({ a: 1, b: { c: 'x' } }, {})).toEqual({ a: 1, b: { c: 'x' } });
    expect(evaluator.eval([1, 'x', true], {})).toEqual([1, 'x', true]);
  });

  it('ref 作用域解析', () => {
    const scopes = { state: { count: 7 }, session: { user: { name: 'opc' } }, item: { id: 3 } };
    expect(evaluator.eval({ ref: 'state.count' }, scopes)).toBe(7);
    expect(evaluator.eval({ ref: 'session.user.name' }, scopes)).toBe('opc');
    expect(evaluator.eval({ ref: 'item.id' }, scopes)).toBe(3);
  });

  it('比较与逻辑', () => {
    const scopes = { state: { count: 7 } };
    expect(evaluator.eval({ gte: [{ ref: 'state.count' }, 7] }, scopes)).toBe(true);
    expect(evaluator.eval({ lt: [{ ref: 'state.count' }, 7] }, scopes)).toBe(false);
    expect(evaluator.eval({ and: [{ gte: [{ ref: 'state.count' }, 1] }, { eq: [{ ref: 'state.count' }, 7] }] }, scopes)).toBe(true);
    expect(evaluator.eval({ not: { eq: [{ ref: 'state.count' }, 7] } }, scopes)).toBe(false);
  });

  it('call 走注册函数（禁 eval）', () => {
    expect(evaluator.eval({ call: 'add', arguments: { a: 2, b: 3 } }, {})).toBe(5);
    expect(evaluator.eval({ call: 'missing', arguments: {} }, {})).toBeNull();
  });

  it('ref 路径收集（静态存在性检查用）', () => {
    expect(exprRefPaths({ and: [{ ref: 'state.a' }, { gt: [{ ref: 'state.b' }, 1] }] })).toEqual(['state.a', 'state.b']);
  });
});

describe('状态存储（§11 三层）', () => {
  it('writeDeep 落位与读取', () => {
    const store = new MFStateStore();
    store.write('page', 'count', 1);
    store.writeDeep('page', 'profile.name', 'opc');
    store.writeDeep('session', 'token', 't1');
    expect(store.peek('page', 'count')).toBe(1);
    expect(store.peek('page', 'profile.name')).toBe('opc');
    expect(store.peek('session', 'token')).toBe('t1');
    // 深路径不污染兄弟键。
    store.writeDeep('page', 'profile.level', 2);
    expect(store.peek('page', 'profile.name')).toBe('opc');
    expect(store.peek('page', 'profile.level')).toBe(2);
  });

  it('快照导出/导入（§16.1）', () => {
    const store = new MFStateStore();
    store.write('session', 'uid', 'u1');
    const snapshot = store.exportLayers(['session']);
    const store2 = new MFStateStore();
    store2.importLayers(snapshot);
    expect(store2.peek('session', 'uid')).toBe('u1');
  });
});

describe('静态门禁（§2.7，诊断码与 Dart 同名）', () => {
  it('mini fixture 通过门禁（无 error）', () => {
    const result = new MFValidator(miniProject()).validate();
    const errors = result.diags.filter((d: { code: string; severity: string }) => d.severity === 'error');
    expect(errors).toEqual([]);
  });

  it('未注册节点引用 → mf.reg.unregistered-ref', () => {
    const project = miniProject();
    project.pages![0]!.tree.children!.push({ id: 'bad', type: 'NotRegistered', props: {} });
    const result = new MFValidator(project).validate();
    expect(result.diags.some((d: { code: string }) => d.code === 'mf.reg.unregistered-ref')).toBe(true);
  });

  it('孤立页面 → mf.nav.isolated-page', () => {
    const project = miniProject();
    project.pages!.push({ id: 'orphan-page', route: '/orphan', tree: { id: 'o', type: 'Text', props: { text: 'x' } } });
    const result = new MFValidator(project).validate();
    expect(result.diags.some((d: { code: string }) => d.code === 'mf.nav.isolated-page')).toBe(true);
  });

  it('路由重复 → mf.route.duplicate', () => {
    const project = miniProject();
    project.pages![1]!.route = '/';
    const result = new MFValidator(project).validate();
    expect(result.diags.some((d: { code: string }) => d.code === 'mf.route.duplicate')).toBe(true);
  });

  it('motion token 形状坏 → mf.motion.token-invalid；替代组悬空 → mf.motion.alternative-dangling', () => {
    const project = miniProject();
    project.tokens!['tokens-mini']!.tokens['motion.entrance'] = { duration: 'fast', curve: [1, 2] };
    project.tokens!['tokens-mini']!.tokens['motion.entrance.reduced'] = { duration: 0, curve: [0, 0, 1, 1] };
    project.tokens!['tokens-mini']!.tokens['motion.orphan.reduced'] = { duration: 0, curve: [0, 0, 1, 1] };
    const result = new MFValidator(project).validate();
    expect(result.diags.some((d: { code: string }) => d.code === 'mf.motion.token-invalid')).toBe(true);
    expect(result.diags.some((d: { code: string }) => d.code === 'mf.motion.alternative-dangling')).toBe(true);
  });

  it('主题不完备 → mf.theme.incomplete', () => {
    const project = miniProject();
    project.pages![0]!.pageOverrides = { background: 'color.bg.canvas' };
    project.themes!['theme-dark'] = { id: 'theme-dark', extends: 'theme-light' };
    project.themes!['theme-dark']!.overrides = { 'color.bg.canvas': { ref: 'color.missing.dark' } };
    // dark 主题重定向到缺失 token：effectiveTokens 深解析落 null → completeness 报缺。
    const result = new MFValidator(project).validate();
    expect(result.diags.some((d: { code: string }) => d.code === 'mf.theme.incomplete')).toBe(true);
  });

  it('motion 形状助手', () => {
    expect(asMotionSpec({ duration: 300, curve: [0.16, 1, 0.3, 1] })).not.toBeNull();
    expect(asMotionSpec({ duration: 'fast', curve: [] })).toBeNull();
    expect(asMotionSpec({ duration: 99999, curve: [0, 0, 0, 0] })).toBeNull();
  });
});

describe('样式求解器（§36.3/§36.6）', () => {
  it('ref 链深解析解到底', () => {
    const project = loadProject(miniProject());
    const resolver = new MFStyleResolver(project.tokens, project.styleSheets, project.themes, 'theme-light');
    expect(resolver.effectiveTokens('theme-light')['color.bg.canvas']).toBe('#F2F1EC');
  });
});
