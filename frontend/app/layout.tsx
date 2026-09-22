import type { Metadata, Viewport } from "next";
import "./globals.css";
import { t } from "@/lib/i18n";

export const metadata: Metadata = {
  title: t("Backtest Lab — MA Breakout Research"),
  description: t("No-lookahead moving-average breakout strategy research dashboard."),
  manifest: "/manifest.webmanifest",
  applicationName: t("Backtest Lab"),
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: t("Backtest Lab") },
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#080d14" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-TW"><body>{children}</body></html>;
}
