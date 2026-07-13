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
