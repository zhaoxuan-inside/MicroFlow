/// 结构化 diff：两个 spec 模型按 id 对齐，报告需求/场景的增删改。
/// 确定性输出：数组一律按 id 排序；"改"= 同 id 条目的规范 JSON 不相等。
import { canonicalDigest, canonicalJson } from './canonical.ts';
import type { SpecModel } from '../model/types.ts';

export interface FamilyDiff {
  added: string[];
  removed: string[];
  changed: string[];
}

export interface SpecDiff {
  digestOld: string;
  digestNew: string;
  requirements: FamilyDiff;
  scenarios: FamilyDiff;
}

function familyDiff<K extends 'requirements' | 'scenarios'>(
  oldModel: SpecModel,
  newModel: SpecModel,
  family: K,
): FamilyDiff {
  const oldById = new Map(oldModel[family].map((item) => [item.id, item]));
  const newById = new Map(newModel[family].map((item) => [item.id, item]));
  const added = [...newById.keys()].filter((id) => !oldById.has(id)).sort();
  const removed = [...oldById.keys()].filter((id) => !newById.has(id)).sort();
  const changed = [...newById.keys()]
    .filter((id) => oldById.has(id) && canonicalJson(newById.get(id)) !== canonicalJson(oldById.get(id)))
    .sort();
  return { added, removed, changed };
}

export function diffSpec(oldModel: SpecModel, newModel: SpecModel): SpecDiff {
  return {
    digestOld: canonicalDigest(oldModel),
    digestNew: canonicalDigest(newModel),
    requirements: familyDiff(oldModel, newModel, 'requirements'),
    scenarios: familyDiff(oldModel, newModel, 'scenarios'),
  };
}
