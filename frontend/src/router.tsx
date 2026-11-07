import { Suspense, lazy, type ComponentType } from "react";
import { createBrowserRouter, useRouteError } from "react-router";
import { Layout } from "@/components/layout/Layout";

const Home = lazy(() => import("@/pages/Home").then((m) => ({ default: m.Home })));
const Agent = lazy(() => import("@/pages/Agent").then((m) => ({ default: m.Agent })));
const RunDetail = lazy(() =>
  import("@/pages/RunDetail").then((m) => ({ default: m.RunDetail })),
);
const Compare = lazy(() =>
  import("@/pages/Compare").then((m) => ({ default: m.Compare })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
const Runtime = lazy(() =>
  import("@/pages/Runtime").then((m) => ({ default: m.Runtime })),
);
const Forex = lazy(() => import("@/pages/Forex").then((m) => ({ default: m.Forex })));
const MarketResearch = lazy(() => import("@/pages/MarketResearch").then((m) => ({ default: m.MarketResearch })));
const Scheduled = lazy(() =>
  import("@/pages/Scheduled").then((m) => ({ default: m.Scheduled })),
);
const Reports = lazy(() =>
  import("@/pages/Reports").then((m) => ({ default: m.Reports })),
);
const PaperTrading = lazy(() => import("@/pages/PaperTrading").then((m) => ({ default: m.PaperTrading })));
const Portfolio = lazy(() =>
  import("@/pages/Portfolio").then((m) => ({ default: m.Portfolio })),
);
const Correlation = lazy(() =>
  import("@/pages/Correlation").then((m) => ({ default: m.Correlation })),
);
const AlphaZoo = lazy(() =>
  import("@/pages/AlphaZoo").then((m) => ({ default: m.AlphaZoo })),
);
const OptionsLab = lazy(() =>
  import("@/pages/OptionsLab").then((m) => ({ default: m.OptionsLab })),
);
const PixelOffice = lazy(() =>
  import("@/pages/PixelOffice").then((m) => ({ default: m.PixelOffice })),
);

function PageLoader() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
      Loading…
    </div>
  );
}

function wrap(Component: ComponentType) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

function RouteErrorFallback() {
  const error = useRouteError();
  const message = error instanceof Error ? error.message : "Đã xảy ra lỗi không mong muốn khi tải trang.";
  return (
    <div className="flex flex-col items-center justify-center p-8 text-center min-h-[50vh] space-y-4">
      <div className="rounded-full bg-destructive/10 p-3 text-destructive">
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>
      <h3 className="text-lg font-bold">Không thể hiển thị trang này</h3>
      <p className="text-sm text-muted-foreground max-w-md">{message}</p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
        >
          Tải lại trang
        </button>
        <button
          type="button"
          onClick={() => { window.location.href = "/"; }}
          className="rounded-lg border border-border px-4 py-2 text-xs font-semibold hover:bg-muted"
        >
          Về trang chủ
        </button>
      </div>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <RouteErrorFallback />,
    children: [
      { path: "/", element: wrap(Agent) },
      { path: "/about", element: wrap(Home) },
      { path: "/agent", element: wrap(Agent) },
      { path: "/pixel-office", element: wrap(PixelOffice) },
      { path: "/runtime", element: wrap(Runtime) },
      { path: "/forex", element: wrap(Forex) },
      { path: "/research", element: wrap(MarketResearch) },
      { path: "/scheduled", element: wrap(Scheduled) },
      { path: "/reports", element: wrap(Reports) },
      { path: "/paper-trading", element: wrap(PaperTrading) },
      { path: "/portfolio", element: wrap(Portfolio) },
      { path: "/settings", element: wrap(Settings) },
      { path: "/runs/:runId", element: wrap(RunDetail) },
      { path: "/compare", element: wrap(Compare) },
      { path: "/correlation", element: wrap(Correlation) },
      { path: "/options", element: wrap(OptionsLab) },
      { path: "/alpha-zoo", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/bench", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/compare", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/:alphaId", element: wrap(AlphaZoo) },
    ],
  },
]);
