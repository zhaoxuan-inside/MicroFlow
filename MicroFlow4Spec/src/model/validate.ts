/// SpecModel v1 静态校验门禁：未知字段拒绝、必填/枚举/类型检查、
/// 悬空引用与重复 id 检查。0 error 诊断才允许进入 coverage/verify。
import { SPCodes, specDiag, type SpecDiag } from '../diagnostics.ts';
import type {
  CarrierKind,
  ScenarioExpectation,
  ScenarioKind,
  SpecCarrier,
  SpecModel,
  SpecPriority,
  SpecScenario,
  SpecStatus,
} from './types.ts';

const PRIORITIES: readonly SpecPriority[] = ['must', 'should', 'could'];
const STATUSES: readonly SpecStatus[] = ['open', 'accepted', 'delivered'];
const SCENARIO_KINDS: readonly ScenarioKind[] = ['backend_run', 'orch_scenario', 'ui_script', 'manual'];
const CARRIER_KINDS: readonly CarrierKind[] = ['operator', 'flow', 'page', 'component', 'scene'];

const REQUIREMENT_KEYS = new Set(['id', 'title', 'statement', 'priority', 'status']);
const SCENARIO_KEYS = new Set(['id', 'title', 'kind', 'requirementRefs', 'carriers', 'expectation']);
const CARRIER_KEYS = new Set(['kind', 'id']);
const EXPECTATION_KEYS: Record<ScenarioKind, ReadonlySet<string>> = {
  backend_run: new Set(['flow', 'input', 'expectOutput', 'expectMetaStatus']),
  orch_scenario: new Set(['scenario', 'expectStatus']),
  ui_script: new Set(['script']),
  manual: new Set(['note']),
};

function isObj(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

/** 未知字段拒绝：path 指向违规键本身。 */
function checkUnknownFields(
  raw: Record<string, unknown>,
  allowed: ReadonlySet<string>,
  path: string,
  diags: SpecDiag[],
): void {
  for (const key of Object.keys(raw)) {
    if (!allowed.has(key)) {
      diags.push(specDiag(SPCodes.unknownField, `未知字段 "${key}"`, { path: `${path}.${key}` }));
    }
  }
}

/** 字段级诊断统一指向字段本身（缺失/坏类型/坏枚举同规则）。 */
function checkString(
  raw: Record<string, unknown>,
  key: string,
  path: string,
  diags: SpecDiag[],
): void {
  const value = raw[key];
  if (value === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, `缺少必填字段 "${key}"`, { path: `${path}.${key}` }));
  } else if (!isNonEmptyString(value)) {
    diags.push(specDiag(SPCodes.badType, `"${key}" 必须是非空字符串`, { path: `${path}.${key}` }));
  }
}

function checkEnum<T extends string>(
  raw: Record<string, unknown>,
  key: string,
  allowed: readonly T[],
  path: string,
  diags: SpecDiag[],
): void {
  const value = raw[key];
  if (value === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, `缺少必填字段 "${key}"`, { path: `${path}.${key}` }));
  } else if (typeof value !== 'string' || !allowed.includes(value as T)) {
    diags.push(
      specDiag(SPCodes.badEnum, `"${key}" 必须是 ${allowed.map((v) => `"${v}"`).join(' | ')}`, { path: `${path}.${key}` }),
    );
  }
}

function checkRequirement(raw: unknown, index: number, diags: SpecDiag[]): void {
  const path = `requirements[${index}]`;
  if (!isObj(raw)) {
    diags.push(specDiag(SPCodes.badType, '需求条目必须是对象', { path }));
    return;
  }
  checkUnknownFields(raw, REQUIREMENT_KEYS, path, diags);
  checkString(raw, 'id', path, diags);
  checkString(raw, 'title', path, diags);
  checkString(raw, 'statement', path, diags);
  checkEnum(raw, 'priority', PRIORITIES, path, diags);
  checkEnum(raw, 'status', STATUSES, path, diags);
}

function checkExpectation(
  kind: ScenarioKind,
  raw: Record<string, unknown>,
  path: string,
  diags: SpecDiag[],
): void {
  const expectation = raw['expectation'];
  if (expectation === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, '缺少必填字段 "expectation"', { path: `${path}.expectation` }));
    return;
  }
  if (!isObj(expectation)) {
    diags.push(specDiag(SPCodes.badType, '"expectation" 必须是对象', { path }));
    return;
  }
  const expPath = `${path}.expectation`;
  checkUnknownFields(expectation, EXPECTATION_KEYS[kind], expPath, diags);
  switch (kind) {
    case 'backend_run':
      checkString(expectation, 'flow', expPath, diags);
      checkStringMap(expectation, 'expectOutput', expPath, diags);
      if (expectation['expectMetaStatus'] !== undefined && !isNonEmptyString(expectation['expectMetaStatus'])) {
        diags.push(specDiag(SPCodes.badType, '"expectMetaStatus" 必须是非空字符串', { path: `${expPath}.expectMetaStatus` }));
      }
      break;
    case 'orch_scenario':
      checkString(expectation, 'scenario', expPath, diags);
      checkString(expectation, 'expectStatus', expPath, diags);
      break;
    case 'ui_script':
      checkString(expectation, 'script', expPath, diags);
      break;
    case 'manual':
      checkString(expectation, 'note', expPath, diags);
      break;
  }
}

function checkStringMap(
  raw: Record<string, unknown>,
  key: string,
  path: string,
  diags: SpecDiag[],
): void {
  const value = raw[key];
  if (value === undefined) return;
  if (!isObj(value)) {
    diags.push(specDiag(SPCodes.badType, `"${key}" 必须是 "点路径 → 期望值" 对象`, { path: `${path}.${key}` }));
    return;
  }
  for (const [k, v] of Object.entries(value)) {
    if (!isNonEmptyString(k)) {
      diags.push(specDiag(SPCodes.badType, `"${key}" 的键必须是非空点路径`, { path: `${path}.${key}` }));
    }
    if (v === undefined) {
      diags.push(specDiag(SPCodes.badType, `"${key}" 的值必须是 JSON 值（不含 undefined）`, { path: `${path}.${key}.${k}` }));
    }
  }
}

function checkCarriers(
  raw: Record<string, unknown>,
  path: string,
  diags: SpecDiag[],
): SpecCarrier[] | undefined {
  const value = raw['carriers'];
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) {
    diags.push(specDiag(SPCodes.badType, '"carriers" 必须是数组', { path: `${path}.carriers` }));
    return undefined;
  }
  const carriers: SpecCarrier[] = [];
  value.forEach((item, index) => {
    const carrierPath = `${path}.carriers[${index}]`;
    if (!isObj(item)) {
      diags.push(specDiag(SPCodes.badType, '载体必须是对象', { path: carrierPath }));
      return;
    }
    checkUnknownFields(item, CARRIER_KEYS, carrierPath, diags);
    checkEnum(item, 'kind', CARRIER_KINDS, carrierPath, diags);
    checkString(item, 'id', carrierPath, diags);
    if (isNonEmptyString(item['id']) && typeof item['kind'] === 'string') {
      carriers.push({ kind: item['kind'] as CarrierKind, id: item['id'] });
    }
  });
  return carriers;
}

function checkScenario(
  raw: unknown,
  index: number,
  requirementIds: Set<string>,
  diags: SpecDiag[],
): void {
  const path = `scenarios[${index}]`;
  if (!isObj(raw)) {
    diags.push(specDiag(SPCodes.badType, '场景条目必须是对象', { path }));
    return;
  }
  checkUnknownFields(raw, SCENARIO_KEYS, path, diags);
  checkString(raw, 'id', path, diags);
  checkString(raw, 'title', path, diags);
  checkEnum(raw, 'kind', SCENARIO_KINDS, path, diags);

  const refs = raw['requirementRefs'];
  if (refs === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, '缺少必填字段 "requirementRefs"', { path }));
  } else if (!Array.isArray(refs) || !refs.every(isNonEmptyString)) {
    diags.push(
      specDiag(SPCodes.badType, '"requirementRefs" 必须是非空字符串数组（可为空 = 场景待挂接）', {
        path: `${path}.requirementRefs`,
      }),
    );
  } else {
    refs.forEach((ref, refIndex) => {
      if (!requirementIds.has(ref)) {
        diags.push(
          specDiag(SPCodes.danglingRequirement, `需求引用 "${ref}" 不存在`, {
            path: `${path}.requirementRefs[${refIndex}]`,
          }),
        );
      }
    });
  }

  checkCarriers(raw, path, diags);

  if (typeof raw['kind'] === 'string' && SCENARIO_KINDS.includes(raw['kind'] as ScenarioKind)) {
    checkExpectation(raw['kind'] as ScenarioKind, raw, path, diags);
  }
}

/** 校验任意 JSON 为 SpecModel 的门禁；返回全部诊断（error 即不通过）。 */
export function validateSpecModel(raw: unknown): SpecDiag[] {
  const diags: SpecDiag[] = [];
  if (!isObj(raw)) {
    diags.push(specDiag(SPCodes.badType, '根必须是 JSON 对象', { path: '$' }));
    return diags;
  }
  checkUnknownFields(raw, new Set(['specVersion', 'project', 'requirements', 'scenarios']), '$', diags);

  if (raw['specVersion'] === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, '缺少必填字段 "specVersion"', { path: '$.specVersion' }));
  } else if (raw['specVersion'] !== 1) {
    diags.push(specDiag(SPCodes.dialectUnsupported, `specVersion 只支持 1，收到 ${JSON.stringify(raw['specVersion'])}`, { path: '$.specVersion' }));
  }
  checkString(raw, 'project', '$', diags);

  const requirementIds = new Set<string>();
  const seenRequirementIds = new Set<string>();
  const requirements = raw['requirements'];
  if (requirements === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, '缺少必填字段 "requirements"', { path: '$' }));
  } else if (!Array.isArray(requirements)) {
    diags.push(specDiag(SPCodes.badType, '"requirements" 必须是数组', { path: '$.requirements' }));
  } else {
    requirements.forEach((item, index) => {
      checkRequirement(item, index, diags);
      if (isObj(item) && isNonEmptyString(item['id'])) {
        if (seenRequirementIds.has(item['id'])) {
          diags.push(specDiag(SPCodes.duplicateId, `需求 id "${item['id']}" 重复`, { path: `requirements[${index}].id` }));
        }
        seenRequirementIds.add(item['id']);
        requirementIds.add(item['id']);
      }
    });
  }

  const seenScenarioIds = new Set<string>();
  const scenarios = raw['scenarios'];
  if (scenarios === undefined) {
    diags.push(specDiag(SPCodes.missingRequired, '缺少必填字段 "scenarios"', { path: '$' }));
  } else if (!Array.isArray(scenarios)) {
    diags.push(specDiag(SPCodes.badType, '"scenarios" 必须是数组', { path: '$.scenarios' }));
  } else {
    scenarios.forEach((item, index) => {
      checkScenario(item, index, requirementIds, diags);
      if (isObj(item) && isNonEmptyString(item['id'])) {
        if (seenScenarioIds.has(item['id'])) {
          diags.push(specDiag(SPCodes.duplicateId, `场景 id "${item['id']}" 重复`, { path: `scenarios[${index}].id` }));
        }
        seenScenarioIds.add(item['id']);
      }
    });
  }
  return diags;
}

/** 仅当 0 error 时才返回模型——调用方据此拒绝半成品（与框架"不发布半成品"同语义）。 */
export function toSpecModel(raw: unknown, diags: SpecDiag[]): SpecModel | undefined {
  if (diags.some((d) => d.severity === 'error')) return undefined;
  return raw as SpecModel;
}
