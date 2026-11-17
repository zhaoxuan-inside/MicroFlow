import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { initI18n, ToastProvider } from "@microflow4kit/ui";
import { App } from "./App";
import "./index.css";
import "./i18n";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

// import 副作用先登记全部命名空间（bizops + admin + ui），此处一次性装载
initI18n();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <App />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
