# MicroFlow

MicroFlow 是面向 VibeCoding 开发方式（AI 结对编程）的业务框架体系：**后端 = 业务无关算子 + 结构化编排配置；前端 = 声明式项目模型 + 带门禁的命令面**。它把业务语义从散落的代码里压缩到少数设计决策处，让 AI 工具的全部工作落在"可校验、可验证、可审计"的结构化轨道上。

本仓库包含两套语言实现与一份本 README——**README 是唯一权威入口**，承载设计愿景、要解决的问题与实现的设计；原 `docs/` 设计文档已归档于 git 历史（文末附录列明对应提交）。

## 一、要解决的问题

### 1.1 VibeCoding 工具的三类失效

认真使用 AI 结对编程的人都会遇到：

1. **假完成**：让 AI"接上真实数据"，它交付 Mock 数据并报告"已完成 ✅"；测试断言被悄悄改成迁就错误实现；异常被静默吞掉。AI 的汇报语气永远自信，而"看起来完成"与"完成"之间的鸿沟正是最大风险区。
2. **二义性脑补**：需求有歧义时，AI 不追问，而是自行脑补一条最短路径的解释直接实现。传统开发中业务语义散落在代码每一行里——每一行都是一次潜在的二义性。
3. **验证自证与注意力衰减**：测试迁就实现而非检验设计；长会话遗忘早期约束、改 A 坏 B；对 GUI、异步、性能等难断言维度系统性回避验证。

### 1.2 传统开发的结构性痛点

- **影响分析靠经验**：改一个函数影响哪些业务？答案在开发者脑子里，不在系统里。
- **采集是成本**：埋点散落且风格不一，AI 生成的代码日志尤其不一致。
- **依赖地狱**：底层框架引入的每个三方依赖都向全部下游传导版本约束。
- **文档-实现漂移**：设计与实现两套真相，漂移无人察觉。

### 1.3 原点命题

**二义性无法消除，只能转移和压缩。** MicroFlow 的解法不是更强的模型，而是更硬的接口：把业务语义压缩进少数设计决策（人守），其余全部工作转化为结构化数据与机器可判定的校验（AI 走轨道）。

## 二、设计愿景：职责重分

| 职责 | 归属 | 载体 |
|---|---|---|
| 目标定义、架构决策、算子粒度 | 人 | 需求描述、接口与边界设计 |
| 长期记忆 | 文档 | 本 README、子项目手册、git 历史 |
| 通过性验证 | 机器门禁 | 静态校验、CLI 检查、一致性基线、守卫测试 |
| 真实环境最终验收 | 人的业务判断 | 运行证据 + 监控运营数据 |
| 算子实现、配置生成、模型修改 | AI 工具 | 契约内填空 + 结构化命令面 |

两端的闭环：**后端**——算子+配置锁定业务边界（无二义性输入）；**前端**——模型+命令面锁定页面边界；**观测**——Fact+Query 提供证据链（无二义性证据）。VibeCoding 的每一次交付都有机器可判定的证据，"假完成"没有解释空间。

## 三、核心设计思想

1. **算子与编排分离**。业务步骤实现为契约明确、副作用如实声明、边界固定的算子；业务功能由编排配置组织算子而成。
2. **编排配置即数据，表达力刻意做小**。Python 后端支持声明式 DSL 和兼容的 JSON，均编译为相同流程模型并使用版本化 Schema；发布前静态检查（环/引用/路径/类型/策略组合），未知规则一律拒绝；表达式为受限白名单，禁止 eval——配置永远不朝图灵完备漂移，表达不了的逻辑答案是"新增算子"。
3. **层次分解**。子图与算子遵守同一契约纪律（端口、错误语义、版本、独立测试），以复合算子身份参与编排；接口预算（建议 ≤8 端口）、目录可读性、引用而非复制。
4. **观测分层**。框架在运行时拦截边界零埋点产生结构化事实/指标/日志；汇聚、查询、看板、告警由上层承载。事件 Schema 与算子契约同为版本化契约；关键业务事件走独立可靠协议。
5. **零依赖内核与端口注入**。框架核心只依赖语言标准库（Python 侧经独立安装验证）；持久化、遥测接收、授权、事件投递以端口接口由宿主注入，能力不足时显式拒绝而非静默降级。零依赖 = AI 面对封闭可读的 API 面，直击幻觉最严重的区域。
6. **面向 VibeCoding 的适配**。局部上下文、影响分析（静态反向索引）、结构化命令面、机器可读验收基线——工具不读全项目也能准确理解边界。
7. **诚实边界**。设计基线、实现状态、验收证据分别管理；内存替身不冒充耐久证据；未知结果进入可判定状态；未验收能力显式拒绝。

## 四、架构总览

```text
算子实现（六参数契约、副作用声明） ─┐
编排配置（DSL 或 JSON / 版本化 Schema）  ─┤
                                 ▼
        编译与静态检查（环/引用/路径/类型/策略组合）  ←─ 变更影响 = 静态反向索引
                                 ▼
                  不可变发布快照（release_id 固定全部版本；T12 切片：内容寻址落库/装载）
                                 ▼
 执行层（调度/执行/熔断/恢复） ⇄ 状态协调（原子 StateBatch） ──▶ [端口] 持久化提供者（宿主注入）
                                 │
          观测采集内核（运行时唯一发射点：零埋点事实/指标/日志）
                                 ▼
        [端口] 遥测接收（业务层承载） ──▶ 上层：汇聚/查询/看板/告警/实验

前端：项目模型（页面/绑定/样式/导航，纯配置） ──▶ 解释运行时 + Tier A/B 元组件
        ▲ 结构化命令面（create_page/…，逐命令过门禁、留审计）      │
        └── 上层工具/AI ＜──── 零埋点运营事件 ──── 遥测接收（业务层承载）

VibeCoding 工具接入：[MCP 桥] CLI 12 命令 → MCP 工具（框架外适配层，零依赖 stdio）
注册面：[Registry 投影] CLI 只读面 → microflow-registry-v1 报告 → 宿主 dispatch（按 contentDigest 幂等）
支撑平台：编排管理（控制面承载）· 运维（含告警中心）· 运营 ── MicroFlow4Kit 共享底座
```

## 五、实现的设计（设计基线摘要）

> 本节是原设计文档体系的浓缩。**完整原文已归档于 git 历史**（见文末附录），语义冲突时以归档原文与代码测试为准。

### 5.1 后端执行框架（MicroFlow4Python 承载）

**算子协议**：六参数签名 `(input, output, context, metrix, debug, log) -> bool`；`True`=成功、`False`=业务否定（OPERATOR_REJECTED）、异常自动进 fallback（须显式声明能力），无 fallback 异常立即熔断根流程（CIRCUIT_BROKEN 闩锁）。Output 标准信封：业务只写 `data`，`meta`/`error` 是框架保留命名空间，输出违反契约即 OUTPUT_CONTRACT_VIOLATION，不发布半成品。副作用三值声明 `pure/read/write`——写入型在未具备确认能力前被拒绝接入。

**数据与契约**：内置 MicroFlow Schema v1（类型/必填/枚举/区间，未知关键字拒绝）；路径 AST（`a.b`、`items[0]`、`["a.b"]`），区分缺失与 null；映射冲突预检（MAPPING_CONFLICT）；表达式为受限白名单 AST（eq/and/or/in…，禁 eval）。金额整数分、时间带时区、禁 pickle 与任意对象。

**编排**：节点类型 operator/subflow/route/join/map/loop/wait；控制依赖与数据依赖联合判环（Kahn + 非递归三色 DFS，确定性最小堆排序）；数据寻址仅在当前图内（不跨层）；数组禁止稀疏写入（SPARSE_ARRAY）。**子图治理**：引用而非复制、接口预算 ≤8 端口、目录可读性（嵌套 ≤3~4 层）、封装（不跨层取数）、引用进入影响索引。

**策略与执行**：执行属性（同步/异步、缓存、幂等、恢复、超时、重试）全部配置化，四层合并（框架默认→算子默认→节点→白名单覆盖）后冻结为 EffectiveOperatorPolicy 并计算摘要；调用成功 ≠ 业务成功；等待超时不取消已接纳业务；根预算、队列/尝试预算原子记录，迟到成功不推进后继。

**状态与恢复**：所有权威变化经 StateStore 以 StateBatch 原子提交（结果、后继就绪、闩锁、幂等记录、事件意图同批）；revision/epoch/owner 校验，提交未知按原 request_id 查询；恢复保留业务身份，旧拥有者被隔离（IN_DOUBT），未知副作用需宿主授权+证据确认，纯/读尝试由接管者经 `recover` 自动重派（幂等身份废弃重建，迟到提交被 fencing 拒绝）；资源租约带世代 fencing。不承诺全局恰好一次——框架不把状态介质与任意外部资源伪装成天然原子。

**幂等与缓存**：业务幂等键 = 租户+域+操作+稳定业务键（独立于缓存，禁止 LRU 淘汰业务身份）；同键异摘要冲突，同键复用已确认结果；缓存默认关闭、仅纯计算、键含全量隔离维度、single-flight 协调。

**发布**：完整快照（源码字节+契约+配置+编译计划，内容寻址摘要）；执行按 release_id 装载，在途实例固定原版本与介质绑定；回退只影响新实例。

**观测**：三类数据分列——运行测量、诊断日志、业务事件（稳定 event_id、聚合序号、原子提交意图）；默认采集由框架产生且基础记录不可覆盖，metrix/log 代理只读补充；失联结束时间保留 null，禁止伪造。

**VibeCoding 适配**：局部上下文（目标实现+schema+直接上下游+测试+边界声明）、影响预览、结构化诊断（码+定位+修复提示）、模板生成、隔离重现；验收场景 A01～A35 逐项挂账。

**关键算法**：Kahn 最小堆判环 O(E+V·logV)、三色 DFS 环定位、类型标记规范树 + SHA-256 规范摘要（bool/int、缺失/null 严格区分）、LRU+TTL+single-flight、full jitter 退避、单调+墙钟混合预算时钟（防进程内回拨）。

### 5.2 前端框架（MicroFlow4Flutter 承载）

**三平面分离**：配置平面（页面/交互/样式/i18n 全声明式，不携带可执行逻辑）、代码平面（宿主注册的真实实现）、数据平面（运行观测，不回写模型）；每项资源恰好归属一个平面，平面间只走声明通道。

**项目模型**：manifest（类型方言版本）→ 页面（节点树、状态成员、图层）→ 绑定图（事件锚点、四类动作 state/adapter/function/navigation、并发策略）→ i18n 目录（回退链）→ Token/主题（extends 重定向）→ 样式片（值只允许 token 引用，字面量静态错误）→ 导航图（可达性检查）。

**元组件与注册**：Tier A 12 个基础组件 + Tier B 6 个复杂组件，渲染由解释器组件表承载；统一资源注册协议（id+version+compatibility，公共字段+类别差异面），未注册引用是静态错误；实现与契约不符是运行错误并进入错误边界。

**解释运行时**：页面实例/导航/三层状态（page/session/product）/绑定映射/并发策略/guard/超时进入 unknown 台账/错误边界（绑定级+页面级）；声明式布局被渲染消费（自约束 fill/fixed、条件布局方案、形式化求解与渲染同语义）；布局不可满足 → mf.layout.unsatisfiable。

**观测与实验**：标准运营事件族由运行时拦截边界零埋点产生（业务手工上报是静态错误）；采集注记（声明键进入事件 payload）走完整校验管道；信封 Schema + 有界队列；实验/运营变体经 Provider 接入，停用只停新曝光、历史冻结；Debug 三级（本地/预览/生产受控）会话授权+快照屏蔽；恢复协议——未知结果只进 unknown 台账，不自动重试；跨栈追踪传播注入。

**authoring 命令面**：create_page / create_page_from_template / connect_navigation / register_finding / validate_project / inspect_impact / undo——每条命令过与发布相同的静态门禁，产生前后摘要、影响对象与可回滚修订（LIFO 回滚，审计追加保留）；findings 结构化回流（自由文本替代是静态错误）；门禁禁止前向引用（绑定与页面同批、目标先存在）。

**一致性基线**：32 条机器可读基线（`MicroFlow4Flutter/baselines.json`），测试以「基线 N」标记覆盖，覆盖表由工具生成；诊断码单一来源注册表，未登记码即实现缺陷（守卫测试强制）。

### 5.3 CLI 命令体系（两端共用纪律）

八条兼容契约：统一信封（`microflow-cli-v1` + 命令专属键）、统一退出码（0 肯定/1 对象否定/2 请求失败）、共享诊断码跨实现一致、`--ephemeral` 显式边界（触发编译/执行必带，纯静态命令禁带）、能力探测替代硬编码（`capabilities`）、只暴露已实现命令、确定性输出（同输入字节一致）、容量预算超限报错。命令封闭集合 17 个：capabilities / diagnostics / describe / operators / schema / context / policy-schema（7 发现读取）＋ scaffold operator|flow（2 构造）＋ check / policy-check / test（3 校验）＋ run / impact / preview / diff（4 演练影响）＋ query（1 观察）。

### 5.4 实现状态（如实声明）

- **MicroFlow4Python**（299 项测试）：T01 包入口 / T02 契约 SDK / T05 本地同步执行 / T03·T04 编译与策略主体——完成；T06 本地闭环；T07 原子状态、T08 调度执行——协议切片通过，并已接入项目内持久化子模块（默认 memory，内置 SQLite 单机耐久提供者，经同一提供者契约测试套件与跨进程 fencing/重启恢复验证）与**失联自动重派**（`recover`：被 fence 旧 owner 的纯/读 CLAIMED 节点由泵循环自动重派，写入型保留手动确认）；T09 幂等确认、T10 事件意图——协议切片通过（内存替身）；本地运行时另已实现 **operator 节点条件执行**与**受控 write 算子**；**T12 切片已落地**：`releases.publish`/`load_release` 内容寻址发布落库与按 release_id 装载（跨机器物化与介质迁移未开始）；**VibeCoding 接入切片已落地**：`context`（算子局部上下文）与 `scaffold`（算子/流程候选骨架生成）CLI 命令 + `platform_graph`（编排平台画布图 → flow 骨架转换，显式限制与诊断）；熔断语义分离：节点级 `UNHANDLED_OPERATOR_EXCEPTION`、运行级闩锁 `CIRCUIT_BROKEN`（已入诊断码目录）；**T11～T13、T14～T16（动态节点执行、缓存接入、运维控制、运行利用分析、最终验收）未开始**。CLI 13/17 已实现（test 命令 2026-11-21 落地：项目声明回归输入输出对与算子契约用例，预期强制来源声明）。
- **MicroFlow4Flutter**（总包 64 项 + 各包测试）：Level 0（模型/契约/校验/i18n/Token/主题/布局静态面）与 Level 1（解释运行时/Tier A+B 渲染/覆盖链）**已实现**；Level 2 协议面部分实现（遥测/实验/Debug/Fact/Recovery/Ingest/Query 参考实现）；阶段六最小命令闭环已实现；基线覆盖 23/32（另 4 条部分）；**未实现**：编译模式产物、发布快照构建器与性能门禁、增量构建、运行期注入通道。
- **支撑平台**（Orchestration/Ops/Bizops + Kit，2026-11 收口）：编排管理平台迁移到**自有控制面**（FastAPI `:8200` + PostgreSQL，独立账号/锁/E2E 阶段门禁/第二人审批/回滚指针 env_current）——实验域、配置中心（灰度）、告警最小闭环（规则求值挂接 debug I/O 上报与场景执行）由控制面承载；运维平台新增告警中心页；`config_hash` 为 SHA-256 内容寻址。哈希/审批/回滚语义见 `MicroFlow4Kit/HOST_CONTRACT.md`。集成测试需 PostgreSQL（缺失时显式跳过）。**字段级契约 v1 已立**（`MicroFlow4Kit/host-contract.fields.json`，`microflow-host-fields-v1`）：参考宿主 26 场景 payload/data 字段单一来源，宿主形状测试精确断言 + Kit 调用场景守卫四分类（contract/delegated/external 登记缺口/**unknown 即红灯**）；Ops 运行页字段对齐契约并新增事件瀑布（`ops.events.list`，按聚合键分组）；Bizops 总览/趋势聚合接入 registry 事件与快照计数。
- **VibeCoding 工具接入**（`MicroFlow4MCP`）：CLI 全部 13 命令经零依赖 stdio MCP 服务器暴露为工具（capabilities/check/run/test/context/scaffold 等），协议适配在框架外，内核不感知 MCP。
- **注册面**（`MicroFlow4Registry`，2026-11-23）：零依赖投影包，两个方向两种信封——**快照**（`export`/`push`，`microflow-registry-v1`，按 `contentDigest` 幂等）与**事件流**（`stream`，`microflow-registry-stream-v1`，逐帧内容派生 `eventId`，outbox 先落盘后发送、at-least-once、`--replay` 按序补发）；库侧 `RecordStream` 适配 `record_sink`（同步回调内零 IO、队列满计数丢弃、后台线程冲刷）；
`accept_intent` 承接框架 `EventIntent`（`microflow-event-v1`）——**身份原样保留**（eventId 不重算、
sequence 不重派、epoch 秒转 ISO），宿主侧信任 event_intent 身份。只读调用 CLI（`check` 门禁 →
`operators`/`policy-schema` 投影），产出确定性报告。借鉴 Spring Boot 外部化配置/条件装配/失败隔离与 Nacos 三元寻址/元数据附着/客户端快照降级；**不做心跳与服务发现**，也**不引入 MQ**（传输留作 provider，等第二个物理消费者出现再换）。如实边界：生效策略暂不可上报（CLI 未暴露，不重算）；`release_id` 含绝对源码路径（跨机器变），可移植键用 `contentDigest`；`registry.publish`/`registry.stream` **服务端已由 MicroFlow4Host 兑现**（快照幂等、事件去重、宿主重算摘要、`ops.events.list` 读面，真实 HTTP 端到端联测通过）。47 项测试全绿。
- **全周期补全**（`MicroFlow4Spec` / `MicroFlow4Verify` / `MicroFlow4Delivery` / `MicroFlow4Host`，2026-11 落地，分析基线见根目录 [LIFECYCLE.md](LIFECYCLE.md)）：需求→验收基线结构化（spec.model.json + 追踪矩阵门禁）；UI 端到端验收执行器（声明式脚本在 4Web 真实运行时执行，`microflow-verify-v1` 信封；flutter 面与 DOM 截图断言属后续切片）；应用产物交付流水线（SHA-256 内容寻址仓库 + 环境链守卫 + 三证据门禁 + 第二人审批）；宿主参考实现（HOST_CONTRACT 的可运行起点：dispatch 网关、18 权限点 RBAC、遥测接收过载显式拒绝、ops/bizops 读时聚合、SPA 托管、scaffold，**+ registry.publish/registry.stream 服务端兑现**（快照按 `contentDigest` 幂等、事件按 `event_id` 去重、宿主侧重算摘要、`ops.events.list` 读面，与 4Registry 真实 HTTP 端到端联测通过）——编排/实验/配置中心场景由编排控制面承载，未接线时诚实 501；32 项契约测试）。
- 两侧共同边界：写入型算子与真实介质验证未开放；内存替身只验证协议。

## 六、语言实现与手册

| 子项目 | 定位 | 手册 |
|---|---|---|
| [MicroFlow4Python](MicroFlow4Python/README.md) | 后端执行框架：契约算子、静态编译、状态协调协议；零三方依赖 | [开发手册](MicroFlow4Python/DEVELOPER_GUIDE.md) |
| [MicroFlow4Flutter](MicroFlow4Flutter/README.md) | 前端框架：统一资源注册、解释运行时、Tier A/B 渲染、命令面 | [开发手册](MicroFlow4Flutter/DEVELOPER_GUIDE.md) |
| [MicroFlow4MCP](MicroFlow4MCP/README.md) | **VibeCoding 工具接入桥**：CLI 12 命令 → MCP 工具（零依赖 stdio，框架外适配层） | README（接入配置） |
| [MicroFlow4Registry](MicroFlow4Registry/README.md) | **注册面**：发布快照 + 事件流元数据 → 平台（快照按内容摘要幂等；事件批 at-least-once + outbox 重放） | README + AGENTS.md |
| [MicroFlow4Orchestration](MicroFlow4Orchestration/README.md) | 编排管理平台：三层资产目录全生命周期 + 自有控制面（审批/回滚/实验/配置中心/告警求值） | AGENTS.md（架构事实） |
| [MicroFlow4Ops](MicroFlow4Ops/README.md) | 运维平台：运行瀑布/指标看板/审计/调试工作台/**告警中心** | AGENTS.md |
| [MicroFlow4Bizops](MicroFlow4Bizops/README.md) | 运营平台：KPI/趋势/漏斗/留存/实验读出（口径诚实披露） | AGENTS.md |
| [MicroFlow4Kit](MicroFlow4Kit/README.md) | 支撑平台共享底座（ui/api/admin 三包）；[宿主契约](MicroFlow4Kit/HOST_CONTRACT.md) | AGENTS.md |
| [MicroFlow4Spec](MicroFlow4Spec/README.md) | 需求与验收基线：需求 → 验收场景 → 追踪矩阵（spec check/coverage/verify/diff） | AGENTS.md |
| [MicroFlow4Verify](MicroFlow4Verify/README.md) | 端到端验收运行器：声明式脚本 × 真实渲染面 → `microflow-verify-v1` 证据信封 | AGENTS.md |
| [MicroFlow4Delivery](MicroFlow4Delivery/README.md) | 交付流水线：应用产物内容寻址仓库 + 环境指针 + 三证据门禁 + 第二人审批 | AGENTS.md |
| [MicroFlow4Host](MicroFlow4Host/README.md) | 宿主参考实现：dispatch 网关 + RBAC 目录 + 遥测接收 + 聚合 + SPA 托管 + scaffold | AGENTS.md |

各子项目根目录均有 `AGENTS.md`（VibeCoding 工具纪律速查）；仓库根 [AGENTS.md](AGENTS.md) 是工具开发的统一入口（纪律 + 读序 + 开发回路 + MCP 用法）。

系列分享文章：[articles/](articles/README.md)（① 愿景与设计思想 ② Python 使用 ③ Flutter 使用）。

## 七、开发纪律速览（写给 VibeCoding 工具与开发者）

1. **小步**：一个会话一个任务，做完即收口；大任务拆到"可单步验证"的粒度。
2. **验收先行**：动手前写下机器可判定的完成标准（check 0 诊断 + run 期望输出 + 测试）。
3. **证据**：每步附真实运行输出；"应该可以了"= 未完成；调用成功 ≠ 业务成功。
4. **负面清单**：禁止 Mock/TODO 代替真实实现；禁止改测试断言迁就实现；禁止把写入声明成 `pure`；先 `capabilities` 探测再使用命令。
5. **不猜，查**：契约看 `schema`，影响看 `impact`，能力看 `capabilities`，诊断看 `diagnostics`——API 面封闭且全部可读，猜测是幻觉的来源。
6. **诚实**：替身不算生产证据；未验收能力不使用；边界声明随交付更新。

## 附录：文档归档索引

原 `docs/` 设计文档体系已删除，完整内容可从 git 历史恢复：

| 原文档 | 版本 | 主要承载提交 |
|---|---|---|
| 平台标准设计（后端需求与行为基线） | v1.4 | `2cc8ebb` 及其前序 |
| 框架内部功能技术选型（22 项算法决策） | v1.3 | 同上 |
| 算法与一致性设计（含 §22 静态影响索引） | v1.10 | 同上 |
| 前端框架完整设计方案 | v1.12 | `b8f5f1b` 及其前序 |
| 外部功能接入规范 | v1.0 | 同上 |
| CLI 命令体系设计（八条兼容契约 + 17 命令） | v1.0 | `2cc8ebb` |
| 实施任务规划 T01～T16 与全部验证记录（§1～§21） | — | `5a769a7`、`0fb8c11` 等 |
| 一致性基线投影 baselines.json | v1.0 | **迁至 `MicroFlow4Flutter/baselines.json`**（工具与守卫测试的数据源，随实现维护） |
| 知乎系列文章三篇 | — | `4ccaa93`（按需可从该提交恢复） |
