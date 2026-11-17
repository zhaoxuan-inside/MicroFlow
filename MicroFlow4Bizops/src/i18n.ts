/** bizops 命名空间登记：文案资源见 resources/bizops.{zh,en}.json（配置平面）。 */
import { registerI18nNamespace } from "@microflow4kit/ui";
import bizopsZh from "./resources/bizops.zh.json";
import bizopsEn from "./resources/bizops.en.json";

registerI18nNamespace("bizops", { zh: bizopsZh, en: bizopsEn });
