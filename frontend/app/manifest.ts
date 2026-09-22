import type { MetadataRoute } from "next";
import { t } from "@/lib/i18n";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: t("Backtest Lab — MA Breakout Research"),
    short_name: t("Backtest Lab"),
    description: t("Run no-lookahead moving-average breakout research from desktop or mobile."),
    lang: "zh-TW",
    start_url: "/",
    display: "standalone",
    background_color: "#080d14",
    theme_color: "#080d14",
    orientation: "any",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
