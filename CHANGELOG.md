# CHANGELOG

커밋 메시지 형태로 변경 이력을 기록한다 (이 프로젝트는 아직 git 저장소가 아니므로 실제 커밋 대신 이 파일로 관리).

## 2026-07-11

- feat: Streamlit 대시보드 초기 구성 (Core CPI, Core PCE, Nonfarm Payrolls, 실업률, 평균시급, ISM 서비스 PMI, FOMC 점도표, 美 2Y·10Y 국채금리)
- feat: FRED API 클라이언트(`fred_client.py`) 추가, 물가·고용·금리 자동 지표 연동
- feat: ISM PMI / FOMC 점도표 수동 입력 UI(`st.data_editor` + CSV) 추가
- fix: 네이티브 차트의 y축이 0부터 시작해 좁은 범위 데이터가 평평하게 보이는 문제 수정 (Altair 도입, `zero=False`)
- feat: Core CPI 차트에 연준 목표(0.2%) 기준선 + 툴팁 추가
- feat: 물가 탭에 WTI 유가, 기대인플레이션(5Y·10Y BEI) 추가
- feat: 고용 탭에 신규 실업수당 청구건수(ICSA) 추가
- feat: 금리 탭에 연준 정책금리(DFEDTARU) 추가
- feat: 한국은행 ECOS API 클라이언트(`ecos_client.py`) 추가, 경기·연준 탭에 한국 경기종합지수(선행·동행 순환변동치) 연동
- refactor: 경기·연준 탭 내 한국 경기종합지수 섹션을 최상단으로 이동
- feat: 시장 탭 신설 — KOSPI, KOSDAQ, Nasdaq, Dow (`market_data.py`, Yahoo Finance 공개 차트 API 클라이언트 추가)
- feat: 가치평가 탭 신설 — Shiller PE(`manual_shiller_pe.csv`), 버핏지수 근사치(S&P500/GDP), 반도체 버블 지수(닷컴버블 vs AI 랠리 비교)
- feat: 우상단 참고자료 메뉴(팝오버 + 지표별 출처 요약표) 추가
- feat: 인간지표 탭 신설 — VIX(공포지수) + 디시인사이드 국내주식 갤러리 크롤링 기반 시장심리 (`sentiment_scraper.py`)
- fix: 감성분류 시간대 버킷 계산 오류 수정 (자정 기준 오프셋 → window_start 09:00 기준 오프셋으로 정정, 21:30~06:00 구간 누락 문제 해결)
- fix: 감성분류 키워드 오탐 수정 ("금"/"은" 한 글자 키워드가 조사·일반단어에 오매칭되던 문제 제거)
- feat: 모든 차트에 확대/축소 브러시(스케일바) 추가 시도 (`charts.py` 신설)
- fix: 브러시의 초기 미선택 상태에서 축 도메인이 잘못 계산되어 차트 값이 틀어지던 문제로 브러시 기능 원복 (일반 차트로 복귀)
- feat: 감성 키워드 시각화를 막대그래프에서 워드클라우드로 변경, 시간대 4구간을 서브탭으로 전환 (`wordcloud` 패키지 도입, 맑은고딕 폰트 사용)
- style: 대시보드 제목 변경 ("미국 경제지표 모니터링 대시보드" → "거시경제 투자심리 대시보드")
- style: 다중 시리즈 차트 범례를 차트 바깥에서 내부(top-left 오버레이)로 이동, 같은 행 카드 간 차트 크기 불일치 해결
- docs: README.md, MEMORY.md, CHANGELOG.md 신설. 장기 프로젝트 운영 규칙 수립 (모듈 단위 기능 추가, 임의 리팩터링 금지, 작업 후 문서 동기화)
- feat: 뉴스 탭 신설 — 어제자 경제 뉴스 Top 10, 클릭 시 원문 링크로 이동 (`news_client.py` 신설, 네이버 뉴스 랭킹 + 경제 키워드 필터링 기반)
- docs: README.md/MEMORY.md에 뉴스 탭 관련 내용 반영 (네이버 카테고리 랭킹 API 부재, sid1 파라미터 무효 확인, "경기"/"경기도" 키워드 오탐 수정 등 조사 과정 기록)
- chore: Streamlit Community Cloud 배포를 위해 git 저장소 초기화 (`.gitignore`로 `.env`/`__pycache__`/`sentiment_raw_posts.json`/`.claude` 제외)
- feat: API 키 로딩에 `st.secrets` 지원 추가 (`get_secret()` 헬퍼) — 로컬 `.env`와 Streamlit Cloud Secrets 둘 다 지원, 기존 동작은 그대로 유지
- docs: README.md에 Streamlit Community Cloud 배포 절차 추가
- deploy: GitHub 저장소(jeonwoobin-hue/macro-dashboard) 연결 및 Streamlit Community Cloud 최초 배포
- fix: 워드클라우드가 Windows 전용 폰트 경로(`C:\Windows\Fonts\malgun.ttf`)를 하드코딩해서 Streamlit Cloud(Linux)에서 `OSError`로 앱이 죽던 문제 수정. 오픈소스 나눔고딕 폰트를 `fonts/`에 번들링하고 상대경로로 참조하도록 변경
- fix(security): 사이드바 FRED/ECOS API Key 입력창이 `type=password`임에도 실제 값이 브라우저로 그대로 전송되어 개발자도구로 열람 가능했던 문제 수정. Secrets에 키가 설정된 경우 입력창 대신 연결 상태만 표시하도록 변경
- fix(security): FRED/ECOS API 요청 실패 시 예외 메시지에 키가 포함된 URL이 그대로 노출되던 문제 수정 (`fred_client.py`, `ecos_client.py`)
- docs: MEMORY.md에 "보안 관련 결정" 섹션 신설, API 키 유출 경로와 수정 내역 기록
- fix: 배포 서버가 버전 미고정 상태로 최신 numpy/pandas/wordcloud 조합을 설치하며 발생한 `Segmentation fault` 수정 — `requirements.txt` 전체 의존성을 로컬 검증된 버전으로 고정
- docs: MEMORY.md에 "배포 트러블슈팅" 섹션 신설
- style: 시장탭 지수명 단순화 ("Nasdaq 종합지수"→"Nasdaq", "다우존스 산업평균지수"→"Dow Jones")
- feat: 금리탭 스프레드 차트에 "장단기금리차(10Y-2Y)" 라벨 및 역전 기준선(0) 추가
- refactor: 가치평가탭 반도체 버블 지수를 최상단으로 재배치
- feat: 차트 확대(스크롤)·이동(드래그) 기능 재도입 — 이전엔 브러시+미니맵 방식의 버그로 되돌렸으나, `bind="scales"` 방식으로 재구현해 동일 버그 없이 동작 확인
- docs: MEMORY.md에 줌 기능 재구현 방식과 이전 실패 원인 기록
- refactor: 인간지표탭에서 "국내주식 인간지표"를 VIX보다 위로 재배치
- feat: 인간지표탭에 MOVE Index(ICE BofA, 채권시장판 VIX) 추가 (Yahoo Finance `^MOVE`, 일봉)
- feat: 시장/물가/고용탭의 가로 스크롤 카드에 모바일 대응 미디어 쿼리 추가 (768px 미만에서는 세로로 자연스럽게 쌓임)
- fix: 배포 서버에서 간헐적으로 재발하는 `Segmentation fault`/장시간 로딩 완화 시도 — `MPLCONFIGDIR`을 임시 디렉터리로 명시 지정 (근본 원인 미확정, MEMORY.md에 다음 시도할 방안 기록)
- fix: 네 번째 세그폴트 재발 이후, matplotlib/wordcloud를 배포 런타임에서 완전히 제거 — 워드클라우드 PNG를 로컬에서 미리 생성하는 `wordcloud_gen.py` 신설, `app.py`는 정적 이미지 파일만 읽도록 변경
- chore: `requirements.txt`에서 `wordcloud`/`matplotlib` 제거 (배포 환경에 더 이상 설치되지 않음)
- docs: MEMORY.md/README.md에 워드클라우드 사전생성 워크플로 반영
- feat: FRED/ECOS API 429 대응 — 신규 http_utils.py에 지수 백오프 재시도 추가, fred_client.py/ecos_client.py 적용
- feat: 데이터 캐시 TTL을 1시간에서 6시간으로 확대(CACHE_TTL_SECONDS 상수), API 호출 빈도 절감
- docs: README.md/MEMORY.md에 API 호출 한도 대응 방식 기록

## 2026-07-16

- fix: 다섯 번째 Segmentation fault 재발 대응 — `st.tabs()`를 `st.segmented_control()` + 조건분기로 교체해 선택 안 한 탭의 코드가 매 rerun마다 실행되지 않도록 변경(재배포 직후 콜드 캐시 상태에서 8개 탭 몫의 외부 API 호출이 한 번에 몰리는 것을 방지)
- feat: 데이터 캐시 TTL을 6시간→24시간으로 확대(FRED/ECOS/뉴스는 대부분 월1회·주1회 발표라 하루 한 번 확인이면 충분)
- feat: 시장 탭(KOSPI/KOSDAQ/Nasdaq/Dow) 전용 `market_cache_bucket()` 추가 — 장중엔 1시간 단위, 장마감·휴장 중엔 마지막 종가로 캐시 고정(요일+로컬 거래시간대 기준 근사치, 공휴일 캘린더는 미사용)
- docs: MEMORY.md 배포 트러블슈팅 섹션에 다섯 번째 세그폴트 재발 및 조치 내역 기록
- feat: 시장 탭 Dow Jones에도 Hot 토픽 버튼 추가
- feat: 모바일에서 안 되는 Vega-Lite 핀치줌(라이브러리 자체 미지원, 공식 문서로 확인) 대신 모든 시간축 차트에 ➕/➖ 확대·축소 버튼 추가(charts.py `render_zoomable_chart`)
- style: 물가·고용탭 "🔍 해석" 버튼을 "🔍 AI해석"으로 변경
- feat: AI 해석 결과를 GitHub Actions로 미리 생성해 커밋하는 `generate_ai_analysis.py` 추가 — 배포 컨테이너 재시작마다 초기화되던 `ai_analysis_cache.json`을 이제 git으로 버전관리해 재배포 후에도 유지, 지표가 실제로 새로 발표됐을 때만 Gemini 호출(그 외엔 버튼 클릭 시 즉시 캐시된 텍스트 표시)

## 2026-07-17

- feat: 참고자료1 표에 WTI·BEI·신규실업수당청구건수 및 그 외 누락 지표(한국 경기종합지수, Fed 정책금리, 수익률곡선, 반도체 버블지수, Shiller PE, 버핏지수, VIX, MOVE, 시장 4지수, 인간지표, 뉴스) 전부 추가, "Nonfarm Payrolls" → "비농업 고용"으로 통일
- fix: 참고자료1 표가 모바일에서 셀이 눌려 읽기 힘들던 문제 — 표를 가로 스크롤 컨테이너로 감싸 텍스트 줄바꿈 대신 스크롤되도록 수정
- feat: 금리탭 차트에 한국은행 기준금리(ECOS `722Y001`/`0101000`, 진한 파란색) 라인 추가 — `ecos_client.fetch_ecos_monthly`가 stat_code를 인자로 받도록 일반화

## 2026-07-20 (`feature/stock-sentiment-tab` 브랜치)

- feat: 별도 프로젝트 SentiStock을 "🗣️ 종목 심리분석" 탭으로 통합 — 시가총액 상위 종목 PER·PBR+수급 추천 그룹표, PER/PBR 산점도, 종합점수 막대, 종목토론실 여론-익일수익률 상관관계를 Altair로 표시
- feat: `stockanalyzer` 패키지(크롤러/분석/저장소 로직, Flask webapp·검색·비교·업종분석 기능 제외) 이식, `run_stock_pipeline.py`(로컬/CI 전용) + `requirements-stock.txt`(kiwipiepy/matplotlib, 메인 배포 의존성과 분리) + `update_stock_sentiment.yml`(매일 00:00 UTC 자동 갱신) 추가
- 배포 앱(`app.py`)은 `stockanalyzer`를 import하지 않고 `data/latest_run.json`만 읽음 — kiwipiepy/matplotlib/flask를 배포 런타임에 넣지 않아 세그폴트 재발 리스크 회피(자세한 내용은 MEMORY.md "종목 심리분석 탭" 섹션)
- feat: "전체 기능 이식"으로 확장 — 종목 검색·비교(최대 6종목, 1/3/7/30일 여론 vs 실제 수익률), 업종분석(14개 업종 그룹, 거래대금 상위 종목), "🔄 지금 다시 분석"(시총 상위 10종목 즉시 재크롤링) 실시간 트리거 추가. kiwipiepy를 메인 `requirements.txt`에도 추가했지만 각 버튼 클릭 핸들러 안에서만 지연 import해서 실제 클릭 전엔 로드되지 않게 함. `stockanalyzer/live.py` 신설(main.py의 run_pipeline을 matplotlib 없이 재구현), `sector_recommend.py`에서 report.py 차트 생성 제거
- 로컬 실측 검증 완료(전체 상장종목 크롤링 → 종목 검색·비교 실행, 정상 동작). **알려진 트레이드오프**: Streamlit 동기 실행 모델 때문에 라이브 크롤링 중엔 같은 컨테이너의 다른 방문자 세션도 함께 멈춤(원본 Flask는 백그라운드 스레드+폴링으로 이 문제를 피했으나, 이식하며 단순화하는 과정에서 잃음) — 인기 종목은 수 분씩 걸릴 수 있음. 스레드 기반 비동기화는 아직 미적용
