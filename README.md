# S-RIM 마법사 Plus

`index.html`은 엑셀 `S-RIM 마법사 Plus_V23.xlsx`의 핵심 RIM 계산식을 웹 계산기로 옮긴 파일입니다.

최신 기준값은 로컬 PC에서 갱신하지 않고 GitHub Actions에서만 갱신합니다. 예약 작업은 매일 한국시간 20:30에 실행되며, `scripts/update_market_data.py`와 `scripts/update_us_market_data.py`를 실행해 `data/latest.json`, `data/us_latest.json`을 업데이트한 뒤 GitHub Pages에 배포합니다.

데이터 갱신 범위:
- KRX KIND 상장법인목록 기준 KOSPI/KOSDAQ 전체 상장회사
- Naver Finance 실시간 폴링 기준 종가, 거래량, 상장주식수, 시가총액
- Naver Finance 시장 요약 기준 PER, ROE 등 재무 배수
- Naver 모바일 재무 분기 데이터 기준 최근 분기 매출액, 영업이익, 순이익의 전년 동기비와 전분기비 증감률
- Naver 모바일 컨센서스 분기 데이터 기준 다음 예상 분기 매출액, 영업이익, 순이익의 전년 동기비와 최신 분기 대비 예상 성장률
- 화면에서는 KOSPI/KOSDAQ 탭과 검색 입력으로 종목을 선택합니다.
- 저평가 순위 탭은 KOSPI 100과 KOSDAQ 100을 분리해 적정가 대비 저평가율 순으로 표시합니다.
- 업종 비교 표는 같은 업종 종목의 PER, ROE, 시가총액, 매출/순이익 YoY·QoQ, 다음 분기 예상 성장률을 함께 보여줍니다.
- 미국 주식 탭은 Nasdaq 종목별 quote info의 종가와 Nasdaq summary의 1년 목표가를 사용합니다. PER, Forward PER, PEG, P/S, P/FCF, EV/EBITDA, ROE, ROIC, 마진, 부채비율, 유동비율, 공매도, 애널리스트 컨센서스, 매출/순이익 YoY·QoQ, 5년 매출 성장 전망, 5년 EPS 성장 전망은 StockAnalysis 공개 통계와 분기 재무 페이지에서 가져오며, 지연 시세나 장마감 데이터는 기준일과 상태를 화면에 함께 표시합니다.
- 미국 주식 저평가 탭은 NASDAQ, NYSE, AMEX 거래소별 버튼과 AI, AI SW, SW, 전력, 광통신, 반도체, 데이터센터, 클라우드 등 상세 테마 필터로 저평가 순위를 보여줍니다.

수집처에서 제공하지 않는 값은 임의로 채우지 않고 `-`로 표시합니다.
