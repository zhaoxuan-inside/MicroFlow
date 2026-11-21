/// 主题级联样式生成（§36.3）：把模型 token 集转换为主题 CSS 块（亮/暗各一
/// 个选择器），由 documentElement 的 data-theme 属性切换——主题切换即属性
/// 翻转（现代 web 原生级联），无需重渲染页面实例。

import type { MFStyleSheetJson, MFThemeJson, MFTokenSetJson } from '../model/types.ts';
import { MFStyleResolver } from '../model/loader.ts';
import { tokenToCssValue } from './color.ts';

/** 主题 CSS 数据源：JSON 模型与已解析模型（MFProjectParsed）共有的最小结构面。 */
export interface ThemeCssSource {
  manifest?: { default_theme?: string };
  tokens?: Record<string, MFTokenSetJson>;
  styleSheets?: Record<string, MFStyleSheetJson>;
  themes?: Record<string, MFThemeJson>;
}

export function buildThemeCss(project: ThemeCssSource, themeIds?: string[]): string {
  const resolver = new MFStyleResolver(
    project.tokens ?? {},
    project.styleSheets ?? {},
    project.themes ?? {},
    project.manifest?.default_theme,
  );
  const ids = themeIds && themeIds.length > 0 ? themeIds : Object.keys(project.themes ?? {});
  const chunks: string[] = [];
  for (const themeId of ids) {
    const effective = resolver.effectiveTokens(themeId);
    const decls: string[] = [];
    for (const [token, value] of Object.entries(effective)) {
      const cssValue = tokenToCssValue(token, value);
      if (cssValue === null) continue;
      decls.push(`--mf-${token.replaceAll('.', '-')}: ${cssValue};`);
    }
    const selector = themeId.endsWith('dark') ? 'html[data-theme="dark"], html[data-mf-theme="dark"]' : `:root, html[data-theme="light"], html[data-mf-theme="${themeId}"]`;
    chunks.push(`${selector} { color-scheme: ${themeId.endsWith('dark') ? 'dark' : 'light'}; ${decls.join('\n  ')} }`);
  }
  return chunks.join('\n');
}

/** 宿主主题同步：把当前主题 id 写入 data-mf-theme（tokenColor 文档级解析用）。 */
export function applyThemeId(themeId: string): void {
  document.documentElement.dataset.mfTheme = themeId;
}
