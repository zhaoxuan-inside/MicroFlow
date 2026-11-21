/// 脚本静态门禁：未知字段拒绝、步骤枚举、锚点引用检查——
/// 断言一律引用 MFProject 已注册锚点（复用"未注册引用是静态错误"纪律）；
/// 标准事件族外的 expect_event 是静态错误（运行时产生不了的事件不可断言）。
import { VRFCodes, vrfDiag, type VrfDiag } from '../diagnostics.ts';
import { DECLARED_OPS, IMPLEMENTED_OPS, type DeclaredOp, type VerifyScript } from './types.ts';
import type { ProjectFacts } from './facts.ts';

const STEP_KEYS: Record<DeclaredOp, ReadonlySet<string>> = {
  open: new Set(['op', 'page', 'params']),
  back: new Set(['op']),
  tap: new Set(['op', 'node', 'event', 'payload', 'item']),
  fill: new Set(['op', 'node', 'value']),
  expect_binding: new Set(['op', 'expr', 'equals']),
  expect_event: new Set(['op', 'event', 'payload']),
  expect_route: new Set(['op', 'page']),
  screenshot: new Set(['op']),
};

function isObj(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function checkUnknownFields(raw: Record<string, unknown>, allowed: ReadonlySet<string>, path: string, diags: VrfDiag[]): void {
  for (const key of Object.keys(raw)) {
    if (!allowed.has(key)) {
      diags.push(vrfDiag(VRFCodes.unknownField, `未知字段 "${key}"`, { path: `${path}.${key}` }));
    }
  }
}

function requireString(raw: Record<string, unknown>, key: string, path: string, diags: VrfDiag[]): void {
  const value = raw[key];
  if (value === undefined) {
    diags.push(vrfDiag(VRFCodes.missingRequired, `缺少必填字段 "${key}"`, { path: `${path}.${key}` }));
  } else if (!isNonEmptyString(value)) {
    diags.push(vrfDiag(VRFCodes.badType, `"${key}" 必须是非空字符串`, { path: `${path}.${key}` }));
  }
}

/** 事件锚检查：节点存在 → 类型契约注册 → 事件在契约 events 面。 */
function checkEventAnchor(step: Record<string, unknown>, path: string, facts: ProjectFacts, diags: VrfDiag[]): void {
  const node = step['node'];
  const event = step['event'];
  requireString(step, 'node', path, diags);
  requireString(step, 'event', path, diags);
  if (!isNonEmptyString(node) || !isNonEmptyString(event)) return;

  const type = facts.nodeTypeById.get(node);
  if (type === undefined) {
    diags.push(vrfDiag(VRFCodes.unknownNode, `节点 "${node}" 不在任何页面树中`, { path: `${path}.node` }));
    return;
  }
  const events = facts.eventsByType.get(type);
  if (events === undefined) {
    diags.push(vrfDiag(VRFCodes.unregisteredNodeType, `节点 "${node}" 的类型 "${type}" 未注册契约`, { path: `${path}.node` }));
    return;
  }
  if (!events.has(event)) {
    diags.push(
      vrfDiag(VRFCodes.unknownEvent, `类型 "${type}" 契约未声明事件 "${event}"（已声明：${[...events].join(', ') || '无'}）`, {
        path: `${path}.event`,
      }),
    );
  }
}

function checkStep(raw: unknown, index: number, facts: ProjectFacts, standardEvents: ReadonlySet<string>, diags: VrfDiag[]): void {
  const path = `steps[${index}]`;
  if (!isObj(raw)) {
    diags.push(vrfDiag(VRFCodes.badType, '步骤必须是对象', { path }));
    return;
  }
  const op = raw['op'];
  if (op === undefined) {
    diags.push(vrfDiag(VRFCodes.missingRequired, '缺少必填字段 "op"', { path: `${path}.op` }));
    return;
  }
  if (typeof op !== 'string' || !DECLARED_OPS.includes(op as DeclaredOp)) {
    diags.push(
      vrfDiag(VRFCodes.badEnum, `"op" 必须是 ${DECLARED_OPS.map((v) => `"${v}"`).join(' | ')}`, { path: `${path}.op` }),
    );
    return;
  }
  if (!IMPLEMENTED_OPS.includes(op as (typeof IMPLEMENTED_OPS)[number])) {
    diags.push(vrfDiag(VRFCodes.opUnimplemented, `步骤 "${op}" 已声明未实现（诚实边界：该面属后续切片）`, { path: `${path}.op` }));
    return;
  }

  checkUnknownFields(raw, STEP_KEYS[op as DeclaredOp], path, diags);
  switch (op as DeclaredOp) {
    case 'open': {
      requireString(raw, 'page', path, diags);
      if (isNonEmptyString(raw['page']) && !facts.pageIds.has(raw['page'])) {
        diags.push(vrfDiag(VRFCodes.unknownPage, `页面 "${raw['page']}" 不在模型中`, { path: `${path}.page` }));
      }
      if (raw['params'] !== undefined && !isObj(raw['params'])) {
        diags.push(vrfDiag(VRFCodes.badType, '"params" 必须是对象', { path: `${path}.params` }));
      }
      break;
    }
    case 'back':
      break;
    case 'tap':
      checkEventAnchor(raw, path, facts, diags);
      if (raw['payload'] !== undefined && !isObj(raw['payload'])) {
        diags.push(vrfDiag(VRFCodes.badType, '"payload" 必须是对象', { path: `${path}.payload` }));
      }
      break;
    case 'fill':
      requireString(raw, 'node', path, diags);
      if (isNonEmptyString(raw['node'])) {
        checkEventAnchor({ node: raw['node'], event: 'change' }, path, facts, diags);
      }
      if (raw['value'] === undefined) {
        diags.push(vrfDiag(VRFCodes.missingRequired, '缺少必填字段 "value"（fill 语义 = change 载荷 {value}）', { path: `${path}.value` }));
      }
      break;
    case 'expect_binding': {
      if (raw['expr'] === undefined || !isObj(raw['expr'])) {
        diags.push(vrfDiag(VRFCodes.badType, '"expr" 必须是 MFExpr 表达式对象（如 {"ref": "state.count"}）', { path: `${path}.expr` }));
      }
      if (!('equals' in raw)) {
        diags.push(vrfDiag(VRFCodes.missingRequired, '缺少必填字段 "equals"', { path: `${path}.equals` }));
      }
      break;
    }
    case 'expect_event': {
      requireString(raw, 'event', path, diags);
      if (isNonEmptyString(raw['event']) && !standardEvents.has(raw['event'])) {
        diags.push(vrfDiag(VRFCodes.unknownStandardEvent, `"${raw['event']}" 不在标准事件族（零埋点：运行时只产生标准事件）`, { path: `${path}.event` }));
      }
      if (raw['payload'] !== undefined && !isObj(raw['payload'])) {
        diags.push(vrfDiag(VRFCodes.badType, '"payload" 必须是对象（子集匹配）', { path: `${path}.payload` }));
      }
      break;
    }
    case 'expect_route': {
      requireString(raw, 'page', path, diags);
      if (isNonEmptyString(raw['page']) && !facts.pageIds.has(raw['page'])) {
        diags.push(vrfDiag(VRFCodes.unknownPage, `页面 "${raw['page']}" 不在模型中`, { path: `${path}.page` }));
      }
      break;
    }
    case 'screenshot':
      break;
  }
}

export function validateScript(raw: unknown, facts: ProjectFacts, standardEvents: ReadonlySet<string>): VrfDiag[] {
  const diags: VrfDiag[] = [];
  if (!isObj(raw)) {
    diags.push(vrfDiag(VRFCodes.badType, '根必须是 JSON 对象', { path: '$' }));
    return diags;
  }
  checkUnknownFields(raw, new Set(['scriptVersion', 'title', 'steps']), '$', diags);

  if (raw['scriptVersion'] === undefined) {
    diags.push(vrfDiag(VRFCodes.missingRequired, '缺少必填字段 "scriptVersion"', { path: '$.scriptVersion' }));
  } else if (raw['scriptVersion'] !== 1) {
    diags.push(vrfDiag(VRFCodes.dialectUnsupported, `scriptVersion 只支持 1，收到 ${JSON.stringify(raw['scriptVersion'])}`, { path: '$.scriptVersion' }));
  }
  requireString(raw, 'title', '$', diags);

  const steps = raw['steps'];
  if (steps === undefined) {
    diags.push(vrfDiag(VRFCodes.missingRequired, '缺少必填字段 "steps"', { path: '$.steps' }));
  } else if (!Array.isArray(steps) || steps.length === 0) {
    diags.push(vrfDiag(VRFCodes.badType, '"steps" 必须是非空步骤数组', { path: '$.steps' }));
  } else {
    steps.forEach((step, index) => checkStep(step, index, facts, standardEvents, diags));
  }
  return diags;
}

/** 仅当 0 error 时才产出脚本——不运行半成品脚本。 */
export function toVerifyScript(raw: unknown, diags: VrfDiag[]): VerifyScript | undefined {
  if (diags.some((d) => d.severity === 'error')) return undefined;
  return raw as VerifyScript;
}
