# MicroFlow4Flutter 实施规划（按 frontend-framework-design v1.12）

版本：v1.0
日期：2026-10-24
状态：规划基线
上游：`docs/design/frontend-framework-design.md`（v1.12，设计基线）
本文角色：MicroFlow4Flutter 子项目的路线图与里程碑验收依据；修订规则见 §8。

---

## 1. 定位与范围

MicroFlow4Flutter 是 MicroFlow Frontend（frontend-framework-design）的 **Flutter 承载**：以 Flutter 实现 Renderer（§12）、解释运行时（§13.2），并逐步补齐编译模式（§13.3）、观测闭环（§24/§30）、恢复与性能门禁（§16/§22）。

- 本规划不改变设计文档的任何契约；只决定“实现顺序、验收条件与责任面”。
- 设计文档 §20 明确“基线即最小完整核心能力集”：本规划不存在“裁剪版交付”，任何阶段产物按 §38.2 如实声明一致性分级。
- 阅读路径：开发本包 → §2（现状）；排期评审 → §4（里程碑）；验收 → §5（判定）；模块负责人 → §6（模块路线）。

## 2. 现状盘点（截至 2026-10-24，commit 7c1b4b4 之后）

### 2.1 模块结构

```text
MicroFlow4Flutter/
├── lib/microflow4_flutter.dart       总包 0.2.0：MicroFlowFramework.create 装配 + 再导出
├── example/                          §44.2 "备忘（Notes）" 最小示例产品
├── test/                             §44.3 可单测基线（11 用例）
└── packages/
    ├── microflow_model  0.1.0   项目模型/契约/诊断注册表/i18n 目录/Token 集（§4-§11、§39、§41、§42）
    ├── microflow_runtime 0.1.0  统一资源注册/静态校验/解释运行时/错误边界/MFEmissionSink（§13.2、§23、§10、§18.1）
    ├── microflow_observability 0.1.0 遥测信封与有界队列/标准事件族/实验冻结/Debug 会话（§24、§29、§31）
    └── microflow_renderer_flutter 0.1.0 Tier A 页面渲染/解释器/MicroFlowApp（§12、§13.3 解释模式、§38）
```

依赖单向：`model ← runtime ← {observability, renderer}`；runtime 通过稳定
`MFEmissionSink` 接口向观测面发射拦截事件（§24.7），互不耦合。

### 2.2 已达成（如实按 §38.2 分级）

| 分级 | 状态 | 证据 |
|---|---|---|
| Level 0 模型与验证核心 | 已达到 | 5 类契约、静态校验器、诊断注册表 26 码、i18n 目录与回退、Token 解析 |
| Level 1 解释运行时 | 部分达到 | 页面实例/导航/状态层/绑定/并发策略/guard/unknown/错误边界；Tier A 渲染 |
| Level 2 完整契约 | 协议面部分实现 | 遥测信封校验与有界队列、标准事件族零埋点（`ops.page.viewed/left`、`ops.feature.used`）、实验冻结/停用、Debug 权限门 |

### 2.3 基线覆盖对照（§44.3，32 条；M2 后由 tool/baseline_coverage.dart 口径）

```text
已覆盖（测试通过）：1、2、3、4、5、7、8、11、12、13、14、15、17、18、19、20、
                  21、26、27、28、29
部分覆盖：         16、22（§36.4 token 规则侧；§36.5 动效面未实现）、30、31、32
未实现：          6、9、10、23、24、25
```

### 2.4 已识别债务

- D1：样式系统只有颜色 Token（§36.3-§36.6 主题/样式片/覆盖链未实现）——已随 M1 交付；
- D2：Tier B 六个元组件缺五个（Tabs/Drawer/Table/Split/Anchor）——M1 交付
  Tabs/Drawer/Table（另含 Grid），M2 收尾清零交付 Split/Anchor（§38.1 6/6）；
- D3：编译模式与产物清单、Source Map、路由注入（§13.3 编译侧、§33 构建部署）；
- D4：Recovery Contract Schema 已建，恢复/迁移执行器与迁移器登记未建
  （§16.1、§22.3）——已随 M2 交付；
- D5：Business Fact 提交确认/去重身份通道（§24.1 第 4 类、§30.1）——已随 M2 交付；
- D6：增量构建与性能预算度量（§22.2 必报七指标管线）;
- D7：受控交叉清单与三平面分离运行期判定（§2.9 静态面已建）。

## 3. 总体路线

按设计文档 §19/§34 六阶段框架，结现状改为五个里程碑。原则：

- **不重建稳定核心**：model/runtime 的公共 API 保持兼容，新增能力走版本递增；
- **每里程碑止于可用验收证据**（基线测试 + analyze 0 issues + 演练记录）；
- **帧级原则贯穿**：每条验收都以 §44.3 基线条目或 §38.2 分级条目为准，不引入设计外目标。

```text
M1 样式与布局完整化（Level 0→1 补全，D1/D2）
M2 观测与恢复闭环（Level 2：调试/回收/事实，D4/D5 部分）
M3 编译模式与发布门禁（§13.3 编译侧 + §16/§22 性能，D3/D6）
M4 三平面与受控交叉运行期化（§2.9 全量，D7）
M5 平台扩展与生态（Tier B 补齐 → ? 、Web 之外、Host 能力、AGENTS 接入面）
```

## 4. 里程碑与交付

### M1 样式与布局完整化（估计 2 周）✅ 完成 (2026-10-24，含证据链收尾提交)

目标：框架基线 §20 中“主题 Token、主题和基础样式片”达到可发布口径；Tier A 布局语义按 §7.3 形式固定并通过确定性基线（18-21）。

交付项：

1. 样式片（§36.4）：样式片资源 Schema、变体条件（state/platform/breakpoint）、承接链 `extends`、字面量禁令与豁免诊断；
2. 主题（§36.3）：`extends` 重定向、默认/可用主题集、解析完整性检查、实例冻结与切换只影响新建实例（基线 7）；
3. 覆盖链（§36.6）：`Token < 组件默认样式片 < 页面覆盖 < 产品主题`；
4. 布局求解 Dart 化（§7.3）：`solve(约束集, 内容度量, 可用空间) → 规范化矩形集`，与 Flutter 布局发动机对齐的 Stack/Grid/Overlay/Scroll 分配规则；冲突/循环/不可满足静态报错（基线 19）；条件布局默认方案必填（基线 20）；
5. Tier B 三个客户端核心：Tabs、Drawer、Table（§38.1 允许替换实现，注册契约不变）。

验收：基线 7、12、18、19、20、21 落入测试；`example` 展示双层主题切换。
证据：`test/baseline_m1_test.dart`（测试名「基线 N」标记符合覆盖工具约定），
`test/microflow4_flutter_test.dart`，`example/lib/main.dart`（theme-light/theme-dark
双层主题 + `style-title` 覆盖链示例）；基线 22 仅部分达成（§36.4 token 规则侧，
§36.5 动效面随 M5 登记后实施）。

风险：§7.3 求解语义与 Flutter BoxConstraints 映射有边界；需在基线测试固定合成元组件度量，避免平台度量噪声。

### M2 观测与恢复闭环（估计 2-3 周）✅ 完成 (2026-10-24)

目标：Level 2 的 Telemetry Ingest/Query、Recovery、Business Fact 与 Debug 达到测试可用。

交付项：

1. Recovery Contract 执行器（§16.1）：快照收集/重校验/过期/迁移；`unknown_side_effects.auto_retry=false` 强制（基线 27）；快照 schema 版本不匹配进错误边界；
2. Business Fact（§24.1 第 4 类、§30.1）：提交确认语义、去重身份（幂等键）、`unknown_result` 查询通道；提交入口是唯一显式例外（§24.7）；
3. Telemetry Ingest 参考实现（§30.1）：批量/压缩/退避/断网缓存落地为可注入 MFTelemetrySink 的默认实现；数据质量指标（丢失率、丢弃计数）暴露；
4. Query/Export 最小协议（§30.2）：`query_events / get_event_schema / get_trace / get_data_quality` 本地参考实现；导出游标与缺口区间声明；
5. Debug（§29）：本地/预览两级可用（上下文读取、状态订阅、首个检查点）；生产受控诊断仅协议。

验收：基线 4、5、8、11、17、27、28；丢失/回放数据的口径一致性在测试中固定。
证据：`test/baseline_m2_test.dart`（基线 5/8/11/17/27/28 + §29 控制面 +
§30 Ingest/Query 口径一致性）；Testable Ingest 参考实现与本地 Query/Export
见 `packages/microflow_observability`。
收尾清零（同日追加，CHANGELOG 0.6.0）：渲染合一（节点自约束/条件布局/
显式图层/插槽全部被渲染消费，基线 12/18-21 语义进渲染路径）、Tier B
Split/Anchor 补齐（6/6）、协议债清零（page.errorBoundary/product 作用域/
queue 排队/手工上报拦截/face-undeclared/Tier A 门禁/Renderer Contract
消费点/renderRevision/MFDiagSink/伪本地化）；测试 `test/closeout_test.dart`
（14 用例）。i18n 镜像已随伪本地化覆盖，翻译平台集成仍按 §20 留在框架外。

风险：恢复快照与实验冻结归属的组合（§24.5）——恢复继续使用原分配，本阶段以“显式声明允许重分浇”为唯一通道。

### M3 编译模式与发布门禁（估计 3 周）

目标：同一 IR 两条产出路径，发布快照可重复构建、可回滚；性能预算进入发布门禁。

交付项：

1. 规范化 IR 版本化落盘（§4.2/§16）：版本化修订面、资源摘要、资源保护清单；
2. Dart 编译目标（§13.3）：模型 → Dart 代码路由/静态子树/绑定表，行为一致性测试（基线 9）随 CI；
3. 发布快照构建器与验证器（§16）：产物清单、Renderer 契约摘要（§12.1）、性能预算、i18n 摘要、诊断规则版本（§16 发布清单全字段）；
4. 增量构建（§22.2）：对象 id + 内容摘要 + 反向索引（§4.3）构成缓存键；与全量产物一致性（基线 25）；
5. Performance Contract 执行（§22.2）：七项必报指标（冷启动/导航 P95/交互 P95/内存/产物体积/增量检查/构建）测量接入 + 门禁（基线 24）。

验收：基线 9、10、24、25；发布演练（回滚 + 重复构建）记录入库。

风险：编译模式容易与解释模式分叉；规则 = 两者共享同一解析器与规范化输出（§37.1），编译器把规范化输出转写为代码。

### M4 三平面与受控交叉运行期化（估计 1 周）

目标：§2.9 判定矩阵全量生效，实验/运营变体的越面改写运行期拒绝。

交付项：

1. 受控交叉清单资源 + 静态/运行双门禁（`mf.exp.variant-out-of-scope`，基线 32）；
2. 实验注记与 §30.2 投影的登记面闭环（§31.1 非实验运营变体清晰区分）；
3. 内容资产通道与 §42.7 双通道判定检查全量化（基线 30 收口）；
4. 实例数据回写项目模型的运行期硬拒绝（`mf.state.writeback-denied` 全阶段化）。

验收：基线 30、31、32；违例注入测试通过。

### M5 平台扩展与生态（估计 2 周起，永续）

目标：跨平台与上层接入面。

交付项：

1. Tier B 收尾：Split/Anchor + 降级诊断（§12.1 allowed_differences 全量登记）；
2. 由 `FlutterRenderer` 声明出完整 Renderer Contract（§12.1 Schema + §38.2 分级），在 `release/` 产物中随包交付；
3. MicroFlow Web/B(公共服务) 的相邻 Renderer 互通：以同一项目模型、同一基线互验（不做跨端像素一致承诺，§20）；
4. Vibe Coding 接入面加厚（§14）：`inspect_impact`、`validate_project`、影响分析查询、修改审计与回滚的最小 CLI（`microflow-ui check/inspect/impact/normalize`）随包发布。

## 5. 验收判定与分级维护

- 每里程碑合入前必须：`flutter analyze`（4 个 packages+ 总包+ example）0 issues、`flutter test` 全绿、新增基线条目标志性测试落库；
- §38.2 `README` 能力分级表同步更新；“分级声明歧义或夸大在验收中按失败处理”（§38.2）；
- §44.4：核心章节（设计文档）修订⇄基线测试同步；本包合入任何“引用基线”的声明都必须能指出对应测试文件与用例名。

## 6. 模块级路线（负责人按模块持续更新）

| 模块 | M1 | M2 | M3 | M4 | M5 |
|---|---|---|---|---|---|
| microflow_model | 样式/主题/覆盖链 Schema、布局约束模型、Tier B 契约 | i18n 镜像/伪本地化、findings 注记（§43.3） | IR 版本、发布清单字段 | 受控交叉清单资源 | — |
| microflow_runtime | 布局求解器、冲突检查 | Recovery 执行器、Business Fact 通道 | 行为一致性用例、增量校验面 | 三平面运行期判定（writeback） | Split/Anchor 求解 |
| microflow_observability | — | Ingest 参考实现、Query/Export、数据质量 | 性能样本采集 | 实验/运营变体双门禁 | 订阅协议实现（§43.2 可选） |
| microflow_renderer_flutter | 样式片/主题渲染、Tabs/Drawer/Table | 恢复 UI 态 | 编译目标产物（由编译器生成） | 内容位容器渲染 | 平台变体、桌面/移动差异面 |
| 总包/CLI | — | 集成测试 | `microflow-ui` 命令 | — | Agent/编辑器接入协议 |

## 7. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| 布局求解与 Flutter 布局机制不完全对齐 | 基线 18 不确定 | 合成元组件固定内容度量；求解输出矩形集逐像素断言 |
| 编译/解释分叉 | 基线 9 长期红 | 共享规范化输出；编译器只做转写 |
| 恢复 × 实验冻结 × 配置刷新组合矩阵爆炸 | 隐性回归 | 用表驱动用例生成（老版本×新配置×恢复场景）|
| 观测协议变化与既有事件数据兼容 | 查询口径断裂 | schema_version 与 identity_version 冻结纪律（§4.4、§24.2） |
| 设计文档继续演进 | 规划漂移 | 本规划 §8 修订规则绑定设计文档版本 |

## 8. 修订规则

- 本规划跟随设计文档大版本：设计文档升级基线（加章/基线条目）时，本规划的“现状盘点/里程碑”必须同步修订；
- 里程碑完成即在 §4 对应小节标注状态（`✅ 完成 (YYYY-MM-DD, commit)` / `部分` / `未开始`），并附验收证据链接（测试文件、演练记录）；
- 未在 §4 列出的新增工作按 M5“生态”口径补充登记后再实施。
