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
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data" / "latest.json"
USER_AGENT = "Mozilla/5.0 (compatible; srim-codexs-updater/2.0)"
NAVER_MARKET_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
NAVER_REALTIME_URL = "https://polling.finance.naver.com/api/realtime"
NAVER_FINANCE_QUARTER_URL = "https://m.stock.naver.com/api/stock/{code}/finance/quarter"
KIND_CORP_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
MARKETS = {"KOSPI": "0", "KOSDAQ": "1"}
REALTIME_CHUNK_SIZE = 80


def require_github_actions() -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise SystemExit("Data refresh is disabled locally. Run this updater from GitHub Actions only.")


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://finance.naver.com/"})
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


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def fetch_realtime_quotes(codes: list[str]) -> tuple[dict[str, dict], list[dict]]:
    quotes: dict[str, dict] = {}
    failures: list[dict] = []
    for chunk in chunked(codes, REALTIME_CHUNK_SIZE):
        query = f"SERVICE_ITEM:{','.join(chunk)}"
        url = f"{NAVER_REALTIME_URL}?{urlencode({'query': query})}"
        try:
            raw = fetch_bytes(url)
            payload = json.loads(raw.decode("euc-kr", "replace"))
            areas = payload.get("result", {}).get("areas", [])
            data = areas[0].get("datas", []) if areas else []
            for item in data:
                code = str(item.get("cd", "")).zfill(6)
                if code:
                    quotes[code] = item
        except (URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
            failures.append({"source": "Naver realtime polling", "error": str(exc), "codes": chunk[:3]})
            print(f"failed realtime chunk {chunk[:3]}: {exc}", file=sys.stderr)
        time.sleep(0.05)
    return quotes, failures


def fetch_quarter_finance(code: str) -> tuple[str, dict | None, str | None]:
    try:
        raw = fetch_bytes(NAVER_FINANCE_QUARTER_URL.format(code=code))
        payload = json.loads(raw.decode("utf-8", "replace"))
        return code, parse_quarter_finance(payload), None
    except (URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        return code, None, str(exc)


def parse_quarter_finance(payload: dict) -> dict | None:
    info = payload.get("financeInfo") or {}
    titles = info.get("trTitleList", [])
    rows = info.get("rowList", [])
    actual_titles = [item for item in titles if item.get("isConsensus") == "N" and item.get("key")]
    if not actual_titles:
        return None

    actual_titles.sort(key=lambda item: item["key"])
    consensus_titles = [item for item in titles if item.get("isConsensus") == "Y" and item.get("key")]
    consensus_titles.sort(key=lambda item: item["key"])
    latest = actual_titles[-1]
    latest_key = latest["key"]
    previous_quarter = actual_titles[-2] if len(actual_titles) >= 2 else None
    previous_quarter_key = previous_quarter.get("key") if previous_quarter else None
    prior_key = f"{int(latest_key[:4]) - 1}{latest_key[4:]}"
    prior = next((item for item in actual_titles if item.get("key") == prior_key), None)
    forecast = next((item for item in consensus_titles if item.get("key", "") > latest_key), consensus_titles[0] if consensus_titles else None)
    forecast_key = forecast.get("key") if forecast else None
    forecast_prior_year_key = f"{int(forecast_key[:4]) - 1}{forecast_key[4:]}" if forecast_key else None
    forecast_prior = next((item for item in actual_titles if item.get("key") == forecast_prior_year_key), None)

    row_map = {strip_html(row.get("title", "")): row.get("columns", {}) for row in rows}

    def column_value(row_title: str, key: str | None) -> int | None:
        if not key:
            return None
        value = row_map.get(row_title, {}).get(key, {}).get("value")
        return parse_int(value)

    def metric(row_title: str) -> dict:
        current = column_value(row_title, latest_key)
        prior_value = column_value(row_title, prior_key)
        previous_value = column_value(row_title, previous_quarter_key)
        forecast_value = column_value(row_title, forecast_key)
        forecast_prior_value = column_value(row_title, forecast_prior_year_key)
        yoy = growth_rate(current, prior_value)
        qoq = growth_rate(current, previous_value)
        forecast_yoy = growth_rate(forecast_value, forecast_prior_value)
        forecast_qoq = growth_rate(forecast_value, current)
        increased = yoy > 0 if yoy is not None else None
        return {
            "current": current,
            "prior_year": prior_value,
            "previous_quarter": previous_value,
            "yoy": yoy,
            "qoq": qoq,
            "increased": increased,
            "qoq_increased": qoq > 0 if qoq is not None else None,
            "forecast": forecast_value,
            "forecast_prior_year": forecast_prior_value,
            "forecast_yoy": forecast_yoy,
            "forecast_qoq": forecast_qoq,
            "forecast_increased": forecast_yoy > 0 if forecast_yoy is not None else None,
            "forecast_qoq_increased": forecast_qoq > 0 if forecast_qoq is not None else None,
        }

    revenue = metric("매출액")
    operating_income = metric("영업이익")
    net_income = metric("당기순이익")
    controlling_income = metric("지배주주순이익")

    return {
        "latestQuarter": latest.get("title"),
        "latestQuarterKey": latest_key,
        "previousQuarter": previous_quarter.get("title") if previous_quarter else None,
        "previousQuarterKey": previous_quarter_key,
        "priorYearQuarter": prior.get("title") if prior else None,
        "priorYearQuarterKey": prior_key if prior else None,
        "forecastQuarter": forecast.get("title") if forecast else None,
        "forecastQuarterKey": forecast_key,
        "forecastPriorYearQuarter": forecast_prior.get("title") if forecast_prior else None,
        "forecastPriorYearQuarterKey": forecast_prior_year_key if forecast_prior else None,
        "revenueEok": revenue["current"],
        "revenuePriorYearEok": revenue["prior_year"],
        "revenuePreviousQuarterEok": revenue["previous_quarter"],
        "revenueYoY": revenue["yoy"],
        "revenueQoQ": revenue["qoq"],
        "revenueIncreased": revenue["increased"],
        "revenueQoQIncreased": revenue["qoq_increased"],
        "forecastRevenueEok": revenue["forecast"],
        "forecastRevenuePriorYearEok": revenue["forecast_prior_year"],
        "forecastRevenueYoY": revenue["forecast_yoy"],
        "forecastRevenueQoQ": revenue["forecast_qoq"],
        "forecastRevenueIncreased": revenue["forecast_increased"],
        "forecastRevenueQoQIncreased": revenue["forecast_qoq_increased"],
        "operatingIncomeEok": operating_income["current"],
        "operatingIncomePriorYearEok": operating_income["prior_year"],
        "operatingIncomePreviousQuarterEok": operating_income["previous_quarter"],
        "operatingIncomeYoY": operating_income["yoy"],
        "operatingIncomeQoQ": operating_income["qoq"],
        "operatingIncomeIncreased": operating_income["increased"],
        "operatingIncomeQoQIncreased": operating_income["qoq_increased"],
        "forecastOperatingIncomeEok": operating_income["forecast"],
        "forecastOperatingIncomePriorYearEok": operating_income["forecast_prior_year"],
        "forecastOperatingIncomeYoY": operating_income["forecast_yoy"],
        "forecastOperatingIncomeQoQ": operating_income["forecast_qoq"],
        "forecastOperatingIncomeIncreased": operating_income["forecast_increased"],
        "forecastOperatingIncomeQoQIncreased": operating_income["forecast_qoq_increased"],
        "netIncomeQuarterEok": net_income["current"],
        "netIncomePriorYearEok": net_income["prior_year"],
        "netIncomePreviousQuarterEok": net_income["previous_quarter"],
        "netIncomeYoY": net_income["yoy"],
        "netIncomeQoQ": net_income["qoq"],
        "netIncomeIncreased": net_income["increased"],
        "netIncomeQoQIncreased": net_income["qoq_increased"],
        "forecastNetIncomeEok": net_income["forecast"],
        "forecastNetIncomePriorYearEok": net_income["forecast_prior_year"],
        "forecastNetIncomeYoY": net_income["forecast_yoy"],
        "forecastNetIncomeQoQ": net_income["forecast_qoq"],
        "forecastNetIncomeIncreased": net_income["forecast_increased"],
        "forecastNetIncomeQoQIncreased": net_income["forecast_qoq_increased"],
        "controllingNetIncomeQuarterEok": controlling_income["current"],
        "controllingNetIncomePriorYearEok": controlling_income["prior_year"],
        "controllingNetIncomePreviousQuarterEok": controlling_income["previous_quarter"],
        "controllingNetIncomeYoY": controlling_income["yoy"],
        "controllingNetIncomeQoQ": controlling_income["qoq"],
        "controllingNetIncomeIncreased": controlling_income["increased"],
        "controllingNetIncomeQoQIncreased": controlling_income["qoq_increased"],
        "forecastControllingNetIncomeEok": controlling_income["forecast"],
        "forecastControllingNetIncomePriorYearEok": controlling_income["forecast_prior_year"],
        "forecastControllingNetIncomeYoY": controlling_income["forecast_yoy"],
        "forecastControllingNetIncomeQoQ": controlling_income["forecast_qoq"],
        "forecastControllingNetIncomeIncreased": controlling_income["forecast_increased"],
        "forecastControllingNetIncomeQoQIncreased": controlling_income["forecast_qoq_increased"],
        "quarterFinanceSource": "Naver mobile stock finance/quarter",
    }


def fetch_quarter_finances(codes: list[str]) -> tuple[dict[str, dict], list[dict]]:
    max_workers = max(1, min(env_int("KR_FINANCE_WORKERS", 8), 16))
    max_stocks = env_int("KR_FINANCE_MAX_STOCKS", 0)
    selected = codes[:max_stocks] if max_stocks > 0 else codes
    finances: dict[str, dict] = {}
    failures: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_quarter_finance, code): code for code in selected}
        for index, future in enumerate(as_completed(future_map), start=1):
            code, finance, error = future.result()
            if finance:
                finances[code] = finance
            elif error:
                failures.append({"source": f"Naver quarter finance {code}", "error": error})
            if index % 200 == 0:
                print(f"quarter finance fetched: {index}/{len(selected)}")
    return finances, failures


def quote_number(quote: dict | None, key: str) -> float | None:
    if not quote:
        return None
    value = quote.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return parse_number(str(value)) if value is not None else None


def quote_int(quote: dict | None, key: str) -> int | None:
    value = quote_number(quote, key)
    return int(round(value)) if value is not None else None


def quote_market_cap_eok(price: int | None, shares: int | None) -> int | None:
    if not price or not shares:
        return None
    return int(round(price * shares / 100000000))


def quote_per(price: int | None, eps: float | None) -> float | None:
    if not price or eps is None or eps <= 0:
        return None
    return price / eps


def quote_roe_from_eps_bps(eps: float | None, bps: float | None) -> float | None:
    if eps is None or bps is None or bps <= 0:
        return None
    return eps / bps


def ratio_or_none(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def growth_rate(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def peg_or_none(pe: float | None, growth: float | None) -> float | None:
    if pe is None or growth is None or growth <= 0:
        return None
    return pe / (growth * 100)


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


def apply_realtime_quote(stock: dict, quote: dict, fetched_at: str) -> dict:
    current_price = quote_int(quote, "nv")
    shares = quote_int(quote, "countOfListedStock")
    volume = quote_int(quote, "aq")
    eps = quote_number(quote, "eps")
    bps = quote_number(quote, "bps")
    consensus_eps = quote_number(quote, "cnsEps")
    per = quote_per(current_price, eps)
    forward_per = ratio_or_none(current_price, consensus_eps)
    forward_eps_growth = consensus_eps / eps - 1 if consensus_eps is not None and eps not in (None, 0) else None
    roe_from_eps_bps = quote_roe_from_eps_bps(eps, bps)
    market_cap_eok = quote_market_cap_eok(current_price, shares)

    if current_price is not None:
        stock["currentPrice"] = current_price
    if shares is not None:
        stock["shares"] = shares
    if volume is not None:
        stock["volume"] = volume
    if market_cap_eok is not None:
        stock["marketCapEok"] = market_cap_eok
    if per is not None:
        stock["per"] = per
    if roe_from_eps_bps is not None:
        stock["roeFromEpsBps"] = roe_from_eps_bps

    stock.update(
        {
            "previousClose": quote_int(quote, "pcv"),
            "openPrice": quote_int(quote, "ov"),
            "highPrice": quote_int(quote, "hv"),
            "lowPrice": quote_int(quote, "lv"),
            "change": quote_int(quote, "cv"),
            "changeRate": (quote_number(quote, "cr") or 0) / 100 if quote_number(quote, "cr") is not None else None,
            "accumulatedTradeValue": quote_int(quote, "aa"),
            "eps": eps,
            "bps": bps,
            "consensusEps": consensus_eps,
            "forwardPer": forward_per,
            "forwardEpsGrowth": forward_eps_growth,
            "futureEpsGrowth": forward_eps_growth,
            "peg": peg_or_none(per, forward_eps_growth),
            "forwardPeg": peg_or_none(forward_per, forward_eps_growth),
            "marketStatus": quote.get("ms"),
            "quoteFetchedAt": fetched_at,
            "priceSource": "Naver Finance realtime polling SERVICE_ITEM",
            "valuationRatiosSource": "Naver realtime EPS and consensus EPS; PEG is derived from estimated EPS growth",
        }
    )
    return stock


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def main() -> int:
    require_github_actions()
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

    quote_fetched_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    if stocks:
        realtime_quotes, realtime_failures = fetch_realtime_quotes([stock["code"] for stock in stocks if stock.get("code")])
        failures.extend(realtime_failures)
        for stock in stocks:
            quote = realtime_quotes.get(stock.get("code"))
            if quote:
                apply_realtime_quote(stock, quote, quote_fetched_at)
                stock["hasRealtimePrice"] = True
            else:
                stock["hasRealtimePrice"] = False

        quarter_finances, quarter_failures = fetch_quarter_finances([stock["code"] for stock in stocks if stock.get("code")])
        failures.extend(quarter_failures[:100])
        for stock in stocks:
            finance = quarter_finances.get(stock.get("code"))
            if finance:
                stock.update(finance)
                stock["hasQuarterFinance"] = True
            else:
                stock["hasQuarterFinance"] = False

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
        "priceFetchedAt": quote_fetched_at,
        "source": "Naver Finance realtime polling + Naver Finance market summary + KRX KIND listed company list",
        "priceSource": "Naver Finance realtime polling SERVICE_ITEM",
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
