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

THEME_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("AI 반도체", ("NVDA", "AMD", "AVGO", "MRVL", "ARM"), ("accelerated computing", "gpu", "ai accelerator", "data center chip")),
    ("AI SW", ("PLTR", "AI", "SNOW", "DDOG", "MDB", "CRM", "NOW", "MSFT", "ORCL", "ADBE", "PATH"), ("ai software", "analytics", "data platform", "machine learning")),
    ("AI 인프라", ("SMCI", "DELL", "VRT", "ANET", "NTAP"), ("ai infrastructure", "server", "storage", "networking products", "data center")),
    ("SW/SaaS", ("MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "ADSK", "TEAM", "WDAY"), ("prepackaged software", "saas", "application software")),
    ("클라우드/데이터", ("AMZN", "GOOGL", "MSFT", "ORCL", "SNOW", "NET", "DDOG", "MDB"), ("cloud", "data platform", "internet services")),
    ("사이버보안", ("PANW", "CRWD", "ZS", "FTNT", "OKTA", "NET", "CHKP", "S"), ("security", "cyber", "identity", "firewall")),
    ("로봇/자동화", ("ISRG", "ROK", "TER", "SYM", "ZBRA", "HON", "EMR"), ("robot", "automation", "laboratory analytical instruments")),
    ("반도체", ("NVDA", "AMD", "AVGO", "QCOM", "MU", "MRVL", "INTC", "TXN", "ADI", "ON"), ("semiconductors", "integrated circuit")),
    ("반도체 장비", ("AMAT", "LRCX", "KLAC", "ASML", "TER"), ("semiconductor equipment", "wafer", "test systems")),
    ("광통신", ("CIEN", "LITE", "COHR", "GLW", "AAOI", "COMM", "FN", "NOK"), ("optical", "photonics", "fiber", "fibre", "laser", "telecommunications equipment")),
    ("전자부품", ("APH", "TEL", "GLW", "JBL", "FLEX"), ("electronic components", "electrical products")),
    ("전력망/전기장비", ("ETN", "GEV", "PWR", "VRT", "HUBB", "GNRC"), ("electrical", "grid", "power generation", "electrical products")),
    ("전력 유틸", ("VST", "CEG", "NRG", "SO", "DUK", "AEP", "EXC"), ("electric utilities", "central")),
    ("원전/우라늄", ("CEG", "CCJ", "SMR", "NNE", "LEU", "BWXT"), ("nuclear", "uranium")),
    ("재생에너지/저장", ("BE", "FLNC", "ENPH", "SEDG", "FSLR"), ("renewable", "solar", "energy storage", "fuel cell")),
    ("천연가스/LNG", ("LNG", "KMI", "WMB", "OKE", "TRGP"), ("natural gas", "lng", "gas distribution")),
    ("석유가스 E&P", ("XOM", "CVX", "COP", "EOG", "OXY", "DVN"), ("oil & gas production", "integrated oil")),
    ("유전서비스", ("SLB", "HAL", "BKR"), ("oilfield", "oil & gas field services")),
    ("바이오텍", ("REGN", "VRTX", "MRNA", "BIIB", "GILD"), ("biotechnology", "biological products")),
    ("제약", ("LLY", "JNJ", "MRK", "ABBV", "PFE", "AMGN", "BMY"), ("pharmaceutical", "drug", "preparations")),
    ("의료기기", ("ISRG", "SYK", "MDT", "BSX", "EW", "ZBH"), ("medical/dental instruments", "medical specialties", "laboratory analytical instruments")),
    ("헬스케어 서비스", ("UNH", "HUM", "CI", "CVS", "HCA"), ("hospital", "health care", "managed care")),
    ("대형은행", ("JPM", "BAC", "WFC", "C", "USB", "PNC"), ("major banks", "commercial banks")),
    ("투자은행/브로커", ("GS", "MS", "SCHW", "IBKR"), ("investment bankers", "brokers")),
    ("자산운용", ("BLK", "BX", "KKR", "APO", "TROW"), ("investment managers", "asset management")),
    ("보험", ("BRK.B", "PGR", "AIG", "MET", "PRU", "ALL"), ("insurance", "insurers")),
    ("핀테크/결제", ("V", "MA", "AXP", "PYPL", "SQ", "COIN"), ("payment", "transaction", "finance: consumer services")),
    ("리츠", ("PLD", "AMT", "EQIX", "DLR", "O", "SPG", "CCI"), ("real estate investment trusts", "reit")),
    ("산업기계", ("CAT", "DE", "ROK", "EMR", "PH", "ITW"), ("industrial machinery", "machinery/components")),
    ("방산/항공", ("RTX", "BA", "LMT", "NOC", "GD", "HWM"), ("aerospace", "military", "defense")),
    ("철도/물류", ("UNP", "CSX", "NSC", "FDX", "UPS"), ("railroads", "transportation", "trucking")),
    ("건설/엔지니어링", ("PWR", "FLR", "J", "ACM", "VMC"), ("construction", "engineering", "building materials")),
    ("상업서비스", ("ADP", "PAYX", "CTAS", "CPRT", "RSG", "WM"), ("business services", "commercial services", "waste")),
    ("자동차/EV", ("TSLA", "RIVN", "LCID", "F", "GM"), ("auto manufacturing", "motor vehicles", "electric vehicle")),
    ("배터리/리튬", ("ALB", "QS", "ENVX", "LAC"), ("battery", "lithium")),
    ("이커머스/리테일", ("AMZN", "WMT", "COST", "TGT", "EBAY"), ("catalog/specialty distribution", "department/specialty retail stores", "retail")),
    ("홈/건자재", ("HD", "LOW", "TSCO"), ("building materials", "home improvement")),
    ("레스토랑/호텔", ("MCD", "SBUX", "CMG", "YUM", "MAR", "HLT"), ("restaurants", "hotels/resorts")),
    ("여행/레저", ("BKNG", "ABNB", "RCL", "CCL", "DIS"), ("amusement", "recreation", "travel")),
    ("의류/스포츠", ("NKE", "LULU", "TPR", "RL"), ("apparel", "shoe", "sporting")),
    ("식음료", ("KO", "PEP", "MDLZ", "KHC", "GIS", "KDP"), ("packaged foods", "beverages", "food")),
    ("생활소비재", ("PG", "CL", "KMB", "EL", "CHD"), ("consumer specialties", "household", "personal care")),
    ("농업/화학", ("CF", "MOS", "DD", "DOW", "LIN"), ("chemicals", "agricultural", "fertilizers")),
    ("금속/광산", ("FCX", "NEM", "SCCO", "AA", "CLF"), ("metal", "mining", "steel")),
    ("통신서비스", ("VZ", "T", "TMUS", "CMCSA"), ("telecommunications", "broadcasting")),
)

SECTOR_LABELS = {
    "Basic Materials": "소재",
    "Consumer Discretionary": "소비재",
    "Consumer Staples": "필수소비재",
    "Energy": "에너지/전력",
    "Finance": "금융",
    "Health Care": "헬스케어",
    "Industrials": "산업재",
    "Miscellaneous": "기타",
    "Real Estate": "부동산",
    "Technology": "테크",
    "Telecommunications": "커뮤니케이션",
    "Utilities": "에너지/전력",
}

INDUSTRY_LABEL_RULES: tuple[tuple[str, str], ...] = (
    ("Advertising", "광고/마케팅"),
    ("Air Freight/Delivery Services", "항공화물/배송"),
    ("Auto & Home Supply Stores", "자동차/홈용품"),
    ("Auto Parts", "자동차부품"),
    ("Automotive Aftermarket", "자동차 애프터마켓"),
    ("Accident &Health Insurance", "건강보험"),
    ("Agricultural Chemicals", "농업/화학"),
    ("Aluminum", "알루미늄"),
    ("Banks", "은행"),
    ("Broadcasting", "방송/미디어"),
    ("Building Products", "건축자재"),
    ("Building Materials", "건축자재"),
    ("Catalog/Specialty Distribution", "이커머스/전문유통"),
    ("Clothing/Shoe/Accessory Stores", "의류/잡화 리테일"),
    ("Computer Manufacturing", "컴퓨터 하드웨어"),
    ("Computer peripheral equipment", "주변기기"),
    ("Construction/Ag Equipment/Trucks", "건설/농기계"),
    ("Consumer Electronics", "소비자전자"),
    ("Containers/Packaging", "포장재"),
    ("Department/Specialty Retail Stores", "전문리테일"),
    ("Diversified Financial Services", "종합금융"),
    ("Durable Goods", "내구소비재"),
    ("Electronics Distribution", "전자유통"),
    ("Engineering & Construction", "건설/엔지니어링"),
    ("Environmental Services", "환경서비스"),
    ("Farming/Seeds/Milling", "농업/종자"),
    ("Finance/Investors Services", "투자서비스"),
    ("Fluid Controls", "유체제어"),
    ("Food Chains", "식품리테일"),
    ("Food Distributors", "식품유통"),
    ("Garments and Clothing", "의류/스포츠"),
    ("Home Furnishings", "가구/인테리어"),
    ("Homebuilding", "주택건설"),
    ("Integrated oil Companies", "통합 석유가스"),
    ("Integrated Freight & Logistics", "통합물류"),
    ("Industrial Specialties", "산업특수재"),
    ("Marine Transportation", "해운/물류"),
    ("Metal Fabrications", "금속가공"),
    ("Meat/Poultry/Fish", "식품"),
    ("Mining & Quarrying of Nonmetallic Minerals", "비금속광물"),
    ("Misc Corporate Leasing Services", "기업리스"),
    ("Multi-Sector Companies", "복합기업"),
    ("Newspapers/Magazines", "출판/미디어"),
    ("Office Equipment/Supplies/Services", "사무장비/서비스"),
    ("Ordnance And Accessories", "방산부품"),
    ("Other Consumer Services", "기타 소비자서비스"),
    ("Other Specialty Stores", "전문상점"),
    ("Package Goods/Cosmetics", "화장품/생활용품"),
    ("Paints/Coatings", "페인트/코팅"),
    ("Paper", "종이/펄프"),
    ("Plastic Products", "플라스틱"),
    ("Pollution Control Equipment", "환경장비"),
    ("Precious Metals", "귀금속"),
    ("Professional Services", "전문서비스"),
    ("Radio And Television Broadcasting And Communications Equipment", "통신장비"),
    ("Publishing", "출판/미디어"),
    ("Real Estate", "부동산 개발/서비스"),
    ("Recreational Games/Products/Toys", "완구/레저용품"),
    ("Rental/Leasing Companies", "렌탈/리스"),
    ("Retail-Auto Dealers and Gas Stations", "자동차딜러/주유"),
    ("Retail-Drug Stores", "드럭스토어"),
    ("Services-Misc. Amusement & Recreation", "레저/엔터"),
    ("Shoe Manufacturing", "신발"),
    ("Specialty Foods", "특수식품"),
    ("Specialty Chemicals", "특수화학"),
    ("Telecommunications Equipment", "통신장비"),
    ("Tools/Hardware", "공구/하드웨어"),
    ("Trucking Freight/Courier Services", "트럭/택배물류"),
    ("Water, Sewer, Pipeline, Comm & Power Line Construction", "인프라 건설"),
    ("Transportation Services", "운송서비스"),
)


def require_github_actions() -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise SystemExit("Data refresh is disabled locally. Run this updater from GitHub Actions only.")


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


def extract_stat_text(text: str, metric_id: str) -> str | None:
    match = re.search(r'\{id:"' + re.escape(metric_id) + r'"[^}]*\}', text)
    if not match:
        return None
    item = match.group(0)
    hover = re.search(r'hover:"([^"]*)"', item)
    value = re.search(r'value:"([^"]*)"', item)
    raw = hover.group(1) if hover else value.group(1) if value else None
    cleaned = strip_html(raw)
    return cleaned if cleaned and cleaned.lower() != "n/a" else None


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
        "ps": extract_stat_metric(stats_text, "ps"),
        "forwardPs": extract_stat_metric(stats_text, "psForward"),
        "pb": extract_stat_metric(stats_text, "pb"),
        "priceToFcf": extract_stat_metric(stats_text, "pfcf"),
        "priceToOcf": extract_stat_metric(stats_text, "pocf"),
        "evToSales": extract_stat_metric(stats_text, "evSales"),
        "evToEbitda": extract_stat_metric(stats_text, "evEbitda"),
        "evToEbit": extract_stat_metric(stats_text, "evEbit"),
        "currentRatio": extract_stat_metric(stats_text, "currentRatio"),
        "quickRatio": extract_stat_metric(stats_text, "quickRatio"),
        "debtEquity": extract_stat_metric(stats_text, "debtEquity"),
        "debtEbitda": extract_stat_metric(stats_text, "debtEbitda"),
        "interestCoverage": extract_stat_metric(stats_text, "interestCoverage"),
        "roe": extract_stat_metric(stats_text, "roe", percent=True),
        "roa": extract_stat_metric(stats_text, "roa", percent=True),
        "roic": extract_stat_metric(stats_text, "roic", percent=True),
        "wacc": extract_stat_metric(stats_text, "wacc", percent=True),
        "beta": extract_stat_metric(stats_text, "beta"),
        "priceChange52w": extract_stat_metric(stats_text, "ch1y", percent=True),
        "sma50": extract_stat_metric(stats_text, "sma50"),
        "sma200": extract_stat_metric(stats_text, "sma200"),
        "rsi": extract_stat_metric(stats_text, "rsi"),
        "shortFloat": extract_stat_metric(stats_text, "shortFloat", percent=True),
        "shortRatio": extract_stat_metric(stats_text, "shortRatio"),
        "grossMargin": extract_stat_metric(stats_text, "grossMargin", percent=True),
        "operatingMargin": extract_stat_metric(stats_text, "operatingMargin", percent=True),
        "profitMargin": extract_stat_metric(stats_text, "profitMargin", percent=True),
        "fcfMargin": extract_stat_metric(stats_text, "fcfMargin", percent=True),
        "dividendYield": extract_stat_metric(stats_text, "dividendYield", percent=True),
        "buybackYield": extract_stat_metric(stats_text, "buybackYield", percent=True),
        "shareholderYield": extract_stat_metric(stats_text, "totalReturn", percent=True),
        "earningsYield": extract_stat_metric(stats_text, "earningsYield", percent=True),
        "fcfYield": extract_stat_metric(stats_text, "fcfYield", percent=True),
        "stockanalysisPriceTarget": extract_stat_metric(stats_text, "priceTarget"),
        "stockanalysisTargetUpside": extract_stat_metric(stats_text, "priceTargetChange", percent=True),
        "analystConsensus": extract_stat_text(stats_text, "analystRatings"),
        "analystCount": extract_stat_metric(stats_text, "analystCount"),
        "piotroskiFScore": extract_stat_metric(stats_text, "fScore"),
        "altmanZScore": extract_stat_metric(stats_text, "zScore"),
        "revenueGrowthForecast5Y": revenue_growth_5y,
        "epsGrowthForecast5Y": eps_growth_5y,
        "futureRevenueGrowth": revenue_growth_5y,
        "futureProfitGrowth": eps_growth_5y,
        "futureEpsGrowth": eps_growth_5y,
        "futureProfitGrowthMetric": "EPS Growth Forecast (5Y)",
        "ttmRevenue": extract_stat_metric(stats_text, "revenue"),
        "ttmGrossProfit": extract_stat_metric(stats_text, "gp"),
        "ttmOperatingIncome": extract_stat_metric(stats_text, "opinc"),
        "ttmNetIncome": extract_stat_metric(stats_text, "netinc"),
        "ttmEbitda": extract_stat_metric(stats_text, "ebitda"),
        "ttmFreeCashFlow": extract_stat_metric(stats_text, "fcf"),
        "totalCash": extract_stat_metric(stats_text, "totalcash"),
        "totalDebt": extract_stat_metric(stats_text, "debt"),
        "netCash": extract_stat_metric(stats_text, "netcash"),
        "bookValuePerShare": extract_stat_metric(stats_text, "bvps"),
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
            f"exchange::{stock.get('exchangeGroup', '')}",
            f"theme::{stock.get('theme', '')}",
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


def normalize_exchange(value: object) -> str:
    text = strip_html(value).upper()
    if "NASDAQ" in text:
        return "NASDAQ"
    if text == "NYSE" or "NEW YORK STOCK EXCHANGE" in text:
        return "NYSE"
    if "AMEX" in text or "NYSE AMERICAN" in text:
        return "AMEX"
    return text or "기타"


def detect_theme_tags(stock: dict) -> list[str]:
    symbol = strip_html(stock.get("symbol")).upper()
    haystack = " ".join(
        strip_html(stock.get(key)).lower()
        for key in ("name", "sector", "industry")
    )
    padded = f" {haystack} "
    tags: list[str] = []
    for theme, symbols, keywords in THEME_RULES:
        if symbol in symbols or any(keyword in padded for keyword in keywords):
            tags.append(theme)
    if not tags:
        industry = strip_html(stock.get("industry"))
        sector = strip_html(stock.get("sector"))
        fallback_rules = (
            ("Real Estate Investment Trusts", "리츠"),
            ("Major Banks", "대형은행"),
            ("Investment Bankers", "투자은행/브로커"),
            ("Investment Managers", "자산운용"),
            ("Insurers", "보험"),
            ("Finance: Consumer Services", "핀테크/결제"),
            ("Industrial Machinery", "산업기계"),
            ("Electrical Products", "전력망/전기장비"),
            ("Metal Fabrications", "금속가공"),
            ("Aerospace", "방산/항공"),
            ("Military", "방산/항공"),
            ("Marine Transportation", "해운/물류"),
            ("Business Services", "상업서비스"),
            ("Biotechnology", "바이오텍"),
            ("Pharmaceutical", "제약"),
            ("Medical/Dental Instruments", "의료기기"),
            ("Medical Specialities", "의료기기"),
            ("Semiconductors", "반도체"),
            ("Computer Software", "SW/SaaS"),
            ("EDP Services", "IT서비스/데이터"),
            ("Telecommunications Equipment", "광통신"),
            ("Electronic Components", "전자부품"),
            ("Electric Utilities", "전력 유틸"),
            ("Power Generation", "전력망/전기장비"),
            ("Natural Gas", "천연가스/LNG"),
            ("Oil & Gas Production", "석유가스 E&P"),
            ("Oilfield", "유전서비스"),
            ("Retail", "이커머스/리테일"),
            ("RETAIL", "이커머스/리테일"),
            ("Restaurants", "레스토랑/호텔"),
            ("Hotels/Resorts", "레스토랑/호텔"),
            ("Amusement", "여행/레저"),
            ("Apparel", "의류/스포츠"),
            ("Packaged Foods", "식음료"),
            ("Beverages", "식음료"),
            ("Chemicals", "농업/화학"),
            ("Steel", "금속/광산"),
        )
        tags.append(next((theme for needle, theme in fallback_rules if needle.lower() in industry.lower()), fallback_theme_tag(sector, industry)))
    return tags


def fallback_theme_tag(sector: str, industry: str) -> str:
    lower_industry = industry.lower()
    industry_label = next(
        (label for needle, label in INDUSTRY_LABEL_RULES if needle.lower() in lower_industry),
        "",
    )
    if industry_label:
        return industry_label
    return f"{SECTOR_LABELS.get(sector, '기타')} 기타"


def fallback_detail_sector(sector: str, industry: str) -> str:
    sector_label = SECTOR_LABELS.get(sector, sector or "기타")
    lower_industry = industry.lower()
    industry_label = next(
        (label for needle, label in INDUSTRY_LABEL_RULES if needle.lower() in lower_industry),
        "기타 세부업종",
    )
    return f"{sector_label} > {industry_label}"


def detect_detail_sector(stock: dict) -> str:
    tags = stock.get("themeTags") or detect_theme_tags(stock)
    sector = strip_html(stock.get("sector"))
    industry = strip_html(stock.get("industry"))
    text = f"{sector} {industry}".lower()

    def has(*names: str) -> bool:
        return any(name in tags for name in names)

    if has("AI 반도체"):
        return "테크 > AI 반도체"
    if has("AI SW", "AI 인프라"):
        return "테크 > AI/데이터 인프라"
    if has("반도체", "반도체 장비"):
        return "테크 > 반도체/장비"
    if has("SW/SaaS", "클라우드/데이터"):
        return "테크 > SW/클라우드"
    if has("사이버보안"):
        return "테크 > 사이버보안"
    if has("광통신", "전자부품"):
        return "테크 > 네트워크/부품"
    if has("전력망/전기장비", "로봇/자동화"):
        return "산업재 > 전력/자동화"
    if has("전력 유틸"):
        return "에너지/전력 > 전력 유틸"
    if has("원전/우라늄", "재생에너지/저장"):
        return "에너지/전력 > 원전/재생"
    if has("천연가스/LNG", "석유가스 E&P", "유전서비스"):
        return "에너지/전력 > 석유가스/LNG"
    if has("바이오텍", "제약"):
        return "헬스케어 > 바이오/제약"
    if has("의료기기"):
        return "헬스케어 > 의료기기"
    if has("헬스케어 서비스"):
        return "헬스케어 > 서비스/보험"
    if has("대형은행"):
        return "금융 > 은행"
    if has("투자은행/브로커", "자산운용"):
        return "금융 > 증권/운용"
    if has("보험"):
        return "금융 > 보험"
    if has("핀테크/결제"):
        return "금융 > 핀테크/결제"
    if has("리츠"):
        return "부동산 > 리츠/인프라"
    if has("산업기계"):
        return "산업재 > 기계/장비"
    if has("방산/항공"):
        return "산업재 > 방산/항공"
    if has("철도/물류"):
        return "산업재 > 물류/철도"
    if has("건설/엔지니어링"):
        return "산업재 > 건설/엔지니어링"
    if has("상업서비스"):
        return "산업재 > 상업서비스"
    if has("자동차/EV", "배터리/리튬"):
        return "소비재 > 자동차/EV"
    if has("이커머스/리테일", "홈/건자재"):
        return "소비재 > 리테일/홈"
    if has("레스토랑/호텔", "여행/레저"):
        return "소비재 > 호텔/레저/외식"
    if has("의류/스포츠"):
        return "소비재 > 의류/스포츠"
    if has("식음료", "생활소비재"):
        return "필수소비재 > 식음료/생활"
    if has("농업/화학"):
        return "소재 > 화학/농업"
    if has("금속/광산"):
        return "소재 > 금속/광산"
    if has("통신서비스"):
        return "커뮤니케이션 > 통신/미디어"
    if "software" in text or "edp services" in text:
        return "테크 > SW/클라우드"
    if "semiconductor" in text:
        return "테크 > 반도체/장비"
    if "bank" in text:
        return "금융 > 은행"
    if "insurance" in text:
        return "금융 > 보험"
    if "biotechnology" in text or "pharmaceutical" in text:
        return "헬스케어 > 바이오/제약"
    if "electric utilities" in text:
        return "에너지/전력 > 전력 유틸"
    if "oil" in text or "natural gas" in text:
        return "에너지/전력 > 석유가스/LNG"
    if "retail" in text:
        return "소비재 > 리테일/홈"
    if "restaurants" in text or "hotels" in text:
        return "소비재 > 호텔/레저/외식"
    return fallback_detail_sector(sector, industry)


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
    require_github_actions()
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
            if not isinstance(merged.get("targetPrice"), (int, float)) and isinstance(fundamental.get("stockanalysisPriceTarget"), (int, float)):
                merged["targetPrice"] = fundamental["stockanalysisPriceTarget"]
                price = merged.get("price")
                merged["targetUpside"] = fundamental.get("stockanalysisTargetUpside") if isinstance(fundamental.get("stockanalysisTargetUpside"), (int, float)) else (merged["targetPrice"] / price - 1 if price else None)
        else:
            merged["hasFundamentals"] = False
        merged["exchangeGroup"] = normalize_exchange(merged.get("exchange"))
        merged["themeTags"] = detect_theme_tags(merged)
        merged["theme"] = merged["themeTags"][0] if merged["themeTags"] else "기타"
        merged["detailedSector"] = detect_detail_sector(merged)
        stocks.append(merged)
    if not stocks:
        stocks = previous.get("stocks", [])

    stocks.sort(key=lambda item: (item.get("sector", ""), item.get("industry", ""), -(item.get("marketCap") or 0)))
    counts: dict[str, int] = {}
    exchange_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    detailed_sector_counts: dict[str, int] = {}
    for stock in stocks:
        counts[stock["sector"]] = counts.get(stock["sector"], 0) + 1
        detailed_sector = stock.get("detailedSector") or detect_detail_sector(stock)
        detailed_sector_counts[detailed_sector] = detailed_sector_counts.get(detailed_sector, 0) + 1
        exchange = stock.get("exchangeGroup") or "기타"
        exchange_counts[exchange] = exchange_counts.get(exchange, 0) + 1
        for theme in stock.get("themeTags") or [stock.get("theme") or "기타"]:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

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
        "detailedSectorCounts": detailed_sector_counts,
        "exchangeCounts": exchange_counts,
        "themeCounts": theme_counts,
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
