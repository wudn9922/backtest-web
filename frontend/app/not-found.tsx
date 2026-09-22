import Link from "next/link";
import { t } from "@/lib/i18n";

export default function NotFound() {
  return <main className="mx-auto max-w-lg p-6"><section className="panel p-6"><h1>{t("Page not found")}</h1><p>{t("The requested page does not exist.")}</p><Link className="text-cyan-300" href="/">{t("Back to dashboard")}</Link></section></main>;
}
