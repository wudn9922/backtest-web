import { lanIPv4Addresses } from "./network.mjs";

const addresses = lanIPv4Addresses();
console.log("\nBacktest Lab access URLs");
console.log("Desktop with npm run dev:");
console.log("  http://127.0.0.1:3000");
console.log("Computer and mobile with npm run dev:network or npm run mobile:");
if (addresses.length) {
  for (const address of addresses) console.log(`  http://${address}:3000`);
} else {
  console.log("  Private LAN IPv4 not detected. Run ipconfig (Windows) or ipconfig getifaddr en0 (macOS). ");
}
console.log("\nMobile mode exposes only the Next.js frontend. FastAPI remains on 127.0.0.1:8000.\n");
