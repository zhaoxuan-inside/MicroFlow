import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { ThemeProvider } from "@microflow4kit/ui";
import { ErrorBoundary } from "@microflow4kit/ui";
import { AppShell } from "./shell/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";
import { OperatorsPage } from "./pages/OperatorsPage";
import { OperatorDetailPage } from "./pages/OperatorDetailPage";
import { SubgraphsPage } from "./pages/SubgraphsPage";
import { ScenariosPage } from "./pages/ScenariosPage";
import { GraphAssetDetailPage } from "./pages/GraphAssetDetailPage";
import { ReleasesPage } from "./pages/ReleasesPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { ConfigsPage } from "./pages/ConfigsPage";

export function App() {
  return (
    <ThemeProvider>
      <ErrorBoundary>
        <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/operators" element={<OperatorsPage />} />
            <Route path="/operators/:name" element={<OperatorDetailPage />} />
            <Route path="/subgraphs" element={<SubgraphsPage />} />
            <Route path="/subgraphs/:code" element={<GraphAssetDetailPage assetKind="subgraph" />} />
            <Route path="/scenarios" element={<ScenariosPage />} />
            <Route path="/scenarios/:code" element={<GraphAssetDetailPage assetKind="scenario" />} />
            <Route path="/releases" element={<ReleasesPage />} />
            <Route path="/experiments" element={<ExperimentsPage />} />
            <Route path="/configs" element={<ConfigsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </ErrorBoundary>
    </ThemeProvider>
  );
}