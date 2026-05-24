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
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data" / "latest.json"
USER_AGENT = "Mozilla/5.0 (compatible; srim-codexs-updater/2.0)"
NAVER_MARKET_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
KIND_CORP_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
MARKETS = {"KOSPI": "0", "KOSDAQ": "1"}


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read()


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]*>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = strip_html(value)
    text = text.replace(",", "").replace("%", "").replace("+", "").strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    number = parse_number(value)
    if number is None:
        return None
    return int(round(number))


def fetch_kind_company_map() -> dict[str, dict]:
    raw = fetch_bytes(KIND_CORP_URL)
    text = raw.decode("euc-kr", "replace")
    rows = re.findall(
        r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td>(.*?)</td>",
        text,
        re.S,
    )
    companies: dict[str, dict] = {}
    for name_html, market_html, code_html, industry_html in rows:
        code = strip_html(code_html).zfill(6)
        market_raw = strip_html(market_html).replace(" ", "")
        if market_raw == "유가":
            market = "KOSPI"
        elif market_raw == "코스닥":
            market = "KOSDAQ"
        else:
            continue
        companies[code] = {
            "code": code,
            "name": strip_html(name_html),
            "market": market,
            "industry": strip_html(industry_html),
        }
    return companies


def market_page_url(market: str, page: int) -> str:
    params = [
        ("sosok", MARKETS[market]),
        ("page", str(page)),
        ("fieldIds", "market_sum"),
        ("fieldIds", "listed_stock_cnt"),
        ("fieldIds", "quant"),
        ("fieldIds", "per"),
        ("fieldIds", "roe"),
    ]
    return f"{NAVER_MARKET_URL}?{urlencode(params)}"


def parse_market_rows(html_text: str, market: str, companies: dict[str, dict]) -> list[dict]:
    row_htmls = re.findall(r'<tr[^>]*onMouseOver[\s\S]*?</tr>', html_text)
    stocks = []

    for row in row_htmls:
        title = re.search(r'/item/main\.naver\?code=(\d+)" class="tltle">([\s\S]*?)</a>', row)
        if not title:
            continue
        code = title.group(1).zfill(6)
        company = companies.get(code)
        if not company or company["market"] != market:
            continue

        cells = [strip_html(cell) for cell in re.findall(r'<td class="number">([\s\S]*?)</td>', row)]
        if len(cells) < 10:
            continue

        current_price = parse_int(cells[0])
        market_cap_eok = parse_int(cells[4])
        listed_stock_thousand = parse_int(cells[5])
        volume = parse_int(cells[7])
        per = parse_number(cells[8])
        roe = parse_number(cells[9])
        shares = listed_stock_thousand * 1000 if listed_stock_thousand is not None else None

        stocks.append(
            {
                "code": code,
                "name": company["name"],
                "market": market,
                "industry": company.get("industry", ""),
                "currentPrice": current_price,
                "shares": shares,
                "marketCapEok": market_cap_eok,
                "volume": volume,
                "per": per,
                "roe": roe / 100 if roe is not None else None,
                "sourceUrl": f"https://finance.naver.com/item/main.naver?code={code}",
            }
        )
    return stocks


def fetch_naver_market(market: str, companies: dict[str, dict]) -> list[dict]:
    stocks: list[dict] = []
    for page in range(1, 90):
        raw = fetch_bytes(market_page_url(market, page))
        text = raw.decode("euc-kr", "replace")
        rows = parse_market_rows(text, market, companies)
        if not rows:
            break
        stocks.extend(rows)
        print(f"{market} page {page}: {len(rows)}")
        time.sleep(0.12)
    return stocks


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def main() -> int:
    previous = read_json(LATEST, {"stocks": []})
    failures = []

    try:
        companies = fetch_kind_company_map()
        print(f"KIND companies: {len(companies)}")
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        companies = {}
        failures.append({"source": "KIND", "error": str(exc)})
        print(f"failed KIND: {exc}", file=sys.stderr)

    stocks: list[dict] = []
    if companies:
        for market in MARKETS:
            try:
                stocks.extend(fetch_naver_market(market, companies))
            except (URLError, TimeoutError, ValueError, OSError) as exc:
                failures.append({"source": f"Naver {market}", "error": str(exc)})
                print(f"failed {market}: {exc}", file=sys.stderr)

    if companies:
        indexed = {stock["code"]: stock for stock in stocks}
        for code, company in companies.items():
            if code in indexed:
                indexed[code]["hasMarketData"] = True
                continue
            indexed[code] = {
                "code": code,
                "name": company["name"],
                "market": company["market"],
                "industry": company.get("industry", ""),
                "currentPrice": None,
                "shares": None,
                "marketCapEok": None,
                "volume": None,
                "per": None,
                "roe": None,
                "hasMarketData": False,
                "sourceUrl": f"https://finance.naver.com/item/main.naver?code={code}",
            }
        stocks = list(indexed.values())

    if not stocks:
        stocks = previous.get("stocks", [])

    market_order = {"KOSPI": 0, "KOSDAQ": 1}
    stocks.sort(key=lambda item: (market_order.get(item.get("market", ""), 9), item.get("name", ""), item.get("code", "")))
    counts = {
        "KOSPI": sum(1 for stock in stocks if stock.get("market") == "KOSPI"),
        "KOSDAQ": sum(1 for stock in stocks if stock.get("market") == "KOSDAQ"),
    }
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    payload = {
        "generatedAt": generated_at,
        "asOf": generated_at,
        "source": "Naver Finance market summary + KRX KIND listed company list",
        "counts": counts,
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
    print(f"saved {len(stocks)} stocks: KOSPI {counts['KOSPI']}, KOSDAQ {counts['KOSDAQ']}")
    return 0 if stocks else 1


if __name__ == "__main__":
    raise SystemExit(main())
