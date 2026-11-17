/** 业务漏斗：步骤动作 × 去重操作者（口径如实披露：非严格时序）。 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dispatch } from "@microflow4kit/api";
import {
  Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Field,
  PageHeader, PermissionGate, Select, useToast,
} from "@microflow4kit/ui";

interface FunnelStep {
  step: string;
  actors: number;
  conversion_from_first: number;
}

export function FunnelPage() {
  const { t } = useTranslation("bizops");
  const { toast } = useToast();
  const actions = useQuery({
    queryKey: ["bizops", "actions"],
    queryFn: () => dispatch<{ actions: Array<{ action: string; count: number }>; sample_size: number; note: string }>("bizops.actions", {}),
  });
  const [steps, setSteps] = useState<string[]>(["auth.login"]);
  const [result, setResult] = useState<{ steps: FunnelStep[]; sample_size: number; note: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const topActions = (actions.data?.actions || []).filter((a) => !steps.includes(a.action));

  const run = async () => {
    setBusy(true);
    try {
      const res = await dispatch<{ steps: FunnelStep[]; sample_size: number; note: string }>(
        "bizops.funnel", { steps },
      );
      setResult(res);
    } catch (err) {
      toast({ title: t("funnel.failed"), description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title={t("nav.funnel")} description={t("funnel.description")} />
      <PermissionGate
        permission="page:bizops_console"
        fallback={<Card className="p-6 text-sm text-muted-foreground">{t("gate")}</Card>}
      >
        <Card className="mb-4">
          <CardHeader>
            <CardTitle>{t("funnel.stepsLabel")}</CardTitle>
            {actions.data && (
              <p className="text-xs text-muted-foreground">
                {actions.data.note} · {t("funnel.sampleNote", { n: actions.data.sample_size })}
              </p>
            )}
          </CardHeader>
          <CardContent className="space-y-3">
            {steps.map((step, i) => (
              <div key={i} className="flex items-center gap-2">
                <Badge>{i + 1}</Badge>
                <Select
                  className="h-8 max-w-md text-xs"
                  value={step}
                  onChange={(e) => setSteps(steps.map((s, j) => (j === i ? e.target.value : s)))}
                >
                  <option value={step}>{step}</option>
                  {(actions.data?.actions || []).map((a) => (
                    <option key={a.action} value={a.action}>{t("funnel.actionOption", { action: a.action, count: a.count })}</option>
                  ))}
                </Select>
                {steps.length > 1 && (
                  <Button variant="ghost" className="h-8 px-2 text-xs text-destructive"
                    onClick={() => setSteps(steps.filter((_, j) => j !== i))}>×</Button>
                )}
              </div>
            ))}
            <div className="flex gap-2">
              <Button variant="secondary" className="h-8 text-xs"
                onClick={() => setSteps([...steps, topActions[0]?.action || ""])} disabled={!topActions.length}>
                {t("funnel.addStep")}
              </Button>
              <Button className="h-8 text-xs" disabled={busy || steps.some((s) => !s)} onClick={run}>
                {busy ? t("funnel.computing") : t("funnel.submit")}
              </Button>
            </div>
          </CardContent>
        </Card>

        {result && (
          <Card>
            <CardHeader>
              <CardTitle>{t("funnel.resultTitle")}</CardTitle>
              <p className="text-xs text-muted-foreground">{result.note} · {t("funnel.sampleNote", { n: result.sample_size })}</p>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={result.steps}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border, #e5e7eb)" />
                    <XAxis dataKey="step" tick={{ fontSize: 10 }} interval={0} angle={-15} height={50} textAnchor="end" />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="actors" name={t("funnel.colActors")} fill="var(--color-primary, #6366f1)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 font-medium font-mono uppercase">{t("funnel.colStep")}</th>
                    <th className="py-2 font-medium font-mono uppercase">{t("funnel.colActors")}</th>
                    <th className="py-2 font-medium font-mono uppercase">{t("funnel.colConversion")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.steps.map((s) => (
                    <tr key={s.step} className="border-b border-border/50 last:border-0">
                      <td className="py-2 text-xs font-medium">{s.step}</td>
                      <td className="py-2 tabular-nums">{s.actors}</td>
                      <td className="py-2 tabular-nums text-muted-foreground">{(s.conversion_from_first * 100).toFixed(1)}%</td>
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

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
      {children}
    </span>
  );
}
