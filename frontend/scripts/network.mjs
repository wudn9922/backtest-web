import os from "node:os";

function isPrivateIPv4(address) {
  const parts = address.split(".").map(Number);
  return parts.length === 4 && (
    parts[0] === 10 ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 192 && parts[1] === 168)
  );
}

export function lanIPv4Addresses(interfaces = os.networkInterfaces()) {
  return Object.values(interfaces)
    .flatMap((items) => items || [])
    .filter((item) => item.family === "IPv4" && !item.internal && isPrivateIPv4(item.address))
    .map((item) => item.address)
    .filter((address, index, all) => all.indexOf(address) === index);
}

export function preferredLanIPv4(interfaces = os.networkInterfaces()) {
  return lanIPv4Addresses(interfaces)[0] || null;
}
