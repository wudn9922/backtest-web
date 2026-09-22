import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { preferredLanIPv4 } from "./network.mjs";

const address = preferredLanIPv4();
if (!address) {
  console.error("No private LAN IPv4 address was detected. Connect to Wi-Fi and try again.");
  process.exit(1);
}

console.log(`\nStarting Backtest Lab for mobile access at http://${address}:3000`);
console.log("FastAPI must be running separately on http://127.0.0.1:8000\n");

const nextBin = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));
const child = spawn(process.execPath, [nextBin, "dev", "--hostname", address, "--port", "3000"], { stdio: "inherit" });
child.on("exit", (code, signal) => process.exitCode = code ?? (signal ? 1 : 0));

