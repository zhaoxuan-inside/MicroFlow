# MicroFlow 实施任务规划

日期：2026-10-22。状态：实施中，首批本地同步执行及状态协调协议已落地；整体实现及验收未完成，不承诺交付日期。

## 1. 依据与边界

本计划直接依据以下项目文档，不依赖已移除的 hs-dev-skill 文档体系、流程记录或任务门禁：

- [平台标准设计 v1.3](design/platform-standard-design.md)：需求和行为基线，重点为第 2、23、25、29、31 章。
- [技术选型 v1.2](design/technical-selection.md)：TS-01～TS-22 及第 24 章实施顺序。
- [算法与一致性设计 v1.2](design/algorithms-and-consistency.md)：算法、提交边界及故障行为。

全部基线能力均纳入下面的任务，不把建议阶段视为已经完成或自动取消后续范围。框架核心运行时只依赖 Python 与标准库。构建工具与宿主提供者依赖分别管理；不为推进实现自行选择数据库、消息系统、Web 框架、页面技术或生产持久化介质。

规划建立时仅交付文档和索引；现已按用户指令进入实施。实施按任务逐项复核已有实现并增补验证，不能直接将文件存在视为功能完成。设计发生冲突时先修订相应设计文档，计划不另造业务语义。

## 2. 当前实现基线

检查范围：`MicroFlow4Python/pyproject.toml` 及 `MicroFlow4Python/src/microflow/`。当前目录尚未加入 Git 跟踪，规划保留现有文件。

- 数据与 SDK 初稿：`values.py`、`schema.py`、`paths.py`、`expressions.py`、`sdk.py`、`errors.py`。
- 注册与编译初稿：`registry.py`、`graph.py`、`compiler.py`。
- 策略与状态初稿：`policy.py`、`persistence.py`、`coordinator.py`；另有 `cache.py`。
- 未发现测试目录、端到端示例、完整执行器、调度恢复、发布管理和 CLI 实现。`pyproject.toml` 已声明 `microflow.cli:main` 及 `py.typed`，对应文件尚未发现，须在 T01 补齐或修正声明。
- 编译器当前显式限制汇合为 `all_active_success`；策略实现也有受限范围，不能视为覆盖设计中的全部配置组合。
- `_EphemeralStore` 是非耐久本地实现，不能作为耐久异步、断点恢复或生产高可用证据。

以上为规划建立时的静态盘点；后续实现及测试记录见各任务状态和第 8 节。设计记录中的临时原型不计为仓库实现通过。未记录进展的任务仍为“待实施/核验”。

## 3. 执行顺序与里程碑

- **M1 本地开发闭环**：T01 → T02 → T03；T04 依赖 T02；T05 依赖 T03、T04；T06 依赖 T05。提供显式同步 ephemeral 演练、异常熔断、基础观测、子图与不可变候选快照，不标记生产耐久通过。
- **M2 耐久执行与发布恢复闭环**：T07 依赖 T04；T08 依赖 T05、T07；T09 依赖 T08；T10 依赖 T06、T08；T11 依赖 T09、T10；T12 依赖 T07、T09；T13 依赖 T11、T12；T14 依赖 T08、T11、T12。最终由 T16 验证绑定介质和部署的实际保证。
- **M3 分析与开发辅助能力**：T15 依赖 T03、T06、T10、T12、T14。T16 汇总全部任务的验收证据。

可在上述依赖满足后安排独立工作；此处不指定人员、工期或并行执行方式。基础安全检查、异常行为与观测随每个任务交付，不留到最后统一补做。

## 4. 任务及完成条件

### T01：建立可验证的包与开发入口

- 状态：**完成（已验证环境内）**。新增公开包入口、`__main__.py`、`cli.py`、`py.typed`、标准库测试、报价示例和包 README；已验证 editable 和独立 wheel 安装、实际 console script、模块入口及零运行依赖。Python 3.12/3.13 尚未在本机验证。
- 目标/输入：以现有 `pyproject.toml` 和源码为起点，建立可导入、可安装、可执行检查的最小项目。
- 影响对象：包公开入口、`cli.py`、类型标记、`tests/`、示例及运行说明；先复核已有代码，不批量重建。
- 执行：确定支持的 Python 版本矩阵；修正缺失入口与分发声明；使用 `unittest` 组织契约和集成测试，提供无真实副作用的样例。
- 验证/完成：安装后导入和 CLI 帮助可用；测试发现确实执行非零用例；核心运行依赖仍为空。记录解释器和实际命令。此时 CLI 仅提供已实现命令。
- 依据：平台 §1.5、§16～17、§21；TS-18、TS-22。依赖：无。

### T02：完成六参数 SDK 与数据契约

- 状态：**完成首批契约实现与回归**。修复 context 深层只读、非法路径写入的原子性、required/default 顺序、全量映射冲突预检、JSON 行列诊断、错误 schema 类型及关键词适用性、非有限表达式和测量输入；对应 `tests/test_contracts.py`。生产敏感字段分级和完整诊断扩展仍随 T10/T14 集成验证，不计为平台验收通过。
- 目标/输入：复核 `sdk/values/schema/paths/expressions/errors`，实现平台 §6～7、§10 的边界行为。
- 执行：固定标准 Output/options、只读输入与 context、独立输出；严格 JSON、Schema v1、MISSING/null、路径 AST、受限表达式及版本化规范摘要；定义统一可脱敏诊断。
- 验证/完成：覆盖 bool/int、重复键、非有限数、深度/容量限制、特殊键与数组、缺失/default、非法表达式、映射覆盖冲突；失败不发布部分 data，错误含配置定位。指标 increment/observe 与普通赋值语义分开。
- 依据：TS-05、TS-06、TS-14；算法 §5、§12。依赖：T01。

### T03：完成原子注册和确定性编译

- 状态：**进行中**。已完成签名/批次失败诊断、源码变更检查、不可变图、控制与数据依赖联合判环、静态路径与保守类型证明；重现 1,000 组随机图及 20,000 节点长链/深环。控制/数据/路由/子图引用保留逐边来源，环和未知端点携带来源；诊断补齐发布/流程/节点上下文，失败编译不伪造 release_id。动态节点已校验字段适用性、路由目标、条件/until 来源、map 集合类型和 wait 结果契约。map/loop 组合输入输出的完整静态契约、展开预算与复杂控制合法性仍随 T11 完成；静态多根入口约定见算法设计 §13。
- 目标/输入：复核 `registry/graph/compiler`，形成可重复的发布候选执行计划。
- 执行：manifest 内文件显式 register、暂存注册表全量生效；检查签名、代理、契约、引用、联合控制/数据 DAG 与子图引用；Kahn 和非递归 DFS；编译路径和三态类型兼容诊断。
- 验证/完成：重复/失败注册不污染原表；随机图对照 graphlib、20,000 节点长链/深环和打乱输入确定性在仓库重现；剩余下游不误报成环；无效引用、不可达节点、类型冲突可定位，UNKNOWN 不当作证明兼容。
- 依据：平台 §8～10；TS-01～03、TS-18；算法 §1～3。依赖：T02。

### T04：完成配置解析和提供者公共协议

- 状态：**进行中**。完成四层合并、字段级覆盖白名单、非法组合/能力检查；统一 `microflow-policy-schema-v1` 描述与逐层校验，默认值只读，新增顶层 checkpoint_policy=operator/explicit 及 CLI policy-schema。非法值即使后层覆盖也拒绝。提供者协议包括版本化描述、配置 schema、绑定修订/摘要校验、一致分页和检查点。仍需产物引用保护详细协议及真实提供者验证；checkpoint_policy 的调度执行语义随 T08/T09 集成，不阻塞 T07 独立协议切片。
- 目标/输入：复核 `policy/persistence`，向宿主提供完整的版本化配置、能力描述和注入接口。
- 执行：四层合并、调用覆盖白名单、冻结摘要与绑定修订；补全状态读取/分页恢复/检查点、提交结果、所有权作用范围、产物引用保护及配置 schema。定义 read/query/checkpoint 等语义与 Python 方法的映射，避免接口只声明一部分设计能力。
- 验证/完成：false/0/空集合保留、数组整体替换、null 按 schema、未知字段和危险组合拒绝；无提供者时拒绝耐久执行；跨实例能力单独检查；上层配置变化不修改已固定实例。说明尚不支持的策略并明确拒绝。
- 依据：平台 §29～31；TS-07、TS-08、TS-21；算法 §7、§12。依赖：T02。

### T05：打通同步单算子执行与根流程停止

- 状态：**完成本地同步切片**。新增 `runtime.py` 的 LocalRuntime/RunResult，支持普通函数及协程、独立 fallback、False/契约错误区分、根闩锁、取消和冻结结果。无 fallback 异常不会派发后继；输入/输出非法不发布部分 data；错误消息不泄露业务异常正文。耐久并发与在途收敛属于 T08/T09，当前未实现。
- 目标/输入：在已编译计划和有效策略上建立最小执行器，先以显式 ephemeral、关闭恢复的同步样例验证行为。
- 执行：主方法/协程适配、独立 fallback 输出、False 与异常区分、完成视图、统一异常转换；从第一版引入根闩锁及命令边界。业务资源按引用解析，不进入持久化数据。
- 验证/完成：True 合法输出、False、输出非法、fallback 成功/失败/异常、无 fallback 的根熔断及取消分别可判断；不捕获 BaseException 冒充业务失败；无 fallback 主异常不自动重试。熔断后不能派发后继，错误立即可查询。
- 依据：平台 §6、§11～13、§25；TS-04、TS-11。依赖：T03、T04。

### T06：完成本地流程、基础采集和候选快照闭环

- 状态：**进行中**。静态 DAG、嵌套子图、默认汇合、基础日志/测量、代理故障隔离、不可变候选源码/manifest 校验及 CLI check/run 示例已打通。尚需完善受控 debug 的运维连接、采集容量/脱敏策略、复杂映射与子图预算验证；动态令牌去重和耐久采集在 T07/T10/T11 接入。当前为可运行本地切片，不声明整个 M1 已完成。
- 目标/输入：从单算子扩展至可演练的静态 DAG/子图和默认 all_active_success 汇合。
- 执行：发布结果再推进依赖，重复完成不重复消减；子图继承版本/deadline；提供基础 logging/测量、特殊代理隔离、受控 debug；构造代码/契约/配置/计划完整候选 manifest，提供本地示例。
- 验证/完成：同步流程从输入映射运行至根 Output；缺失代理仍有基础记录，自定义代理失败不改变业务终态；输入不互改，父子等待释放工作容量；候选摘要可校验。候选构建与耐久发布分别标记。
- 依据：平台 §9、§14～17；TS-03、TS-15、TS-19、TS-20。依赖：T05。

### T07：建立原子状态协调与提供者契约测试

- 状态：**进行中，状态提交协议切片通过**。Coordinator 将命令摘要、原始 JSON 返回值与 StateBatch 同批提交；重复控制请求返回原回执，UNKNOWN/查询中断阻止后续写入。已有有界内存替身、绑定范围拥有者隔离、一致分页和检查点测试。T08 命令切片已将静态算子结果、根闩锁、后继就绪、attempt_epoch 与事件意图同批提交。完整业务幂等、事件投递、产物引用及跨进程/真实介质验证仍未完成。
- 目标/输入：复核 `coordinator`，让所有权威变化通过 StateBatch 提交；提供内存及模拟故障替身，仅用于协议验证。
- 执行：固定命令身份、revision/epoch/owner 校验、去重摘要和回执；结果、幂等、闩锁、后继任务、可靠事件意图同批提交；UNKNOWN 使用原请求查询，不先发布内存成功。
- 验证/完成：部分写入、提交失败/未知、应答丢失、重复请求同/异摘要、revision 冲突、过期拥有者、恢复视图混读和产物缺失均有测试；实际提供者可复用同一套契约。请求身份在重启和查询中可追溯。
- 依据：平台 §13、§20、§29；TS-07～10、TS-22；算法 §6～8。依赖：T04。

### T08：完成耐久接纳和混合同步异步调度

- 状态：**进行中，静态执行与预算状态切片通过**。`ExecutionCommands` 固定 release/policy/binding，原子处理接纳、领取、结果、闩锁与后继就绪；隔离过期 owner/attempt_epoch。`ScheduledRuntime` 支持有界线程池、协程、独立状态 I/O、非阻塞等待、采集隔离和排空。新增状态 v2：持久接纳/就绪/领取/完成时间及 queue/attempt/deadline，计时器、领取及完成均检查预算；在途到期仍为 CLAIMED/STOPPING，迟到结果保存但不推进后继。默认时钟以单调经过时间防回拨，旧格式拒绝隐式重建预算。仍缺 CPU 进程池、硬时间隔离、自动恢复/检查点、公平队列和产物引用保护；写入型算子、动态节点、子图及未支持策略继续拒绝，LocalRuntime 保持本地软超时边界。完整生产耐久性、时钟/主机故障和性能未验收。
- 目标/输入：以已通过契约测试的绑定能力接入统一执行器和调度器。
- 执行：原子接纳、READY/CLAIMED 耐久任务、可重建就绪/延迟堆；协程、阻塞 I/O、CPU 隔离池；租户公平性、配额、背压；分别实施 wait/queue/attempt/deadline 超时及根停止判定。
- 验证/完成：获得耐久确认后才返回 accepted；同步等待与异步节点混用不耗尽池；断连只结束等待；线程超时后不并发重执副作用；重启可重建任务；熔断与领取/迟到完成竞态不推进后继。
- 依据：平台 §11～13、§19、§28；TS-04、TS-09～11、TS-17；算法 §6、§10。依赖：T05、T07。

### T09：完成业务幂等、恢复与临界资源约束

- 状态：**进行中，业务身份、失联隔离与授权证据确认协议切片通过**。新增 `idempotency.OperationScope` 和独立于缓存的 operation 记录；可信业务范围在接纳时固定，key_paths 只引用算子 input，完整输入/语义版本参与摘要，release/trace/attempt 不改变业务身份。记录创建与领取、结果确认与节点结果/后继同批提交；并发同键等待原操作，同摘要复用确认结果，异摘要冲突；跨发布校验旧结果契约，保留期结束仍保留身份。新拥有者可用 expected_revision 将旧 CLAIMED 隔离为 IN_DOUBT，保留未知结束时间和旧身份，禁止自动重派。ConfirmationService 要求宿主授权和证据查询，重新检查 CAS/授权期限并原子提交结果与审计，保留原停止闩锁。当前仅开放已支持的纯计算/读取型算子；真实写入、生产授权/外部结果查询提供者、自动安全重执、资源锁/心跳及检查点恢复仍待 D03/D04 及后续集成，不计为完整恢复完成。
- 状态：**进行中，业务身份、失联隔离、授权证据确认及资源租约协议切片通过**。新增 `idempotency.OperationScope` 和独立于缓存的 operation 记录；可信业务范围在接纳时固定，key_paths 只引用算子 input，完整输入/语义版本参与摘要，release/trace/attempt 不改变业务身份。记录创建与领取、结果确认与节点结果/后继同批提交；并发同键等待原操作，同摘要复用确认结果，异摘要冲突；跨发布校验旧结果契约，保留期结束仍保留身份。新拥有者可用 expected_revision 将旧 CLAIMED 隔离为 IN_DOUBT，保留未知结束时间和旧身份，禁止自动重派。ConfirmationService 要求宿主授权和证据查询，重新检查 CAS/授权期限并原子提交结果与审计，保留原停止闩锁。`LeaseRequest`/`ResourceLease` 固定排序资源键、所有者世代和到期时间，旧租约续租/释放被拒绝。当前仅开放已支持的纯计算/读取型算子；真实写入、生产授权/外部结果查询提供者、资源适配器/跨进程租约、自动安全重执、心跳及检查点恢复仍待 D03/D04 及后续集成，不计为完整恢复完成。
- 目标/输入：建立独立于缓存的持久业务身份与恢复判定。
- 执行：IN_PROGRESS/成功/失败/IN_DOUBT、结果与墓碑保留、跨版本去重；资源键有序取得、心跳世代和接管；算子边界/显式检查点恢复、安全重试与 full jitter；未知副作用查询或人工确认。
- 验证/完成：同键并发仅一个执行归属、异输入冲突；在执行前/外部写后/结果提交前后退出不会盲目重写；旧工作者被隔离；原 release/policy/binding/业务键固定；恢复关闭时不自动重执；缓存清空不删除幂等。
- 依据：平台 §12～13、§27；TS-10～12；算法 §8、§10。依赖：T08。

### T10：完成可靠采集、debug 与业务事件

- 目标/输入：把 T06 的基础观测接入耐久终态及采集意图。
- 执行：默认和特殊采集、指标基数/缓冲预算、可查询 trace；关键事件稳定 event_id、消费凭据和投影原子提交；debug 检查点/暂停/继续及临界资源限制；信任字段与敏感值脱敏。
- 验证/完成：观测失败不重跑主方法；失联结束时间保留 null/observedEndedAt；重复/乱序/迟到事件不重复事实且可修正投影；代理投递中断可恢复；积压背压明确，暂停不无限持锁。
- 依据：平台 §14、§21；TS-15、TS-16、TS-20；算法 §10。依赖：T06、T08。

### T11：完成动态控制节点与耐久触发

- 目标/输入：补齐静态 DAG 之外的条件路由、多种汇合、集合、有限循环、信号等待及定时/事件触发。
- 执行：持久激活集合、SKIPPED 和去重令牌；any_success/collect/指定数量语义及其他分支收敛；有界展开/循环；信号先到/重复处理；时区、DST、latest/forbid 默认及显式补跑/重叠策略。
- 验证/完成：恢复不重新决定路由；缺失必需结果失败；无在途副作用遗留才可完全成功；信号鉴权且等待释放容量；计划时刻/代际去重，记录与接纳意图原子提交；生成可读触发表，非支持周期表达拒绝。
- 依据：平台 §9、§28；TS-03、TS-09、TS-17；算法 §4、§10。依赖：T09、T10；受 D02 的具体策略协议约束。

### T12：完成完整发布、回退和介质迁移

- 目标/输入：将候选快照、ArtifactStore 与原子活动指针连接为完整发布协议。
- 执行：完整产物保存/验证、目标环境兼容检查、指针切换、版本路由、在途引用保护/GC；绑定修订及状态/幂等/事件/产物迁移的一致切点、核验、接管和回退；备份恢复一致性检查。
- 验证/完成：缺失/损坏/不兼容产物阻止发布；回退只影响新实例；子图/代理/恢复固定原版本；仍有引用的绑定或产物不删除；迁移/备份恢复后先核验未知副作用再开放写入。
- 依据：平台 §15、§29～30；TS-19、TS-21；算法 §7、§11。依赖：T07、T09；真实介质演练受 D03 约束。

### T13：完成配置化结果缓存

- 目标/输入：复核 `cache.py` 并接入幂等核验后的调用路径。
- 执行：LRU/TTL/字节与条目预算、完整隔离键、仅合法主成功 data、single-flight、代际失效及故障旁路；跨工作进程协调或明确隔离本地范围，保留对象引用。
- 验证/完成：命中生成新的 meta/观测；不同租户/权限/版本/输入/数据版本不串用；取消等待者不取消共享填充；填充故障、过期、失效并发回填受控；失败/fallback/写入不入缓存；不旁路幂等故障。
- 依据：平台 §26～27；TS-13、TS-14；算法 §9。依赖：T11、T12。

### T14：完成公开 API/CLI 与可信运行控制

- 目标/输入：公开查询、校验、提交/等待、信号、取消、暂停/继续、恢复/重跑、未知确认、迁移及快照控制。
- 执行：版本化 JSON、稳定诊断码、主体和能力校验、expected_revision、控制请求去重与审计；提供者描述/配置 schema/绑定校验接口供宿主页面使用；人工处理队列和责任/时限挂接接口。
- 验证/完成：接纳与业务完成、请求取消与已取消区分；旧结果重新鉴权；重跑不绕过业务身份；未知确认附证据；页面离线不影响已接纳执行，宿主和核心自行校验配置。示例宿主不访问真实业务资源。
- 依据：平台 §16～17、§21、§28～31；TS-18、TS-20、TS-21。依赖：T08、T11、T12。

### T15：完成内置分析与局部开发辅助

- 目标/输入：基于编译反向索引、可靠事件和公开接口提供分析及开发上下文。
- 执行：静态引用、逻辑/实际调用、缓存/幂等/重试分母、关键路径与墙钟等待分析；分页导出和保留预算；模板、契约查询、直接上下游、影响预览、版本差异及隔离重现接口。
- 验证/完成：并行耗时不简单累加、桶统计不冒称精确 p99；分析可定位 release；局部上下文声明遗漏并脱敏；以固定任务记录上下文规模、修改范围、回归率及修复时间。无需内置 AI 代理或模型。
- 依据：平台 §14、§16、§19、§22；TS-16、TS-18。依赖：T03、T06、T10、T12、T14。

### T16：完成配置矩阵、故障和质量验收

- 目标/输入：汇总 T01～T15 的测试与示例，分别验证框架协议、实际提供者、部署故障域及维护效果。
- 执行：覆盖缓存/幂等开关、配置覆盖、同步异步、恢复/绑定固定；进程/主机/介质故障和备份回退演练；固定图规模、负载、资源、尾延迟、吞吐、恢复时限及运行时长。
- 验证/完成：A01～A35 逐项附可重复命令、版本、环境、数据、期望来源及结果；未实现/未接入介质/未定指标标为未验收或阻断，不能用替身、单机或平均数替代生产声明。
- 依据：平台 §19～23、§30；TS-21、TS-22。依赖：T01～T15；生产质量验收受 D01、D03 约束。各任务内测试随实现进行，不等待本任务开始。

## 5. 验收场景归属

下列为主责任务；集成场景需要其前置任务共同完成。T16 统一保存最终证据，当前所有场景均未验收。

- T02：A03。
- T03：A02、A04。
- T04：A31、A32、A33（A31 的真实提供者切换由 T12/T16 验证）。
- T05：A07、A17。
- T08：A01、A18、A25。
- T09：A08、A09、A23、A24。
- T10：A10、A11、A19、A20、A27。
- T11：A05、A06、A26。
- T12：A12、A13、A30、A34（提交故障依赖 T07）。
- T13：A21、A22。
- T14：A29、A35。
- T15：A14、A15。
- T16：A16、A28。

技术选型覆盖：TS-01/02→T03；03→T06/T11；04→T05/T08；05/06→T02；07/08→T04/T07；09→T08/T11；10/12→T09；11→T05/T08；13→T13；14→T02/T13；15→T06/T10；16→T10/T15；17→T08/T11；18→T03/T14/T15；19→T06/T12；20→T10/T14；21→T04/T12/T16；22→各任务测试及 T16。

## 6. 实施前待决项与处理位置

- **D01 质量基线**：平台 §22 尚无数值目标。实施启动时记录目标图规模、数据量、并发、负载类型、支持运行环境、吞吐/尾延迟/框架开销、SLO/RTO/RPO 和长稳时长，由项目负责人确定。可先建立功能测试和基准工具；未明确前不能关闭 T16 或宣称性能/高可用达标。
- **D02 控制与策略详细协议**：平台已规定节点能力，但指定数量汇合、信号消费、部分失败、周期策略及可覆盖字段仍需细化配置格式、错误码和状态转换。checkpoint_policy 的字段及边界已在算法设计 §15 对齐，调度集成尚未完成。分别在 T03/T04/T11 开始相应能力前将结论写回设计，不把当前受限实现升级为规范，不阻塞无关基础任务。
- **D03 真实提供者及部署**：由宿主确定实际实现、能力作用范围、绑定与凭据管理、迁移和故障模型。框架可先交付协议及故障替身；真实耐久、多实例接管、主机/介质故障与生产迁移验收依赖真实绑定证据。宿主页面按协议集成，具体 UI 不在核心实现中自行新增。
- **D04 权限和业务确认**：在 T09/T14 对接前明确宿主能力校验接口、真实资源幂等/查询能力、人工确认的证据结构及处理责任。核心拒绝能力缺失请求；不自行实现身份系统或用示例授权冒充生产授权。

## 7. 状态更新和变更恢复

实施已从 T01 开始。每项任务结束时在本文件对应任务下补充状态、实际影响文件、验证命令/环境/结果及剩余限制，避免另建一套与设计并行的权威体系。部分实现保留“进行中”，验证未通过不得标为完成。阶段通过只代表列明范围，生产声明还须满足 D01/D03 和 T16。

当前 README、docs 和 MicroFlow4Python 有既有未提交内容。后续修改前复核差异，保留用户修改，不整目录覆盖或使用 reset/clean 清理。恢复只撤回当前任务的明确变更；涉及公共协议、状态编码或检查点版本时保留兼容与迁移方案。测试使用隔离数据和业务替身，发布/迁移演练记录源目标绑定、切点、核验与回退结果。

## 8. 首批实施验证记录（2026-10-21）

命令工作目录：`MicroFlow4Python/`。环境：Windows，CPython 3.14.5rc1 常规构建及 3.14.5rc1 free-threading 构建；后者实际 `sys._is_gil_enabled()` 为 False。这是本机证据，不扩展为 Python 3.12/3.13 或其他操作系统已验证。

- `.venv/Scripts/python.exe -m pip install -e .`：成功，包入口和 console script 可用。
- `.venv/Scripts/python.exe -m unittest discover -s tests -q`：54 项通过；包含 1,000 组随机图、20,000 节点长链/深环、契约/策略、异常/fallback/熔断/取消、采集故障、子图、候选产物及 CLI 集成。
- `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 54 项通过；free-threading 构建不代表已完成生产并发压力验证。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功构建 `microflow4python-0.1.0-py3-none-any.whl`；SHA-256 `5414667df4ca282e8dda2bc93c023bbab4c6e0c98677cf3039c3df1f05e92a0d`。
- 在独立 `.venv/wheel-check/` 环境用 `pip install --no-deps --force-reinstall dist/microflow4python-0.1.0-py3-none-any.whl` 后，执行 `python -m unittest discover -s tests -q`：54 项通过。确认 microflow 来自该环境的 `site-packages`，不是 editable 的 src；`Requires-Dist` 为 None。
- wheel 环境的 `microflow.exe run examples/quote.flow.json quote examples/quote.input.json --ephemeral`：成功，`output.data.total=3900`；`microflow check` 与缺少 `--ephemeral` 的拒绝场景有集成测试。

以上使用纯计算示例和本地内存状态，没有真实业务资源、生产介质或外部副作用。源码回归、配置矩阵子集与平台 A01～A35 最终验收分别管理，所有平台场景仍未标为最终验收通过。

下一实施顺序：补齐 T03 的定位诊断及 T04 的配置/提供者详细协议，完善 T06 本地边界，再进入 T07 原子状态契约与 T08 耐久调度；D01/D03/D04 仍保留原有依赖条件。

## 9. 状态协调协议切片验证记录（2026-10-22）

影响文件：`MicroFlow4Python/src/microflow/{persistence,coordinator,testing}.py`、`tests/test_coordinator.py` 及本节对应设计/README。保留既有本地执行器行为，未连接真实资源或提供者。

- 在 `MicroFlow4Python/` 执行 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：80 项通过，其中本批新增 26 项。
- 设置 `PYTHONPATH=src`，执行 `py -3.14t -m unittest discover -s tests -q`：80 项通过；本机 CPython 3.14.5rc1 free-threading 构建。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：构建成功，SHA-256 `7ecd338bdf82508013a4462f98118bcdf05503f3492ba25ef86ca083e4ffd393`。
- 独立 `.venv/wheel-check/` 强制安装该 wheel 后，运行同一测试命令：80 项通过；确认 `microflow.testing` 来自该环境 `site-packages`。
- 协调器重新创建后通过同一个存储对象取回原结果，证明对象生命周期内的请求回执复用；不作为进程崩溃恢复或刷盘证据。测试替身 `durable_ack=False`，默认不允许声明耐久能力；即使声明能力，耐久协调器仍检查实际提交回执。

T03 的逐边定位诊断、T04 的统一策略配置 schema/checkpoint_policy 继续保留；后续先补这两处，再将 T07 状态协议接入 T08 接纳/派发/完成状态机。真实介质、部署故障域和权限决定继续依赖 D01/D03/D04，平台场景仍未最终验收。

## 10. 编译定位与统一策略协议验证记录（2026-10-22）

本批修改 `src/microflow/{graph,compiler,errors,policy,cli}.py`，扩充 `tests/{test_compiler,test_policy,test_package}.py`；新增行为写回算法设计 v1.3 §15，并更新包 README。任务保持进行中，未把动态节点可编译等同于已能执行。

- `MicroFlow4Python/` 下 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：96 项通过，本批新增 16 项测试；包含重复边各来源、联合依赖环/子图环/未知端点定位、来源路径实际取值、诊断元数据不改变发布身份、畸形动态节点、until 依赖、map/wait 契约、所有策略叶字段拒绝 null（包括被覆盖值）、禁用配置形状、时长及 checkpoint_policy 摘要与覆盖、CLI 描述/项目解析诊断。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 96 项通过；本机 CPython 3.14.5rc1 free-threading 构建，仍不扩展为其他平台或生产并发验收。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功，wheel SHA-256 `8f9c61f7e440d876529dc10e58f924b7db736b72e809699b95ac9c2612a16bff`。
- 独立 `.venv/wheel-check/` 强制安装新 wheel 后，同一 96 项测试通过；确认 policy 模块来自该环境 site-packages，Requires-Dist 为 None。

checkpoint_policy 新字段进入生效策略摘要，策略固定身份随语义变化；配置来源文件和诊断元数据不参与发布身份计算。字段约定已明确，调度检查点尚未启用。下一切片进入 T08 的原子接纳/派发/完成状态机并复用 T07 协调协议；map/loop 完整静态契约与复杂动态合法性留在 T11，产物引用/真实提供者验证继续按 T04/T12/T16 跟踪。

## 11. T08 静态状态命令验证记录（2026-10-22）

新增 `src/microflow/scheduling.py`、`tests/test_scheduling.py`；协议边界见算法设计 v1.4 §16，更新 T07/T08 状态及包 README。本批只改变框架状态，不执行外部业务方法，不接入真实介质。

- `MicroFlow4Python/` 下 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：119 项通过，新增 23 项测试。
- 新增覆盖：接纳与完成区分、请求摘要冲突、结果与后继就绪原子提交、依赖未完成拒绝领取、并行领取竞态、根首错/STOPPING/迟到成功、取消收敛、IN_DOUBT、输入/输出非法不发布部分结果、错误 worker/release/binding/attempt/owner（包含 bool/int 代际混淆）隔离、同存储对象重建状态及旧领取拒绝、接纳/节点/领取/算子并发预算、expected_revision、提交前查询未知/提交后应答未知/应答丢失、空图以及未支持能力拒绝。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 119 项通过；本机 CPython 3.14.5rc1 free-threading 构建。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功，最终 wheel SHA-256 `1c4fc5667da2b9ad73076716adc708c4a49737d66a11d142c0337f45ee4dee50`。
- 独立 `.venv/wheel-check/` 强制安装最终 wheel 后，同一 119 项测试通过；确认 scheduling 模块来自该环境 site-packages。

所有新测试显式使用 protocol_test=True 的内存替身，不能作为生产接纳耐久性、进程崩溃恢复、真实副作用恰好一次、工作池或性能验收证据。下一切片将命令层接入工作执行与非阻塞等待，再补队列/执行/截止时间和恢复确认；仍不自动重派旧 CLAIMED。D01/D03/D04 及完整平台验收状态保持原有约束。

## 12. T08 工作执行与等待验证记录（2026-10-22）

新增 `src/microflow/worker.py`、`tests/test_worker.py` 和可执行示例 `examples/scheduled_quote.py`；扩展包公开入口，调整 `runtime._operator` 以复用业务语义并在可选采集前提交结果，补充状态命令数据冻结前的值预算校验。同步更新算法设计 v1.5 §17、README 及 T08 状态。

- `MicroFlow4Python/` 下 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：138 项通过，本批新增 19 项（18 项工作执行测试及 1 项示例集成）。
- 覆盖静态结果与 LocalRuntime 一致、稳定调用身份、重复接纳、协程/同步业务与有界并行、单业务线程下依赖推进、等待取消/超时及接纳期间断连、显式取消后的活线程收敛、提交先于慢采集、fallback/False/采集故障隔离、完成提交失败不重跑、旧 CLAIMED 拒绝自动恢复、有界诊断/暂停拒绝、同步/异步节点策略、关闭排空、完成回执未确认不提前返回终态、致命异常优先于软时长检查、非法等待预算不接纳及事件循环归属。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 138 项通过；本机 CPython 3.14.5rc1 free-threading 构建。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功，最终 wheel SHA-256 `aec760deca611b44c2681088c9bb7b4aa100175c94e54dc54f13a4d195f45983`。
- 独立 `.venv/wheel-check/` 强制安装最终 wheel 后，同一 138 项测试通过；worker 模块来自该环境 site-packages，Requires-Dist 为 None。
- 示例集成实际运行 `python examples/scheduled_quote.py`，返回 `total=3900`、protocol_test=true、durability=ephemeral；未访问真实业务资源。

本批验证使用显式内存协议模式，混合节点策略测试也不提供真实 durable 介质确认。服务生命周期存活时客户端断开与业务分离；进程/事件循环销毁、主机故障、工作者租约接管及外部副作用确认仍待后续验证。下一切片补 T08 的队列/流程截止时间和执行预算状态，再进入 T09 恢复确认；CPU 分池、公平调度、检查点与发布引用继续跟踪，T08 和平台最终验收仍未关闭。

## 13. T08 预算状态验证记录（2026-10-22）

新增 `src/microflow/timing.py`、`tests/test_timing.py`；调整 scheduling/worker/runtime，将队列、尝试与根截止时间接入原子命令和工作服务。ScheduledRuntime 返回真实迟到结果，LocalRuntime 保持软超时默认行为。更新算法设计 v1.6 §18、README 与 T08 当前状态。

- `MicroFlow4Python/` 下 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：158 项通过，本批新增 20 项（16 项预算/时钟状态测试，4 项工作服务集成）。
- 覆盖精确到期边界、未到期计时器不占请求身份、无计时器时领取/完成自行拒绝越界、依赖 WAITING 不消耗 queue、根预算固定、在途保留容量/结束时间未知、迟到成功保留结果但停止推进、过期领取不再发放、多个到期预算排序与同刻优先级、取消不掩盖到期、非法/回拨时钟拒绝、默认单调时钟及前跳后回拨、旧格式拒绝、同存储对象重新创建协调器不重置原预算、计时器应答丢失去重、工作池满时队列超时、活线程/协程到期收敛及 fallback 不越预算开始。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 158 项通过；本机 CPython 3.14.5rc1 free-threading 构建。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功，最终 wheel SHA-256 `1609c0d2304e667aff25efb96f8a1ab8896c723099134ca99cda2a488c3caf8f`。
- 独立 `.venv/wheel-check/` 强制安装新 wheel 后，同一 158 项测试通过；确认 timing 模块来自 site-packages，STATE_PROTOCOL 为 microflow-execution-state-v2。

格式变更明确拒绝旧 v1 记录，未删除记录或自动重置预算；真实状态迁移未实施。预算时刻与调度测试使用注入时钟及内存替身，不作为跨主机时钟、真实耐久性、硬时间上限或主机故障恢复证据。下一切片进入 T09 的恢复确认/业务幂等协议；T08 的 CPU 隔离、公平调度等和 T12 的产物/迁移保护继续保留，平台最终验收不关闭。

## 14. T09 业务幂等与失联隔离验证记录（2026-10-22）

新增 `src/microflow/idempotency.py`、`tests/test_idempotency.py`，调整 scheduling/worker 将业务记录与领取/完成原子提交、复用已确认结果并轮询原操作；增加旧拥有者失联隔离命令。更新算法设计 v1.7 §19、README 与 T09 状态。执行协议仍为 v2，新增业务记录协议为 microflow-business-operation-v1；只给启用幂等的新节点保存 scope/operation 元数据。

- `MicroFlow4Python/` 下 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：183 项通过，本批新增 25 项。
- 覆盖并发同键单归属、处理中不占第二领取槽、同键异输入冲突、确认失败不重试、跨发布旧结果复用、语义版本冲突、输出契约不兼容不重执、租户与 bool/int 键隔离、接纳 scope 固定、结果到期保留身份、非法范围/键路径/缺失键拒绝、完成应答丢失、当前拥有者不能假装活任务失联、旧代际隔离/expected_revision/重复命令/结束时间未知/旧工作者拒绝、损坏记录拒绝、取消或超时重复等待者不影响原操作、存储/容量故障不拆散节点和账本、未知结果身份不按 TTL 释放、新调用回拨时钟拒绝，以及 ScheduledRuntime 的并发等待和确认结果复用不调用第二次业务。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 183 项通过；本机 CPython 3.14.5rc1 free-threading 构建。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功，最终 wheel SHA-256 `d5ea69f48dc53b97fbb3844998d4632afbd6c468879a37a816ba686be83996cf`。
- 独立 `.venv/wheel-check/` 强制安装最终 wheel 后，同一 183 项测试通过；idempotency 模块来自 site-packages，operation 协议版本正确，Requires-Dist 为 None。

全部新行为使用显式内存协议替身与纯计算测试方法；scope、记录和拥有者模型不提供真实业务授权、跨主机接管或外部副作用证据。IN_DOUBT 的含义是未知且禁止重复派发，不是已经确认成功/失败或可重跑。当前没有自动清除 operation/原执行/命令回执数据的保留清理器，保留期仅约束新的逻辑调用复用。T09 继续跟踪外部结果确认器、证据/授权接口、资源租约、检查点与安全恢复，写入型算子仍拒绝，平台最终验收不关闭。

## 15. T09 授权证据确认协议验证记录（2026-10-22）

新增 `src/microflow/confirmation.py` 和 `tests/test_confirmation.py`，更新算法设计 v1.8 §20、包 README 及 T09 当前状态。提供必需的宿主授权/证据查询协议、限时且绑定目标的授权、未知结果确认与原子审计；未增加实际授权器、外部查询适配器或公开控制端点。

- 常规 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：206 项通过，本批新增 23 项。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 206 项通过；本机 CPython 3.14.5rc1 free-threading 构建。
- 覆盖成功/失败确认与新逻辑调用复用、旧代际来源固定、原执行停止/已跳过后继保留、未知物理结束时间保留、证据冻结及身份错配拒绝、缺少提供者/错误授权目标/拒绝/过期/不可用授权、重复请求重新授权和撤销拒绝、不同主体请求冲突、未验证/不可用查询及 truthy 非 True 拒绝、查询前 CAS/输出 schema 校验、查询期间到期/修订变化/时钟回拨、查询在协调器锁外、容量失败无部分提交、应答丢失/UNKNOWN 后回执恢复无重复审计或查询、已确认结果不可覆盖、原发布不符/缺少 CAS、未知或查无结果不能确认为失败、冻结 scope 损坏拒绝。
- `.venv/Scripts/python.exe -m pip wheel . --no-deps --wheel-dir dist`：成功，wheel SHA-256 `78d99ef481c14db623eefb5b258dea4652d31fe8977eb382b335e8beb2a0350b`。
- 独立 `.venv/wheel-check/` 强制安装该 wheel 后，同一 206 项测试通过；确认 confirmation 模块来自该环境 site-packages，Requires-Dist 为 None。

全部验证使用显式内存协议替身、测试授权器和测试证据查询器，不证明真实外部副作用、生产授权或耐久介质正确。授权有效期和已发放授权的撤销粒度由宿主决定；确认不解除原根停止闩锁、不重派业务、不补造物理结束时间。原始证据保存和结果最终性、生产授权/查询提供者仍依赖 D03/D04；资源租约/心跳、检查点及安全恢复继续列为 T09 后续，写入型算子与平台最终验收保持未开放/未关闭。

## 16. T09 资源租约协议验证记录（2026-10-22）

新增 `src/microflow/resources.py` 与 `tests/test_resources.py`。`LeaseRequest` 固定唯一、排序后的资源键；`ResourceLease` 绑定 owner/generation/expiry；内存提供者覆盖多资源申请、冲突、到期观察、续租/释放 CAS 和旧世代隔离。该切片只定义宿主注入协议，不接入 ScheduledRuntime 的业务执行或真实资源系统。

- 常规 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：210 项通过，本批新增 4 项。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 210 项通过。

测试替身不会跨进程保留租约，也不阻止已获得租约的工作者对外部系统写入；实际租约服务、心跳、接管和状态批次绑定仍待 D03 及 T09 后续集成。

## 17. T10 可靠事件意图协议验证记录（2026-10-22）

新增 `src/microflow/events.py` 与 `tests/test_events.py`。`EventIntent` 固定事件来源、聚合键、连续序号及不可变 payload；`MemoryEventStore` 提供 event_id 去重、摘要冲突拒绝、聚合序号检查、容量原子拒绝、PENDING/DELIVERED 确认和有界 pending 查询。该切片尚未接入 StateBatch 或外部消息提供者。

- 常规 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：214 项通过，本批新增 4 项。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 214 项通过。

验证使用内存替身，不能证明跨进程投递、消费凭据、背压、迟到事件重算或生产介质耐久性。T10 后续仍需把事件意图接入状态批次、实现投递重试与权限审计，并保留真实业务事实与投递状态的区分。

## 18. T10 调度事件批次接入验证记录（2026-10-22）

调整 `src/microflow/scheduling.py` 与 `tests/test_scheduling.py`：所有调度命令的 `_batch` 现在构造 `microflow-event-v1` 事件记录，保存连续 execution 序号、内容摘要、发布来源和 PENDING 投递状态，与执行状态、后继意图、operation 记录继续同批提交；稳定 command replay 不生成第二条意图。

- 常规 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：214 项通过。
- 设置 `PYTHONPATH=src` 后 `py -3.14t -m unittest discover -s tests -q`：同一 214 项通过。
- 新增断言覆盖事件序号、协议版本和内容摘要；原有应答丢失、重复接纳、完成回执及容量故障测试继续通过。

该接入仍只保存可靠意图，不执行外部投递；投递器、消费凭据、背压、迟到事件修正和生产介质验证继续属于 T10/D03。
