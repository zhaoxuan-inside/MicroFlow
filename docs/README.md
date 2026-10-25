# MicroFlow 文档

## 设计基线

### 后端执行框架（业务算子与流程执行；对应实现 MicroFlow4Python）

- [平台标准设计方案 v1.4](design/platform-standard-design.md)：平台协议、持久化提供者接口、配置化算子执行属性、子图治理纪律及发布恢复要求；语言无关设计基线，以 Python 为首个实现参照。
- [框架内部功能技术选型 v1.3](design/technical-selection.md)：22 项内部算法、数据结构与接口决策，具体介质由上层绑定，不进入核心依赖。
- [算法与一致性设计 v1.10](design/algorithms-and-consistency.md)：DAG、动态依赖、介质无关提交、配置解析、幂等、缓存、发布算法及静态影响反向索引。

后端执行框架的需求与行为以平台标准设计为准，技术实现遵守配套选型和一致性设计。

### 前端框架（元组件、样式与页面编排；对应实现 MicroFlow4Flutter）

- [前端框架完整设计方案 v1.12](design/frontend-framework-design.md)：面向 Vibe Coding 的元组件、组件、图层、页面、产品模型，样式与主题模型、交互与绑定语法、绑定映射，以及编译器、运行时、Renderer 和发布边界；代码、数据、配置三平面分离（§2.9）与文案通道判定（§42.7）；框架不提供可视化编辑器，向上层工具提供编排接入协议。
- [外部功能接入规范 v1.0](design/external-capability-integration-spec.md)：宿主实现（统一资源注册）、上层工具（结构化命令与项目模型读写）、平台服务（遥测/实验/Debug 契约）三类接入方的通道、交付物与验收清单；对前端设计方案接入面的操作化收敛，不引入新语义。

前端框架的需求与行为以《前端框架完整设计方案》为基线；接入面以《外部功能接入规范》为操作化收敛。

### 工具接入（跨实现）

- [CLI 命令体系设计 v1.0](design/cli-command-system-design.md)：面向 VibeCoding 工具的 CLI 兼容契约（信封、退出码、诊断码、能力探测）、17 个命令的封闭集合与状态、一致性测试判定与实施映射；对平台标准 §16 / TS-18 接入面的操作化收敛，不引入新语义。设计基线草案，实现由 T14/T15 管理。

### 配套资源

机器可读资源：[一致性基线投影 v1.0](design/baselines.json) —— 前端框架 §44.3 全部 32 条基线的投影，测试以「基线 N」引用，覆盖表由 `MicroFlow4Flutter/tool/baseline_coverage.dart` 生成；该文件随基线设计同步修订，不引入新语义。

对应的语言实现位于 [MicroFlow4Python](../MicroFlow4Python/README.md) 与 [MicroFlow4Flutter](../MicroFlow4Flutter/README.md)，实现状态以子项目 README、测试和后续实施记录为准。

本文档目录是项目内的设计维护入口；先前会话输出保留为历史参考，不与仓库内文档并行维护为两份权威版本。

## 实施规划

- [实施任务规划](implementation-plan.md)：依据后端执行框架设计拆分 T01～T16，列明现有代码基线、依赖顺序、完成条件、A01～A35 验收归属及实施前待决项。任务状态与验证证据在该计划中更新；计划完成不代表实现或验收完成。
