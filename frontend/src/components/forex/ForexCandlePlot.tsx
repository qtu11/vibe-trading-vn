import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";
import { calcEMA } from "@/lib/indicators";
import { forexCandleTooltip, type ForexChartSnapshot } from "@/lib/forexChart";

export function ForexCandlePlot({ snapshot }: { snapshot: ForexChartSnapshot }) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<ReturnType<typeof echarts.init> | null>(null);
  const dark = useThemeDark();
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  useEffect(() => {
    if (!container.current) return;
    const chart = echarts.init(container.current);
    instance.current = chart;
    const t = getChartTheme();
    chart.setOption({ animation: false, backgroundColor: "transparent", useUTC: true,
      grid: [{ left: 12, right: 84, top: 28, height: "64%" }, { left: 12, right: 84, top: "77%", height: "10%" }],
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      xAxis: [0, 1].map(gridIndex => ({ type: "category", data: [], gridIndex, boundaryGap: true,
        axisLine: { lineStyle: { color: t.axisColor } }, axisTick: { show: false },
        axisLabel: { color: t.textColor, show: gridIndex === 1, formatter: (v: string) => v.slice(5, 16).replace("T", " ") } })),
      yAxis: [0, 1].map(gridIndex => ({ type: "value", scale: true, position: "right", gridIndex,
        splitNumber: gridIndex === 1 ? 2 : 5,
        axisLabel: { color: t.textColor, fontSize: 10 }, splitLine: { show: gridIndex === 0, lineStyle: { color: t.gridColor } } })),
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 55, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], bottom: 2, height: 20, start: 55, end: 100 }],
      tooltip: { trigger: "axis", axisPointer: { type: "cross" }, backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder, textStyle: { color: t.tooltipText }, confine: true,
        extraCssText: "max-width:100%;white-space:normal;overflow-wrap:anywhere;",
        formatter: forexCandleTooltip },
      series: [],
    });
    let frameId = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(() => chart.resize());
    });
    observer.observe(container.current);
    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, [dark]);
  useEffect(() => {
    const chart = instance.current;
    if (!chart) return;
    const t = getChartTheme();
    const dates = snapshot.bars.map(b => b.time);
    chart.setOption({
      xAxis: [{ data: dates }, { data: dates }],
      series: [{ id: "candles", name: "OHLC", type: "candlestick",
        data: snapshot.bars.map(b => ({ value: [b.open, b.close, b.low, b.high],
          itemStyle: b.complete ? undefined : { borderWidth: 2, opacity: .7 } })),
        itemStyle: { color: t.upColor, color0: t.downColor, borderColor: t.upColor, borderColor0: t.downColor },
        markLine: { symbol: "none", silent: true, label: { position: "end", formatter: (p: { name: string; value: number }) => `${p.name} ${p.value}` },
          data: [{ name: "Bid", yAxis: Number(snapshot.quote.bid), label: { show: false }, lineStyle: { color: t.infoColor } },
            { name: "Ask", yAxis: Number(snapshot.quote.ask), lineStyle: { color: t.warningColor, type: "dashed" } }] } },
      { id: "ema20", name: "EMA20", type: "line", data: calcEMA(snapshot.bars.map(b => b.close), 20),
        symbol: "none", lineStyle: { color: t.warningColor, width: 1 } },
      { id: "ticks", name: "Ticks", type: "bar", xAxisIndex: 1, yAxisIndex: 1,
        data: snapshot.bars.map(b => ({ value: b.volume, itemStyle: { color: b.close >= b.open ? t.volumeUp : t.volumeDown } })) }],
    }); // Merge by series id: preserve user's zoom/pan on every refresh.
  }, [snapshot, dark]);
  // ECharts retains an absolutely positioned hidden tooltip after resizing.
  // Keep it in the canvas bounds so it cannot widen the surrounding layout.
  return <div ref={container} className="h-96 w-full min-w-0 overflow-hidden" role="img"
    aria-label={vi ? `Biểu đồ nến ${snapshot.symbol}, ${snapshot.timeframe}, giờ UTC; bảng OHLC nằm bên dưới` : `${snapshot.symbol} ${snapshot.timeframe} candlestick chart, UTC; OHLC table available below`} />;
}
