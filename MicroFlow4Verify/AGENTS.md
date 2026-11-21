# AGENTS.md —— MicroFlow4Verify（端到端验收运行器）

纯逻辑 TS 包 + 薄 CLI。**零第三方依赖**；跨包消费 MicroFlow4Web 源码（族内相对路径 + tsconfig include，不用 npm file 依赖——对齐 Kit 的族内约定）。

## 架构事实（先查再改）

- **面中性是本包的骨架**：`src/runner.ts` 与 `src/script/*` 不 import 任何渲染器；唯一 import 4Web 的文件是 `src/surface/web.ts`。换渲染面只动 surface 层，测试里 FakeSurface 覆盖 runner 全逻辑。
- 脚本门禁 `src/script/validate.ts`：断言引用已注册锚点（节点/契约事件/标准事件/页面）；`IMPLEMENTED_OPS` 与 `DECLARED_OPS` 之差 = 已声明未实现（`vrf.op.unimplemented` 静态拒绝）。
- 诊断码单一来源 `src/diagnostics.ts`（`vrf.*`），守卫测试固定格式与唯一性。
- fill 语义 = Tier A input 的 change 载荷 `{value}`（与 DOM 渲染器同契约，`primitives.ts:125`）；模型侧 guard 在链开始前求值，**不能引用本链 prev**——auth 类模型须"适配器写 state + 第二绑定 guard 读 state"（fixture `demo.project.json` 是范式）。

## 门禁语义

| 场景 | exit | 说明 |
|---|---|---|
| verdict pass | 0 | 全部断言 pass 且无中断 |
| 断言 fail/skipped | 1 | fail detail 带 expected/actual |
| 脚本/模型不可读、静态门禁不过、模型 MFValidator 有 error | 2 | `requestFailed: true` + diagnostics |

- 运行中抛错：当前步合成失败断言（error 明细），后续 expect 步记 skipped——不静默吞。
- 面诊断透明披露（meta.surfaceDiagnostics），不改变判定；判定与披露分离。

## 纪律

- 新步骤 op：先 `types.ts`（DECLARED_OPS/STEP_KEYS）→ `validate.ts` → `runner.ts` → 测试负例；不许先在 runner 偷读未登记 op。
- 4Web 侧改动后本包 `npm test` + `npm run typecheck` 必须回归（tsconfig include 覆盖 4Web src）。
- node 直跑：`node --experimental-transform-types src/cli.ts ...`；vitest：`node node_modules/vitest/vitest.mjs run`。
- 期望面与执行面分离：Spec 定义"期望什么"，Verify 产出"证据"，Delivery 消费"证据"——三者只通过文件与信封耦合，禁止反向 import。
