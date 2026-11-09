/**
 * Crosshair Event Bus dong bo con tro chu thap giua cac bieu do da khung thoi gian (M1, M5, H1, D1)
 * Su dung thuat toan Tim kiem Nhi phan (Binary Search) tren epoch timestamp mili-giay.
 */
import type { ECharts } from "echarts/core";

export class MultiTimeframeCrosshairBus {
  private charts: Map<string, { instance: ECharts; timestamps: number[] }> = new Map();

  register(chartId: string, instance: ECharts, timestamps: number[]) {
    this.charts.set(chartId, { instance, timestamps });
  }

  unregister(chartId: string) {
    this.charts.delete(chartId);
  }

  updateTimestamps(chartId: string, timestamps: number[]) {
    const entry = this.charts.get(chartId);
    if (entry) {
      entry.timestamps = timestamps;
    }
  }

  broadcast(sourceChartId: string, sourceTimestamp: number) {
    for (const [id, { instance, timestamps }] of this.charts.entries()) {
      if (id === sourceChartId || timestamps.length === 0) continue;

      // Tim index co moc thoi gian gan nhat bang Binary Search
      let left = 0;
      let right = timestamps.length - 1;
      while (left <= right) {
        const mid = (left + right) >> 1;
        if (timestamps[mid] < sourceTimestamp) {
          left = mid + 1;
        } else {
          right = mid - 1;
        }
      }
      const targetIndex = Math.min(Math.max(0, left), timestamps.length - 1);

      instance.dispatchAction({
        type: "showTip",
        seriesIndex: 0,
        dataIndex: targetIndex,
      });
    }
  }
}

export const globalCrosshairBus = new MultiTimeframeCrosshairBus();
