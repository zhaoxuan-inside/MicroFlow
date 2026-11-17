/** i18next 生产初始化：文案 = JSON 资源文件（配置平面），代码零硬编码。
 *
 * 各包在模块作用域经 [registerI18nNamespace] 登记自己的命名空间资源（纯数据收集）；
 * 宿主 SPA 在 main.tsx 调 [initI18n] 一次性装载（import 先于函数体执行，顺序安全）。
 * 语言探测 localStorage → navigator（持久化键 host.localeKey），回退语言 zh；
 * 全局单例 + react-i18next，无需 Provider；未调 initI18n 的 SPA 中共享组件经
 * 默认上下文渲染中文（未接入平台零影响）。
 */
import i18next, { type i18n as I18nInstance } from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { host } from "@microflow4kit/api";
import { Button } from "../primitives";
import uiZh from "./resources/ui.zh.json";
import uiEn from "./resources/ui.en.json";

export type Locale = "zh" | "en";
export type I18nBundle = Record<string, unknown>;

const registered: Array<{ ns: string; zh: I18nBundle; en: I18nBundle }> = [
  { ns: "ui", zh: uiZh as I18nBundle, en: uiEn as I18nBundle },
];

/** 各包在模块作用域登记命名空间资源；须在任何 initI18n 调用前完成 import。 */
export function registerI18nNamespace(ns: string, bundles: { zh: I18nBundle; en: I18nBundle }) {
  registered.push({ ns, ...bundles });
}

let instance: I18nInstance | null = null;

export interface InitI18nOptions {
  /** 固定语言（跳过探测与持久化）；未提供语言切换面的 SPA 传 "zh"。 */
  lng?: Locale;
}

/** 幂等初始化：重复调用返回既有实例。 */
export function initI18n(options: InitI18nOptions = {}): I18nInstance {
  if (instance) return instance;
  const resources: Record<Locale, Record<string, I18nBundle>> = { zh: {}, en: {} };
  for (const { ns, zh, en } of registered) {
    resources.zh[ns] = zh;
    resources.en[ns] = en;
  }
  void i18next.use(initReactI18next).use(LanguageDetector).init({
    lng: options.lng,
    fallbackLng: "zh",
    supportedLngs: ["zh", "en"],
    defaultNS: "ui",
    resources,
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: host.localeKey,
      caches: ["localStorage"],
    },
    interpolation: { escapeValue: false },
    returnEmptyString: false,
    react: { useSuspense: false },
  });
  instance = i18next;
  return instance;
}

/** 语言切换按钮：显示目标语言（当前 zh 显示 EN，当前 en 显示 中文）。 */
export function LocaleSwitcher() {
  const { t } = useTranslation("ui");
  return (
    <Button
      variant="ghost"
      aria-label={t("switcher.aria")}
      className="h-8 px-2 text-xs"
      onClick={() => void i18next.changeLanguage(i18next.language === "zh" ? "en" : "zh")}
    >
      {t("switcher.target")}
    </Button>
  );
}
