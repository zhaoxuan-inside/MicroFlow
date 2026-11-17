/** 运营总览：真实 KPI（实体在册量/近 24h 场景运行）+ 按日趋势（审计足迹 + 运行记录）。 */
import { useQuery } from "@tanstack/react-query";
import { entityLabelKey } from "../lib/entities";

/** 实体名 → 文案键（bizops.entity_*）。 */
const ENTITY_LABELS: Record<string, string> = {
  "user.account": "entity_user_account",
  "forum.thread": "entity_forum_thread",
  "product.item": "entity_product_item",
  "demands.item": "entity_demands_item",
  "policy.item": "entity_policy_item",
  "perk.item": "entity_perk_item",
  "sop.template": "entity_sop_template",
  "interaction.record": "entity_interaction_record",
};
import { useTranslation } from "react-i18next";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { dispatch } from "@microflow4kit/api";
import { Card, CardContent, CardHeader, CardTitle, PageHeader, PermissionGate, Spinner } from "@microflow4kit/ui";

interface Overview {
  entities: Record<string, number>;
  runs_24h: number;
}
interface Trend {
  series: Array<{ day: string; events: number; denied: number; active_actors: number; scenario_runs: number }>;
  sample_size: number;
  note: string;
}

/** 实体名 → 文案键（bizops.entity_*）；未登记实体如实回退显示原名。 */


export function OverviewPage() {
  const { t } = useTranslation("bizops");
  const overview = useQuery({
    queryKey: ["bizops", "overview"],
    queryFn: () => dispatch<Overview>("bizops.overview", {}),
  });
  const trend = useQuery({
    queryKey: ["bizops", "trend"],
    queryFn: () => dispatch<Trend>("bizops.trend", { days: 14 }),
  });

  const entities = Object.entries(overview.data?.entities || {});
  const series = trend.data?.series || [];

  return (
    <div>
      <PageHeader title={t("nav.overview")} description={t("overview.description")} />
      <PermissionGate
        permission="page:bizops_console"
        fallback={<Card className="p-6 text-sm text-muted-foreground">{t("gate")}</Card>}
      >
        {overview.isPending ? (
          <Card><CardContent className="flex justify-center py-16"><Spinner /></CardContent></Card>
        ) : (
          <div className="mb-4 grid gap-4 grid-cols-2 lg:grid-cols-4">
            {/* 主指标卡：近 24h 场景运行 + 迷你趋势 */}
            <Card className="col-span-2 border-primary/30">
              <CardHeader>
                <CardTitle className="text-muted-foreground">{t("overview.runs24h")}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-5xl font-semibold tracking-tight tabular-nums">{overview.data?.runs_24h ?? 0}</div>
                <div className="mt-2 h-10">
                  {series.length > 0 && (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={series}>
                        <Line type="monotone" dataKey="scenario_runs" stroke="#0070f3" dot={false} strokeWidth={1.5} />
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </CardContent>
            </Card>
            {entities.map(([name, count]) => (
              <Card key={name}>
                <CardHeader>
                  <CardTitle className="text-muted-foreground">
                    {entityLabelKey(name, ENTITY_LABELS) !== name ? t(`overview.${entityLabelKey(name, ENTITY_LABELS)}`) : name}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-semibold tracking-tight tabular-nums">{count}</div>
                </CardContent>
              </Card>
            ))}
            {/* 趋势迷你卡补满网格 */}
            <Card className="col-span-2">
              <CardHeader><CardTitle className="text-muted-foreground">{t("overview.seriesAudit")}</CardTitle></CardHeader>
              <CardContent>
                <div className="text-3xl font-semibold tracking-tight tabular-nums">
                  {series.reduce((s, r) => s + (r.events || 0), 0)}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{t("overview.trendTitle")}</p>
              </CardContent>
            </Card>
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle>{t("overview.trendTitle")}</CardTitle>
            {trend.data && (
              <p className="text-xs text-muted-foreground">
                {trend.data.note} · {t("overview.sampleNote", { n: trend.data.sample_size })}
              </p>
            )}
          </CardHeader>
          <CardContent>
            {trend.isPending ? (
              <div className="flex justify-center py-16"><Spinner /></div>
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={series}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border, #e5e7eb)" />
                    <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="events" name={t("overview.seriesAudit")} stroke="#6366f1" dot={false} />
                    <Line type="monotone" dataKey="active_actors" name={t("overview.seriesActors")} stroke="#22c55e" dot={false} />
                    <Line type="monotone" dataKey="scenario_runs" name={t("overview.seriesRuns")} stroke="#f59e0b" dot={false} />
                    <Line type="monotone" dataKey="denied" name={t("overview.seriesDenied")} stroke="#ef4444" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
      </PermissionGate>
    </div>
  );
}
