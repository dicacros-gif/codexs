from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KST = dt.timezone(dt.timedelta(hours=9), "KST")
KR_DATA = ROOT / "data" / "latest.json"
US_DATA = ROOT / "data" / "us_latest.json"


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(KST)


def generated_date(path: Path) -> dt.date | None:
    try:
        data = read_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    generated_at = parse_time(data.get("generatedAt"))
    return generated_at.date() if generated_at else None


def set_github_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def decide() -> int:
    today = dt.datetime.now(KST).date()
    event = os.getenv("GITHUB_EVENT_NAME", "")
    force = event in {"push", "workflow_dispatch"}
    kr_date = generated_date(KR_DATA)
    us_date = generated_date(US_DATA)
    needs_update = force or kr_date != today or us_date != today
    reason = (
        f"event={event or 'unknown'} force={force} "
        f"today={today.isoformat()} kr={kr_date or 'missing'} us={us_date or 'missing'}"
    )
    set_github_output("needs_update", "true" if needs_update else "false")
    set_github_output("reason", reason)
    print(f"needs_update={'true' if needs_update else 'false'}")
    print(reason)
    return 0


def count_positive(stocks: list[dict], field: str) -> int:
    return sum(1 for stock in stocks if isinstance(stock.get(field), (int, float)) and stock.get(field) > 0)


def validate_kr(today: dt.date) -> None:
    data = read_json(KR_DATA)
    generated_at = parse_time(data.get("generatedAt"))
    price_fetched_at = parse_time(data.get("priceFetchedAt"))
    stocks = data.get("stocks") if isinstance(data.get("stocks"), list) else []
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    priced = count_positive(stocks, "currentPrice")
    errors = []
    if not generated_at or generated_at.date() != today:
        errors.append(f"KR generatedAt is not today: {data.get('generatedAt')}")
    if not price_fetched_at or price_fetched_at.date() != today:
        errors.append(f"KR priceFetchedAt is not today: {data.get('priceFetchedAt')}")
    if len(stocks) < 2000:
        errors.append(f"KR stock count too low: {len(stocks)}")
    if counts.get("KOSPI", 0) <= 0 or counts.get("KOSDAQ", 0) <= 0:
        errors.append(f"KR market counts invalid: {counts}")
    if priced < 1000:
        errors.append(f"KR priced stock count too low: {priced}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"KR valid: generated={generated_at.isoformat()} stocks={len(stocks)} priced={priced}")


def validate_us(today: dt.date) -> None:
    data = read_json(US_DATA)
    generated_at = parse_time(data.get("generatedAt"))
    stocks = data.get("stocks") if isinstance(data.get("stocks"), list) else []
    priced = count_positive(stocks, "price")
    errors = []
    if not generated_at or generated_at.date() != today:
        errors.append(f"US generatedAt is not today: {data.get('generatedAt')}")
    if len(stocks) < 900:
        errors.append(f"US stock count too low: {len(stocks)}")
    if priced < 900:
        errors.append(f"US priced stock count too low: {priced}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"US valid: generated={generated_at.isoformat()} stocks={len(stocks)} priced={priced}")


def validate() -> int:
    today = dt.datetime.now(KST).date()
    validate_kr(today)
    validate_us(today)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("decide", "validate"))
    args = parser.parse_args()
    if args.mode == "decide":
        return decide()
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
