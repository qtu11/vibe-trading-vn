import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { ForexLiveChart } from "./ForexLiveChart";
import type { ForexFrame } from "@/lib/forexChart";

/** Mount polling only when the user opens this particular saved answer's chart. */
export function ForexPlanChart({ connectionId, symbol }: { connectionId: string; symbol: string }) {
  const [open, setOpen] = useState(false);
  const [frame, setFrame] = useState<ForexFrame>("5m");
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  return <div className="rounded-lg border p-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
      <button className="font-medium underline underline-offset-4" aria-expanded={open} onClick={() => setOpen(p => !p)}>{open ? vi ? "Ẩn biểu đồ nến" : "Hide candle chart" : vi ? "Mở biểu đồ nến trực tiếp" : "Open live candle chart"}</button>
      <Link className="text-primary underline underline-offset-4" to={`/forex?${new URLSearchParams({ connection_id: connectionId, symbol })}`}>{vi ? "Mở trang Forex" : "Open Forex workspace"}</Link>
    </div>
    {open && <div className="mt-3"><ForexLiveChart connectionId={connectionId} symbol={symbol} frame={frame} onFrameChange={setFrame} /></div>}
  </div>;
}
