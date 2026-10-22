# MicroFlow 框架内部功能技术选型

版本：v1.2  
日期：2026-10-21  
关联：[平台标准设计](platform-standard-design.md)、[算法与一致性设计](algorithms-and-consistency.md)。

## 1. 选型范围

本文只选择框架内部的算法、数据结构、状态协议和标准库实现方式。不选择数据库、消息中间件、外部缓存、Web 框架、观测平台、部署系统或第三方 Python 包。框架核心只依赖 Python 运行时与标准库；持久化仅定义接口，由上层页面配置并绑定具体介质实现。介质实现及其依赖由宿主负责，不进入框架核心。

业务算子访问的数据库、服务等属于业务依赖，不转化为框架运行前提。协议或官方文档作为参考不构成组件依赖。本文取代上一版包含基础设施选型的方案。

同一执行分区的状态命令采用串行判定，工作者经统一提交接口报告结果。框架不固定宿主拓扑和持久化介质；恢复和可用性保证由框架协议、绑定提供者能力及部署共同决定。缓存、幂等、同步/异步等通过版本化配置解析，不在算子方法中写死。

## 2. TS-01：DAG 表示与环检测

选择邻接表、入度表、Kahn 入度消减算法。使用 heapq 最小堆按稳定节点标识输出就绪节点，保证相同定义的编译结果可重复。

判定标准为输出节点数是否等于全部节点数。剩余节点不能全部视为环：它们可能只是环的下游。未知节点、重复边和自环分别校验。

复杂度：邻接构建 O(V+E)，使用最小堆的 Kahn 为 O(E+V log V)，空间 O(V+E)。不选择邻接矩阵、全路径枚举或第三方图引擎。

## 3. TS-02：环路径定位与子图引用检查

选择非递归三色 DFS，显式栈和路径位置索引提取闭合环。对剩余诱导图按稳定根和后继顺序遍历，输出具体节点、边与配置路径；多环默认返回首个确定性见证。

每个子图独立检查，另对“子图引用图”执行同样检查，拒绝递归引用。有限循环通过控制节点产生每轮实例，不在单轮 DAG 内引入回边。

DFS 扫描 O(V+E)，排序有额外成本；不用解释器递归调用处理深图。标准库 graphlib 只作为测试对照，不承担业务运行状态。

## 4. TS-03：就绪调度、分支与汇合

选择事件驱动依赖令牌、后继索引、去重集合与就绪堆。完成事件先在同一提交批次去重再改变依赖状态，重复消息不得重复减入度。

控制令牌与数据依赖分开，路由选择和激活集合持久化。all_active_success、any_success、collect 明确处理跳过、失败和必要输入；根流程熔断覆盖局部汇合。集合展开限制并发和数量，子图复用编译计划，不复制全部图结构。

## 5. TS-04：同步异步与并发执行

选择 asyncio 管理协程与非阻塞等待，concurrent.futures 的有界线程池承载阻塞 I/O，multiprocessing 管理 CPU/隔离工作进程。同步或异步仍是本次调用属性，与方法是否 async def 无关。

父流程等待子节点时释放工作容量。资源和连接在工作进程内重建，不持久化 Python 运行对象。跨进程仅传受控序列化消息，不把六个参数原样交给进程池隐式 pickle。

取消采用协作信号；需要硬终止时终止隔离工作进程并核验副作用。线程超时不等于线程已停止。

## 6. TS-05：配置与业务契约

选择 JSON 为核心配置格式，标准库 json 解析。通过 object_pairs_hook 拒绝重复键，通过 parse_constant 拒绝非有限数，并设置字节、深度、字段和集合数量上限。语法错误报告行列，语义错误报告文件与配置路径。

内置 MicroFlow Schema v1 校验器支持 object/array/string/integer/number/boolean/null、properties、required、additionalProperties、items、enum、数值区间和长度约束。type(value) 检查避免将 bool 当成 integer；未知关键字在发布期拒绝，不静默忽略。

该契约是明确版本化的框架协议，不宣称完整支持任意 JSON Schema。复杂条件交给验证算子。YAML、第三方校验库不是必需依赖，也不在本轮自行开发完整 YAML 解析器。

## 7. TS-06：路径和表达式

选择词法扫描加 Field/Index token AST。支持 a.b、items[0]、["a.b"]，解析 O(L)，访问 O(D)。采用独立 MISSING 标记区分缺失与 null。

条件使用受限 JSON AST：eq/ne/lt/lte/gt/gte/and/or/not/exists/in。规定类型和短路规则；不使用 eval、脚本模板或通用查询引擎。复杂业务判断由算子实现。

输入深度冻结，输出在独立容器构造；校验成功后才发布，不通过共享 Map 隐式互改数据。

## 8. TS-07：状态协调与原子提交

选择逻辑状态拥有者与 revision/epoch 校验。状态拥有者是执行分区的一致性角色，不固定为唯一机器；线程和工作进程通过命令接口提交变化，不能绕过接口写具体介质。每条命令含 command_id、expected_revision、execution_epoch。

同一批次包含节点结果、幂等结果、流程闩锁、后继任务及可靠采集意图，经 StateStore.commit 原子提交后才发布可见状态。多个框架实例共享执行分区时，提供者必须支持跨实例条件更新及所有权隔离；不能仅凭进程内锁声称满足。

框架选择命令顺序、批次和重放语义，提供者实现实际耐久提交，不强制文件日志或数据库事务。

## 9. TS-08：持久化提供者接口与断点恢复

选择 typing.Protocol 定义的 PersistenceProvider、StateStore 和 ArtifactStore 接口。上层页面选择已注册 provider、命名空间及参数，宿主服务验证后将实例注入框架。页面不是耐久状态拥有者，页面关闭不影响已接纳任务。

StateStore 提供 capability 描述、read/query、原子 commit、按请求标识查询提交结果、checkpoint 和恢复游标；ArtifactStore 提供不可变对象的 put/get/verify 与引用保护。框架不指定介质，也不内置必须使用的文件 journal、刷盘或文件锁实现。

耐久接纳要求提供者明确保证 atomic_batch、conditional_write、request_deduplication 和 durable_ack。多实例接管另外要求 scope 合适的 ownership/fencing。缺少能力或未绑定提供者时，拒绝启用依赖该能力的异步/恢复配置，不静默降级成内存成功。

恢复固定原 execution、release、policy_digest 和 storage_binding；从提供者返回的有效状态/检查点继续，不回放任意 Python 栈。提供者可采用日志重放或直接状态读取，框架不要求其内部格式相同。

## 10. TS-09：耐久任务与公平调度

选择 durable READY/CLAIMED 状态记录加内存 heapq 索引；queue/asyncio.Queue 只承担唤醒和消息传递。进程重启从提供者已提交状态重建队列，不能把内存消息当成可靠接纳证据。

延时任务使用 available_at 最小堆；租户采用加权轮转/deficit round-robin，租户内按优先级和 aging，配额由状态拥有者统一计数。重试、恢复也受配额和 deadline 约束。

## 11. TS-10：执行身份与临界资源

选择 owner_generation、attempt_epoch、revision 组合校验。资源互斥按完整资源键管理，多个资源按固定顺序取得。单实例使用内部协调；多实例通过已绑定提供者的所有权接口取得耐久执行权，不能用本地锁代替跨实例约束。

世代增长、领取和条件完成由提供者原子保证。旧工作者结果被拒绝，未知副作用仍由业务幂等/确认处理。是否允许恢复、并发和自动重试取决于有效配置及能力校验，不因某种介质自行改变业务协议。

## 12. TS-11：异常、fallback 与熔断

选择统一调用包装器和根流程停止闩锁。普通业务 Exception 被拦截；有 fallback 则按协议调用，没有则生成 Output.error，提交根 CIRCUIT_BROKEN 并停止新业务派发。

派发、完成和熔断命令在同一状态拥有者中串行判定。无 fallback 异常不自动重试。已领取的工作标记在途并请求取消，迟到完成仅收敛副作用，不清除停止闩锁。

退出、取消和失联进入恢复路径，不能用 catch BaseException 掩盖。默认日志和测量仍执行，业务熔断不等于停掉诊断通道。

## 13. TS-12：配置化幂等与去重

幂等策略由 idempotency.enabled、key_paths、scope、result_retention 和 replay_policy 配置。算子默认、节点配置及允许的本次覆盖共同形成有效策略；所有恢复尝试沿用原业务操作身份。

选择完整业务键的规范摘要和请求摘要校验，幂等记录与执行结果通过 StateStore 原子提交，提供者以条件写入/唯一身份语义防止重复领取，不要求具体哈希表或文件格式。同键不同输入拒绝，处理中返回原执行标识，已完成复用确认结果。

配置关闭业务幂等时不承诺业务去重，框架内部 command_id 去重仍保留。带副作用且缺少可靠确认的节点禁止自动重试/自动恢复重执，能力不足在配置检查时拒绝。不用普通缓存替代幂等状态。

## 14. TS-13：算子级缓存

缓存行为由 cache.enabled、ttl、max_entries、max_bytes、key_paths、scope 和 single_flight 配置；内置内存缓存实现选择 OrderedDict LRU + TTL + 字节/条目双预算。每项保存 data、来源、到期与数据版本，缓存默认关闭。时间使用 monotonic；淘汰与过期不删除幂等记录。

相同键采用进程内 Future/Event 的 single-flight 协调，取消等待者不取消其他调用共享的填充。跨工作进程通过协调器缓存服务串行申请，或显式使用隔离本地缓存；不宣称跨主机共享。

键包含完整规范输入、声明 context 依赖、租户/权限域、release、契约和数据版本。只缓存合法主方法成功结果，命中重建 meta/options 并采集观测。生成代际防止失效后的陈旧回填；重启默认冷缓存。

## 15. TS-14：数据规范化与摘要

选择带类型标记的规范树编码 + hashlib SHA-256，需要时使用 hmac。区分 bool/int、缺失/null、字符串/数值和列表顺序；Map 键确定排序，浮点禁止非有限值，金额按契约使用整数单位或十进制文本。

编码有明确版本，缓存键和请求摘要记录版本。不能使用 hash()、repr(dict) 或默认 JSON 输出冒充规范协议。摘要不等于脱敏、授权或签名。

## 16. TS-15：默认日志、测量与 trace

选择内置结构化事件模型和 logging，输出到注入的观测接收接口；JSON Lines 作为交换格式，不强制保存为本地文件。log/metrix 代理缺失时自动记录 options.scene、version、releaseId、traceId、operatorName、startedAt、endedAt、duration 和状态；存在代理时补充特殊信息，基础记录不可覆盖。

traceId 使用标准库生成及校验，span 关系由框架字段表达，跨异步调度传递 trace 上下文。测量使用 Counter、固定桶 histogram、sum/count 和时间窗口；traceId 只在明细中保留，不形成无限维度。

诊断可采用有界缓冲和丢弃计数；可靠运营事件通过已绑定 StateStore 耐久提交后才确认。进程失联的实际结束时间未知时保留 null 和 observedEndedAt，不伪造时间。无需外部日志、监控或追踪服务。

## 17. TS-16：运营投影与利用分析

选择持久业务事件 + 消费游标 + event_id 去重集合 + 增量投影，使用索引和提供者的分页/检查点接口查询导出。消费凭据和投影变化原子提交；积压满时背压，不无声丢失关键事件。

静态利用来自编译计划反向索引；动态利用区分逻辑调用、实际执行、重试、cache_hit、幂等复用和业务事实。关键路径采用拓扑动态规划 O(V+E)，实际墙钟路径结合等待和时间事件分析，不把并行耗时相加。

统计与索引均有保留和容量预算，明细通过提供者能力支持分页导出。该选择是可维护的内置分析能力，不承诺无限量即席分析或外部 BI 能力。

## 18. TS-17：定时、重试与时间

选择 heapq 定时堆、datetime/zoneinfo、monotonic 和内置受限周期表达。首版支持一次性时刻、固定间隔和带时区的日/周规则，不依赖 cron 库，也不声称已实现任意 cron 方言。

错过采用 latest，重叠采用 forbid，可显式配置有界补跑。DST 缺失时刻跳过，重复默认 fold=0。触发以计划/时刻/代际去重，记录与接纳意图一起提交。

重试用有上限指数退避和 full jitter，受总 deadline 限制；主异常无 fallback 时直接熔断，不受重试配置放宽。

## 19. TS-18：注册与局部上下文

选择 importlib + inspect + 发布 manifest。每个接入 .py 提供 register，注册到暂存表，统一校验后生效；私有辅助函数可不注册。运行中不扫描任意目录执行代码，不自动安装依赖。

算子用途、契约、来源及直接上下游建反向索引；VibeCoding 通过 Python API/argparse CLI 读取结构化上下文、影响与诊断。不集成模型、AI 代理或工具链，不引入搜索服务作为前提。

## 20. TS-19：介质无关的完整快照与回退

选择内容寻址 manifest、完成标记及版本化发布指针。框架生成并验证代码/配置/契约/计划的摘要；ArtifactStore 保存不可变产物，StateStore 在候选完整可读后原子切换发布指针。上层页面选择介质，框架不固定目录、对象存储或打包系统。

实例固定 release_id、有效策略摘要及 storage_binding。在途版本保留，回退只影响新实例；GC 根据活动发布、在途/恢复实例和保留规则进行引用可达性检查，再调用提供者受控清理。提供者不得自行按 TTL 删除仍被引用的状态或产物。

业务运行环境由宿主显式提供，候选不兼容时拒绝发布。变更状态介质需要显式迁移和一致性验证，不能通过页面切换绑定就让在途实例读取空的新介质。

## 21. TS-20：调试与运维控制

选择 threading.Event/asyncio.Event 控制本次调用的检查点暂停，通过管理命令继续或取消。持有临界资源时禁止无限暂停，进程退出后的恢复依赖业务检查点。

提交、查询、取消、恢复、重跑、未知结果确认、快照检查使用公开 Python API 与标准 argparse CLI。宿主可包装为网络接口，但框架不依赖 Web 服务、网关或身份系统。控制接口包含主体、权限能力、预期 revision、请求去重和审计；不自制密码/JWT 系统。

## 22. TS-21：可用性与能力协商

选择工作者隔离、心跳、失败接管、背压和可恢复状态协议。框架恢复能力依赖 StateStore 的已声明提交与读取保证，多实例接管还依赖其条件写入、所有权和隔离范围。

上层页面在启用策略前显示能力检查结果；宿主启动时再次核验，避免前端校验成为唯一门禁。提供者不可用或提交结果未知时停止确认新耐久工作，并按原 request_id 查询状态；不能自动切换介质重执业务。

框架不捆绑外部组件，也不把提供者自称“高可用”当成证据。进程、主机和介质故障分别演练，质量保证限定为实际绑定和部署通过验证的范围。

## 23. TS-22：接口契约与性能验证

选择 unittest、unittest.mock、random、subprocess 等标准库工具。图算法与 graphlib 对照；状态机使用命令序列和不变量测试。提供内存测试替身和模拟故障提供者，验证 commit 冲突、应答丢失、重复提交、恢复游标及产物缺失。

测试替身只验证框架调用协议，不提供生产耐久性。每个实际介质实现必须通过相同的提供者契约测试和声明故障范围测试。缓存/幂等开关、配置继承、sync/async 切换、策略固定和介质迁移纳入配置矩阵验证。

## 24. 模块、配置与实施顺序

内部模块包括 contracts、paths、registry、compiler、policy、runtime、scheduler、persistence_protocols、recovery、idempotency、cache、events、observability、releases、api/cli。具体介质实现位于宿主或独立适配包，不放入框架核心依赖。

配置分四层：框架默认 → 算子默认 → 编排节点 → 明确允许的本次覆盖。上层页面读取配置 schema，提交版本化配置；框架解析为不可变 EffectiveOperatorPolicy，运行不反复读取页面当前值。

实施顺序：契约/图编译 → 配置解析与提供者接口 → 原子状态协议/幂等/熔断 → 同步异步/恢复 → 缓存/默认采集 → 快照、迁移及能力验收。

## 25. 来源与验证记录

标准库依据：[graphlib](https://docs.python.org/3/library/graphlib.html)、[asyncio](https://docs.python.org/3/library/asyncio-task.html)、[threading](https://docs.python.org/3/library/threading.html)、[collections](https://docs.python.org/3/library/collections.html)、[json](https://docs.python.org/3/library/json.html)、[os](https://docs.python.org/3/library/os.html)。算法组合与持久化接口协议属于本框架设计，引用不代表标准库自动提供这些完整能力。

已在 CPython 3.12.14 临时原型验证：1,000 组随机有向图与标准库对照；20,000 节点长链和深环；自环、重复边、未知节点与打乱输入后的确定性。该记录只支持图算法原型，不是具体介质、集群可用性或平台实现的验证结果。
