/// MicroFlow4Verify 公共 API 面：脚本门禁、面端口、runner、web 面、CLI。
export * from './diagnostics.ts';
export * from './script/types.ts';
export { validateScript, toVerifyScript } from './script/validate.ts';
export { extractFacts, type ProjectFacts } from './script/facts.ts';
export type { VerifySurface, SurfaceImpls, SurfaceOptions, SurfacePage, CapturedEvent, SurfaceDiag } from './surface/port.ts';
export { createWebSurface, webStandardEvents } from './surface/web.ts';
export { runVerifyScript, type VerifyReport, type VerifyAssertion, type RunVerifyOptions } from './runner.ts';
export { runVerifyCli } from './cli.ts';
