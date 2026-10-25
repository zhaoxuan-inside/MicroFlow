# 知乎系列文章

面向知乎平台的三篇连载（发布时可按平台习惯调整标题与排版；技术事实以仓库代码与测试为准）：

1. [给 VibeCoding 修一条轨道：MicroFlow 的愿景、原理与设计思想](01-vision-and-philosophy.md) —— 从"AI 交付假完成"的痛点出发，阐述框架的原点命题（二义性的转移与压缩）与四个设计支柱（配置表达力预算、子图即复合算子、观测分层、零依赖内核）、诚实边界底线。
2. [后端篇：算子 + 编排——用 MicroFlow 从零攒一个交易平台](02-python-usage.md) —— 算子契约、编排 JSON、CLI 回路（check/run/impact）、影响分析、监控运营聚合与边界声明；全部示例来自 `MicroFlow4Python/examples/trading/`。
3. [前端篇：页面即配置——用 MicroFlow Flutter 声明同一个交易平台](03-flutter-usage.md) —— 三平面分离、声明式页面与绑定、零埋点观测、authoring 命令面与门禁纪律；示例来自 `MicroFlow4Flutter/apps/trading_app/`。

发布约定：文中的命令、输出与数字均来自仓库实测（测试 227/64 项、交易示例的 releaseId 与金额等可复现）；转载请注明仓库地址。
