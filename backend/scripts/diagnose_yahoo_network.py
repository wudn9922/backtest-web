"""Print a safe, terminal-friendly Yahoo connectivity diagnostic.

This script never prints proxy credentials or full URLs.  It is intentionally
independent from the strategy engine and can be run while the detached service
is serving requests.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from app.data.yahoo import YAHOO_HOSTS, _chart_url, safe_yahoo_error


def _dns(host: str) -> dict:
    addresses: list[str] = []
    errors: list[str] = []
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            address = sockaddr[0]
            if address not in addresses:
                addresses.append(address)
    except OSError as exc:
        errors.append(safe_yahoo_error(exc))
    return {"resolved": bool(addresses), "addresses": addresses, "errors": errors}


def _tcp(host: str, addresses: list[str]) -> dict:
    results = []
    for address in addresses:
        try:
            with socket.create_connection((address, 443), timeout=5):
                pass
            results.append({"address": address, "reachable": True})
        except OSError as exc:
            results.append({"address": address, "reachable": False, "error": safe_yahoo_error(exc)})
    return {"reachable": any(item["reachable"] for item in results), "attempts": results}


def _https(host: str) -> dict:
    request = urllib.request.Request(
        _chart_url(host, "SPY", date.today() - timedelta(days=3), date.today()),
        headers={"Accept": "application/json", "User-Agent": "BacktestLab/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return {"reachable": int(getattr(response, "status", 200) or 200) < 400, "status": int(getattr(response, "status", 200) or 200)}
    except urllib.error.HTTPError as exc:
        return {"reachable": False, "status": int(exc.code), "error": safe_yahoo_error(f"HTTP {exc.code}: {exc.reason}")}
    except Exception as exc:
        return {"reachable": False, "error": safe_yahoo_error(exc)}


def _proxy_environment() -> dict[str, str]:
    names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")
    values: dict[str, str] = {}
    for name in names:
        value = os.getenv(name)
        if value:
            # Reveal only whether a proxy is set and its host/port shape.  Never
            # return usernames, passwords, tokens or complete URLs.
            if name.lower() == "no_proxy":
                values[name] = "configured"
            else:
                parsed = urllib.parse.urlsplit(value if "://" in value else f"http://{value}")
                values[name] = f"configured ({parsed.hostname or 'unknown'}:{parsed.port or 'default'})"
    return values


def main() -> None:
    report = {"hosts": {}, "proxy_environment": _proxy_environment()}
    for host in YAHOO_HOSTS:
        dns = _dns(host)
        report["hosts"][host] = {"dns": dns, "tcp_443": _tcp(host, dns["addresses"]), "https": _https(host)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
