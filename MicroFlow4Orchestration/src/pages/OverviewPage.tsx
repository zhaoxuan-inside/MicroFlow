import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Button, Card, CardContent, CardHeader, CardTitle, PageHeader, Spinner } from "@microflow4kit/ui";
import { orchDispatch } from "../orchClient";

interface CatalogList {
  total?: number;
}

export function OverviewPage() {
  const navigate = useNavigate();
  const counts = useQuery({
    queryKey: ["catalog-counts"],
    queryFn: async () => {
      const [operators, subgraphs, scenarios] = await Promise.all([
        orchDispatch<CatalogList>("GET", "/operators?page=1&page_size=1"),
        orchDispatch<CatalogList>("GET", "/subgraphs?page=1&page_size=1"),
        orchDispatch<CatalogList>("GET", "/scenarios?page=1&page_size=1"),
      ]);
      return {
        operators: operators?.total ?? 0,
        subgraphs: subgraphs?.total ?? 0,
        scenarios: scenarios?.total ?? 0,
      };
    },
  });

  const stat = (label: string, value: number | undefined, hint: string) => (
    <Card>
      <CardHeader>
        <CardTitle className="text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight tabular-nums">
          {counts.isPending ? <Spinner /> : value ?? 0}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );

  return (
    <div>
      <PageHeader title="总览" description="三层资产目录与 MicroFlow release 概览" />
      {/* bento：场景为主指标占宽列，算子/子图次级 */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Card className="col-span-2 border-primary/30">
          <CardHeader>
            <CardTitle className="text-muted-foreground">场景</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-5xl font-semibold tracking-tight tabular-nums">
              {counts.isPending ? <Spinner /> : counts.data?.scenarios ?? 0}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">对外发布的业务流程（含运行时内置管线）</p>
          </CardContent>
        </Card>
        {stat("算子", counts.data?.operators, "契约化的最小业务单元")}
        {stat("子图", counts.data?.subgraphs, "可复用的复合编排")}
      </div>

      <Card className="mt-4">
        <CardHeader><CardTitle>快速开始</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <Button variant="secondary" className="h-9 justify-start" onClick={() => navigate("/operators")}>
            ⚙ 浏览算子目录
          </Button>
          <Button variant="secondary" className="h-9 justify-start" onClick={() => navigate("/scenarios")}>
            ⎇ 编辑场景画布
          </Button>
          <Button variant="secondary" className="h-9 justify-start" onClick={() => navigate("/releases")}>
            ⎋ 版本与发布审批
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
