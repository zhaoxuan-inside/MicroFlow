# MicroFlow 算法与一致性设计

版本：v1.9  
日期：2026-10-22  
关联：[平台标准设计](platform-standard-design.md)、[功能技术选型](technical-selection.md)。

本文规定框架内部算法、原子状态提交和失败行为，只依赖 Python 标准库。伪代码用于实现设计，不代表这些模块已经实现或完成验证。

## 1. 图表示与编译前置检查

令 V 为当前图节点，E 为边。边 u → v 表示 u 是 v 的前驱，区别于某些库使用的“节点 → 前驱集合”输入格式。编译生成 successors、predecessors、入度、路由元数据和每条边的 source_location。

节点必须先声明。未知端点报 UNKNOWN_NODE，不通过拓扑库自动补节点。重复依赖边合并计数并保留来源诊断，不把重复数据映射规则一同合并；自环报具体边。节点标识使用稳定规范字符串，编译不得依赖 set 的遍历顺序或 Python hash 随机种子。

控制依赖与由数据路径推导的依赖均纳入联合 DAG 判环；未显式表达且不能推导的隐藏业务调用禁止作为编排依赖。每个子图独立编译，子图引用关系另建一张有向图判环。循环节点通过受限迭代语义表达，不向单轮图插入回边。

## 2. Kahn 判环与确定性拓扑顺序

### 2.1 算法

```text
indegree = 每个节点的不同前驱数量
ready = 所有 indegree 为 0 的节点组成的最小堆
order = []

while ready 非空:
    u = pop_min(ready)
    order.append(u)
    for v in successors[u]:
        indegree[v] -= 1
        if indegree[v] == 0:
            push(ready, v)

if len(order) == len(V):
    返回完整 order
else:
    remaining = V - set(order)
    cycle = iterative_three_color_dfs(remaining)
    返回 CYCLE_DETECTED、cycle 及每条边的 source_location
```

最小堆使每一步从全部已就绪节点中选最小标识，因此后继集合以任意顺序访问仍得到相同的最终编译 order。该 order 用于稳定编译，不要求运行时把并行节点依次执行，也不保证受外部时间影响的业务结果确定。

### 2.2 正确性边界与复杂度

无环图的非空剩余图必有入度为零的节点；若队列耗尽但仍有节点，剩余图包含环。剩余图可能含被环阻塞的无环下游，不能直接将全部 remaining 当作环见证。

邻接构建与基础 Kahn 扫描 O(V+E)，确定性最小堆版本 O(E+V log V)，空间 O(V+E)。不要将最小堆版本写成总时间严格 O(V+E)。节点字符串比较成本随标识长度计入实际实现预算。

## 3. 非递归三色 DFS 环定位

WHITE 表示未访问，GRAY 表示位于当前 DFS 路径，BLACK 表示搜索完成。显式栈保存节点及后继迭代位置，path 保存当前路径，position 保存节点在 path 中的下标。

```text
for root in sorted(remaining):
    if color[root] != WHITE: continue
    push_frame(root)
    color[root] = GRAY

    while stack 非空:
        u = 当前栈顶节点
        if u 没有下一个剩余图后继:
            color[u] = BLACK
            pop_frame_and_path(u)
            continue

        v = 下一个后继
        if color[v] == GRAY:
            return path[position[v]:] + [v]
        if color[v] == WHITE:
            color[v] = GRAY
            push_frame_and_path(v)
```

根与后继按稳定顺序访问，保证诊断见证一致。DFS 本身 O(V+E)，后继排序有额外成本。采用显式栈消除解释器递归深度限制。首版不输出所有简单环，因为数量可能指数增长；若未来需要批量圈定互相依赖模块，可增加非递归 SCC 检查，但不阻塞当前图合法性判断。

官方对照：[Python graphlib](https://docs.python.org/3.13/library/graphlib.html)。graphlib 在判环时提供环信息，但其未规定多环时的固定见证选择；平台提供自己的稳定顺序。

## 4. 动态分支、汇合和重复完成事件

编译序列不等于执行状态。运行态为每个节点实例记录控制令牌、必需数据依赖、激活集合和 result_revision。

完成投递使用唯一键 (root_instance, target_invocation, predecessor_invocation, delivery_kind, iteration/item)。同一逻辑前驱只能交付一次最终依赖；重试 attempt 不是新前驱。先插入去重凭据，再修改依赖状态，二者同事务；重复通知不再次消减计数。

路由判定将选择结果和每条输出令牌一并提交。恢复读取已提交结果，不重新计算已生效的分支。嵌套分支必须明确 SKIPPED 传播，汇合等待激活集合完整及其策略满足，不以“暂时没到其他分支”认定其他分支被跳过。

all_active_success 需要全部激活分支成功；任一必需输入来自跳过节点且无备用源则失败。any_success 先选出有提交序号的胜出结果，再按策略等待其他业务收敛；未显式拆成独立根流程时，父流程不能遗留未跟踪副作用就标为完全成功。

## 5. 路径 AST 与类型检查

读取器扫描 Field("order")、Field("items")、Index(0) 等 token，拒绝非法转义、负下标、通配符、函数调用及属性执行。索引只作用于列表，字段只作用于 Map。特殊键使用 JSON 字符串语法解析，不把字符串交给 eval。

结果为 PRESENT(value) 或 MISSING；null 是 PRESENT(null)。required 在转换前判断缺失；默认值只替代 MISSING；schema 校验显式允许的转换结果。每个 output.data 在独立容器中构造，全量验证后一次提交。

schema 静态检查分成 PROVED_COMPATIBLE、PROVED_INCOMPATIBLE、UNKNOWN。未知 union、复杂条件或动态扩展不能当成已证明兼容。运行时实际值必须再次验证。

## 6. 状态协调与根流程熔断

所有派发、完成、恢复、幂等领取和熔断都通过执行分区的协调器命令序列处理；多实例的权威顺序由提供者条件提交及拥有权约束保证。工作者只执行业务并回传结果，不能写权威状态。每个命令包含 command_id、expected_revision、owner_generation 和 attempt_epoch。

```text
handle(command):
    核验调用主体、命令去重和执行身份
    在短状态临界区读取当前 revision
    校验全部前置条件
    构造完整 StateBatch
    调用 StateStore.commit 原子提交，取得提供者的耐久确认
    应用已提交变化，推进 revision
    发布完成通知 / 派发意图
    返回提交结果
```

StateBatch 是一次原子状态变化的载体，可同时包含 Output、根停止闩锁、幂等结果、依赖令牌、任务和可靠事件。提交失败不得先发布内存成功；提交结果未知时通过 get_commit(command_id) 查询，重复请求返回同一批次结果。具体介质是否刷盘或组提交属于提供者内部实现，框架不据此提前应答。

派发命令核验根闩锁，在同一批次记录 CLAIMED 和执行身份。无 fallback 异常命令写节点 Output.error、根首错、STOPPING/CIRCUIT_BROKEN 与采集意图。其后所有业务派发被拒绝；此前领取的工作属于在途并请求取消。

迟到完成只能记录和收敛真实副作用，不能清除闩锁或推进后继。首错按提交序号确定。普通日志、测量和受控清理不属于被禁止的业务派发。该串行化边界不依赖数据库行锁或外部原子操作。

## 7. 持久化接口与提交能力

### 7.1 上层绑定与能力检查

上层页面读取提供者描述和配置 schema，选择 provider_id、binding_id、namespace 及参数；宿主验证并创建介质实现，再以对象接口注入框架。框架只使用 PersistenceProvider/StateStore/ArtifactStore，不依赖页面保持在线，也不根据页面输入动态导入任意代码。

capabilities 至少声明 atomic_batch、conditional_write、request_deduplication、durable_ack、consistent_recovery；多实例运行另声明 ownership/fencing 及其作用范围。配置请求的保证超出能力时拒绝生效，不能自动替换为文件或内存介质。

### 7.2 原子批次

```text
校验 EffectiveOperatorPolicy 与 provider capabilities
构造完整 StateBatch，绑定 request_id 与摘要
StateStore.commit(batch, expected_revision, request_id, owner_token)
    COMMITTED -> 发布可见结果和派发意图
    CONFLICT -> 重新读取状态并重新判定，不重复外部动作
    UNKNOWN -> get_commit(request_id)，不能假定未提交
    FAILED -> 明确失败，保留诊断
```

同一 request_id 和同一摘要重复提交得到原结果；不同摘要冲突。提交回执包含 commit_id、revision 和提供者保证范围。禁止将一批变化逐项 set 后声称原子；提供者必须原子提交或明确不支持。

### 7.3 恢复与产物

StateStore 返回一致的 RecoveryView，包括 revision、执行/幂等/任务/事件状态、检查点及绑定版本。内部实现可以使用日志、快照或其他方式，框架不固定恢复格式。ArtifactStore 在状态引用发布前确认不可变对象已可读取并通过摘要检查；失败不发布引用。

在途实例固定 storage_binding_id、namespace、binding_revision 和 policy_digest，不能跟随页面的当前选择切换介质。介质迁移单独进行停写/切点、拷贝、校验和接管协议；旧引用保留到恢复不再需要。

## 8. 幂等与恢复判定

```text
在状态拥有者处理 claim_operation(key, request_digest):
    无记录 -> 创建 IN_PROGRESS，绑定本次执行身份，持久提交后允许业务开始
    同键不同摘要 -> IDEMPOTENCY_CONFLICT
    同键处理中 -> 返回原执行标识，不再派发副作用
    同键成功/失败 -> 返回已确认结果
    同键未知 -> IN_DOUBT，等待确认
```

幂等状态通过 StateStore 条件提交与恢复；内存哈希索引只是可重建的加速层。缓存淘汰不影响该索引。结果清理后保留业务操作墓碑或明确的拒绝旧请求窗口，禁止自动把旧操作当成新业务。

外部动作发生与框架状态提交之间存在故障窗口：进程可能在外部动作成功后、完成记录前退出。框架根据业务声明的幂等/查询能力确认，无法确认则 IN_DOUBT。提供者的原子批次不能覆盖任意外部资源，禁止因此承诺全局恰好一次。

恢复生成新的持久 owner_generation，过期工作者消息不能覆盖新执行状态。重启先恢复持久任务和幂等，再决定继续哪些尝试，不把日志里“未完成”一律当作“未执行”。

## 9. LRU、TTL 与 single-flight

缓存用 OrderedDict 保存条目，命中移到尾部，超预算从头部淘汰；受锁保护的 LRU 操作平均 O(1)。TTL 使用 monotonic 截止，内存缓存重启清空，不将上次进程的单调时钟值跨重启使用。

```text
权限与接纳约束 -> 幂等核验 -> 规范缓存键
命中有效条目 -> 复制 data，重建本次 meta/观测
未命中 -> 按 key 共享一个受控填充 Future
填充者执行主方法 -> 校验 -> 提交业务结果
    若仍是原数据代际，尽力放入缓存
等待者按自身预算等待，不取消共享填充
```

填充成功只保存 data。异常、失败、fallback 及写入操作不缓存。旧代际填充结果不能覆盖新代际；同一状态拥有者维护跨工作者协调，不假定进程本地锁能覆盖其他机器。

## 10. 调度、超时和分析

耐久任务记录和 READY/CLAIMED 状态通过 StateStore 提交，内存就绪堆只是可重建索引。延迟堆按 available_at 排序；同一运行周期使用 monotonic 管理等待，持久时间采用 UTC。重启根据 UTC 和执行策略重新计算，不能直接恢复旧 monotonic 值。

重试使用 full jitter：random(0, min(cap, base * 2^retry_index))，max_attempts 包含首次执行且默认 1。deadline 限制排队、执行、fallback 和重试。无 fallback 的主异常直接熔断，不进入重试。

静态关键路径使用拓扑动态规划 D[v] = weight[v] + max(D[u])，O(V+E)。实际端到端时间结合等待和调度记录，不能直接加总并行耗时。固定桶直方图只提供相应桶精度，不能声称获得精确 p99。

运营事件按 event_id 去重，消费游标、去重凭据与投影变化同批次提交。采集和内置分析有容量边界，通过提供者的分页游标和时间窗查询，避免每次分析加载全部历史。

## 11. 介质无关的完整快照与回退

构造候选 manifest -> ArtifactStore 保存并验证不可变产物 -> 校验注册/契约/图/有效策略与介质能力 -> StateStore 原子提交活动发布指针 -> 新调用使用目标 release。

根调用及其子图、重试和恢复固定 release_id、policy_digest 及 storage_binding。回退不改在途实例。产物 GC 在引用可达性检查后调用提供者删除，具体路径或对象标识由 ArtifactStore 定义。

页面变更介质配置只创建新 binding_revision，不自动迁移旧实例。删除绑定时仍有执行、幂等、事件或快照引用则拒绝。宿主无法提供目标版本的介质与环境能力时拒绝发布/恢复，不能隐式创建另一种介质。

## 12. 配置解析、验证记录与能力边界

有效策略按“框架默认 → 算子默认 → 编排节点 → 允许的本次覆盖”确定性合并。Map 逐字段合并，数组整体替换，enabled=false 必须保留，未设置与 null 分开。未知字段拒绝，最终结果校验后深度冻结并计算 policy_digest。

同步/异步、缓存、幂等、持久化及恢复以有效策略执行。恢复不重新读取页面最新策略。改变可能影响数据含义的策略需新配置/快照版本；显式运行控制命令不伪装为任意配置热改。

前一轮已在 CPython 3.12.14 临时图算法原型通过：1,000 组随机图对照、确定性及 20,000 节点长链/深环检查。该记录不证明持久化提供者或新配置协议已实现。

后续验证配置继承/开关、无提供者、能力不足、重复 commit、未知提交、恢复视图、绑定迁移与产物缺失；实际介质另执行其声明的进程/主机/存储故障验收。框架零外部组件依赖与宿主可提供具体介质是不同层次的要求。

## 13. 首批本地执行接口与限制

`LocalRuntime` 是显式 sync/ephemeral 的演练执行器，按确定性拓扑顺序串行推进静态 DAG、子图和 all_active_success 汇合。所有无前驱节点均为静态入口；图中独立根节点不因未被输出引用而自动视为不可达或删除。条件、集合、循环和信号等待的控制令牌执行另行实现。

`run` 同步等待完成，`run_async` 提供同一流程的协程等待；后者不代表 execution_mode=async 的耐久后台接纳。同步业务函数在线程执行，协程函数直接等待，父流程不占用工作线程等子流程。每次运行使用独立停止闩锁、取消信号和结果集合。出现无 fallback 的主异常立即停止该根流程后续业务，失败的暂存 data 不发布。

本地执行器在预检查中拒绝耐久、后台异步、恢复、业务幂等、结果缓存、自动重试、资源互斥及动态节点请求，避免静默忽略策略。方法超时目前只在检查点及返回后判断，不能中断线程或提供硬时间隔离；生产执行池、在途收敛和故障恢复仍按前述协议实现。当前实现不替代平台的生产超时要求。

编译器先检查全部映射目标重叠，再读取来源；required 判断早于 default，默认值不掩盖必需来源缺失。静态契约证明只接受能够覆盖全部目标约束的子集；可判定的顶层类型冲突拒绝，无法证明的约束生成 UNKNOWN 警告，执行时仍校验实际值。特殊字段使用相邻括号形式 `a["b.c"]`，点后必须是普通字段名，不接受 `a.["b.c"]`。

调用覆盖白名单使用字段路径，如 `cache.enabled`；允许修改该字段不隐含允许修改 `cache.ttl`。未绑定提供者即拒绝 durable 策略。候选快照保存 manifest 和不可变源码字节，核验摘要及源码集合；这只构成候选构建与完整性检查，尚未构成 ArtifactStore 耐久发布、迁移或回退验收。

## 14. 状态提交协议切片（2026-10-22）

提供者协议版本为 `microflow-persistence-v1`。宿主显式注入可信提供者对象，`validate_provider` 检查描述版本、配置的 MicroFlow Schema v1、逻辑绑定/命名空间/绑定修订/配置摘要、接口完整性及能力一致性；不按字符串自动加载提供者，也不以结构检查替代真实介质验收。

协调器要求原子批次、条件写入及请求去重能力。`decide(view)` 只进行纯状态判定，不执行外部动作；事务通过 StateBatch 一次提交 puts/deletes、JSON 返回值和 command_digest。显式 request_id 必须同时提交完整控制命令摘要，摘要包含 expected_revision 等影响命令含义的字段。重复请求在重新判定之前读取原回执，摘要不同报 REQUEST_CONFLICT，摘要相同返回首次结果的独立副本。明确 revision 冲突才可重新执行纯判定；显式控制请求冲突返回调用者处理。

提交异常及 UNKNOWN 均查询原 request_id；结果仍未知或查询失败时保留写入闸门，后续事务先解决该原请求，不能换新身份跳过。get_commit 返回 NOT_COMMITTED 必须是权威否定，保证该请求不会在没有新提交时迟到成功；仅查询不到在途请求时应返回 UNKNOWN。确认回执须匹配批次摘要、命令和返回值；耐久模式还要求回执自身 durable=True。完整权威命令中的 attempt_epoch、调度意图、幂等/闩锁及可靠事件仍由后续状态机集成。

`RecoveryView` 固定 revision、binding_revision 和只读 records。query 首次创建一致快照，续页使用原快照，支持同一游标重复读取；不同前缀、外来或已关闭游标明确拒绝。调用者持有任一有效续页游标后，须调用 close_cursor 释放整份快照，即使已读取最后一页；不把失效游标静默改为当前状态查询。

`microflow.testing.MemoryStateStore` 只用于测试：记录数、回执保留数、同时查询快照数和检查点数均有上限，容量耗尽时在写入前拒绝，不淘汰未过保留协议的回执。拥有者令牌包含绑定修订及代际；释放/重新领取后拒绝旧令牌。检查点固定调用前的完整视图并以请求身份去重。该替身没有进程存活外持久性、租约到期/自动接管或介质确认，不能用作耐久运行提供者；LocalRuntime 尚未接入状态协调协议。

## 15. 策略描述与编译定位协议（2026-10-22）

### 15.1 策略字段与恢复边界

`describe_policy()` 和 `microflow policy-schema` 返回 `microflow-policy-schema-v1`：包含 schema、完整默认值和 merge 规则。此描述使用 object、boolean、integer、string、array、path、duration 类型；它是策略专用词汇，不冒充 JSON Schema 或业务 MicroFlow Schema v1。object 只接受声明字段，配置层可以只提供部分字段；整数预算最小为 1；path 使用框架字段/索引路径语法；duration 接受正有限数值秒或带 ms/s/m/h/d 单位的正数文本。业务 schema 的单类型限制保持原有定义。

框架默认值 → 平台/场景 → 算子默认 → 节点配置 → 经白名单批准的调用覆盖，逐层校验后合并；对象递归合并，数组整体替换，缺失继承。false、空数组正常保留，所有字段拒绝 null，零值按字段最小值拒绝；后层覆盖不能使前层非法类型或未知字段合法。运行组合再检查能力与安全约束。默认值及生效策略只读；描述 API 返回独立 JSON 副本。

顶层 `checkpoint_policy` 默认 `operator`，允许 `operator` / `explicit`：前者要求耐久调度在算子终态边界形成可恢复检查点；后者只在显式控制命令形成额外检查点，不跳过任何权威状态、结果或调度意图的原子提交，也不授权重放结果未知的外部副作用。检查点请求含 expected_revision、稳定 request_id 和绑定/拥有者约束；中间外部副作用能否确认仍由 T09 能力协议决定。`recovery.enabled=False` 时不启用恢复，checkpoint_policy 保留在冻结策略中但不触发自动检查点。现有 LocalRuntime 拒绝恢复配置；上述调度行为仍须 T08/T09 集成测试。

### 15.2 来源与诊断

Graph.edge_sources 以 (前驱, 后继) 为键，保存不可变来源列表：source_file、flow_id、node_id、path、kind。path 以项目配置的 `flows[index]` 起始，字段使用 JSON 双引号转义，指向 depends_on 项、inputs 映射的 from、condition/until、路由 target/default、map.items 或子图 flow 字段。重复依赖只合并图中的边，保留各个声明来源。表达式内多个来源共享所在表达式的字段位置；本批不提供逐 AST 操作数或 JSON 文本行列定位。

环诊断保留确定性 cycle 和每条见证边的 source_locations，未知端点也带具体边及来源；子图引用环使用相同协议。错误诊断附 flow_id/node_id/source_file/hint，已知类型冲突给出 expected/actual 类型；不包含实际业务值。编译失败尚无有效发布身份，release_id 为空；成功编译的 UNKNOWN 警告带固定 release_id，继续要求运行时值校验。诊断文件路径与边来源不进入 manifest 身份摘要，移动项目配置文件不会单独改变发布身份。

动态节点声明须符合节点种类的字段集合；路由分支是 when/target 对象且目标为非空节点 id，默认目标为节点 id 或 null。条件与 loop.until 的输入来源纳入依赖与静态路径校验；map.items 已知契约必须为 array；wait 输出可按 result_schema 静态检查。完整动态输入输出组合、展开容量和运行控制仍由 T11 实现；编译通过不代表 LocalRuntime 已支持动态执行。

## 16. 静态 DAG 状态命令切片（2026-10-22）

`microflow.scheduling.ExecutionCommands` 是可信宿主调用的原子命令层，不执行业务方法或建立后台任务服务。生产模式要求 durable Coordinator；宿主仍须先完成提供者能力核验、发布产物耐久保存/引用保护以及工作者权限与执行集成，不能单凭命令层宣称完整耐久运行已实现。测试用 `protocol_test=True` 显式允许内存协议替身，返回结果带 protocol_test=True、durability=ephemeral；此模式不作为生产异步 ephemeral 的支持入口。LocalRuntime 保持现有同步演练边界。

accept 固定 release_id、flow_id、原始输入、effective policy 及摘要、完整 StorageBinding；节点初始化为无前驱 READY 或有前驱 WAITING。执行身份由绑定与接纳请求身份派生，接纳记录和稳定 event-intent 同批提交；返回 status=ACCEPTED、execution_status 为当前实际状态，接纳不能解释为节点成功。空图可在该提交中生成流程结果。输入不合法、超容量或策略不支持时不接纳。所有命令 request_id 在同一提供者分区内唯一，摘要包含完整载荷、绑定、发布身份及 expected_revision。

claim 在协调器临界区检查根停止闩锁、READY、分区领取容量与当前节点策略的 concurrency（同分区相同算子 ref 的在途上限），验证映射输入后原子生成 CLAIMED。领取回执固定节点输入、算子 ref、policy、owner 代际与绑定、attempt_epoch 和 worker_id。输入非法则原子失败并停止流程，不发放工作许可。接纳/节点总量/领取容量有显式上限；这不是完整租户公平调度或 CPU/I/O/协程分池。

complete 只接受当前 CLAIMED 身份与合法终态；旧拥有者、错误 worker/release/binding/attempt_epoch 或已经完成的尝试拒绝。成功 data 需输出契约校验，之后才将该结果和后继 READY 放进同一 StateBatch。主异常无法处理时使用 FAILED + unhandled_exception + UNHANDLED_OPERATOR_EXCEPTION，根首错按命令提交顺序保留；False 对应 FAILED/OPERATOR_REJECTED，不伪造 fallback 恢复。命令层只接收可信执行器的报告，不代替实际 SDK 方法及 fallback 调用。

任一失败、取消或 IN_DOUBT 设置根 stop，未领取节点变为 SKIPPED，已领取节点标记 cancel_requested。尚有 CLAIMED 时根为 STOPPING，不伪造已经取消或终态；收到在途结果后收敛为 FAILED/CANCELLED/IN_DOUBT。迟到成功保存节点结果以供核验，但不清除首错、不重激活后继，根不转为成功。正常根完成需所有节点成功且流程输出通过契约。未知副作用不通过 cancel 转成已知失败，不自动重新领取。

重复完成命令返回原回执，不能重复更新结果或产生新的事件意图；重复领取返回相同活动身份，若身份已结束或拥有者变更则拒绝再发放。工作者/传输仍必须防止同一活动领取回执被重复执行业务，外部副作用确认与去重依赖 T09；命令去重不等于外部动作恰好一次。提交 UNKNOWN 通过原请求查询并阻断后续命令；不提前返回接纳或领取许可。

query/ready 从一致视图重建当前状态，返回只读数据；进程内唤醒不是权威。协调器重新创建可重读 READY，但旧 CLAIMED 不自动重派，旧拥有者完成消息拒绝，后续需 T09 的恢复确认协议。测试只在同一个内存存储对象上重建命令对象，不提供崩溃存活性证据。

事件记录目前是含稳定 event_id 的 PENDING 意图，与权威变化原子保存；未实现投递、消费凭据或保留清理。工作池/等待、预算及业务幂等的当前切片分别见 §17～19。checkpoint_policy、子图与动态执行、缓存/重试/资源键以及发布产物引用仍按 T08～T14 接入。当前命令预检拒绝写入型主方法及 fallback、动态节点/子图和尚未集成的缓存/重试/资源键，避免授予不能安全恢复的执行权。

## 17. 工作执行和非阻塞等待（2026-10-22）

`microflow.ScheduledRuntime` 接受一个已绑定发布的 ExecutionCommands，在单个事件循环内运行；使用 `async with` 管理生命周期。submit 只返回命令层确认的接纳，run 为 submit + wait，wait 返回只读的实际执行终态（含节点状态和标准 output）。工作者执行 SDK 六参数方法，支持普通函数及协程；复用 LocalRuntime 的输入/输出契约、True/False、异常/fallback、基础采集与特殊代理逻辑，不另建业务执行语义。节点 invocationId、attemptId、父实例身份与已提交任务稳定关联。

服务最多持有 workers 个执行任务，同步业务/同步代理进入独立 ThreadPoolExecutor，协程直接等待；状态命令使用宿主线程池执行 I/O，与业务容量分开。根等待和依赖等待不占业务线程。当前没有 CPU 进程池、跨进程执行、外部工作者传输或租户公平调度；长时间不返回的同步方法无法硬中断。

接纳调用在服务所有的任务中完成，并在返回前登记调度；调用方取消 submit 的等待，不取消正在确认的接纳。接纳未确认时不发放任务。run/wait 的 timeout 只结束该次等待，抛出 TimeoutError；取消等待仅取消轮询协程，服务所有的 pump、业务任务和状态提交继续执行。服务需在独立于请求处理器的宿主生命周期内存活；销毁事件循环或进程不属于普通客户端断连。本批内存替身没有进程存活外保证。

显式 cancel 提交取消请求，由 pump 为在途任务设置线程安全的协作取消事件；无法中断的同步方法未返回前保持 CLAIMED/STOPPING，不释放执行容量、不并发重派。当前预算状态与协作检查见 §18；调度执行保留方法实际返回的迟到结果，LocalRuntime 继续采用返回后软检查。debug.pause 明确拒绝，业务检查点和硬时间隔离尚未接入。已经观察到且无 fallback 的主异常先进入停止闩锁，不用其后检查覆盖首错；若计时器已经先提交停止，后来的异常仍保留在节点结果中。

工作者得到业务结果后，先通过 complete 原子确认结果/闩锁/后继和事件意图，再执行可选 log/metrix。等待接口还检查本服务未确认的完成提交，不能仅凭提前可见的终态视图代替完成回执；确认后终态可以先于慢采集返回。采集失败保持基础记录并不重跑业务。records 是有界、保留最新条目的内存诊断环，非可靠事件归档；可靠采集及消费仍在 T10。

完成提交失败/未知、状态查询失败或发现没有本服务归属的旧 CLAIMED 时，停住该执行，不重新执行业务。wait 抛 EXECUTION_BLOCKED，blocked 提供只读 execution_id → 诊断码；持久状态仍保留实际 CLAIMED 等信息，交给宿主确认/恢复。不会为了使等待结束而虚构 FAILED、成功或已取消。重复接纳复用原执行且不会再次执行已完成节点。

close 停止新接纳，等正在确认的接纳和已登记工作排空，再关闭线程池；不通过取消协程来遗弃活线程。遇到需宿主介入的 blocked 执行不自动重派，关闭后仍可查看 blocked 和诊断记录。调用方应保证宿主关闭预算，卡住不返回的业务/采集仍会延长排空；后续分池、时间隔离与恢复协议解决这些限制。

## 18. 队列、尝试与根预算状态（2026-10-22）

执行状态协议升级为 `microflow-execution-state-v2`。run 固定 accepted_at、observed_at、deadline_at；node 保存 ready_at、queue_deadline_at、claimed_at、attempt_deadline_at、finished_at 和 timeout_code，单位为预算时钟的数值秒。领取不是物理业务开始：不伪造业务 startedAt；实际开始/结束仍由 SDK 生命周期记录。旧 v1 不含足够的预算证据，读取时明确报 UNSUPPORTED_EXECUTION_STATE，保持原记录，不能自动以重启时刻重建。真实介质迁移仍须 T12 协议。

queue 从进入 READY 开始，依赖 WAITING 不消耗 queue；后继实际就绪时固定新的 ready_at/queue_deadline_at。queue 到期记 FAILED/QUEUE_TIMEOUT、phase=queue、effectStatus=not_started、attempt_epoch=0、claimed_at=null，停止该根后续派发；不产生业务开始记录。attempt 从领取授权开始，包含状态回执/执行交接及主方法/fallback 的全部时间，是保守的总尝试预算。当前根 deadline 是接纳时各节点有效 deadline 的最小值，后继激活不延长根预算；静态子图尚未接入。

到期条件为 now >= deadline。expire 在协调器命令中读取可信时间、核对固定绑定和状态修订，将到期事实、停止闩锁和事件意图原子提交。没有到期预算则报 BUDGET_NOT_EXPIRED，不消耗请求身份；相同已提交计时器命令复用原回执。一次观察的多个到期预算按绝对时刻排序，同刻依次为根 deadline、队列、尝试，再按节点 id 排序；后续观察不覆盖既有根首错。工作服务用执行身份和下一到期时刻构造稳定计时器请求，不能用一个永久请求身份处理所有未来预算。

claim 自行检查预算，避免依赖及时轮询；过期时提交停止状态并返回状态摘要，不发放任务。重发已过期领取回执也不得再授予业务派发。complete 在发布结果前再次检查预算，计时器未及时运行也不能把越界成功变成根成功。已观察到的无 fallback 致命异常先保留；如果之前已有计时器/取消/其他分支首错，沿用先提交的停止原因。cancel 也先观察已到期预算，不能用后来取消掩盖超时事实。

在途 attempt 或根 deadline 到期只写 timeout_code/cancel_requested 并停止新派发；节点继续 CLAIMED，根保持 STOPPING，finished_at 仍为空，占用领取和工作容量。SDK 方法入口和 fallback 入口检查协作事件及预算；不能在已耗尽尝试/根预算后开始 fallback。线程和协程不会被强行终止，不会因超时自动并发重试。返回后的真实成功 data 仍写入节点结果用于副作用核验，但首错和停止闩锁保留，不发布后继 READY，根按失败或未知结果收敛。主动协作取消则记录实际取消结果。硬时间隔离、外部副作用核验及安全恢复仍在 T09。

默认 BudgetClock 以墙钟为可持久比较的起点，每次读取结合单调经过时间并保留新的时间锚；进程内墙钟回拨不会延长预算，墙钟前跳保留为更早到期。ExecutionCommands 可注入相同时间域的时钟供测试/宿主使用，时间必须非负有限且不能落后于已持久 observed_at；否则报 INVALID_CLOCK/CLOCK_REGRESSION，拒绝写入而不重置预算。时间在协调器串行判定中采样，revision 重判可重新观察时间，不执行任何业务动作；命令重放复用原回执，不重新计算时间。跨主机时钟精度、重启后回拨与校时纪律须由真实部署核验；不据本机替身宣称时钟故障验收通过。

ScheduledRuntime 的 pump 在没有空闲业务槽时也观察已登记执行的下一到期预算；确认计时器提交后再应用取消信号。轮询和忙协程可能使观察延迟，领取/完成边界检查保持结果安全，但不构成硬响应时间保证。wait_timeout 继续只结束调用者等待，不能替代上述业务预算。LocalRuntime 未改变为耐久调度器，继续保留其显式同步演练与软超时限制。

## 19. 业务身份账本与失联隔离（2026-10-22）

本节实现 T09 的首个切片，继续使用执行状态 v2，新增 `microflow-business-operation-v1` 记录。v2 新增的 operation 引用和冻结 scope 为可选字段，旧的未启用幂等执行仍可读取；此前运行命令不允许接纳启用幂等的节点，因而不把缺失 scope 的旧状态推测为新的业务身份。

### 19.1 身份与接纳绑定

宿主通过 `OperationScope(tenant, domain, operation, semantic_version)` 为算子 ref 注入可信业务范围，由 ExecutionCommands.operation_scopes 接收。启用 idempotency 的节点必须有对应绑定，接纳时复制到该节点的固定 policy 记录；后续宿主对象换配置不重新解释在途业务身份。该绑定不从调用方输入中的 tenant 或运行时 trace 推导；具体鉴权和作用域配置发布仍属于宿主/T14。

policy.idempotency.key_paths 使用 `input.<field>` 指向已经映射并通过契约的算子输入。缺失或 null 键明确失败，context/trace/attempt 不能直接作为 key_paths。业务身份摘要覆盖 tenant/domain/operation 和规范编码的复合键值，区分 bool/int；不含 release_id、traceId、attemptId 或 semantic_version。请求摘要覆盖完整算子输入与 semantic_version；不支持裁剪输入。发布更换不建立新业务操作，业务语义版本改变则同键冲突，不能借升级重复已发生操作。键路径选择必须表达真正稳定的业务操作键；核心不能从字段名称证明业务唯一性。

### 19.2 原子领取、等待与结果复用

operation/<identity_hash> 保存在 StateStore 权威分区，与缓存独立。首次领取原子创建 IN_PROGRESS、请求摘要、origin（原 release/执行/节点/拥有者/attempt_epoch）和 CLAIMED，再向工作者返回许可；批次失败或未知不发放新的执行权。主结果提交时，operation 的 SUCCEEDED/FAILED/IN_DOUBT 与节点结果、后继就绪、根停止状态和事件意图同批确认。

同键异摘要使新的逻辑节点产生 IDEMPOTENCY_CONFLICT，既有记录不修改，不执行业务。同键处理中将新逻辑节点置为 WAITING_OPERATION，不占业务领取槽；该节点仍受原 queue 和根 deadline 约束。工作服务从一致视图查询 operation，在其确认后原子 refresh：成功复用 data，确认失败复用原失败，未知保持 IN_DOUBT；不调用主方法或 fallback。取消/排队超时一个等待者不取消原操作。原操作即使所属根因其他原因失败，其实际确认的业务成功仍可用于后续同键核验。

跨发布复用原结果时再次校验新目标输出 schema，不兼容返回 IDEMPOTENCY_RESULT_INCOMPATIBLE，不能为了适配契约执行第二次业务。复用节点拥有本次 trace/invocation 元数据，resolution=idempotency，附 sourceReleaseId/sourceInvocationId；原业务 origin 不变。每个逻辑调用产生自己的事件意图，物理尝试仍只有原归属；完整逻辑/物理采集投影在 T10。

result_retention 控制确认结果供新的逻辑节点复用的截止时间；到期报 IDEMPOTENCY_RESULT_EXPIRED 并继续保留原键/摘要，不能把旧操作变为新业务。当前不自动清除 operation、原执行或命令回执中的数据，完整保留清理/压缩及墓碑迁移仍待 T12/T16；不得将此字段解释为已经实现敏感数据到期擦除。IN_PROGRESS/IN_DOUBT 不采用结果到期自动释放身份。存储容量不足时原子拒绝，不通过 LRU/TTL 淘汰解除业务去重。

### 19.3 已失联尝试的保守隔离

业务记录也保存 observed_at；新逻辑调用的预算时间落后于该业务事实观察时，报 CLOCK_REGRESSION，不借新执行的较早时钟延长旧结果保留期。该检查不代替跨主机校时验证。

`mark_in_doubt(execution_id, node_id, request_id, expected_revision)` 只接受 CLAIMED 且 owner 与当前拥有者不同的旧尝试。当前拥有者不能用该命令把仍属自己的活任务宣布为失联；生产调用还要求提供者声明 ownership_fencing，部署作用范围及实际租约证明继续依赖 D03。协议测试使用显式内存代际模型，不作为跨进程接管证明。

该命令只承认无法确认：节点与原 operation 同批变为 IN_DOUBT，根停止派发，未开始节点跳过；仍有其他 CLAIMED 则保持 STOPPING，收敛后根为 IN_DOUBT。保留原 owner/attempt_epoch、claimed_at；finished_at=null，observed_ended_at 只表示本次观察时刻。旧工作者完成消息被隔离，后续同键请求得到未知状态，不获得第二个执行权。

mark_in_doubt 不确认外部副作用、不解除闩锁或授权重跑；确认协议见 §20。自然幂等/查询能力的真实验证、生产授权与确认提供者、安全重执、资源租约和检查点仍待后续 T09/T14。写入型主方法及 fallback 继续拒绝；不能仅靠开启本节的账本就放开真实写入或宣称端到端恰好一次。权威记录缺失/损坏或服务不可用时停住业务身份路径，不降级为无幂等执行。

## 20. 未知业务结果的授权证据确认协议

`microflow.confirmation.ConfirmationService` 通过宿主注入的 ConfirmationAuthorizer 和 ConfirmationVerifier 确认 IN_DOUBT 结果。缺失提供者、拒绝授权、不可用查询或未验证证据均拒绝；核心不提供默认放行器。当前仅提供同步库接口，没有对外控制端点，也不接通写入型算子。

ConfirmationEvidence 固定业务身份、完整请求摘要、原尝试来源摘要、证据编号/来源和 SUCCEEDED/FAILED 结果；成功 data 必须满足原发布输出契约，失败不得带成功 data。查无结果、超时、取消和 UNKNOWN 均不能作为确认失败。服务从原执行的冻结 scope、输入和键路径重建业务身份，并核对发布、绑定、拥有者和 attempt_epoch，防止替换租户范围或确认另一次尝试。

授权目标包含 action、业务身份与请求摘要、原尝试、绑定、冻结 scope、证据提案摘要、request_id 和 expected_revision。宿主接收不透明 principal 并返回绑定目标摘要的限时 ConfirmationGrant；核心只保存主体和授权决定标识，不保存会话凭据。授权到期使用与命令一致的时钟域；每次调用（包括重复请求）重新授权。已发放授权在到期前有效，宿主须决定有效期与撤销粒度，不能把后续请求的撤销检查解释为在途授权即时撤销。

服务先在协调器内执行不写状态的探测：检查原回执、CAS 修订、IN_DOUBT 状态、停止闩锁和输出契约；只有新确认才在协调器锁外调用只读证据查询器。查询器必须明确返回 True，不得执行业务写入或重试。随后再次在事务中检查修订、目标、时钟及授权有效期，避免查询期间状态变化。稳定命令摘要绑定主体和证据，新的授权决定标识不改变同主体重放身份；不同主体不能复用原请求。回执已知时仍须授权，但不重复外部查询或审计；UNKNOWN 继续阻断并查询原命令，不另发业务动作。

确认将节点结果、业务账本、事件意图和 `microflow-confirmation-audit-v1` 审计同批提交。审计包含业务/来源/证据摘要、证据编号与来源、主体、授权决定与目标摘要/到期时间、原修订及确认时刻。容量或提交失败不得留下部分结果；应答丢失通过原请求恢复回执。审计记录证据引用和摘要，宿主负责原始证据保存、查询事实的最终性与访问权限。

确认保留根停止闩锁和已经跳过的后继，不恢复原执行、不创建新尝试、不补造物理结束时间。新逻辑调用可在原策略的结果保留期内复用已确认结果，保留期从确认时刻开始；身份、原执行、审计及回执不按该 TTL 自动删除。当前内存替身测试只验证协议原子性、授权拒绝和竞态；真实介质、生产授权策略、外部查询提供者和故障域仍依赖 D03/D04。

资源租约协议由 `microflow.resources` 提供宿主注入边界。`LeaseRequest` 要求资源键唯一并按字典序排列；多资源始终按同一顺序申请，避免由框架产生锁顺序反转。`ResourceLease` 固定 lease_id、资源集合、owner_id、执行世代和到期时刻；续租和释放必须提交当前完整令牌，过期或旧世代一律 `LEASE_FENCED`。内存实现只用于协议测试，在下一次操作观察到到期，不代表跨进程租约或外部资源锁已经实现。租约获得/续租/释放仍须与业务状态和主机实际资源适配器集成，不能单独阻止过期执行者对外部系统写入。

## 21. 可靠业务事件意图协议

`microflow.events.EventIntent` 表示与权威状态一起保存的待投递业务事件。事件固定 `event_id`、类型/schema、aggregate_key、连续 sequence、业务 payload、执行/发布来源及 occurred/recorded 时间；payload 经过严格 JSON 校验和冻结。`content_digest` 覆盖事件事实但不覆盖 recorded_at，因重试投递不能改变业务内容。

`EventStore.append` 按 event_id 去重：同摘要返回原事件，异摘要拒绝；同一聚合的 sequence 必须连续，避免乱序投影。容量不足在保存前拒绝，不改变已有事件。`acknowledge` 必须提交事件摘要后才把 PENDING 变为 DELIVERED；投递器可安全重复调用。`pending(limit)` 返回有界待投递意图，消费端仍须按 event_id 去重，不能把投递回执当成业务事实。

当前 `MemoryEventStore` 只用于协议测试，未接入 StateBatch、外部消息系统、消费凭据或保留清理。生产事件提供者需把意图和状态变化原子保存，并定义重试、背压、迟到事件重算及权限；平台不承诺全局顺序。

调度命令的 `_batch` 已使用同一事件协议生成执行事件意图：每个 execution 的事件序号从 1 连续递增，`event_id` 仍由 execution 与稳定 command_id 派生，内容摘要绑定事件类型、状态、发布和发生时刻。状态批次同时保存旧兼容字段和协议字段，因此命令回执去重、应答丢失恢复与事件意图具有同一提交边界。
