## 0.3.0

* 新增 packages/microflow_authoring：§14 结构化命令面最小闭环
  （create_page / create_page_from_template / connect_navigation /
  validate_project / inspect_impact），候选项目过同一静态校验门禁，
  修改审计与可回滚修订，页面模板参数化实例化（§4、§2.7）；
* 模型新增：MFPageTemplate 页面模板、MFControlledCrossingList 受控交叉
  清单（§2.9）、manifest 类型方言版本（§4.6）、诊断码 route.duplicate /
  schema.template-param-invalid / schema.dialect-unsupported /
  schema.inline-logic / exp.variant-out-of-scope；
* 校验器新增：类型方言检查（基线 14）、结构树内联可执行逻辑拒绝
  （基线 31 静态部分）、受控交叉清单门禁（基线 32 静态部分）、
  consumes 可解析到上游容器 provides（基线 16 增强）；
* 一致性基线机器可读化：docs/design/baselines.json 为 §44.3 投影，
  tool/baseline_coverage.dart 生成覆盖表，守卫测试锁定基线引用与
  §41 诊断码单一来源（修复未登记码 mf.reg.deprecated、mf.tele.schema-invalid）；
* 总包再导出 authoring 模块。

## 0.4.0

M1（PLAN.md）：样式与布局完整化 ——
* packages/microflow_model 0.2.0：新增 `styles.dart`（MFTheme extends 重定向、
  MFStyleSheet 变体条件、覆盖链 MFOverrideTier、MFStyleResolver、
  validateStyleSheets 字面量禁令）与 `layout.dart`（MFSelfConstraint、
  MFConditionalLayout 默认方案必填）；MFCodes 并入 layout/style 区域码。
* packages/microflow_runtime 0.2.0：`layout_solver.dart` —— §7.3 形式化求解
  （solve → 规范化矩形集，hug/fill 分配与 mf.layout.overflow 诊断）、
  staticLayoutChecks（同轴 fill+fixed、fixed 超界、覆盖环、模糊选择器、
  未声明降级）；MFValidator 启动门禁并入布局与样式检查；
  MFRuntime 增加 themeProvider（基线 7 切换只影响新建实例）。
* packages/microflow_renderer_flutter 0.2.0：Tier B Tabs/Drawer/Table、
  样式片 foreground/background 解析进渲染、mfFlutterRendererContract
  （§12.1 Schema + validate）；
  主题渲染闭环：MFStyleResolver 按实例冻结主题解析（`resolveNode/resolveSheet`
  增加 themeId，页面覆盖值改为在生效主题内判定），MicroFlowApp 增加
  themeSelection/themeNames 切换面与按选中主题推导种子色。
* example：双层主题演示（theme-light 默认 + theme-dark extends 重定向），
  标题经样式片 `style-title` 走覆盖链（§36.6），AppBar 菜单切换只影响新建实例
  （PLAN M1 验收项）。
* 测试 test/baseline_m1_test.dart：基线 7、12、18、19、20、21 落入可执行判据；
  测试名统一为「基线 N」标记语法（18-21 此前不在覆盖工具扫描范围内）；
  基线 22 如实标记「部分」（当前仅覆盖 §36.4 token 规则侧，§36.5 动效面未实现）。

## 0.2.0

模块化重构：将框架实现拆分为 4 个可独立升级的子包，总包仅做装配：

* packages/microflow_model —— 项目模型/契约/诊断注册表/i18n/Token；
* packages/microflow_runtime —— 统一资源注册/静态校验/解释运行时/错误边界，
  新增 MFEmissionSink 稳定发射接口（运行时不依赖观测面实现）；
* packages/microflow_observability —— 遥测信封与有界队列（实现了
  MFEmissionSink）、标准事件族、实验冻结、Debug 会话；
* packages/microflow_renderer_flutter —— Tier A 渲染、解释器、MicroFlowApp；
* 总包 MicroFlowFramework.create：一次装配 + 静态校验门禁。
* 依赖单向收敛：model ← runtime ← {observability, renderer}。

## 0.1.0

* 首次实现框架核心（Level 0 + Level 1 解释模式 + Level 2 部分契约面），
  §44.2 备忘示例与基线测试。

首次按 `docs/design/frontend-framework-design.md` v1.12 实现框架核心：

* Level 0：项目模型 / 契约（组件、元组件、容器信息面）/ 静态校验器 / 统一
  诊断码注册表 / i18n 资源模型 / Token 最小集。
* Level 1：解释运行时（页面实例、导航、状态层、绑定映射与并发策略、
  guard、unknown 结果语义、错误边界）、Tier A 元组件 Flutter 渲染。
* Level 2 契约面：Telemetry 信封 Schema 与有界队列、标准运营事件族零埋点
  采集、实验分配冻结与停用语义、Debug 会话授权与快照屏蔽。
* example/：§44.2 “备忘（Notes）” 规范性最小示例产品。
* 一致性基线测试覆盖 §44.3 可单测条目（1、2、3、13、15、16、26、29、30 部分）。

## 0.0.1

* 骨架包：仅占位的 project model 与 app 入口。
