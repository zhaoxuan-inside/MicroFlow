# MicroFlow 前端框架完整设计方案

版本：v1.2
日期：2026-10-22
状态：设计基线，尚未代表已实现能力

## 1. 定位

MicroFlow Frontend 是与 MicroFlow Python 后端框架平行的前端开发框架。它面向 Vibe Coding，将前端产品表示为可组合、可验证、可版本化的结构模型，并将模型编译或运行到 Web、桌面和移动端。

框架定位为前端产品的底层构建与运行基础，不负责具体业务规则和业务组件实现。框架负责项目模型、组件/图层/页面/产品编排、规范化 IR、静态检查、编译、解释运行、发布快照、运行数据采集、诊断数据上报，以及多版本配置的加载、校验、兼容性检查和运行时冻结。

上层产品负责业务领域模型、业务规则、业务组件、业务数据适配器，并通过配置编排组件、图层、页面和产品。上层不得通过配置绕过 Schema、权限、版本和能力检查。

框架不依赖 RPC、HTTP、数据库、特定后端或特定云平台。后端连接、文件访问、设备能力和第三方服务都属于可选的宿主适配能力。没有后端时，框架仍能构建完整的静态页面、本地应用、交互原型和纯客户端产品。

框架解决的问题是：

- 用稳定的结构描述产品，而不是让 AI 在文件之间猜测关系；
- 用元组件组合组件，用组件组合图层，用图层组合页面，用页面组合产品；
- 让 AI、可视化编辑器和人工代码修改共享同一份项目模型；
- 在 Web 和客户端之间复用产品结构，同时允许平台差异；
- 对布局、依赖、导航、状态和平台能力进行静态检查；
- 让草稿、发布版本和运行中的产品具有明确边界。

框架不试图替代 React、Vue、Flutter 或原生 UI 工具包，也不替代上层业务组件库。它定义产品模型、组合协议、编译边界、数据采集协议和版本化配置协议，再由 Renderer 将模型落到目标平台。

## 2. 核心分层

产品由五个主要层级组成：

```text
元组件 → 组件 → 图层 → 页面 → 产品
```

### 2.1 元组件

元组件是最小可复用的 UI 或交互能力，例如 Text、Icon、Image、Button、Input、Stack、Grid、Scroll、Modal 和 List。

元组件不绑定业务名称，但必须具有明确的属性、插槽、事件、状态、布局能力和平台能力声明。

### 2.2 组件

组件是具有语义的可复用模块，由元组件或其他组件组合而成。例如 LoginForm、ProductCard、Sidebar、DataTable、SearchPanel 和 EmptyState。

组件可以公开：

- 输入属性；
- 内容插槽；
- 输出事件；
- 内部状态；
- 可替换的主题令牌；
- 平台变体；
- 可调用的交互动作。

组件必须隐藏内部结构，页面只能依赖组件的公开契约。这样修改组件内部布局时，不会让所有页面跟着修改。

### 2.3 图层

图层是页面中的结构区域，同时表达视觉层级、布局职责和交互边界。典型图层包括 AppShellLayer、HeaderLayer、NavigationLayer、ContentLayer、PanelLayer、OverlayLayer 和 ModalLayer。

图层不是简单的 z-index。图层定义可以声明：

- 约束区域；
- 子组件集合；
- 对其他图层的依赖；
- 进入和离开动画；
- 响应式策略；
- 是否固定、滚动或覆盖；
- 在某个平台是否隐藏或替换。

### 2.4 页面

页面是可被导航、渲染和恢复的产品单位。页面包含页面参数、图层树、页面状态、页面事件、生命周期和错误边界。

### 2.5 产品

产品包含页面集合、导航图、主题、资源、产品级状态、应用入口、平台目标和发布配置。

页面之间不是树，而是有向图。菜单可以是树状投影，但真实导航必须支持返回、条件跳转、弹窗、Tab、深链接和外部入口。

## 3. 总体架构

```text
                    ┌──────────────────────┐
                    │ Vibe Coding Interface │
                    │ Editor / CLI / Agent  │
                    └──────────┬───────────┘
                               │ Context + Commands
                    ┌──────────▼───────────┐
                    │ Project Model / IR   │
                    │ Product Graph        │
                    └───────┬───────┬──────┘
                            │       │
             ┌──────────────▼─┐ ┌──▼──────────────┐
             │ Static Validator │ │ Compiler        │
             │ Schema/Layout    │ │ Code/Manifest   │
             │ Route/Capability │ │                 │
             └──────────────┬──┘ └──┬──────────────┘
                            │       │
                    ┌───────▼───────▼──────┐
                    │ Frontend Runtime     │
                    │ State/Nav/Event      │
                    └───────┬───────┬──────┘
                            │       │
               ┌────────────▼─┐ ┌──▼────────────┐
               │ Web Renderer  │ │ Client Renderer│
               │ DOM/React/Vue │ │ Flutter/Native │
               └───────────────┘ └───────────────┘
```

框架核心只依赖项目模型、Schema、编译规则和运行时协议。具体渲染器、构建工具和平台 SDK 由目标适配包提供。

## 4. 项目模型

项目模型是所有工具的唯一事实来源。编辑器、AI 和编译器都通过模型操作，不直接通过文本搜索猜测产品结构。

```text
Project
├── manifest
├── design_system
├── primitives
├── components
├── layers
├── pages
├── navigation
├── interactions
├── data_models
├── telemetry
├── experiments
├── assets
├── platform_profiles
├── tests
└── release
```

### 4.1 Manifest

Manifest 描述项目 ID、模型版本、目标平台、入口页面、默认主题、工具链版本和能力要求。

### 4.2 资源身份

每个元组件、组件、图层、页面、动作和资源拥有稳定的 `id`。名称可以修改，ID 不随重命名变化。

每个对象还包含：

- `kind`：对象类型；
- `schema_version`：结构版本；
- `revision`：对象修订；
- `source`：来源文件或生成来源；
- `description`：供人和 AI 使用的语义说明；
- `tags`：检索和分类标签；
- `dependencies`：显式依赖；
- `capabilities`：平台能力要求。

### 4.3 可追踪引用

对象之间的引用使用稳定 ID，编译器生成反向索引：

```text
component → used_by layers/pages
page → reachable_from routes
asset → used_by components
interaction → reads/writes states
```

AI 修改前必须能查询影响范围；删除对象前必须经过引用检查。

### 4.4 观测与实验身份

日志事件、运营事件、性能样本和实验配置引用都属于项目模型中的版本化资源。每条事件和配置必须关联 `project_id`、`release_id`、`renderer_version`、`environment` 和 `schema_version`。用户身份、设备身份和实验分流身份必须分开建模，不能用原始账号、设备序列号或凭据作为公开事件字段。实验分流身份和分流结果由外部实验控制方提供，框架只负责校验、应用、冻结和上报。

### 4.5 配置版本与运行时冻结

配置是框架加载和运行上层产品的输入，不是框架内部的隐式全局状态。每份配置至少包含 `config_id`、`config_version`、`schema_version`、`effective_at`、`expires_at`、`target_platform`、`compatibility` 和内容摘要。加载流程必须执行：

```text
发现版本 → 校验 Schema → 校验平台能力 → 校验兼容范围 → 选择版本 → 冻结运行上下文 → 记录并上报结果
```

页面或产品配置发生变化时，只影响新建的运行实例；已运行实例继续使用已冻结的配置版本，除非显式声明支持迁移。配置缺失、过期、不兼容或加载失败时，使用发布快照中声明的默认配置，并上报可诊断的降级原因。

## 5. 元组件契约

元组件契约应采用平台无关的描述方式：

```json
{
  "id": "button",
  "kind": "primitive",
  "props": {
    "label": {"type": "string"},
    "variant": {"type": "enum", "values": ["primary", "secondary", "danger"]},
    "disabled": {"type": "boolean"}
  },
  "slots": {},
  "events": {
    "press": {"payload": "void"}
  },
  "states": ["enabled", "disabled", "busy", "focused"],
  "layout": {
    "display": ["inline", "block"],
    "sizing": ["hug", "fill", "fixed"]
  },
  "accessibility": {
    "role": "button",
    "requires_label": true
  }
}
```

契约必须支持：

- 类型检查；
- 默认值；
- 可选和必填属性；
- 插槽类型；
- 事件载荷类型；
- 状态集合；
- 布局能力；
- 可访问性要求；
- 主题令牌；
- 平台能力和降级策略。

元组件不能直接依赖业务对象。业务语义应由上层组件通过属性、数据映射和事件适配提供。

## 6. 组件组合模型

组件由树状节点组成，节点可以引用元组件或其他组件：

```json
{
  "id": "login-form",
  "kind": "component",
  "props": ["title", "submitText"],
  "events": ["submit", "cancel"],
  "tree": {
    "type": "Card",
    "children": [
      {"type": "Text", "bind": "title"},
      {"slot": "fields"},
      {"type": "Button", "bind": "submitText", "on": "press → submit"}
    ]
  }
}
```

组件必须区分：

- **结构**：组件有哪些子节点；
- **样式**：组件如何呈现；
- **数据**：组件读取哪些输入；
- **状态**：组件内部保存什么；
- **行为**：组件产生哪些事件；
- **平台变体**：不同平台如何替换实现。

组件内部可以使用本地状态，但不能偷偷修改外部页面或产品状态。外部变化必须通过事件和公开绑定完成。

## 7. 图层与布局系统

布局采用约束模型，不把某一个平台的 CSS 或坐标系统暴露为核心协议。

基础布局能力包括：

- Stack：横向或纵向排列；
- Grid：网格排列；
- Overlay：覆盖排列；
- Split：可调整分栏；
- Scroll：滚动区域；
- Anchor：相对锚定；
- Constraint：最小、最大、固定和填充尺寸；
- Responsive：断点、容器查询和平台条件。

布局约束应能表达：

```text
width: fill
maxWidth: 640
padding: space.4
mobile: stack(vertical)
tablet: split(2)
desktop: split(3)
```

布局编译器负责发现：

- 无法满足的尺寸约束；
- 循环依赖；
- 互相冲突的定位规则；
- 平台不支持的布局能力；
- 在目标窗口下可能溢出的内容。

图层需要声明滚动和覆盖关系。不能让每个组件自行决定页面滚动，否则页面会出现多个不可控滚动容器。

## 8. 页面模型

```json
{
  "id": "dashboard-page",
  "kind": "page",
  "route": "/dashboard",
  "parameters": {},
  "shell": "app-shell",
  "layers": ["header-layer", "sidebar-layer", "content-layer"],
  "state": ["selectedPeriod", "isFilterOpen"],
  "lifecycle": {
    "onEnter": "loadDashboard",
    "onLeave": "saveDraft"
  },
  "errorBoundary": "dashboard-error",
  "platformVariants": {
    "mobile": "dashboard-mobile-page"
  }
}
```

页面必须定义：

- 路由标识和参数；
- 页面壳和图层顺序；
- 页面级状态；
- 生命周期事件；
- 空、加载、错误和成功状态；
- 页面级快捷操作；
- 可访问性标题和焦点入口；
- 平台变体；
- 可被哪些页面导航到。

页面不应直接承载不可复用的复杂业务逻辑。复杂逻辑应提取为交互流程或组件动作。

## 9. 产品和导航模型

导航模型使用有向图：

```text
NavigationGraph
├── nodes: pages, dialogs, external entries
├── edges: push, replace, modal, tab, back
├── guards: conditions and access rules
├── parameters: typed route parameters
└── fallback: missing/denied/error targets
```

导航检查包括：

- 路由 ID 唯一；
- 参数类型一致；
- 入口可达；
- 不存在孤立页面；
- 返回路径有定义；
- 权限拒绝有 fallback；
- 深链接可恢复；
- 页面变体存在或有降级策略。

菜单是导航图的一个投影，不是导航图本身。

## 10. 交互模型

交互使用受限事件图，不鼓励在模板中写任意脚本：

```text
事件 → 前置条件 → 状态变更 → 副作用 → 后续事件
```

示例：

```text
submit.press
  → validate(form)
  → set(submitting, true)
  → execute(local action)
  → set(submitting, false)
  → navigate(success)
```

动作分为：

1. **UI Action**：显示、隐藏、聚焦、滚动、动画；
2. **State Action**：读写组件、页面、会话或本地持久状态；
3. **Navigation Action**：push、replace、modal、back；
4. **Local Function**：在本地执行的纯计算；
5. **Host Capability**：文件、摄像头、通知、剪贴板等宿主能力；
6. **External Adapter**：可选的 API、文件或服务适配，不进入核心依赖。

所有动作都要声明输入、输出、错误和取消语义。运行时不把“请求超时”自动当成“操作未执行”。

## 11. 状态模型

状态按所有权和生命周期分层：

```text
Component State
Page State
Session State
Product State
Persistent Local State
Derived State
```

规则如下：

- 组件状态不能被任意页面修改；
- 页面状态随页面实例创建和销毁；
- 会话状态由产品运行时拥有；
- 持久状态必须声明版本和迁移规则；
- 派生状态不能作为第二份事实来源；
- 异步状态必须区分 idle、loading、success、empty、error 和 cancelled；
- 进程挂起和恢复不能依赖内存对象仍然存在。

框架核心不强制某个状态库。Renderer 可以把模型映射到 React、Flutter、Compose 或原生状态机制。

## 12. Web 与客户端适配

核心模型保持平台无关，Renderer 处理平台差异：

```text
Shared Model
├── Web Renderer
│   ├── browser navigation
│   ├── DOM/accessibility
│   └── responsive layout
├── Mobile Renderer
│   ├── native lifecycle
│   ├── system back
│   └── device capabilities
└── Desktop Renderer
    ├── window lifecycle
    ├── keyboard/menu
    └── filesystem integration
```

平台差异通过三种方式表达：

- 同一组件的属性适配；
- 同一组件的平台实现替换；
- 页面或图层的平台变体。

不能把所有平台压缩成最低共同能力。能力不足时，编译器应拒绝、替换或使用明确声明的降级实现。

## 13. 编译器和运行时

### 13.1 编译阶段

编译器执行：

1. 解析项目模型；
2. 校验 Schema；
3. 建立对象索引；
4. 检查组件和页面引用；
5. 检查布局约束；
6. 检查导航图；
7. 检查交互事件图；
8. 检查平台能力；
9. 生成规范化 IR；
10. 输出目标平台 manifest、代码和资源清单。

### 13.2 运行阶段

运行时负责：

- 创建产品实例；
- 管理页面栈和导航；
- 管理状态生命周期；
- 分发事件；
- 执行动作；
- 调用宿主适配器；
- 处理加载、错误、取消和恢复；
- 输出结构化运行诊断。

运行时不能修改项目定义。运行中的实例使用发布时固定的模型和策略。

运行时可以产生观测事件，也可以读取外部下发的配置和实验上下文，但不能直接修改实验配置或项目模型。事件通过版本化 Telemetry Contract 进入受控的采集队列；采集器故障不能阻断核心用户流程，除非该事件属于明确声明的可靠业务事实。框架不负责实验分流、样本选择、指标计算、实验启停和实验结论。

运行时加载配置时必须使用声明的配置版本，完成 Schema、平台能力、有效期和兼容范围检查后，将有效配置摘要冻结到运行实例。配置加载失败时使用发布快照中的默认配置并上报降级原因；配置刷新不静默修改已运行实例。

### 13.3 解释执行和代码生成

首版建议同时保留两种模式：

- **解释模式**：适合 Vibe Coding 预览、调试和快速迭代；
- **编译模式**：生成目标平台代码和静态资源，适合发布。

两种模式必须使用同一个 IR，避免预览行为和发布行为分叉。

## 14. 面向 Vibe Coding 的设计

Vibe Coding 的第一类对象不是文件，而是项目模型中的资源。

AI 操作应使用结构化命令：

```text
create_component
update_component
insert_layer
replace_page_variant
connect_navigation
add_interaction
rename_resource
inspect_impact
validate_project
```

每次 AI 修改都应产生：

- 修改目标；
- 修改前后摘要；
- 影响对象；
- 验证结果；
- 未解决问题；
- 可回滚修订。

AI 上下文按任务裁剪：

```text
当前页面
→ 当前图层
→ 目标组件
→ 相关状态
→ 相关交互
→ 被影响的导航和资源
```

不把整个项目所有源代码无条件塞给模型。模型可以通过索引查询页面、组件、引用、依赖和可用能力。

AI 生成的文本代码只能通过受控入口进入项目模型；不能让任意字符串直接绕过 Schema、权限和编译检查。

## 15. 目录与源文件组织

推荐的项目布局：

```text
product/
├── microflow.frontend.json
├── design-system/
│   ├── tokens.json
│   └── themes/
├── primitives/
├── components/
├── layers/
├── pages/
├── navigation/
├── interactions/
├── data/
├── assets/
├── platforms/
│   ├── web/
│   ├── mobile/
│   └── desktop/
├── generated/
├── tests/
└── releases/
```

`generated/` 不作为人工编辑的事实来源。人工代码扩展必须放在明确的 extension 目录，并通过稳定契约回接模型。

## 16. 发布和版本

项目采用草稿、验证、发布和运行四种状态：

```text
Draft → Validated → Published → Running
```

发布产物包含：

- 完整项目模型摘要；
- IR 版本；
- Renderer 版本；
- 资源摘要；
- 平台能力要求；
- 主题和配置摘要；
- 迁移信息；
- 诊断规则版本。

页面编辑只产生新修订，不改变已运行实例。运行实例固定 `release_id`。回滚只影响新启动实例，除非明确执行运行实例迁移。

发布必须是不可变快照。资源、组件和页面不能在发布后被原地修改，否则无法复现构建结果。

## 17. 扩展机制

扩展分为：

- Primitive Extension：新增元组件；
- Component Extension：新增可复用组件；
- Renderer Extension：新增平台实现；
- Host Extension：新增设备或系统能力；
- Compiler Extension：新增编译目标或优化；
- Tool Extension：新增编辑器、CLI 或 AI 工具。

扩展必须提供：

- 稳定 ID；
- Schema；
- 能力声明；
- 版本；
- 兼容范围；
- 预览实现；
- 运行实现；
- 测试和降级策略。

核心框架不动态执行任意项目目录中的代码。可信扩展通过显式注册进入构建环境，运行时能力通过宿主注入。

## 18. 验证和质量机制

### 18.1 静态验证

- Schema 和类型检查；
- 组件插槽检查；
- 布局约束检查；
- 路由和参数检查；
- 不可达页面检查；
- 交互循环和未处理错误检查；
- 平台能力检查；
- 资源引用检查；
- 可访问性必填项检查。

### 18.2 运行验证

- 页面初始化和销毁；
- 前进、后退和深链接；
- 状态恢复；
- 加载、空、错误和取消状态；
- 窗口尺寸和屏幕旋转；
- 平台能力不可用；
- 资源加载失败；
- 版本迁移和回滚。

### 18.3 Vibe Coding 回归

同一项目模型应验证：

- AI 修改后对象 ID 不丢失；
- 未修改页面不产生无关差异；
- 组件修改能正确报告影响页面；
- 解释模式和编译模式行为一致；
- 发布结果可重复生成；
- 删除资源不能留下隐式引用。

### 18.4 质量属性契约

高可用、高性能和高可维护性不能只作为实现目标，必须成为模型、Renderer、Host 和发布工具共同遵守的契约。

框架增加以下最小契约：

- **Data Contract**：数据源、输入输出 Schema、加载、缓存、变更、权限和陈旧策略；
- **Action Contract**：动作输入输出、幂等、超时、取消、失败、未知结果和提交边界；
- **Capability Contract**：宿主能力的可用、拒绝、暂不可用、不支持和结果未知状态；
- **Renderer Contract**：各平台必须一致的状态、事件、导航、错误和可访问性行为，以及允许差异；
- **Recovery Contract**：路由、参数、页面状态、待处理动作和发布版本的恢复与迁移规则；
- **Performance Contract**：模型检查、增量编译、启动、导航、交互、内存和资源体积预算。
- **Telemetry Contract**：事件名称、Schema、身份边界、采样、隐私分类、队列、重试、丢弃和保留策略；
- **Experiment Contract**：外部实验控制方提供的实验键、配置版本、分流结果、稳定性标识、实验组和曝光要求；框架负责校验、应用、冻结和上报，不负责分流和实验决策。

上层业务组件和业务规则不属于上述核心契约的实现范围；它们必须通过公开组件契约、数据适配器、交互动作和版本化配置接入框架。

上述契约必须有版本、Schema、诊断码和兼容范围。缺少契约的扩展只能作为实验能力，不能进入可发布快照。

## 19. 推荐实施顺序

### 阶段一：模型、契约和验证核心

实现 Project、Primitive、Component、Layer、Page、Navigation、Interaction 的 Schema、ID、规范化序列化、引用索引、版本迁移和静态验证器；同时固化 Data Contract、Action Contract、Capability Contract 和 Recovery Contract。

交付一个命令行工具：

```text
microflow-ui check
microflow-ui inspect
microflow-ui impact
microflow-ui normalize
```

### 阶段二：解释运行时

实现规范化 IR、页面实例、组件树渲染、状态、导航、事件分发、动作取消、重复提交处理、错误边界和基础恢复。先选择一个 Renderer，建议优先 Web。

### 阶段三：Vibe Coding 接口

实现结构化编辑命令、局部上下文查询、影响分析、差异预览、回滚、AI 修改审计、观测 Schema 查询和外部配置/实验上下文校验。

### 阶段四：编译器

将同一 IR 编译为 Web 产物，加入增量编译、内容寻址缓存、路由代码分割、资源清单和观测/实验版本清单，确保解释预览与编译产物保持行为一致。

### 阶段五：客户端 Renderer

在 IR 稳定后接入 Flutter、React Native、Compose 或原生 Renderer。平台差异通过能力声明和变体处理。

### 阶段六：可视化编辑器

最后建设画布、图层树、组件面板、属性面板、页面导航图、交互编辑器和实时预览。编辑器只是 Project Model 的一个客户端，不应成为新的事实来源。

每个阶段必须有对应的性能基准、故障注入和 Renderer 一致性测试，不把内存替身或单次预览结果视为生产能力证据。

## 20. 首版范围建议

首版只实现：

- 元组件和组件树；
- Stack、Grid、Overlay 三类布局；
- 页面和页面导航；
- 页面、组件和会话状态；
- 基础交互动作；
- 最小 Data Contract、Action Contract 和 Recovery Contract；
- 加载、空、错误状态；
- Web Renderer；
- JSON 或等价结构化项目模型；
- `check`、`inspect`、`impact` 和 `build` 命令；
- 解释预览和编译产物；
- 发布快照和回滚；
- 增量构建、路由级代码分割和基础性能预算；
- 基础可访问性校验和宿主能力降级诊断。
- 最小 Telemetry Contract、可靠队列和本地失败降级；
- 版本化配置加载、Schema/能力/兼容性校验、运行时冻结、默认配置降级和配置结果上报；
- 外部实验分流结果、曝光事件、配置版本和外部停用状态的接入与校验。

首版暂不固定：

- RPC 或 API 协议；
- 数据库和后端服务；
- 具体状态管理库；
- 具体 Web UI 库；
- 具体移动端工具包；
- 可视化编辑器的实现技术；
- 任意脚本执行；
- 全自动跨平台像素级一致。

首版还必须明确不承诺：跨主机高可用、外部业务资源的全局恰好一次、任意宿主能力的自动恢复，以及没有实际部署和故障演练证据的生产级可用性。

## 21. 基础设计结论

MicroFlow Frontend 的核心抽象不是“前端调用后端”，而是：

```text
元组件
  ↓
组件
  ↓
图层
  ↓
页面
  ↓
产品
  ↓
目标平台产物
```

它的核心资产不是某个 React 项目或 Flutter 项目，而是可查询、可组合、可验证、可版本化的前端产品模型。

后端 MicroFlow 负责业务流程和执行协议；前端 MicroFlow 负责产品界面和交互结构。两者可以集成，但任何一方都不应成为另一方的运行前提。

这套设计的第一目标不是提供更多 UI 控件，而是让 Vibe Coding 具备可靠的结构边界、影响分析、局部上下文和可重复生成能力。

## 22. 高可用、高性能与高可维护性增强设计

### 22.1 高可用

前端可用性按“资源可获取、应用可启动、页面可导航、核心动作可执行、外部依赖可降级、实例可恢复、版本可回退”分层定义。每一层都必须声明成功条件、超时、降级目标和诊断码。

运行实例固定 `release_id`、`renderer_version`、`capability_binding` 和 `policy_digest`。页面恢复快照至少包含路由、参数、页面状态、会话状态、待处理动作、最后确认的状态修订和快照版本。恢复时必须重新校验权限、版本和数据新鲜度；无法确认的副作用只能进入 `unknown`，不能当作失败后自动重试。

Host Capability 必须返回 `available`、`permission_denied`、`temporarily_unavailable`、`unsupported` 或 `unknown_result` 等可判定状态。能力不足时，运行时只能使用声明过的降级实现或进入明确错误边界。

发布系统必须保证模型、IR、Renderer、资源和配置来自同一不可变快照；灰度、回滚和资源清理都以快照引用关系为依据。高可用声明必须通过目标平台的启动、恢复、依赖故障、资源失败和回滚演练验证。

### 22.2 高性能

模型编辑和构建采用增量策略。对象 ID、规范化内容摘要和反向索引共同形成缓存键；修改资源时，只重新验证、编译和打包受影响的闭包。解释模式运行规范化 IR，不直接重复解析原始项目文件。

Web Renderer 必须支持路由级代码分割、按需加载、资源优先级、列表虚拟化、静态子树复用和受控状态订阅。客户端 Renderer 必须声明冷启动、页面切换、内存、后台恢复和大列表预算。布局编译器在编译期解决可静态解决的约束，运行期只处理必须动态计算的约束。

首版性能指标至少包括：增量检查时间、增量构建时间、冷启动时间、页面导航 P95、交互反馈 P95、典型页面内存峰值和发布产物体积。指标必须记录目标设备、数据规模和网络条件。

### 22.3 高可维护性

对象放置必须遵循职责规则：视觉结构放入组件，页面生命周期逻辑放入页面，跨页面流程放入交互，纯计算放入 Local Function，设备和系统访问放入 Host Capability，业务数据访问放入 External Adapter，平台差异放入 Renderer Variant。

Schema、IR、Renderer、Host 和扩展采用兼容矩阵管理。每次破坏性变更必须提供迁移器、诊断和回滚条件；扩展必须有锁定版本、依赖范围、能力声明、测试和废弃策略。

生成代码不作为模型事实来源。手写扩展只能通过稳定契约引用生成结果，生成器必须提供确定性序列化、清晰的覆盖边界和失败时保留上一版产物的策略。

维护期诊断统一关联 `release_id`、`renderer_version`、`page_instance_id`、`component_instance_id`、`interaction_id`、`action_request_id` 和 `state_revision`，以便从用户动作追踪到状态、宿主调用和最终渲染结果。

### 22.4 必须通过的质量门禁

- Schema、规范化、迁移和引用索引检查通过；
- 解释模式与编译模式通过行为一致性测试；
- 所有 Renderer 通过核心状态、导航、错误、取消和可访问性一致性测试；
- 外部能力不可用时按照契约降级或失败；
- 发布快照可重复构建并可回滚；
- 增量构建不会重新生成无关页面；
- 恢复不会重复提交未知结果的副作用；
- 性能指标达到目标设备和数据规模下的预算；
- 故障注入结果、诊断链路和剩余风险均有记录。

## 24. 观测、运营分析与多版本实验

### 24.1 事件分类

前端事件分为四类：

1. **Diagnostic Log**：用于错误、异常、状态冲突、资源失败和宿主能力失败；
2. **Operational Event**：用于页面访问、功能使用、流程完成、漏斗和业务运营分析；
3. **Performance Sample**：用于启动、导航、交互、网络、资源和渲染性能；
4. **Business Fact**：需要可靠确认的业务事实，例如订单提交成功或文件写入完成。

四类事件必须有不同的可靠性、重试、隐私、保留和查询策略。普通日志或运营事件丢失不能阻断用户流程；Business Fact 必须使用明确的提交确认和去重身份，不能用普通日志代替。

### 24.2 Telemetry Contract

事件定义至少包含：

```text
event_id
event_name
schema_version
occurred_at
release_id
renderer_version
environment
session_id
page_instance_id
route
component_instance_id
interaction_id
experiment_assignments
payload
privacy_class
sampling_policy
```

事件 Schema 必须限制字段、类型、大小、嵌套深度和高基数字段。密码、令牌、原始文件内容、完整表单内容和未经授权的个人信息不得进入事件。需要分析的用户标识必须使用受控的匿名化或哈希身份，并声明保留期限和访问范围。

采集器采用有界内存队列和持久化可选队列。事件上报支持批量、压缩、退避、取消和断网缓存；队列达到预算后按事件优先级丢弃，并记录丢弃计数。日志上报故障不能导致页面主线程阻塞或业务动作失败。

每个事件必须携带 `trace_id`、`release_id` 和页面实例关联信息，使问题能够从用户动作追踪到交互、状态修订、宿主调用和错误边界。诊断数据要区分客户端观察时间和服务端接收时间，不能用接收时间替代事件发生时间。

### 24.3 运营数据和问题分析

框架提供标准事件查询和导出接口，但不把具体分析平台写入核心依赖。框架负责提供可按实验组、版本和平台筛选的事件数据；指标计算、显著性分析和实验结论由外部运营或实验平台完成。事件投影至少支持：

- 页面和功能使用量；
- 漏斗和转化率；
- 错误率、崩溃率和错误聚类；
- 版本、平台、设备和网络条件分布；
- 性能 P50、P95、P99；
- 实验组、配置版本和分流来源维度的数据筛选；
- 事件 Schema 版本和采集丢失率。

事件查询必须按时间、版本、平台、实验、页面和错误类型建立有界过滤，禁止默认返回无限明细。原始事件、聚合结果和诊断索引分别设置保留期限、容量预算和权限。

### 24.4 多版本配置和外部 AB 实验控制

框架支持多版本配置的读取、Schema 校验、兼容性检查、运行时冻结和结果上报。实验分流由外部实验平台、配置中心或运营系统完成，外部控制方至少提供：

```text
experiment_id
config_version
target_scope
assignment_id
assignment_source
variants
exposure_event
start_at
end_at
compatibility
```

框架不实现 `allocation_rules`、样本选择、随机算法、互斥实验决策或指标计算。外部控制方负责根据稳定身份完成分流，并返回不可变的 `assignment_id`、实验组和配置版本。框架必须校验分流结果与目标平台、Schema、发布版本和有效期兼容，然后将分流结果写入运行上下文。曝光只有在目标页面或功能真实可见且可操作时才确认，不能在配置加载时提前计数。

外部配置和实验上下文必须经过 Schema、目标平台能力、默认变体、结束时间和兼容性检查。缺失配置、配置过期、版本不兼容或外部控制方不可用时，框架使用发布快照中声明的默认配置和默认变体，并记录降级原因。实验停用由外部控制方发布新状态或停用配置；框架负责接收、校验和应用，不自行作出实验决策。已确认的历史曝光归属不能改变。

实验不得绕过权限、数据校验、错误处理和安全边界。外部控制方只能选择框架已经声明并允许的属性、布局、交互顺序或策略；框架不得通过配置执行未注册代码、启用未声明能力或写入未验证的数据。

### 24.5 实验与发布、恢复的关系

运行实例固定实验配置摘要和分流结果。页面恢复时继续使用原实验归属，除非实验协议明确允许重新分流；发布回滚必须同时校验实验配置版本和 Renderer 兼容性。实验配置变化产生新修订，新页面实例使用新版本，已运行实例不被静默改写。

实验结果必须同时记录应用版本、Renderer 版本、平台、数据 Schema 版本、外部 `assignment_id`、分流来源和实验配置版本，避免把版本变化误判为实验效果。指标计算、实验比较和实验结论由外部控制方完成。实验结束后，外部控制方负责保留实验墓碑和历史曝光索引；框架继续在事件中保留来源摘要，防止旧事件被错误归入新实验。

### 24.6 观测和实验质量门禁

- 事件 Schema、隐私分类、采样和保留策略通过检查；
- 普通采集故障不阻断核心页面和业务动作；
- Business Fact 支持去重、确认和未知结果查询；
- 事件能够关联到 release、页面实例、交互、状态修订和错误边界；
- 外部提供的 assignment 在运行实例内稳定且可追踪；
- 曝光事件只在真实曝光后产生；
- 缺失、过期和不兼容配置使用默认变体并记录原因；
- 外部停用状态能停止新曝光且不改写历史归属；
- 事件包含应用、Renderer、平台、assignment 和配置版本，供外部平台拆分指标；
- 采集队列的大小、延迟、丢弃和重试均有性能预算和诊断。

## 25. 观测与实验设计结论

日志、运营事件、性能样本、可靠业务事实和实验曝光都通过版本化契约进入前端运行时。框架负责数据和多版本配置的接收、校验、冻结、应用和上报；外部系统负责实验分流、运营控制、指标计算、实验启停和结论。采集系统不能阻断核心流程，可靠业务事实必须具备确认和去重语义，实验上下文必须可追踪且不改变历史归属。

## 26. 修订后的总设计结论

MicroFlow Frontend 仍以“元组件 → 组件 → 图层 → 页面 → 产品 → 目标平台产物”为核心抽象，但可发布的产品模型还必须同时携带数据、动作、能力、恢复、Renderer 和性能契约。

项目模型是事实来源，规范化 IR 是编译和运行的共同输入，发布快照是可复现和回滚的边界，Renderer 和 Host 只能通过已声明的契约扩展平台能力。高可用、高性能和高可维护性必须由静态检查、运行验证、性能基准、故障演练和版本兼容共同证明，不能由模型分层本身推定。

## 27. 可实施能力边界

前面的模型和契约是框架的核心，但不能把“已定义”当成“已提供”。每项能力必须同时标记设计状态、运行时接口、宿主实现和验证证据。上层只能依赖已经注册并通过兼容检查的能力。

```text
Project Model / IR
  ├── Web Runtime Contract
  ├── Debug Contract
  ├── Telemetry Ingest Contract
  ├── Telemetry Query Contract
  ├── Experiment Provider Contract
  ├── Security and Privacy Contract
  ├── Test and Verification Contract
  └── Build and Deployment Contract
```

核心框架只定义协议和生命周期，不内置具体日志平台、实验平台、数据库、身份服务或云厂商 SDK。每个协议都必须提供版本、Schema、稳定错误码、兼容范围、能力声明、降级策略和契约测试。未实现或未验证的协议不得在发布清单中标记为生产可用。

## 28. Web Runtime Contract

Web Renderer 必须把浏览器行为落实为可验证的运行时契约，而不是只提供组件渲染函数。契约至少包括：

- 浏览器支持矩阵、资源基路径和生产路由重写要求；
- `push`、`replace`、`back`、深链接、刷新、未知路由和权限拒绝行为；
- 页面实例创建、激活、挂起、恢复和销毁；
- SSR、静态生成或纯客户端模式的选择，以及序列化和 Hydration 边界；
- 浏览器专用 API 的能力检测、权限拒绝、暂不可用和不支持状态；
- 请求取消、超时、重试、缓存失效和用户切换时的数据隔离；
- 错误边界、资源失败、空状态、加载状态和可恢复入口；
- 文档标题、焦点入口、键盘导航、语义角色和可访问性失败诊断；
- Service Worker、离线缓存和更新接管策略（如果目标产品声明支持离线）；
- Web Vitals、资源体积、首屏和交互性能预算。

Renderer 必须输出确定性的运行时标识，包括 `page_instance_id`、`component_instance_id` 和 `render_revision`。解释模式和编译模式必须使用同一契约，并对导航、状态、错误、取消和可访问性行为执行一致性测试。

## 29. Debug Contract

Debug 能力分为本地开发、预览环境和生产受控诊断三个等级。所有等级都必须通过权限、环境和数据分类检查。

Debug API 至少支持：

- 按 `release_id`、页面实例和交互实例读取运行上下文；
- 读取组件树、图层树、页面状态和状态修订；
- 订阅导航、动作、状态变更、网络和宿主能力事件；
- 在已声明的检查点暂停、继续和读取快照；
- 查询请求的取消、重试、未知结果和最终确认状态；
- 使用 Source Map 将编译错误映射回源资源和模型对象；
- 对错误进行聚类、去重、关联和首次出现版本定位；
- 采集可选的用户流程回放数据，但必须遵守字段屏蔽、同意和保留策略；
- 远程诊断授权、过期、审计和强制撤销。

Debug 快照与发布快照、恢复快照是不同对象。快照必须限制大小、深度、保存时间和敏感字段；生产环境默认不允许任意暂停，也不能长期占用业务临界资源。暂停、继续、读取和导出都必须具有稳定请求 ID、权限主体、审计记录和幂等语义。

## 30. Telemetry Ingest 与 Query Contract

### 30.1 接收契约

Telemetry SDK 和接收端必须共同实现：

- 批量、压缩、退避、取消、断网缓存和有界队列；
- `event_id` 去重、顺序信息、客户端发生时间和服务端接收时间；
- Schema、大小、深度、高基数字段和隐私分类校验；
- 采样决策、丢弃原因、队列延迟和重试次数；
- 普通日志、运营事件、性能样本和 Business Fact 的不同可靠性等级；
- Business Fact 的提交确认、消费凭据、重复消费和未知结果查询；
- 采集故障不阻断核心页面，除非调用方声明该事件是可靠业务事实。

### 30.2 查询契约

框架必须提供版本化查询和导出接口，至少支持：

```text
query_events(filter, group_by, measures, time_range, page_token)
get_event_schema(event_name, schema_version)
get_trace(trace_id)
export_events(filter, format, retention_scope)
get_data_quality(scope, time_range)
```

查询过滤器必须限制时间范围、版本、平台、页面、实验、错误类型和事件类型，禁止默认返回无限明细。响应必须包含 Schema 版本、数据截止时间、采样比例、丢失率、分页令牌和一致性级别。原始事件、聚合结果、诊断索引和回放数据分别配置保留期限、容量预算、访问角色和删除策略。

指标口径、漏斗步骤、留存窗口和聚合维度必须作为版本化分析资源登记。框架提供事件投影和基础聚合能力；统计显著性、实验结论和业务解释由外部分析或实验系统完成。

## 31. Experiment Provider Contract

外部实验系统通过 Provider 接入，不能直接修改运行时内部状态。Provider 至少提供：

```text
resolve_assignment(experiment_id, subject_scope, release_context)
get_experiment_config(experiment_id, assignment_id)
record_exposure(exposure_event)
get_experiment_status(experiment_id)
```

返回值必须包含 `assignment_id`、实验组、配置版本、分流来源、有效期、目标平台、兼容范围和停用状态。框架负责 Schema、权限、平台能力、发布版本和有效期校验，并将有效结果冻结到运行实例。

曝光事件只能由页面或功能在真实可见且可操作后产生。Provider 不得通过配置启用未注册代码、未声明宿主能力、绕过权限或修改历史曝光。Provider 不可用、结果缺失、配置过期或版本不兼容时，框架使用发布快照中声明的默认变体并记录降级原因。

实验配置刷新默认只影响新建页面实例。页面恢复继续使用原分流归属，除非实验协议明确允许重新分流。停用只能停止新曝光，不能改写已确认的历史归属。

## 32. Security and Privacy Contract

安全和隐私必须成为发布门禁，而不是 Telemetry 的附加说明。契约至少包括：

- 身份认证、会话续期、权限拒绝和登出后的数据清理；
- CSP、Trusted Types、XSS 防护、第三方脚本清单和资源完整性；
- 浏览器端配置与服务端密钥的隔离，禁止把凭据写入模型、日志、快照或事件；
- 用户、设备、会话和实验身份的分离及最小化使用；
- 采集同意、敏感字段分类、字段屏蔽、哈希化、保留和删除；
- Debug、查询、导出、实验配置和远程控制的主体、角色、作用域和审计；
- 跨租户、跨项目、跨发布和跨实验的数据隔离；
- 第三方依赖、扩展和 Host Capability 的签名、版本锁定和撤销。

安全检查失败时不得通过默认配置或降级路径绕过。发布清单必须记录安全策略摘要、依赖摘要、隐私版本和审计策略版本。

## 33. 测试、构建与部署契约

每个 Renderer 和 Host 必须提供以下测试层：

- Schema、规范化、迁移、引用和静态诊断测试；
- 组件、页面、导航、状态、动作和错误边界测试；
- 浏览器端路由、深链接、刷新、恢复和权限场景测试；
- 端到端业务流程测试和关键页面视觉回归测试；
- 可访问性自动化测试及键盘、焦点和屏幕阅读器抽查；
- 解释模式与编译模式的一致性测试；
- 资源失败、离线、超时、重复提交、未知结果和版本回滚故障注入；
- Bundle、Web Vitals、内存、启动、导航和交互性能预算测试。

构建系统必须生成可追踪的产物清单、Source Map、依赖摘要、路由清单、Telemetry/Experiment Schema 清单和安全策略摘要。部署系统必须验证资源完整性、基路径、重写规则、配置兼容性、缓存策略和回滚条件。开发服务器成功不能替代生产预览或目标浏览器验证。

## 34. 优化后的实施顺序

在原有六个阶段基础上，实施顺序调整为：

1. 先完成 Project Model、IR、Schema、引用索引和最小 Data/Action/Recovery/Telemetry 契约；
2. 完成 Web Runtime Contract 和一个可运行的 Web Renderer，先覆盖客户端渲染、路由、状态、错误和可访问性；
3. 同步完成 Telemetry SDK、接收接口、查询接口和隐私校验，避免先产生不可查询的事件；
4. 完成 Debug Contract 的本地和预览能力，再接入受控生产诊断；
5. 以 Experiment Provider 接口接入外部分流和配置系统，验证曝光、冻结、恢复、停用和回滚；
6. 建立安全门禁、端到端测试、视觉回归、性能基准和生产预览；
7. 最后扩展编译器、可视化编辑器和移动/桌面 Renderer。

每个阶段的完成条件必须同时包含：协议实现、契约测试、故障注入、性能数据、隐私检查和实际运行证据。只有设计文件或内存替身通过，不能标记为生产能力。

## 35. 优化后的结论

MicroFlow Frontend 可以作为现代前端平台的底层模型和能力协议，但完整能力来自以下闭环：

```text
模型 → Schema/IR → Renderer/Host → 运行实例
                     ↓
          Debug / Telemetry / Experiment
                     ↓
        Query / Analysis / Release / Recovery
```

上层业务可以通过稳定的组件、数据、动作、能力、观测和实验接口构建产品；下层必须提供可查询、可审计、可恢复、可测试和可回滚的运行证据。当前仓库仍处于后端和本地运行时的实施阶段，Web Renderer、查询面、完整 Debug 和生产安全门禁完成前，不应宣称已经支持全部现代前端能力。

