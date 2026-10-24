## 0.1.0

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
