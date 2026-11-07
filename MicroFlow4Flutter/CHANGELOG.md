## 0.7.0

产品级能力扩展与首个真实应用交付（两个纯 Web 应用 + 端到端运营闭环）——
* 框架扩展（由真实产品需求驱动）：
  - 声明式列表绑定：List 节点携带求值后的 `items`（List<Map>）时按项模板
    渲染，模板内 `item.<field>` 表达式作用域 + 项事件分发携带项上下文
    （键/锚点按 `#<itemKey>` 区分）；
  - 事件载荷契约：`dispatchEvent` 支持 `payload`（`value` 键，§5）并按
    组件契约校验载荷类型——不符进错误边界（mf.reg.contract-mismatch），
    不静默改型；Input/Select 的 change 值经 `prop.value` 进入绑定执行；
  - 表单元组件去桩：Input（TextFormField + onChanged 载荷回传）、Select
    （options 来自求值 props + initialValue + change 回传）、Tabs（labels
    声明）、Icon（闭合名称表）；builders 统一消费求值后 props；
  - 表达式：`item.<field>` 作用域、`prev.<as>.<path>` 深路径；
  - 采集注记 `args`：只有显式声明的参数键进入事件 payload（§24.7 定向内容）；
  - 信封恢复 `MFEventEnvelope.fromJson`（event_id/occurred_at 保留，§30.2
    查询消费面）；查询分组维度增加 session_id 与 payload.<key>；
    get_data_quality 补 loss_rate（§30.2）；
  - 恢复快照序列化 `MFRecoverySnapshot.toJson/fromJson`（§16.1 跨会话）；
    validator 支持页面生命周期锚（`<pageId>.onEnter|onLeave`）；
  - **遥测队列自动投递**：MFTelemetryQueue 增加 autoFlushAfter（默认 1s）
    ——低流量场景事件不再滞留队列（真实 Web 会话验证暴露的缺陷）。
* 应用 `apps/habit_tracker`（个人习惯打卡平台，纯 Web）：
  模型驱动（页面/绑定/导航/列表绑定/注记），宿主只注册真实实现——
  HabitStore 本地持久化（Web localStorage / VM 文件双实现，幂等键=习惯@日期、
  连击按本地日历计算）、打卡走 Business Fact 通道（去重身份幂等确认 +
  record_id 运行引用 + unknown 可查询）、§16.1 跨会话恢复（启动恢复 +
  随渲染代持久化）、MFStorageSink 遥测落盘（同源共享通道）。
* 应用 `apps/habit_admin`（运营管理平台，纯 Web）：
  读同源打卡平台遥测日志 → §30.2 查询引擎封装为运营适配器——概览指标
  （事件/打卡/会话/丢失率口径）、事件明细（query_events）、追踪查询
  （get_trace）、数据质量（get_data_quality）；自身事件独立落盘；
  损坏行计入丢弃口径，空数据如实空态（无假数据）。
* 测试：test/framework_ext_test.dart（6 用例）+ 应用级测试（tracker 6 +
  admin 3，跑真实存储实现）；全仓 73 用例。
* 浏览器端到端验证（真实 Chrome 会话）：创建习惯 → 打卡（幂等确认）
  → 遥测落盘 → 管理平台概览/明细呈现真实事件与分组计数 → 恢复快照还原
  页面状态（"连续 1 天/已打卡"）。
* `tool/serve_apps.py`：同源托管两端（/ 与 /admin/），localStorage 共享
  是管理平台读取打卡平台运营数据的前提。

## 0.6.0

M2 收尾清零（遗留项完整修复）——
* 渲染合一（Level 1 遗留主项）：解释器消费声明式布局模型——节点自约束
  `MFSelfConstraint` 映射渲染（fill 主轴 → Expanded、fixed → SizedBox、
  hug 按内容）；页面 `conditionalLayouts` 条件方案被渲染消费（§7.4，
  target 页面/节点均可，命中方案覆盖 Stack 方向/对齐）；显式 `layerRegions`
  按 header/footer/overlay/content 结构化渲染（§7.1，content 支持声明滚动，
  overlay 不再收缩宿主），未声明仍走隐式 ContentLayer（基线 12）；插槽
  区分（§23.9）：`slotOf`/命名插槽不再静默并入默认插槽，MFNodeView 按
  契约插槽传递。
* 修复渲染管道断点：primitive builders 改为消费已求值的 MFRenderContext
  （此前读取原始 node.props，条件布局方向、i18n 文本覆盖与样式 aspect
  均不会生效）。
* Tier B 补齐 Split/Anchor（§38.1 6/6）：Split 声明式 weights 分配，
  Anchor 仅相对容器边锚定（§7.3）。
* 协议债清零：`MFPage.errorBoundary` 被消费（绑定未声明边界时回退页面级
  边界）；product 状态作用域如实落位（§11，此前静默写 page 层）；queue
  并发策略真排队串行执行（§39.1，此前空实现）；`mf.tele.manual-standard-event`
  发射点落地（观测面拦截无运行时来源标记的标准事件族上报）；`mf.style.face-undeclared`
  发射点落地（节点样式片消费的 aspect 未在契约 exposedStyles 声明）；MFTierA
  单一来源移至模型层 + validator Tier A 缺失 warning 门禁；`MicroFlowApp.contract`
  暴露 mfFlutterRendererContract 生产消费点；渲染修订号 renderRevision 进入
  Debug 上下文（§12.1）；组件实例键走 `componentInstanceId`；运行诊断统一经
  MFDiagSink 承载；i18n 伪本地化视图 `MFI18nCatalog.pseudoLocalized`（§42
  开发期工具）。
* MFNode 新增 `layer` 显式图层归属字段（§7.1），validator 校验归属悬空；
  authoring 模板实例化携带 layer/style/constraints。
* 测试 test/closeout_test.dart（14 用例）：queue 排队、手工上报拦截、
  product 作用域、页面级边界、renderRevision、Tier A 门禁、face-undeclared、
  图层悬空、伪本地化 + 5 个 widget 测试（显式图层/约束映射/条件布局/
  Split/Anchor/契约）。全量 58 用例，analyze 0 issues。

## 0.5.0

M2（PLAN.md）：观测与恢复闭环 ——
* packages/microflow_model 0.3.0：Recovery Contract Schema（§16.1）、findings
  注记资源（§43.3，页面/组件/绑定可携带引用）、采集注记 MFTelemetryAnnotation
  与追踪传播 MFTracePropagation 契约（§24.7/§24.8）、标准事件族单一来源
  （events.dart）、隐私分类枚举收敛模型层；MFProject/MFPage/
  MFComponentDefinition/MFBinding 增加 copyWith；诊断码新增 8 个
  （build.recovery-auto-retry、state.snapshot-version-mismatch /
  snapshot-expired / release-migration-missing、data.fact-duplicate、
  tele.annotation-invalid / trace-ref-missing、reg.finding-invalid）。
* packages/microflow_runtime 0.3.0：Recovery 执行器（§16.1：快照收集/
  重校验/过期/显式迁移；auto_retry=false 强制、版本不匹配进错误边界，
  基线 27）；Business Fact 通道（§24.1 第 4 类、§30.1：提交确认 + 去重
  身份幂等 + 超时/缺运行引用进 unknown 可查询，基线 28）；追踪传播运行时
  注入出站上下文并记录外部运行引用（§24.8，基线 11）；unknown 结果台账
  （§22.1）；采集注记运行时零埋点发射、走完整校验管道（基线 8）；
  validator 绑定锚点改为全局解析（与 dispatchEvent 一致，多页面项目不再
  误报）+ Recovery/注记/findings 三道静态门禁；Debug 拦截事件流与检查点
  挂起（§29）。
* packages/microflow_observability 0.2.0：Telemetry Ingest 参考实现
  （§30.1：批量/退避/断网缓存/event_id 去重/数据质量指标与缺口窗口）；
  Query/Export 本地参考实现（§30.2 五协议：过滤/分页/分组、事件 Schema、
  追踪汇集、游标导出与缺口区间声明、数据质量）；Debug 控制面（订阅事件流、
  检查点暂停/继续、快照读取，逐 grant 授权）。
* packages/microflow_renderer_flutter 0.3.0：mfLocalizePageMessage 提取
  （§42.5，基线 5：回退链展示并上报缺失翻译，回退降级为 warning）。
* packages/microflow_authoring 0.2.0：register_finding 命令（§43.3 回流
  标准入口）；mutator 改用 copyWith，资源字段不再丢失。
* 测试 test/baseline_m2_test.dart：基线 5、8、11、17、27、28 落入可执行
  判据 + §29 控制面 + §30 口径一致性测试；覆盖 21/32 已覆盖 + 5 部分。

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
