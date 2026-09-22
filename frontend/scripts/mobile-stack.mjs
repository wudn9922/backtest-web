import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { preferredLanIPv4 } from "./network.mjs";

const frontendDir = fileURLToPath(new URL("..", import.meta.url));
const backendDir = path.resolve(frontendDir, "../backend");
const address = preferredLanIPv4();
if (!address) {
  console.error("No private LAN IPv4 address was detected. Connect to Wi-Fi and try again.");
  process.exit(1);
}

const venvPython = process.platform === "win32"
  ? path.join(backendDir, ".venv", "Scripts", "python.exe")
  : path.join(backendDir, ".venv", "bin", "python");
const candidates = [
  process.env.PYTHON_EXECUTABLE && { command: process.env.PYTHON_EXECUTABLE, prefix: [] },
  fs.existsSync(venvPython) && { command: venvPython, prefix: [] },
  { command: process.platform === "win32" ? "python" : "python3", prefix: [] },
  process.platform === "win32" && { command: "py", prefix: ["-3.12"] },
].filter(Boolean);
const python = candidates.find(candidate => spawnSync(candidate.command, [...candidate.prefix, "-c", "import fastapi, uvicorn"], { stdio: "ignore" }).status === 0);
if (!python) {
  console.error("No Python environment with FastAPI and Uvicorn was found. Install backend/requirements.txt into backend/.venv first.");
  process.exit(1);
}
const nextBin = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));

console.log("\nBacktest Lab mobile stack");
console.log(`  Open on this computer or phone: http://${address}:3000`);
console.log(`  Frontend bind: ${address}:3000`);
console.log("  Backend bind: 127.0.0.1:8000 (not exposed to LAN)");
console.log("  Press Ctrl+C to stop both services.\n");

const backend = spawn(python.command, [...python.prefix, "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"], { cwd: backendDir, stdio: "inherit" });
const frontend = spawn(process.execPath, [nextBin, "dev", "--hostname", address, "--port", "3000"], { cwd: frontendDir, stdio: "inherit" });

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  backend.kill("SIGTERM");
  frontend.kill("SIGTERM");
  process.exitCode = code;
}
backend.on("exit", code => stop(code || 0));
frontend.on("exit", code => stop(code || 0));
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
