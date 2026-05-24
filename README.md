# S-RIM 마법사 Plus

`index.html`은 엑셀 `S-RIM 마법사 Plus_V23.xlsx`의 핵심 RIM 계산식을 웹 계산기로 옮긴 파일입니다.

매일 최신 기준값은 GitHub Actions가 `scripts/update_market_data.py`와 `scripts/update_us_market_data.py`를 실행해 `data/latest.json`, `data/us_latest.json`을 갱신합니다.

데이터 갱신 범위:
- KRX KIND 상장법인목록 기준 KOSPI/KOSDAQ 전체 상장회사
- Naver Finance 시장 요약 기준 현재가, 상장주식수, 시가총액, PER, ROE
- 화면에서는 KOSPI/KOSDAQ 탭과 검색 입력으로 종목을 선택합니다.
- 미국 주식 탭은 Nasdaq 스크리너와 종목 요약 기준으로 섹터, 업종/테마, 종목 드롭다운을 구성하고 1년 목표가와 경쟁사 중간 목표상승률로 저평가/고평가를 계산합니다.
