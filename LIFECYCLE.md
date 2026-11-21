# 产品开发全周期覆盖分析与新子项目设计

> 状态：**设计已全部落地（2026-11-21）。** 四个新子项目均已实现并有测试证据（各自 README/AGENTS.md 承载边界声明，根 README §六 已回填）；本文 §二矩阵保留设计时的分析基线，§四每节标注落地切片，§七纪律问题已修复。实现状态以各子项目 README 与根 README §5.4 为准。

## 一、分析基线

以一个宿主产品（如 OpcHub）的一生走全周期：**需求 → 设计 → 开发（前端+后端） → 验收 → 发布部署 → 运维 → 运营迭代**。

判定标准不是"有没有工具"，而是 MicroFlow 自己的原点命题：**每个阶段是否有结构化承载——版本化数据模型 + 机器可判定门禁 + 封闭命令面**。自由文本、人脑记忆、"应该可以了"在该框架里都不算承载。二义性压缩到算子契约与页面模型，但压缩之前（需求期）与验证之后（UI 证据、产物交付）是否同样走结构化轨道，决定了全周期是否真正闭合。

## 二、现有子项目覆盖矩阵

| 全周期阶段 | 承载 | 覆盖事实（证据） | 结论 |
|---|---|---|---|
| ① 需求与设计 | — | 根 README §二 把"目标定义、架构决策"划给人守，载体"需求描述、接口与边界设计"无任何工具化：无 schema、无校验、无追踪矩阵。验收先行的纪律（根 AGENTS.md 纪律 2）要求"动手前写下机器可判定的完成标准"，但没有存放这个标准的结构化位置 | ❌ 断链 |
| ② 后端开发 | MicroFlow4Python + 4MCP | CLI 12 命令实装（capabilities/check/run/scaffold/impact/context 等，`cli.py:367-420` 实证）；**`test`/`preview`/`diff`/`query` 设计在 17 命令集合内但未实装** | ✅（验收命令留缺口） |
| ② 前端开发 | 4Flutter + 4Web | 4Flutter authoring 命令面（create_page 等 7 命令，进程内）；4Web DOM 渲染器（新增，未入库）首次把 MFProject 模型 JSON 文件化（宿主经 `export_model.dart` 导出） | ✅（文件化 authoring 命令面未落地） |
| ② AI 工具接入 | MicroFlow4MCP | 后端 12 工具全量暴露；前端 authoring 明确未暴露（README 边界声明："需要先建立文件化项目模型格式"——该格式现已由 4Web 确立） | ⚠️ 单侧接入 |
| ③ 场景级验收 | 4Python run/check + Orchestration 控制面 | E2E 阶段门禁（dev→test→staging→online 不可跳过 + 上一环境须有 debug 上报 SUCCESS）是场景级；后端 `test` 命令未实装，"期望输出对照"目前只能 run --ephemeral 人工比对 | ⚠️ 最小闭环 |
| ③ UI 端到端验收 | — | 根 README §一.1.3 点名"对 GUI、异步、性能等难断言维度系统性回避验证"；4Web/4Flutter 的 validate_project 只是静态面，没有执行期 UI 证据链 | ❌ 断链 |
| ④ 构建与发布 | （T12 部分） | 后端 releases.publish 内容寻址已落地，跨机器物化未开始；4Flutter 发布快照构建器/性能门禁未实现（§5.4 如实声明）；**产品应用产物（前端 bundle、后端服务包、模型快照）的构建登记→仓库→部署无任何承载**——Orchestration 只管编排配置下发 | ❌ 断链 |
| ④ 部署与宿主 | — | HOST_CONTRACT.md 是文档（场景清单 + 权限点目录），无参考实现、无脚手架；宿主要从零自写 dispatch 网关 + RBAC + 遥测接收端口 | ❌ 断链（本仓库用户已自建宿主 OpcHub，不阻塞自身；阻塞生态复用） |
| ⑤ 运维 | MicroFlow4Ops | 运行瀑布/指标看板（读时聚合真实分位）/审计检索/调试工作台/告警中心（控制面最小闭环） | ✅ |
| ⑥ 运营迭代 | 4Bizops + 实验域 | KPI/趋势/漏斗/留存/实验读出，口径诚实披露，零埋点依赖 | ✅ |
| 贯穿：审计与回滚 | Orchestration env_current + authoring 修订 | 配置面闭合（追加保留审计、LIFO 回滚、指针表）；应用产物面缺（与 ④ 同源） | ⚠️ |

## 三、结论

**闭合的**：开发期（两端框架 + AI 接入）、运维期、运营期、配置面发布治理。

**断链的（三个，都发生在阶段的"上游入口/下游出口"）**：

1. **需求 → 验收基线无结构化**——VibeCoding 三类失效的源头（二义性脑补）恰恰发生在没有结构化轨道的阶段；"验收先行"纪律无载体。
2. **UI 端到端验收无执行器**——难断言维度（GUI/异步）没有证据链，"假完成"在 UI 层仍有解释空间；现有 E2E 门禁只看场景级 debug 上报。
3. **应用产物构建 → 发布 → 部署无承载**——环境治理（审批/回滚/指针）只覆盖编排配置；产品本身怎么从源码变成某环境上运行的产物，全周期表上是空白。

**另有一条生态断链**：宿主契约无参考实现——不是本仓库用户的阻塞项（宿主已存在），但是框架"可复用"声明与现实的差距。

## 四、新子项目设计（四个，各自独立设计轮次）

### 4.1 MicroFlow4Spec —— 需求与验收基线（P0）—— **已落地（2026-11-21）**：纯 TS 库 + CLI 四命令（check/coverage/verify/diff），29 项测试；backend_run/orch_scenario 证据执行器对接属后续切片

- **定位**：把需求描述与验收基线结构化为版本化数据，使"验收先行"有载体；需求 ↔ 证据 ↔ 实现载体的追踪矩阵机器可判定。这是 README §一.1.2"业务语义散落"问题在需求期的收口。
- **形态**：纯 TypeScript 包（零运行时依赖，对齐 4Web 先例）+ 文件化基线 `spec.model.json` + CLI（node 直跑）。SPA 面不做（起步阶段）。
- **对象模型（v1）**：
  - `requirements[]`：id / title / statement / priority / status（open|accepted|delivered）
  - `scenarios[]`：id / requirement_refs[] / kind（`backend_run` | `orch_scenario` | `ui_script` | `manual`）/ expectation（结构化期望：flow+输入→期望输出 | 场景 id+期望终态 | 脚本 id | 人审说明）
  - `trace[]`：需求 ↔ 证据（scenario id）↔ 实现载体（算子/flow/页面/组件 id）
- **命令面**（对齐八条兼容契约）：`spec check`（0 诊断才继续）/ `spec coverage`（矩阵 + 缺失报告：每条需求有无证据、每个证据是否仍指向存在的载体）/ `spec verify`（调 Verify 合并证据）/ `spec diff`。
- **门禁**：未知字段拒绝；悬空引用静态错误；环状 requirement 引用静态错误。
- **先例对齐**：MicroFlow4Flutter `baselines.json`（32 条机器可读基线）——Spec 是它的产品级同类物。
- **第一个可收口切片**：schema + loader + check（0 诊断）+ coverage 报告，负例测试覆盖未知字段/悬空引用/环引用。
- **不做什么**：不做需求撰写 AI、不做文档渲染、不存储运行证据（证据由各执行器产生，Spec 只登记引用与摘要）。

### 4.2 MicroFlow4Verify —— 端到端验收运行器（P1）—— **已落地（2026-11-21）**：面中性 runner + web 面（4Web MFRuntime 适配）+ `microflow-verify-v1` 信封，23 项测试；DOM 渲染断言/截图与 flutter 面属后续切片

- **定位**：GUI 验收的执行器。声明式脚本在两个真实渲染面（4Web DOM / 4Flutter）执行，产出统一信封证据——直接打 §一.1.3"GUI 难断言维度系统性回避验证"的痛点，让 UI 层"假完成"没有解释空间。
- **形态**：TS 库 + CLI；web 面先 jsdom 语义级（事件分发 + DOM 断言），后 Playwright 截图级；flutter 面薄适配（integration_test driver）。
- **对象模型**：`verify.script.json`：meta（project 引用 + 模型 digest）/ steps[]（open | tap | fill | expect_binding | expect_event | expect_route | screenshot）。**断言一律引用 MFProject 已注册锚点**——复用"未注册引用是静态错误"纪律。
- **信封**：`microflow-verify-v1`：逐断言 verdict + 证据引用（截图/事件流）+ 耗时；确定性输出纪律（同输入字节一致，时间戳进 meta 分离）。
- **表达力刻意做小**：脚本不得内嵌任意 JS 逻辑；表达不了的交互答案是"新增元组件/事件锚点"，与编排"新增算子"同构。
- **接口**：输入 = MFProject JSON + 脚本；输出 = 供 Spec `spec verify` 合并、未来供 Orchestration 阶段门禁消费（本期只产出信封，不动控制面）。
- **第一个可收口切片**：4Web（jsdom）执行 8 步以内的导航/绑定/事件断言脚本 + 信封 + 确定性输出测试。
- **不做什么**：不做性能压测（归框架路线 SCALABILITY.md / T15）、不做视觉 AI 判断（截图证据人审；像素基线对比属后续切片）、不做移动端真机（4Flutter integration 属后续切片）。

### 4.3 MicroFlow4Delivery —— 交付流水线（P1）—— **已落地（2026-11-21）**：内容寻址仓库 + promotions 历史 + 环境链守卫 + 三证据门禁 + 第二人审批 + CLI/REST，17 项测试；blob 上传 REST 与部署执行钩子属后续切片

- **定位**：应用产物（前端 bundle / 后端服务包 / 模型快照）的构建登记 → 内容寻址仓库 → 环境部署 → 回滚。补全周期表 ④ 的空白。
- **形态**：CLI + 仓库服务（FastAPI + SQLite 单机起步；提供者经契约测试套件，对齐 4Python 持久化提供者先例）。SPA 面为后续切片。
- **对象模型**：
  - `artifact`：kind（web_bundle | backend_service | model_snapshot）/ digest（SHA-256 内容寻址，对齐 T12 语义）/ build_inputs_digest / baseline_digest（Spec 基线）/ verify_report_digest
  - `env_pointer`：dev/test/staging/online 同键（与 Orchestration 环境键对齐），语义同构 env_current
- **门禁**：发布要求 spec coverage 全绿 + 对应 verify 信封 + 编排 check 0 诊断；staging/online 强制第二人审批（同人禁审服务端硬校验，复用 Orchestration 审批纪律）；dev→test→staging→online 不可跳过。
- **分工边界**：编排配置下发留 Orchestration，本平台只管应用产物；release_id 固定全部版本、回退只影响新实例的语义按产物类型映射（web bundle = 指针切换；后端服务包 = 部署清单）。
- **第一个可收口切片**：内容寻址落库 + 登记 CLI + 指针查询（单机 SQLite），负例：同摘要异内容冲突拒绝、基线缺失拒绝。
- **不做什么**：不做容器编排/K8s（部署执行先走部署清单 + 脚本钩子，留宿主扩展点）；不做编排配置管理（归 Orchestration）；不做跨机器物化（归 4Python T12 演进）。

### 4.4 MicroFlow4Host —— 宿主参考实现与脚手架（P2）—— **已落地（2026-11-21）**：dispatch 网关 + 17 权限点目录 + 治理/遥测/聚合/托管 + bootstrap/scaffold，20 项契约测试；委托接线与生产介质归宿主扩展

- **定位**：把 HOST_CONTRACT.md 从文档变成可运行起点：dispatch 网关参考实现 + `host scaffold` 生成器。消除"宿主契约人人从零自写"的生态断链。
- **内容**：FastAPI dispatch 单端点（场景清单最小实现 + 权限点目录 + `{code,data,message,trace_id}` 信封）+ 遥测接收端口（接 4Flutter/4Web EmissionSink 的 HTTP sink，有界队列、过载显式拒绝）+ 持久化提供者接线（SQLite 起步）+ 三平台 SPA 静态托管 + `ops.runs.*`/`bizops.*` 聚合最小实现。
- **scaffold 纪律**：`host scaffold --into <dir>`——只写显式目录、永不覆盖，对齐 4MCP scaffold。
- **诚实边界**：参考实现验证协议正确性，不冒充生产部署证据（替身不算生产证据；生产验证归宿主部署方）。
- **第一个可收口切片**：dispatch 网关 + `auth.login`/`auth.session`/`platform.scope.my` 三场景，由契约测试套件驱动（对齐 4Python 提供者契约测试先例）。
- **不做什么**：不做完整身份体系（最小账号起步，宿主关切归部署方扩展）；不实现具体业务场景（业务归算子）。

## 五、明确不设新子项目的判断

| 候选 | 判决 | 理由 |
|---|---|---|
| 性能/负载验证平台 | 不设 | SCALABILITY.md 已是路线文档，承载归框架 T15/T16 与 benchmarks；另立门户会与框架验收路线重复 |
| 身份/账号服务 | 不设 | HOST_CONTRACT 已定界：auth.* 是宿主关切；Kit admin 已有管理页。做进框架违背"支撑平台业务无关" |
| 遥测存储/汇聚服务 | 不设 | 遥测接收端口由宿主注入，Ops 读时聚合已承载查询面；4Flutter MFLocalQueryEngine 已有 §30.2 五协议参考实现 |
| 前端 authoring 的 MCP 暴露 | 不设（扩展项） | 归 MicroFlow4MCP 扩展。模型 JSON 文件化形态已由 4Web 确立，MCP README 预告的"独立设计轮次"条件已成熟 |
| 4Flutter 发布快照构建器/性能门禁 | 不设（扩展项） | 原规划未实现项（§5.4），归 4Flutter |
| 数据介质迁移 | 不设（扩展项） | 归 4Python T12（跨机器物化与介质迁移） |

## 六、优先级与依赖

```
P0  MicroFlow4Spec     ──场景脚本──▶  P1  MicroFlow4Verify ──报告──┐
P1  MicroFlow4Delivery ◀──门禁消费(coverage + verify 信封)──────────┘
P2  MicroFlow4Host（独立，无前置）
```

- Spec 最轻、先例最硬（baselines.json 同构）、且是其余门禁的基线来源，先行。
- Verify 依赖 4Web 模型格式（已存在），可与 Spec 并行设计、串行落地。
- Delivery 的门禁消费 Spec/Verify 产出，落地排后；其 CLI/仓库主体不依赖前两者，可先行打桩。
- 每轮落地后回填根 README §六 表与本文件矩阵，未验收能力不写入。

## 七、顺带发现的纪律问题（本次分析实测）

1. **4Web 外部路径测试**：~~硬编码仓库外路径~~ **已修复（2026-11-21）**：`OPCHUB_MODEL` 环境变量显式锚定 + 缺失显式 skip + 惰性读取；顺带 4Web 整体入库并完成 node 直跑规范化（导入说明符 .ts + allowImportingTsExtensions）。
2. **后端 `test` 命令未实装**：~~设计 17 命令集合中的验收命令未实装~~ **已实装（2026-11-21，CLI 13/17）**：项目配置声明 tests（flow 回归输入输出对 + 算子契约用例，每条预期强制 `source` 来源声明），MCP 同步暴露 `microflow_test`（13 工具）；preview/diff/query 仍未实装。
