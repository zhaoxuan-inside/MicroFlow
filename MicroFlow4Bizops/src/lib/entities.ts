/** 运营概览实体标签解析（纯函数）。
 * 实体名 → i18n 文案键（bizops.entity_*）；未登记实体如实回退显示原名，
 * 不做任何"猜测式美化"——数据口径诚实披露优先于展示。 */
export function entityLabelKey(name: string, mapping: Record<string, string>): string {
  return mapping[name] || name;
}
