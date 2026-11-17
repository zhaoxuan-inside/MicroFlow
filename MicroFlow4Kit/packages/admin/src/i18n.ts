/** admin 命名空间登记：文案资源见 resources/admin.{zh,en}.json（配置平面）。 */
import { registerI18nNamespace } from "@microflow4kit/ui";
import adminZh from "./resources/admin.zh.json";
import adminEn from "./resources/admin.en.json";

registerI18nNamespace("admin", { zh: adminZh, en: adminEn });
