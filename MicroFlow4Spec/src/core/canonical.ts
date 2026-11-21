/// 规范化与内容寻址：键递归排序的规范 JSON + SHA-256 摘要。
/// 与框架 config_hash（SHA-256 规范化 JSON）同语义；边界：值必须是 JSON 可序列化的
/// （模型经 validateSpecModel 门禁后满足）。

import { createHash } from 'node:crypto';

/** 键递归排序的规范 JSON：同输入字节一致（确定性输出纪律的摘要基础）。 */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (typeof value === 'object' && value !== null) {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    const body = keys
      .map((key) => `${JSON.stringify(key)}:${canonicalJson((value as Record<string, unknown>)[key])}`)
      .join(',');
    return `{${body}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

export function sha256Hex(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

/** 模型内容寻址摘要（带算法前缀，与宿主 config_hash 风格一致）。 */
export function canonicalDigest(value: unknown): string {
  return `sha256:${sha256Hex(canonicalJson(value))}`;
}
