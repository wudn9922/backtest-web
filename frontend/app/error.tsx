"use client";
import { t } from "@/lib/i18n";

export default function ErrorBoundary({error,reset}:{error:Error & {digest?:string};reset:()=>void}) {
  return <main className="mx-auto max-w-lg p-6"><section className="panel p-6" role="alert"><h1>{t("The page could not load")}</h1><p>{t("Your saved backtests are unchanged. Please try again.")}</p><button onClick={reset} className="input text-cyan-300">{t("Retry")}</button><details className="mt-4"><summary>{t("Technical details")}</summary><pre className="technical-raw">{error.message}{error.digest ? ` (${error.digest})` : ""}</pre></details></section></main>;
}
