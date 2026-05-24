# S-RIM 마법사 Plus

`index.html`은 엑셀 `S-RIM 마법사 Plus_V23.xlsx`의 핵심 RIM 계산식을 웹 계산기로 옮긴 파일입니다.

매일 최신 기준값은 GitHub Actions가 `scripts/update_market_data.py`와 `scripts/update_us_market_data.py`를 실행해 `data/latest.json`, `data/us_latest.json`을 갱신합니다.

데이터 갱신 범위:
- KRX KIND 상장법인목록 기준 KOSPI/KOSDAQ 전체 상장회사
- Naver Finance 실시간 폴링 기준 최신 체결가, 거래량, 상장주식수, 시가총액
- Naver Finance 시장 요약 기준 PER, ROE 등 재무 배수
- 화면에서는 KOSPI/KOSDAQ 탭과 검색 입력으로 종목을 선택합니다.
- 미국 주식 탭은 Nasdaq 종목별 quote info의 최신 체결가와 Nasdaq summary의 1년 목표가를 사용합니다. 지연 시세나 장마감 데이터는 기준일과 상태를 화면에 함께 표시합니다.
