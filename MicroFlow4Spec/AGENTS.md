# AGENTS.md —— MicroFlow4Spec（需求与验收基线）

纯逻辑 TS 包：模型/门禁/矩阵/证据合并/diff + 薄 CLI（`src/cli.ts`，node 直跑）。**零第三方依赖**；vitest 仅 devDependency。

## 架构事实（先查再改）

- 模型即契约：`src/model/types.ts` 定义 v1 形态，`src/model/validate.ts` 是唯一门禁（未知字段拒绝、字段级诊断指向字段本身、悬空引用 error、空 requirementRefs = 待挂接矩阵洞）。
- 诊断码单一来源：`src/diagnostics.ts`（`spec.<area>.<name>`），发出未登记码 = 实现缺陷（守卫测试固定格式与唯一性）。
- 摘要 = SHA-256 规范化 JSON（键递归排序，`src/core/canonical.ts`）——与宿主 `config_hash` 同语义；确定性输出纪律依赖它。
- 证据合并只消费 `microflow-verify-v1` 信封的 `script/verdict/summary` 最小面；`summary.failed > 0` 却 `verdict = pass` 的自证报告按坏报告拒绝。

## 门禁语义（改前必读）

| 命令 | exit 0 | exit 1 | exit 2 |
|---|---|---|---|
| check | 0 error 诊断 | 有 error | JSON 不可解析 |
| coverage | uncovered=0 且 orphans=0 | 有矩阵洞 | JSON 不可解析 |
| verify | ui_script 场景全部 pass | fail/pending/坏报告 | 报告不可读 |
| diff | 恒 0（信息性） | — | 任一侧模型损坏 |

- pending 拦门禁（"没跑 = 通过"不存在）；manualOnly 是 info 不拦截——两层语义不要混。
- `manual` 场景是诚实披露（人审证据），不是绕过门禁的后门。

## 纪律

- 新字段先进 `types.ts` + `validate.ts` + 测试负例，再谈消费方；禁止先在合并/矩阵层偷读未登记字段。
- CLI 输出确定性：同输入字节一致（时间戳类信息不进信封）。
- 测试：`npm test`（vitest，node 环境）；`npm run typecheck` 全绿。
- 共享盘：`npm install --no-bin-links`；vitest 经 `node node_modules/vitest/vitest.mjs run` 直跑。
