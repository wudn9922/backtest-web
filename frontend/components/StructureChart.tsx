"use client";

import { useMemo, useRef, useState } from "react";
import type { StructureArtifact } from "@/lib/api";
import { dateText, num, t } from "@/lib/i18n";

type Props = { artifact: StructureArtifact | null; className?: string };

/**
 * Numerical candlestick audit view.  Every candle, MA point and marker is
 * drawn from the persisted OHLC/event artifact; there is no image inference
 * path.  SVG keeps the view responsive on mobile and makes fullscreen safe.
 */
export default function StructureChart({ artifact, className = "" }: Props) {
  const shell = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const rows = useMemo(() => (artifact?.ohlc ?? []).map((row) => ({
    timestamp: String(row.timestamp ?? ""),
    date: String(row.date ?? row.timestamp ?? "").slice(0, 10),
    open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close),
    reference: row.reference_ma == null ? null : Number(row.reference_ma),
  })).filter((row) => [row.open, row.high, row.low, row.close].every(Number.isFinite)), [artifact]);
  const geometry = useMemo(() => {
    if (!rows.length) return null;
    const values = rows.flatMap((row) => [row.high, row.low, ...(row.reference == null ? [] : [row.reference])]);
    const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, Math.abs(max) * 0.01, 1e-9);
    const width = Math.max(720, rows.length * 10), height = 330;
    const y = (value: number) => 18 + (max - value) / span * (height - 36);
    return { width, height, y, candleWidth: Math.max(3, Math.min(8, width / Math.max(rows.length * 1.7, 1))) };
  }, [rows]);
  const toggleFullscreen = async () => {
    if (!shell.current) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      setFullscreen(false);
    } else {
      await shell.current.requestFullscreen?.();
      setFullscreen(true);
    }
  };
  if (!artifact || !geometry) return <div className={`structure-chart-empty ${className}`}>{t("No Structure chart data")}</div>;
  const markers = artifact.events ?? [];
  const pointForDate = (value: unknown) => {
    const target = dateText(value);
    const index = rows.findIndex((row) => row.date === target);
    return index < 0 ? null : rows[index];
  };
  return <div ref={shell} className={`structure-chart-shell ${fullscreen ? "structure-chart-fullscreen" : ""} ${className}`}>
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <div><strong className="text-xs">{t("K 線結構檢視")} · MA {artifact.ma_period}</strong><p className="m-0 text-[10px] text-slate-500">{artifact.train_start} ～ {artifact.train_end} · {t("Numerical OHLC audit only")}</p></div>
      <button type="button" className="min-h-10 rounded border border-[#304159] px-3 py-2 text-xs" onClick={toggleFullscreen}>{t(fullscreen ? "Exit fullscreen" : "Fullscreen chart")}</button>
    </div>
    <div className="structure-chart-scroll scrollbar" tabIndex={0} aria-label={t("K 線結構檢視")}>
      <svg viewBox={`0 0 ${geometry.width} ${geometry.height}`} width={geometry.width} height={geometry.height} role="img" aria-label={`${t("K 線結構檢視")} MA ${artifact.ma_period}`}>
        <rect x="0" y="0" width={geometry.width} height={geometry.height} fill="#0a111b" />
        {rows.map((row, index) => {
          const x = 12 + index * (geometry.width - 24) / Math.max(rows.length - 1, 1);
          const color = row.close >= row.open ? "#34d399" : "#fb7185";
          const top = geometry.y(Math.max(row.open, row.close)), bottom = geometry.y(Math.min(row.open, row.close));
          return <g key={row.timestamp || index}>
            <line x1={x} x2={x} y1={geometry.y(row.high)} y2={geometry.y(row.low)} stroke={color} strokeWidth="1" />
            <rect x={x - geometry.candleWidth / 2} y={top} width={geometry.candleWidth} height={Math.max(1, bottom - top)} fill={color} opacity=".9" />
            {row.reference != null && <circle cx={x} cy={geometry.y(row.reference)} r="1.2" fill="#22d3ee" />}
          </g>;
        })}
        {rows.length > 1 && <polyline fill="none" stroke="#22d3ee" strokeWidth="1.4" points={rows.map((row, index) => `${12 + index * (geometry.width - 24) / Math.max(rows.length - 1, 1)},${row.reference == null ? geometry.y(row.close) : geometry.y(row.reference)}`).join(" ")} />}
        {markers.map((marker, index) => {
          const row = pointForDate(marker.date ?? marker.timestamp);
          if (!row) return null;
          const rowIndex = rows.findIndex((item) => item.date === row.date);
          const x = 12 + rowIndex * (geometry.width - 24) / Math.max(rows.length - 1, 1);
          const bullish = String(marker.direction ?? "").toUpperCase() === "BULL";
          const y = geometry.y(Number(marker.trigger ?? marker.trigger_price ?? (bullish ? row.high : row.low))) + (bullish ? -8 : 8);
          const color = String(marker.status ?? "").includes("FAIL") || String(marker.status ?? "").includes("VIOLATION") ? "#fb7185" : bullish ? "#34d399" : "#fbbf24";
          const trigger = marker.trigger ?? marker.trigger_price;
          const target = marker.target ?? marker.target_price;
          const flags = `gap=${marker.gap_breakout ? "yes" : "no"} · executable=${marker.strategy_executable ? "yes" : "no"} · missed=${marker.entry_zone_missed ? "yes" : "no"}`;
          return <g key={`${String(marker.timestamp)}-${index}`}>
            <circle cx={x} cy={y} r="3" fill={color} stroke="#080d14" strokeWidth="1" />
            <title>{`日期 ${dateText(marker.date ?? marker.timestamp)} · 事件 ${t(String(marker.event_type ?? marker.event ?? "event"))} · 狀態 ${t(String(marker.status ?? ""))} · OHLC ${num(row.open)} / ${num(row.high)} / ${num(row.low)} / ${num(row.close)} · MA(t−1) ${num(row.reference)} · trigger ${num(trigger)} · target ${num(target)} · ${flags}`}</title>
          </g>;
        })}
      </svg>
    </div>
    <p className="m-0 mt-2 text-[10px] text-slate-500">{t("Chart markers come from numerical backend events and are for visual audit only.")}</p>
  </div>;
}
