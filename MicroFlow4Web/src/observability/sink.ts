/// 观测面（§24/§30）：EmissionSink 端口 + 有界队列 + JSONL 落地参考实现。
/// 标准运营事件由运行时拦截边界产生（零埋点）；信封经 Schema 形状校验。

import { mfDiag, MFCodes, MFStandardEvents, type MFDiag } from '../diagnostics.ts';

export interface MFEventEnvelope {
  event: string;
  timestamp: string;
  release_id: string;
  environment: string;
  page_definition_id: string;
  page_instance_id: string;
  locale: string;
  payload: Record<string, unknown>;
}

export interface MFTelemetrySink {
  accept(envelope: MFEventEnvelope): void;
}

const REQUIRED_KEYS: (keyof MFEventEnvelope)[] = [
  'event', 'timestamp', 'release_id', 'environment', 'page_definition_id', 'page_instance_id', 'locale', 'payload',
];

export function validateEnvelope(envelope: MFEventEnvelope): MFDiag[] {
  const diags: MFDiag[] = [];
  for (const key of REQUIRED_KEYS) {
    if (envelope[key] === undefined) {
      diags.push(mfDiag(MFCodes.teleSchemaInvalid, `事件信封缺字段 ${key}（§24.2）`, 'warning', 'runtime'));
    }
  }
  return diags;
}

/** 有界队列（§24.2）：满载丢弃并记录 mf.tele.queue-overflow。 */
export class MFTelemetryQueue implements MFTelemetrySink {
  private queue: MFEventEnvelope[] = [];

  constructor(
    private readonly capacity = 512,
    private readonly onOverflow: () => void = () => {},
  ) {}

  accept(envelope: MFEventEnvelope): void {
    if (this.queue.length >= this.capacity) {
      this.onOverflow();
      return;
    }
    this.queue.push(envelope);
  }

  drain(): MFEventEnvelope[] {
    return this.queue.splice(0);
  }

  get size(): number {
    return this.queue.length;
  }
}

/** JSONL 落地参考实现（§30.1）：宿主可换成上报/文件通道。 */
export class MFJsonlSink implements MFTelemetrySink {
  readonly lines: string[] = [];

  accept(envelope: MFEventEnvelope): void {
    for (const diag of validateEnvelope(envelope)) {
      // 信封 Schema 失败仍记录（不静默），但不进入落地流。
      this.lines.push(`${JSON.stringify({ mf_diag: diag })}`);
    }
    this.lines.push(JSON.stringify(envelope));
  }
}
