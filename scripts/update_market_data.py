from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "data" / "watchlist.json"
LATEST = ROOT / "data" / "latest.json"
USER_AGENT = "Mozilla/5.0 (compatible; srim-codexs-updater/1.0)"


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=25) as response:
        raw = response.read()
    return raw.decode("utf-8", "replace")


def clean_number(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9.-]", "", value)
    if not digits:
        return None
    return int(float(digits))


def search(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.S)
    if not match:
        return None
    return html.unescape(match.group(1).strip())


def parse_naver_stock(code: str, market: str | None = None) -> dict:
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    text = fetch_text(url)
    name = search(r'<div class="wrap_company">.*?<h2>\s*<a[^>]*>(.*?)</a>', text)
    current_price = clean_number(search(r'<p class="no_today">.*?<span class="blind">([0-9,]+)</span>', text))
    shares = clean_number(search(r"<th scope=\"row\">상장주식수</th>\s*<td><em>(.*?)</em>", text))
    as_of = search(r'<em class="date">\s*([0-9.]+)', text)

    return {
        "code": code,
        "name": name or code,
        "market": market or "",
        "currentPrice": current_price,
        "shares": shares,
        "asOf": as_of,
        "sourceUrl": url,
    }


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def main() -> int:
    watchlist = read_json(WATCHLIST, {"stocks": [{"code": "005930", "market": "KOSPI"}]})
    stocks = []
    failures = []

    for item in watchlist.get("stocks", []):
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        try:
            stock = parse_naver_stock(code, item.get("market"))
            stocks.append(stock)
            print(f"updated {code}: {stock.get('name')} {stock.get('currentPrice')}")
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            failures.append({"code": code, "error": str(exc)})
            print(f"failed {code}: {exc}", file=sys.stderr)
        time.sleep(0.6)

    previous = read_json(LATEST, {"stocks": []})
    if not stocks:
        stocks = previous.get("stocks", [])

    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    payload = {
        "generatedAt": generated_at,
        "market": {
            "riskFreeRate": env_float("RISK_FREE_RATE", 0.016),
            "marketRiskPremium": env_float("MARKET_RISK_PREMIUM", 0.0664),
            "defaultRequiredReturn": env_float("DEFAULT_REQUIRED_RETURN", 0.0805),
            "source": "GitHub Actions daily updater; rates can be overridden with repository environment variables",
        },
        "stocks": stocks,
    }
    if failures:
        payload["failures"] = failures

    LATEST.parent.mkdir(parents=True, exist_ok=True)
    with LATEST.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0 if stocks else 1


if __name__ == "__main__":
    raise SystemExit(main())
