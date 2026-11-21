# MicroFlow4Spec —— 需求与验收基线

MicroFlow 全周期的"验收先行"载体：把需求描述与验收基线结构化为版本化数据（`spec.model.json`），需求 → 验收场景 → 实现载体三条边构成机器可判定的追踪矩阵。二义性压缩的第一站——需求期不再是没有轨道的自由文本（设计动机见根目录 [LIFECYCLE.md](../LIFECYCLE.md)）。

技术：纯 TypeScript，零第三方依赖；诊断码单一来源注册表（`spec.*`）；八条兼容契约风格的 CLI（统一信封 `microflow-spec-v1`、退出码 0 肯定/1 对象否定/2 请求失败、确定性输出）。

## 模型（spec.model.json v1）

- `requirements[]`：需求条目（id/title/statement/priority must|should|could/status open|accepted|delivered）
- `scenarios[]`：验收场景，四类期望面，各自对应证据执行器：
  - `backend_run`——MicroFlow4Python `test` 命令的期望输出对照
  - `orch_scenario`——编排控制面场景执行（E2E 阶段门禁证据）
  - `ui_script`——MicroFlow4Verify 声明式脚本（`microflow-verify-v1` 信封）
  - `manual`——人审证据，矩阵如实标记 `manualOnly`，不进机器门禁
- 场景挂接需求（可为空 = 待挂接矩阵洞，orphan 警告并拦门禁）；可选挂接实现载体（operator/flow/page/component/scene）

## 命令面

```bash
npm install --no-bin-links   # Samba 共享盘一律 --no-bin-links
npm test                     # vitest run（Node >= 22.7）
node src/cli.ts check <spec.json>     # 结构门禁（0 error 才继续）
node src/cli.ts coverage <spec.json>  # 覆盖矩阵；exit 0 = 全绿（无 uncovered/orphan）
node src/cli.ts verify <spec.json> <report.json...>   # 合并 verify 信封；pending/fail 都算未通过
node src/cli.ts diff <old.json> <new.json>            # 结构化增删改（信息性，exit 恒 0）
```

交付门禁语义：`coverage` 全绿（uncovered=0 且 orphans=0）+ `verify` 全 pass 才允许进入 Delivery 发布门禁；`manualOnly` 如实披露不拦截。

## 与其它子项目

- 消费：MicroFlow4Verify 的 `microflow-verify-v1` 信封（按 `script` 对号入座 ui_script 场景）
- 被 Delivery 消费：coverage 报告与模型内容寻址摘要（SHA-256 规范化 JSON，与框架 config_hash 同语义）

## 边界声明

- 载体（operator/flow/page/…）存在性校验属跨项目门禁，v1 只做结构校验。
- `backend_run` / `orch_scenario` 的证据执行器对接（4Python `test` 命令、控制面场景）属后续切片。
- 期望面的执行语义归各执行器；Spec 只做结构校验与证据对账，不重复实现执行。
