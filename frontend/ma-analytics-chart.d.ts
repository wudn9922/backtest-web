declare module "@/lib/maAnalyticsChart.mjs" {
  export const MA_ANALYTICS_TARGET_TYPES: readonly string[];
  export const MA_ANALYTICS_OBSERVATION_ORIGINS: readonly string[];
  export const MA_ANALYTICS_TERMINAL_LABELS: Readonly<Record<string, string>>;
  export const MA_ANALYTICS_DAY2_STATUS_LABELS: Readonly<Record<string, string>>;

  export function buildAnalyticsDay2Marker(bar: any, selectedEvent: any): {
    eventId: string; date: string; status: string; label: string;
  } | null;

  export function buildAnalyticsStopPath(
    rows: any[], indexByDate: Map<string, number>, x: (index: number) => number, y: (value: number) => number,
  ): string;

  export function prepareMaAnalyticsChart(chart: any, selectedEventId: string | null, selection?: {
    targetType?: string; condition?: string; origin?: string;
  }): {
    bars: any[];
    events: any[];
    selectedEvent: any | null;
    targets: any[];
    selectedTarget: any | null;
    stopAudit: any[];
    failure: any | null;
    retestZoneHistory: any[];
    selectedTargetType: string;
    selectedCondition: string;
    selectedOrigin: string;
  };

  export function buildAnalyticsBoundaryPath(
    rows: any[], valueKey: string, x: (index: number) => number, y: (value: number) => number,
  ): string;
}
