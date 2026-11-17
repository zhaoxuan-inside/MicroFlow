/** 实验读出：按实验键读取真实分配与结果指标聚合（平台管理员视角跨项目读取）。 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { dispatch } from "@microflow4kit/api";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Field,
  Input, PageHeader, PermissionGate, Spinner,
} from "@microflow4kit/ui";

interface Readout {
  experiment: { key: string; name: string; status: string; traffic_percent: number };
  total_assignments: number;
  variants: Array<{
    variant: string;
    assignments: number;
    metrics: Record<string, { count: number; sum: number; avg?: number }>;
  }>;
}

export function ExperimentsPage() {
  const { t } = useTranslation("bizops");
  const [key, setKey] = useState("");
  const [submitted, setSubmitted] = useState("");
  const readout = useQuery({
    queryKey: ["bizops", "experiment-readout", submitted],
    queryFn: () => dispatch<Readout>("experiment.readout", { experiment_key: submitted }),
    enabled: Boolean(submitted),
  });

  return (
    <div>
      <PageHeader title={t("nav.experiments")} description={t("experiments.description")} />
      <PermissionGate
        permission="page:bizops_console"
        fallback={<Card className="p-6 text-sm text-muted-foreground">{t("gate")}</Card>}
      >
        <Card className="mb-4">
          <CardContent className="flex items-end gap-3 px-4 py-3">
            <Field label={t("experiments.keyLabel")}>
              <Input className="h-8 w-64 text-xs" value={key} onChange={(e) => setKey(e.target.value)}
                placeholder={t("experiments.keyPlaceholder")} />
            </Field>
            <Button className="h-8 text-xs" disabled={!key} onClick={() => setSubmitted(key)}>
              {t("experiments.submit")}
            </Button>
          </CardContent>
        </Card>

        {submitted && readout.isPending && (
          <Card><CardContent className="flex justify-center py-16"><Spinner /></CardContent></Card>
        )}
        {submitted && readout.isError && (
          <Card><div className="p-5"><EmptyState title={t("experiments.notFound")} hint={readout.error instanceof Error ? readout.error.message : t("experiments.notFoundHint")} /></div></Card>
        )}
        {readout.data && (
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CardTitle className="text-base">{readout.data.experiment.name}</CardTitle>
                <Badge tone={readout.data.experiment.status === "RUNNING" ? "success" : "neutral"}>
                  {readout.data.experiment.status}
                </Badge>
                <span className="text-xs tabular-nums text-muted-foreground">{t("experiments.traffic", { n: readout.data.experiment.traffic_percent })}</span>
              </div>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 font-medium font-mono uppercase">{t("experiments.colVariant")}</th>
                    <th className="py-2 font-medium font-mono uppercase">{t("experiments.colAssigned")}</th>
                    <th className="py-2 font-medium font-mono uppercase">{t("experiments.colMetric")}</th>
                  </tr>
                </thead>
                <tbody>
                  {readout.data.variants.map((v) => (
                    <tr key={v.variant} className="border-b border-border/50 last:border-0">
                      <td className="py-2 font-medium">{v.variant}</td>
                      <td className="py-2 tabular-nums">{v.assignments}</td>
                      <td className="py-2 text-xs text-muted-foreground">
                        {Object.entries(v.metrics).length
                          ? Object.entries(v.metrics).map(([m, s]) => `${m}: n=${s.count} avg=${s.avg ?? 0}`).join(" · ")
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </PermissionGate>
    </div>
  );
}
