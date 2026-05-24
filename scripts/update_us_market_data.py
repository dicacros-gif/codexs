from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data" / "us_latest.json"
USER_AGENT = "Mozilla/5.0 (compatible; srim-codexs-us-updater/1.0)"
SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?download=true"
INFO_URL = "https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=stocks"
SUMMARY_URL = "https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks"
NASDAQ_STOCK_URL = "https://www.nasdaq.com/market-activity/stocks/{symbol}"
STOCKANALYSIS_STATS_URL = "https://stockanalysis.com/stocks/{symbol}/statistics/"
STOCKANALYSIS_FINANCIALS_URL = "https://stockanalysis.com/stocks/{symbol}/financials/?p=quarterly"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
STOCKANALYSIS_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EXCLUDED_NAME_PATTERNS = (
    "acquisition corp",
    "acquisition corporation",
    "acquisition company",
    "blank check",
    "bond",
    "closed end",
    "debenture",
    "depositary shares",
    "etf",
    "etn",
    "exchange traded",
    "fund",
    "notes due",
    "preferred",
    "preference",
    "right",
    "rights",
    "series ",
    "unit",
    "units",
    "warrant",
    "warrants",
)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_json(url: str, timeout: int = 30) -> dict:
    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def fetch_text(url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers=headers or HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def strip_html(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = strip_html(value)
    if not text or text.upper() in {"N/A", "NA", "--", "NONE"}:
        return None
    text = text.replace("$", "").replace(",", "").replace("%", "").replace("+", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_percent(value: object) -> float | None:
    number = parse_number(value)
    return number / 100 if number is not None else None


def growth_rate(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def parse_range(value: object) -> tuple[float | None, float | None]:
    text = strip_html(value)
    if "/" in text:
        high_text, low_text = text.split("/", 1)
        return parse_number(high_text), parse_number(low_text)
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", text.replace("$", "").replace(",", ""))
    if match:
        low = parse_number(match.group(1))
        high = parse_number(match.group(2))
        return high, low
    return None, None


def nested_value(summary: dict, key: str) -> str:
    item = summary.get(key)
    if isinstance(item, dict):
        return strip_html(item.get("value"))
    return strip_html(item)


def deep_value(payload: dict | None, *keys: str) -> object:
    item: object = payload or {}
    for key in keys:
        if not isinstance(item, dict):
            return None
        item = item.get(key)
    return item


def valid_common_stock(row: dict) -> bool:
    symbol = strip_html(row.get("symbol")).upper()
    name = strip_html(row.get("name"))
    lowered_name = name.lower()
    country = strip_html(row.get("country"))
    sector = strip_html(row.get("sector"))
    industry = strip_html(row.get("industry"))
    price = parse_number(row.get("lastsale"))
    market_cap = parse_number(row.get("marketCap"))
    volume = parse_number(row.get("volume"))

    if country != "United States" or not sector or not industry:
        return False
    if not symbol or any(token in symbol for token in ("^", "$", "=", "/", "\\")):
        return False
    if not price or price <= 0 or not market_cap or market_cap <= 0 or not volume or volume <= 0:
        return False
    return not any(pattern in lowered_name for pattern in EXCLUDED_NAME_PATTERNS)


def fetch_screener_rows() -> list[dict]:
    payload = fetch_json(SCREENER_URL)
    rows = payload.get("data", {}).get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("Nasdaq screener returned no rows")
    return rows


def fetch_quote_payload(symbol: str) -> tuple[str, dict | None, dict | None, str | None]:
    try:
        summary_payload = fetch_json(SUMMARY_URL.format(symbol=symbol.lower()), timeout=20)
        info_payload = fetch_json(INFO_URL.format(symbol=symbol.lower()), timeout=20)
        summary = summary_payload.get("data", {}).get("summaryData", {})
        info = info_payload.get("data", {})
        if not isinstance(summary, dict):
            summary = {}
        if not isinstance(info, dict):
            info = {}
        return symbol, summary, info, None
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return symbol, None, None, str(exc)


def fetch_quote_summary(symbol: str) -> tuple[str, dict | None, str | None]:
    symbol, summary, _info, error = fetch_quote_payload(symbol)
    return symbol, summary, error


def stockanalysis_slug(symbol: str) -> str:
    return symbol.lower().replace(".", "-")


def extract_stat_metric(text: str, metric_id: str, percent: bool = False) -> float | None:
    match = re.search(r'\{id:"' + re.escape(metric_id) + r'"[^}]*\}', text)
    if not match:
        return None
    item = match.group(0)
    hover = re.search(r'hover:"([^"]*)"', item)
    value = re.search(r'value:"([^"]*)"', item)
    raw = hover.group(1) if hover else value.group(1) if value else None
    return parse_percent(raw) if percent else parse_number(raw)


def extract_financial_headers(text: str) -> list[str]:
    table = re.search(r'<table id="main-table"[\s\S]*?</table>', text)
    if not table:
        return []
    return re.findall(r'<th id="(\d{4}-\d{2}-\d{2})"', table.group(0))


def clean_cell(value: str) -> str:
    text = re.sub(r"<[^>]*>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_financial_row(text: str, row_id: str) -> list[str]:
    marker = f'id="{row_id}"'
    marker_index = text.find(marker)
    if marker_index < 0:
        return []
    row_start = text.rfind("<tr", 0, marker_index)
    row_end = text.find("</tr>", marker_index)
    if row_start < 0 or row_end < 0:
        return []
    row = text[row_start:row_end + 5]
    cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
    return [clean_cell(cell) for cell in cells[1:]]


def parse_stockanalysis_fundamentals(symbol: str) -> dict | None:
    slug = stockanalysis_slug(symbol)
    stats_text = fetch_text(STOCKANALYSIS_STATS_URL.format(symbol=slug), timeout=25, headers=STOCKANALYSIS_HEADERS)
    financials_text = fetch_text(STOCKANALYSIS_FINANCIALS_URL.format(symbol=slug), timeout=25, headers=STOCKANALYSIS_HEADERS)

    headers = extract_financial_headers(financials_text)
    revenue = extract_financial_row(financials_text, "revenue")
    revenue_growth = extract_financial_row(financials_text, "revenueGrowth")
    net_income = extract_financial_row(financials_text, "netIncome")
    net_income_growth = extract_financial_row(financials_text, "netIncomeGrowth")

    revenue_millions = parse_number(revenue[0]) if revenue else None
    revenue_previous_millions = parse_number(revenue[1]) if len(revenue) > 1 else None
    net_income_millions = parse_number(net_income[0]) if net_income else None
    net_income_previous_millions = parse_number(net_income[1]) if len(net_income) > 1 else None
    revenue_yoy = parse_percent(revenue_growth[0]) if revenue_growth else None
    net_income_yoy = parse_percent(net_income_growth[0]) if net_income_growth else None
    revenue_qoq = growth_rate(revenue_millions, revenue_previous_millions)
    net_income_qoq = growth_rate(net_income_millions, net_income_previous_millions)
    revenue_growth_5y = extract_stat_metric(stats_text, "revenue5y", percent=True)
    eps_growth_5y = extract_stat_metric(stats_text, "eps5y", percent=True)
    forward_pe = extract_stat_metric(stats_text, "peForward")

    return {
        "per": extract_stat_metric(stats_text, "pe"),
        "forwardPer": forward_pe,
        "peg": extract_stat_metric(stats_text, "pegRatio"),
        "forwardPeg": forward_pe / (eps_growth_5y * 100) if forward_pe is not None and eps_growth_5y and eps_growth_5y > 0 else None,
        "revenueGrowthForecast5Y": revenue_growth_5y,
        "epsGrowthForecast5Y": eps_growth_5y,
        "futureRevenueGrowth": revenue_growth_5y,
        "futureProfitGrowth": eps_growth_5y,
        "futureProfitGrowthMetric": "EPS Growth Forecast (5Y)",
        "ttmRevenue": extract_stat_metric(stats_text, "revenue"),
        "ttmNetIncome": extract_stat_metric(stats_text, "netinc"),
        "ttmEps": extract_stat_metric(stats_text, "eps"),
        "latestQuarterDate": headers[0] if headers else None,
        "revenueQuarterMillions": revenue_millions,
        "revenuePreviousQuarterMillions": revenue_previous_millions,
        "revenueYoY": revenue_yoy,
        "revenueQoQ": revenue_qoq,
        "revenueIncreased": revenue_yoy > 0 if revenue_yoy is not None else None,
        "revenueQoQIncreased": revenue_qoq > 0 if revenue_qoq is not None else None,
        "netIncomeQuarterMillions": net_income_millions,
        "netIncomePreviousQuarterMillions": net_income_previous_millions,
        "netIncomeYoY": net_income_yoy,
        "netIncomeQoQ": net_income_qoq,
        "netIncomeIncreased": net_income_yoy > 0 if net_income_yoy is not None else None,
        "netIncomeQoQIncreased": net_income_qoq > 0 if net_income_qoq is not None else None,
        "fundamentalsSource": "StockAnalysis statistics and quarterly financials pages",
    }


def fetch_stockanalysis_fundamentals(symbol: str) -> tuple[str, dict | None, str | None]:
    try:
        return symbol, parse_stockanalysis_fundamentals(symbol), None
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return symbol, None, str(exc)


def median_or_none(values: list[float]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return float(median(cleaned)) if cleaned else None


def build_group_stats(stocks: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[float]] = {}
    for stock in stocks:
        upside = stock.get("targetUpside")
        if not isinstance(upside, (int, float)):
            continue
        for key in (
            f"sector::{stock.get('sector', '')}",
            f"industry::{stock.get('sector', '')}::{stock.get('industry', '')}",
        ):
            groups.setdefault(key, []).append(float(upside))

    return {
        key: {
            "targetCount": len(values),
            "medianTargetUpside": median_or_none(values),
        }
        for key, values in groups.items()
        if values
    }


def normalize_base_row(row: dict) -> dict:
    symbol = strip_html(row.get("symbol")).upper()
    return {
        "symbol": symbol,
        "name": strip_html(row.get("name")),
        "sector": strip_html(row.get("sector")),
        "industry": strip_html(row.get("industry")),
        "price": parse_number(row.get("lastsale")),
        "marketCap": parse_number(row.get("marketCap")),
        "volume": parse_number(row.get("volume")),
        "sourceUrl": NASDAQ_STOCK_URL.format(symbol=symbol.lower()),
    }


def quote_price(info: dict | None, fallback: float | None) -> float | None:
    return parse_number(deep_value(info, "primaryData", "lastSalePrice")) or fallback


def quote_volume(info: dict | None, summary: dict | None, fallback: float | None) -> float | None:
    return (
        parse_number(deep_value(info, "primaryData", "volume"))
        or parse_number(nested_value(summary or {}, "ShareVolume"))
        or fallback
    )


def quote_market_cap(summary: dict | None, fallback: float | None) -> float | None:
    return parse_number(nested_value(summary or {}, "MarketCap")) or fallback


def quote_52w_range(info: dict | None, summary: dict | None) -> tuple[float | None, float | None]:
    high, low = parse_range(deep_value(info, "keyStats", "fiftyTwoWeekHighLow", "value"))
    if high and low:
        return high, low
    return parse_range(nested_value(summary or {}, "FiftTwoWeekHighLow"))


def merge_quote(base: dict, summary: dict | None, info: dict | None) -> dict:
    sector = nested_value(summary or {}, "Sector") or base["sector"]
    industry = nested_value(summary or {}, "Industry") or base["industry"]
    target_price = parse_number(nested_value(summary or {}, "OneYrTarget"))
    high_52w, low_52w = quote_52w_range(info, summary)
    average_volume = parse_number(nested_value(summary or {}, "AverageVolume"))
    share_volume = parse_number(nested_value(summary or {}, "ShareVolume"))
    previous_close = parse_number(nested_value(summary or {}, "PreviousClose"))
    price = quote_price(info, base.get("price"))
    volume = quote_volume(info, summary, base.get("volume"))
    market_cap = quote_market_cap(summary, base.get("marketCap"))
    net_change = parse_number(deep_value(info, "primaryData", "netChange"))
    pct_change = parse_number(deep_value(info, "primaryData", "percentageChange"))

    target_upside = target_price / price - 1 if price and target_price and price > 0 else None
    if target_upside is not None and (target_upside < -0.9 or target_upside > 4):
        target_upside = None

    position_52w = None
    if price and high_52w and low_52w and high_52w > low_52w:
        position_52w = max(0, min((price - low_52w) / (high_52w - low_52w), 1))

    return {
        **base,
        "name": strip_html(deep_value(info, "companyName")) or base["name"],
        "price": price,
        "marketCap": market_cap,
        "volume": volume,
        "sector": sector,
        "industry": industry,
        "exchange": strip_html(deep_value(info, "exchange")) or None,
        "stockType": strip_html(deep_value(info, "stockType")) or None,
        "marketStatus": strip_html(deep_value(info, "marketStatus")) or None,
        "priceAsOf": strip_html(deep_value(info, "primaryData", "lastTradeTimestamp")) or None,
        "isRealTime": deep_value(info, "primaryData", "isRealTime") if isinstance(deep_value(info, "primaryData", "isRealTime"), bool) else None,
        "priceSource": "Nasdaq quote info primaryData.lastSalePrice",
        "netChange": net_change,
        "pctChange": pct_change / 100 if pct_change is not None else None,
        "targetPrice": target_price,
        "targetUpside": target_upside,
        "fiftyTwoWeekHigh": high_52w,
        "fiftyTwoWeekLow": low_52w,
        "fiftyTwoWeekPosition": position_52w,
        "averageVolume": average_volume,
        "shareVolume": share_volume,
        "previousClose": previous_close,
    }


def main() -> int:
    previous = read_json(LATEST, {"stocks": []})
    min_market_cap = env_int("US_MIN_MARKET_CAP", 1_000_000_000)
    max_stocks = env_int("US_MAX_STOCKS", 1000)
    workers = max(1, min(env_int("US_SUMMARY_WORKERS", 8), 16))
    fundamental_workers = max(1, min(env_int("US_FUNDAMENTAL_WORKERS", 8), 12))
    fundamental_max_stocks = env_int("US_FUNDAMENTAL_MAX_STOCKS", max_stocks)
    failures: list[dict] = []

    try:
        rows = fetch_screener_rows()
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        rows = []
        failures.append({"source": "Nasdaq screener", "error": str(exc)})
        print(f"failed Nasdaq screener: {exc}", file=sys.stderr)

    bases = [
        normalize_base_row(row)
        for row in rows
        if valid_common_stock(row)
    ]
    bases = [stock for stock in bases if stock["marketCap"] and stock["marketCap"] >= min_market_cap]
    bases.sort(key=lambda item: item.get("marketCap") or 0, reverse=True)
    bases = bases[:max_stocks]
    print(f"Nasdaq US common stocks selected: {len(bases)}")

    summaries: dict[str, dict | None] = {}
    infos: dict[str, dict | None] = {}
    if bases:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(fetch_quote_payload, stock["symbol"]): stock["symbol"] for stock in bases}
            for index, future in enumerate(as_completed(future_map), start=1):
                symbol, summary, info, error = future.result()
                summaries[symbol] = summary
                infos[symbol] = info
                if error:
                    failures.append({"source": f"Nasdaq quote {symbol}", "error": error})
                if index % 100 == 0:
                    print(f"quote fetched: {index}/{len(bases)}")

    fundamentals: dict[str, dict | None] = {}
    fundamental_bases = bases[:fundamental_max_stocks] if fundamental_max_stocks > 0 else []
    if fundamental_bases:
        with ThreadPoolExecutor(max_workers=fundamental_workers) as executor:
            future_map = {executor.submit(fetch_stockanalysis_fundamentals, stock["symbol"]): stock["symbol"] for stock in fundamental_bases}
            for index, future in enumerate(as_completed(future_map), start=1):
                symbol, fundamental, error = future.result()
                fundamentals[symbol] = fundamental
                if error:
                    failures.append({"source": f"StockAnalysis fundamentals {symbol}", "error": error})
                if index % 100 == 0:
                    print(f"fundamentals fetched: {index}/{len(fundamental_bases)}")

    stocks = []
    for stock in bases:
        merged = merge_quote(stock, summaries.get(stock["symbol"]), infos.get(stock["symbol"]))
        fundamental = fundamentals.get(stock["symbol"])
        if fundamental:
            merged.update(fundamental)
            merged["hasFundamentals"] = True
        else:
            merged["hasFundamentals"] = False
        stocks.append(merged)
    if not stocks:
        stocks = previous.get("stocks", [])

    stocks.sort(key=lambda item: (item.get("sector", ""), item.get("industry", ""), -(item.get("marketCap") or 0)))
    counts: dict[str, int] = {}
    for stock in stocks:
        counts[stock["sector"]] = counts.get(stock["sector"], 0) + 1

    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    target_count = sum(1 for stock in stocks if isinstance(stock.get("targetPrice"), (int, float)))
    payload = {
        "generatedAt": generated_at,
        "asOf": generated_at,
        "source": "Nasdaq screener stocks API + Nasdaq quote info and summary APIs",
        "priceSource": "Nasdaq quote info primaryData.lastSalePrice",
        "filters": {
            "country": "United States",
            "minimumMarketCap": min_market_cap,
            "maximumStocks": max_stocks,
            "fundamentalMaximumStocks": fundamental_max_stocks,
            "excluded": "funds, ETFs, warrants, units, preferred shares, notes, SPAC-like acquisition companies",
        },
        "counts": counts,
        "targetCount": target_count,
        "groupStats": build_group_stats(stocks),
        "stocks": stocks,
    }
    if failures:
        payload["failures"] = failures[:50]

    LATEST.parent.mkdir(parents=True, exist_ok=True)
    with LATEST.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"saved {len(stocks)} US stocks, {target_count} with one-year targets")
    return 0 if stocks else 1


if __name__ == "__main__":
    raise SystemExit(main())
