# MicroFlow4Web

MicroFlow Frontend 的 **Web DOM 渲染器**：把平台无关的 `MFProject` 声明式模型解释为现代 web 平台原语（vanilla TypeScript，零运行时依赖）。

与 MicroFlow4Flutter 平级：同一份模型（页面/绑定图/导航图/i18n/Token/主题），两个渲染面。模型 JSON 由宿主产品导出（见 OpcHub `frontend_flutter/tool/export_model.dart`）。

## 架构

```
src/
  diagnostics.ts     统一诊断码注册表（与 Flutter 实现同名同语义，§41）
  model/
    types.ts         MFProject JSON 形态类型
    loader.ts        模型加载/绑定动作解析/i18n 回退链/MFStyleResolver 移植
  validator/
    validator.ts     静态校验门禁：方言/路由导航/引用/绑定锚/状态成员/
                     motion token/样式片/主题完备性
  runtime/
    state-store.ts   三层状态存储（page/session/product，writeDeep 语义）
    evaluator.ts     受限表达式求值器（白名单子集，禁 eval）
    runtime.ts       解释运行时：页面实例/导航栈/绑定链执行/并发策略/
                     guard/超时 unknown/零埋点标准事件/History 同步
  renderer/
    primitives.ts    Tier A 12 + Tier B 6 元组件的 DOM 实现
    interpreter.ts   MFNode → DOM 解释器（token→CSS 变量、语义落位、动效面）
    motion.ts        动效 token 解析（§36.5 声明面 + §36.7 减少动效替代组）
    styles.css       框架基础样式（color-scheme/focus-visible/scrollbar-color/
                     View Transitions/@starting-style 入场/reduced-motion）
  observability/
    sink.ts          EmissionSink + 有界队列 + JSONL 落地参考实现
```

## 现代平台原语对位

| 模型概念 | Web 实现 |
| :--- | :--- |
| 页面切换 | View Transitions API（`document.startViewTransition`，reduced 时直切） |
| 对话框 | 原生 `<dialog>`（showModal / ::backdrop / 焦点管理内置） |
| 按钮/链接 | 原生 `<button>` / `<a href>`（SEO/键盘/中键全兼容） |
| 输入 | 原生 `<input>/<select>`（autofill/校验/label 语义） |
| token | CSS 自定义属性（oklch 值原样透传） |
| 入场动效 | CSS transition（时长/曲线来自 motion token） |
| 长列表 | `content-visibility: auto` |
| 暗色 | prefers-color-scheme + class 覆盖 + `color-scheme` 同步 |
| 滚动条 | `scrollbar-color` / `scrollbar-width`（不隐藏） |
| 键盘焦点 | 全局 `:focus-visible` ring |

## 纪律（与 4Flutter 一致）

- 三平面分离：配置不带逻辑；一切修改过同一 `MFValidator` 门禁。
- 动效只解析到 motion token；未声明面拒绝并记录。
- 零埋点：标准运营事件由运行时边界产生；业务手工上报是静态错误。
- 诊断码单一来源（§41.3）：与 Dart 侧 `MFCodes` 一一对应。

## 测试

```bash
npm install          # 共享盘环境加 --bin-links=false
npm test             # vitest run（求值器/门禁诊断码/运行时语义/DOM 冒烟）
npm run typecheck    # tsc --noEmit
```
