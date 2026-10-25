/// MicroFlow 前端创作接入面（§14 结构化命令面）的公共导出。
///
/// 依赖方向：model ← runtime ← authoring。编辑器、CLI 与 AI Agent 通过
/// 本包以结构化命令操作项目模型；任何修改都必须通过同一静态校验门禁
/// （§2.7、§18.1），失败时项目保持不变，不产生隐式状态。
library;
export 'src/authoring.dart';
export 'src/capabilities.dart';
