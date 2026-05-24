# S-RIM 마법사 Plus

`index.html`은 엑셀 `S-RIM 마법사 Plus_V23.xlsx`의 핵심 RIM 계산식을 웹 계산기로 옮긴 파일입니다.

매일 최신 기준값은 GitHub Actions가 `scripts/update_market_data.py`를 실행해 `data/latest.json`을 갱신합니다.

데이터 갱신 범위:
- KRX KIND 상장법인목록 기준 KOSPI/KOSDAQ 전체 상장회사
- Naver Finance 시장 요약 기준 현재가, 상장주식수, 시가총액, PER, ROE
- 화면에서는 KOSPI/KOSDAQ 탭과 검색 입력으로 종목을 선택합니다.
