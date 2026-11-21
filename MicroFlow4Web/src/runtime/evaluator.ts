/// 受限表达式求值器（§37.2 白名单子集）：字面量 / ref / 比较 / 逻辑 /
/// call / 结构深求值。禁 eval/new Function——只按形状解释。
/// 诊断：未声明成员 → mf.interaction.unknown-member。

import type { MFDiag } from '../diagnostics.ts';
import { mfDiag, MFCodes } from '../diagnostics.ts';

export interface EvalScopes {
  /** prop 作用域（节点 props 求值时的已解析值）。 */
  prop?: Record<string, unknown>;
  /** 页面实例参数。 */
  param?: Record<string, unknown>;
  /** 页面状态成员（page 层当前实例）。 */
  state?: Record<string, unknown>;
  /** 会话层。 */
  session?: Record<string, unknown>;
  /** 产品层。 */
  product?: Record<string, unknown>;
  /** 动作链结果（prev.<as>）。 */
  prev?: Record<string, unknown>;
  /** 组件实例 provided 值（模型组合组件 §6）。 */
  provided?: Record<string, unknown>;
  /** 列表模板 item 上下文。 */
  item?: unknown;
  /** capability 探针结果。 */
  capability?: Record<string, unknown>;
}

export type FunctionRegistry = (id: string) =>
  | ((args: Record<string, unknown>, ctx: { evaluate: (v: unknown) => unknown }) => unknown)
  | undefined;

export class MFExpressionEvaluator {
  private readonly diags: MFDiag[] = [];

  constructor(private readonly functions: FunctionRegistry = () => undefined) {}

  drainDiags(): MFDiag[] {
    return this.diags.splice(0);
  }

  /** 深求值：表达式形状节点求值，字面量骨架保持（§37.2 MFStruct）。 */
  deep(value: unknown, scopes: EvalScopes): unknown {
    return this.eval(value, scopes);
  }

  /** 求值一个表达式/字面量。 */
  eval(value: unknown, scopes: EvalScopes): unknown {
    if (value === null || typeof value !== 'object') return value;
    if (Array.isArray(value)) return value.map((v) => this.eval(v, scopes));
    const rec = value as Record<string, unknown>;
    const keys = Object.keys(rec);
    // ref
    if (keys.length >= 1 && 'ref' in rec && typeof rec['ref'] === 'string') {
      return this.resolveRef(rec['ref'], scopes);
    }
    // call
    if ('call' in rec && typeof rec['call'] === 'string') {
      const fn = this.functions(rec['call']);
      if (!fn) {
        this.diags.push(mfDiag(MFCodes.interactionUnknownMember,
          `表达式 call 引用未注册函数：${rec['call']}`));
        return null;
      }
      const rawArgs = (rec['arguments'] ?? {}) as Record<string, unknown>;
      const args: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(rawArgs)) args[k] = this.eval(v, scopes);
      return fn(args, { evaluate: (v) => this.eval(v, scopes) });
    }
    // 比较
    for (const op of ['gt', 'gte', 'lt', 'lte', 'eq', 'neq'] as const) {
      if (op in rec) {
        const operands = (rec[op] as unknown[]).map((v) => this.eval(v, scopes));
        return compare(op, operands[0], operands[1]);
      }
    }
    // 逻辑
    if ('and' in rec) return (rec['and'] as unknown[]).every((v) => truthy(this.eval(v, scopes)));
    if ('or' in rec) return (rec['or'] as unknown[]).some((v) => truthy(this.eval(v, scopes)));
    if ('not' in rec) return !truthy(this.eval(rec['not'], scopes));
    // 字面量映射骨架：递归深求值（0.8.0 §37.2）。
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(rec)) out[k] = this.eval(v, scopes);
    return out;
  }

  private resolveRef(path: string, scopes: EvalScopes): unknown {
    const parts = path.split('.');
    const scope = parts[0]!;
    const rest = parts.slice(1);
    const layer = (scopes as Record<string, unknown>)[scope];
    let cur: unknown = layer;
    // 无余路径：整个作用域层对象。
    if (rest.length === 0) return cur ?? null;
    // item 上下文特殊：item.x 直接取字段；裸 item 也允许。
    if (scope === 'item') {
      cur = scopes.item;
    }
    for (const p of rest) {
      if (cur !== null && typeof cur === 'object') {
        cur = (cur as Record<string, unknown>)[p];
      } else {
        this.diags.push(mfDiag(MFCodes.interactionUnknownMember, `表达式引用未声明的成员：${path}`));
        return null;
      }
    }
    return cur ?? null;
  }
}

function truthy(v: unknown): boolean {
  return v !== null && v !== undefined && v !== false && v !== 0 && v !== '';
}

function compare(op: string, a: unknown, b: unknown): boolean {
  switch (op) {
    case 'gt': return (a as number) > (b as number);
    case 'gte': return (a as number) >= (b as number);
    case 'lt': return (a as number) < (b as number);
    case 'lte': return (a as number) <= (b as number);
    case 'eq': return a === b;
    case 'neq': return a !== b;
    default: return false;
  }
}
