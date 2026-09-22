import assert from "node:assert/strict";
import test from "node:test";
import { lanIPv4Addresses, preferredLanIPv4 } from "../scripts/network.mjs";

const fixtures = {
  Loopback: [{ family: "IPv4", internal: true, address: "127.0.0.1" }],
  WiFi: [{ family: "IPv4", internal: false, address: "192.168.1.123" }],
  Public: [{ family: "IPv4", internal: false, address: "203.0.113.9" }],
};

test("detects only private, non-loopback LAN IPv4 addresses", () => {
  assert.deepEqual(lanIPv4Addresses(fixtures), ["192.168.1.123"]);
});

test("selects the first private LAN IPv4 for mobile binding", () => {
  assert.equal(preferredLanIPv4(fixtures), "192.168.1.123");
});

test("returns null when no private LAN address is available", () => {
  assert.equal(preferredLanIPv4({ Loopback: fixtures.Loopback }), null);
});

