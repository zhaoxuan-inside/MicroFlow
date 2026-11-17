# AGENTS.md —— MicroFlow4Flutter（前端框架）纪律速查

前置阅读：根 `AGENTS.md`、本目录 `README.md`（五步接入 + 命令面）、`DEVELOPER_GUIDE.md`。

## 三平面分离（每项资源恰好归属一个平面）

- **配置平面**：页面/交互/样式/i18n 全声明式，不携带可执行逻辑。
- **代码平面**：宿主注册的真实实现（Tier A/B 元组件、adapter）。
- **数据平面**：运行观测，不回写模型。
平面间只走声明通道；跨平面内联逻辑是静态错误。

## 工具路径：authoring 命令面（不要直接拼模型）

```dart
final caps = mfAuthoringCapabilities();          // 先探测
final session = MFAuthoringSession(model: ...);  // 逐命令过门禁
session.createPage(...); session.connectNavigation(...);
session.validateProject(); session.inspectImpact(...); session.undo(...);
```

- 每条命令过与发布相同的静态门禁；失败不改模型；MFRevision 审计可 LIFO 回滚。
- **前向引用禁止**（实战教训）：绑定引用的目标必须先存在——onEnter 绑定与页面同批创建、多页面分批推进。
- 结构化 findings 回流：`registerFinding`；自由文本替代是静态错误。

## 一致性基线纪律

- `baselines.json` 32 条机器可读基线是单一权威；测试以「基线 N」标记覆盖。
- 覆盖率表由 `tool/baseline_coverage.dart` 生成，**不要手工编辑**。
- 当前覆盖 23/32（另 4 条部分）——基线 6/9/10/24/25 未覆盖（编译模式/发布快照/性能门禁属 M3，未实现）。

## 元组件

Tier A 12 个（Text/Icon/Image/Button/Input/Select/Checkbox/Stack/Scroll/Overlay/List/Modal）+ Tier B 6 个（Grid/Split/Anchor/Tabs/Drawer/Table）——全部在 `contracts.dart` 单一来源注册；未注册引用是静态错误，实现与契约不符进错误边界。

## 运行语义（不要绕过）

- 三层状态 page/session/product + persistent；并发策略五档；guard 求值；超时进 unknown 台账（不当作失败）；错误边界绑定级+页面级。
- 标准运营事件族由运行时零埋点产生——**业务手工上报同类事件是静态错误**。
- 恢复协议：未知结果只进 unknown 台账，不自动重试。

## 测试

```bash
flutter analyze       # 每包独立
flutter test          # 总包基线测试；基线覆盖只升不降
```
