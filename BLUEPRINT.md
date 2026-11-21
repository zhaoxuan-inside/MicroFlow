# 完美形态蓝图（BLUEPRINT）—— 全部应用的最完备设计

> 状态：**设计基线（2026-11-21）。** 本文档不分优先级，对支撑体系内**每一个应用**给出"该服务域应具备的完整能力面"设计：数据模型增量、命令与 API 面、UI 页面清单、机器可判定验收标准。实现按**依赖序**分轮收口（依赖序是工程因果关系，不是价值排序——Kit 是其余一切的底座，必须先行）。设计冲突时以各子项目 README 与归档设计原文为准；每个能力落地时回填对应 README 边界声明。

## 〇、终态不变式（所有设计共守）

1. **门禁唯一**：一切修改过同一静态门禁；证据链闭合（Spec 定义期望 → Verify 产出证据 → Delivery 消费证据 → Host 承载运行）。
2. **诚实边界**：AI 不当第二审批人（第二人是人的业务判断——MCP 只暴露读面与 verify/spec 工具，审批永远人工）；替身不冒充生产证据；未实现的能力显式拒绝而非占位。
3. **UI 四通**：每个 SPA 页面必须同时过 i18n（zh/en 双资源、禁裸文案守卫）、响应式（断点 token，无硬编码 px 布局）、a11y（原语自带 aria/键盘/focus 管理）、状态面（StateView 统一加载/错误/空态）四道检查。
4. **生产底线**：每个有状态服务具备：限流、备份/恢复、介质 Provider 接口（SQLite/PG 同过契约测试）、自身可观测、容器化部署清单。

## 一、终态架构

```text
                    AI 工具（MCP：框架 13 工具 + spec_* + verify_run 读面）
                                    │
 需求基线 Spec ──场景脚本──▶ Verify ──证据信封──▶ Delivery ──产物+指针──▶ Host 网关 ──▶ 环境运行
   │serve        │serve            │serve            │serve                │
   └─────────────┴────────┬────────┴─────────────────┘                    │
                          ▼                                               ▼
              Pipeline 控制台（新 SPA：矩阵/脚本/报告/产物/审批/拓扑/审计）
                                     Host 静态托管 /apps/*
        编排控制面 :8200（委托代理接线）── 三平台 SPA :4601-4603（Kit 完备态）
```

## 二、Kit 完备态（一切 UI 的底座，先行收口）

**新增原语**（`packages/ui/src`）：

| 原语 | 设计 | 验收 |
|---|---|---|
| `StateView` | loading/error/empty 三态统一：`<StateView state={q} empty={...}>`；空态文案必须走 i18n | 全部页面替换手写三态；守卫测试扫描裸 `暂无`/`加载中` 字面量 |
| `DataTable` | 列定义驱动、键盘方向键导航、`aria-sort`、行选中 `aria-selected`、万行级虚拟滚动（content-visibility） | a11y 基线脚本（Verify browser 面）逐页跑通 |
| `Dialog` / `Menu` / `Tooltip` | `role="dialog|menu|tooltip"` + focus trap + `Esc` 关闭 + 返回焦点 | 焦点环可见（`:focus-visible` token） |
| `SkipLink` / `VisuallyHidden` | 页首跳转 + 仅供读屏文本 | 三平台 AppShell 接入 |
| 断点 token | `--bp-sm 640 / --bp-md 1024 / --bp-lg 1440` + 栅格原语（`Grid` 列随断点坍缩） | 页面禁裸 `px` 布局（守卫测试扫描） |
| 对比度审计 | token 对比度按 WCAG AA 计算的守卫测试（oklch→线性 RGB） | 亮暗两套全部 ≥4.5:1（正文）/3:1（大字与图形） |

**i18n 收口**：资源补全至全页面键位；`useI18n` 全覆盖；守卫测试扫描 tsx 裸 CJK 字面量（诊断码守卫同型）。

## 三、MicroFlow4Verify —— 浏览器面 + Flutter 面（执行器完备）

**browser 面（Playwright）**：
- 依赖显式声明：`playwright`（这是 Verify 唯一三方依赖，README 如实登记）。
- 新增步骤 op：`expect_text`（`{node, contains|equals}`——渲染后 DOM 文本断言）、`screenshot`（`{name, baseline, max_diff_ratio}`——像素基线对比，阈值容忍；`--update-baselines` 显式刷新基线，基线入库随产物版本）。
- 运行壳：Verify 自带 **test harness 页**（`harness/index.html` + boot 脚本：装载 MFProject + `MFRuntime` + `MFInterpreter`，模型经 URL 注入）——真实浏览器渲染面，Playwright 驱动真实事件（点击/键入/焦点），不再只是运行时语义级。
- `BrowserSurface implements VerifySurface`（端口兑现）；信封 meta 记录 `surface: "browser"` + 截图证据文件引用（截图不进 stdout 确定性域，文件随报告落盘）。
- **验收**：金路径脚本在 chromium 跑通导航/交互/文本/截图断言；同脚本在 web 语义面并行可跑（面中性回归）。

**flutter 面**：`microflow_verify_flutter` Dart 包（4Flutter packages/ 下新模块）：`VerifySurface` 的 Dart 实现，驱动 `integration_test` 执行**同一份脚本 JSON**；CI 门禁 `flutter test` 挂接。验收：mini 工程同一脚本在 web/browser/flutter 三面 verdict 一致。

**报告聚合**：`verify report` 子命令——按场景聚合历次运行（verdict 序列、失败回归定位），供 Delivery 门禁与 Pipeline 报告页消费。

## 四、MicroFlow4Spec —— 执行器接线 + 服务面 + MCP

- **`backend_run` 执行器**：`spec verify` 对 flow 场景调 `python -m microflow test <project> --ephemeral`（子进程 + `microflow-cli-v1` 信封解析），用例 verdict 映射进证据合并；连接参数经环境变量 `MF_SPEC_PYTHON_ENTRY`。
- **`orch_scenario` 执行器**：调编排控制面场景执行 REST（`MF_SPEC_CONTROL_PLANE` 锚定），期望终态对照——补齐全周期验收的最后一类证据。
- **服务面**：`spec serve --dir`（FastAPI：GET 模型/coverage/证据；POST 证据登记）——Pipeline 控制台数据源。
- **MCP**：`spec_check` / `spec_coverage` / `spec_verify` 三工具（AI 工具"验收先行"直接可查）。
- **验收**：金路径——Spec 基线中 `backend_run` 用例真实调 4Python test 得 pass；`ui_script` 调 Verify；`orch_scenario` 调控制面；coverage 汇总三类证据。

## 五、MicroFlow4Delivery —— 上传 + 部署执行器 + 控制台

- **blob 上传**：`POST /api/v1/artifacts`（multipart：blob + 三证据文件 + kind），大小上限 512MB（超限 413 显式拒绝）；登记语义与 CLI 完全一致（同一存储层判定源）。
- **部署执行器**：`--deploy-target` 语义——promote 时**先执行部署钩子后推指针**：钩子是显式登记的命令（部署清单：容器重启/脚本/SSH），失败 → 指针不推进 + `deploy-failed` 审计事件 + GateRejected 语义分层（部署失败是门禁否定 exit 1）。审计区分 `deploy` 事件。
- **控制台页面**（Pipeline SPA 内）：产物浏览器（按 kind/spec.digest 过滤）、审批队列（待办 + 同人禁审前置提示）、环境拓扑视图（指针链可视化 + 回滚操作走同守卫）、审计时间线。
- **验收**：上传→审批→部署钩子成功推指针；钩子失败指针不动的负例。

## 六、MicroFlow4Host —— 委托接线 + 限流 + 自身可观测 + 生产介质 + 备份 + 容器化

- **委托代理接线**：`orchestration.*`/`experiment.*`/`configcenter.*` 透传编排控制面（`MF_HOST_CONTROL_PLANE` 锚定；宿主持服务令牌；宿主权限点 → 控制面动作映射表单一来源）。501 → 真实代理；控制面不可达 → 502 + 诚实信封。
- **限流**：dispatch/telemetry 按（身份, 类别）token bucket（dispatch 120/min burst 30；telemetry 既有容量语义保留）；超限 429 + `RATE_LIMITED`；配置显式声明。
- **自身可观测**：`/api/v1/health` 细分组件状态（db/apps/delegation 可达性）；结构化请求日志（trace_id 贯穿）；host 自身 run 记录已供 Ops 消费。
- **介质 Provider**：`HostStore` 协议抽取（现 SQLite 实现改名 `SQLiteHostStore`）+ `PostgresHostStore`（可选 extra `pg`）；两实现同过**提供者契约测试套件**（对齐 4Python 持久化提供者纪律）。
- **备份/恢复**：`host backup --into DIR`（SQLite backup API 一致性快照 + 校验和清单）与 `host restore --from DIR`；恢复后自检（schema 版本 + 计数对账）。
- **容器化**：多阶段 Dockerfile + `compose.yaml`（host + 编排控制面 + PostgreSQL + 平台 SPA 静态挂载）；健康检查与重启策略进清单。
- **验收**：同一契约套件在 SQLite/PG 双介质全绿；限流负例；备份→清库→恢复→对账一致。

## 七、Pipeline 控制台（新 SPA，工程面）

- **定位**：Spec/Verify/Delivery 三服务的统一人机面（一条工作流：基线 → 验收 → 交付）；Host 托管于 `/apps/pipeline`，Kit 完备态消费。
- **页面清单**：基线矩阵（需求覆盖热力 + 证据状态列）、脚本库与运行（声明式编辑器：表单化步骤编辑，**不允许自由 JS**——表达力刻意做小纪律延伸到 UI）、报告详情（断言明细 + 截图对比滑块）、产物浏览器、审批队列、环境拓扑、审计时间线。
- **数据源**：三个 serve 面（spec/verify/delivery）经 Vite 代理；权限门沿用 Kit `PermissionGate`。
- **验收**：金路径 E2E（Verify browser 面）——建需求→挂场景→跑脚本→报告 pass→登记产物→审批→指针推进，全程截图基线。

## 八、三平台 SPA 完备态改造（逐页挂账）

| 平台 | 改造 |
|---|---|
| Orchestration（8 页） | 响应式栅格化（画布页保最小宽度并声明）、a11y 基线脚本逐页挂账、i18n 键位补全 |
| Ops（6 页） | 同上 + 瀑布/告警页键盘导航（DataTable 化） |
| Bizops（5 页） | 同上 + 状态面加厚（loading/空态用 StateView 替换手写） |
| 共同 | 每页一条 Verify browser 脚本进 `baselines/`（截图 + 交互断言），CI 门禁全绿才可交付 |

## 九、MCP 扩面（AI 工具全回路，读面纪律）

新增：`spec_check` / `spec_coverage` / `spec_verify` / `verify_run`（跑脚本出信封）/ delivery 读面（list/pointers/audit）；**不暴露**：`delivery promote`（审批是第二人人责）、任何写宿主治理的面。工具 description 内嵌对应纪律。

## 十、跨切面验收（全链金路径，机器可判定）

1. `spec check` 0 诊断 → `spec coverage` 全绿；
2. `verify run` 三面（语义/web 语义/browser）同一脚本 verdict 一致；
3. Delivery 登记→审批→部署→指针推进→Host 托管新产物可访问；
4. 三平台 + Pipeline 每页截图基线与 a11y 基线全绿；
5. Host 备份→恢复→对账一致；SQLite/PG 契约套件双绿；
6. 全部证据随产物 release 登记（Delivery artifacts 记录 spec.digest/verify digest——追溯闭环）。

## 十一、实现轮次（依赖序，非优先级）

| 轮 | 内容 | 收口物 |
|---|---|---|
| R1 | Kit 完备态（原语/断点/对比度/i18n/守卫测试） | Kit 测试 + 三平台回归 |
| R2 | Verify browser 面 + harness + 截图基线 | verify 测试 + 金路径 |
| R3 | Spec/Verify/Delivery 三个 serve 面 + 执行器接线（backend_run/orch_scenario） | 各包测试 + 信封联测 |
| R4 | Delivery 上传 + 部署执行器 | 门禁负例 |
| R5 | Host 限流/委托/备份/PG Provider/容器化 | 契约套件双介质 |
| R6 | Pipeline SPA（全部页面） | tsc + vite + 纯逻辑测试 |
| R7 | 三平台 SPA 改造 + 全链金路径 + 基线入库 + 文档收口（README/LIFECYCLE/BLUEPRINT 回填） | 全部门禁绿 |

每轮：验收先行写标准 → 实现 → 测试全绿 → 一个 commit（message 写清做什么+为什么）。`microflow_verify_flutter`（R2 的 flutter 面）依赖 Flutter 工具链环境，设计已定，落地排在 R7 前的可用窗口。
