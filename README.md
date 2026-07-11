# 거시경제 투자심리 대시보드

주식 투자자를 위한 거시경제 지표 + 시장 심리 모니터링 Streamlit 대시보드.

**배포 링크**: https://macro-dashboard-r3wrnmsfvuwtrqtrc3v3r7.streamlit.app
**저장소**: https://github.com/jeonwoobin-hue/macro-dashboard

## 실행 방법

```
streamlit run app.py
```

(PATH에 streamlit이 없으면 `python -m streamlit run app.py`)

## 필요한 API 키 (.env)

`.env.example`을 복사해 `.env`로 만들고 값을 채운다.

| 키 | 용도 | 무료 발급처 |
|---|---|---|
| `FRED_API_KEY` | 물가·고용·금리·GDP 등 미국 지표 전반 | https://fred.stlouisfed.org/docs/api/api_key.html |
| `ECOS_API_KEY` | 한국 경기종합지수(선행·동행) | https://ecos.bok.or.kr/api/ |

FRED 키가 없으면 앱이 시작 화면에서 멈춘다(필수). ECOS 키가 없으면 경기·연준 탭의 한국 지수 섹션만 비활성화되고 나머지는 정상 작동한다.

## 배포 (Streamlit Community Cloud)

친구 등 외부에 공유할 URL이 필요하면 무료로 배포할 수 있다.

1. GitHub에 새 저장소를 만든다 (README/gitignore 없이 빈 저장소로 생성).
2. 로컬에서 원격 저장소를 연결하고 푸시한다.
   ```
   git remote add origin https://github.com/<사용자명>/<저장소명>.git
   git push -u origin master
   ```
3. https://share.streamlit.io 에서 GitHub 계정으로 로그인 후 "New app" → 방금 만든 저장소 선택, `app.py`를 진입점으로 지정해 배포한다.
4. 배포된 앱의 **Settings → Secrets**에 아래 내용을 추가한다 (`.env` 파일은 저장소에 올라가지 않으므로 이 단계가 꼭 필요하다).
   ```toml
   FRED_API_KEY = "발급받은_키"
   ECOS_API_KEY = "발급받은_키"
   ```
5. 발급된 `https://xxxx.streamlit.app` 링크를 공유하면 된다.

`sentiment_data.json`, `manual_*.csv`는 저장소에 포함되어 배포 직후에도 값이 채워진 채로 보인다. 최신 데이터로 갱신하려면 로컬에서 `python sentiment_scraper.py` 등을 다시 실행하고 커밋·푸시한다.

## 프로젝트 구조

```
app.py                   Streamlit 앱 진입점 · 탭/레이아웃 구성
charts.py                공통 차트 렌더링 헬퍼 (zoom_chart)
fred_client.py            FRED API 클라이언트
ecos_client.py            한국은행 ECOS API 클라이언트
market_data.py            Yahoo Finance 공개 차트 API 클라이언트 (지수·주가)
news_client.py             네이버 뉴스 랭킹 기반 경제 뉴스 Top N 추출 클라이언트
sentiment_scraper.py      디시인사이드 크롤링 + 키워드 감성분류 스크립트 (독립 실행)
manual_ism_pmi.csv        ISM 서비스 PMI 수동 입력 데이터 (앱 내 표에서 편집 가능)
manual_fomc.csv           FOMC 점도표 수동 입력 데이터 (앱 내 표에서 편집 가능)
manual_shiller_pe.csv     Shiller PE 히스토리 (multpl.com 스크랩, 1995~)
sentiment_raw_posts.json  디시인사이드 원본 게시글 캐시 (당일 재사용, 자동 생성)
sentiment_data.json       감성분류 결과 (앱이 읽는 파일, 자동 생성)
```

## 모듈 추가 규칙 (장기 프로젝트 컨벤션)

- 새 데이터 출처는 `xxx_client.py` 형태의 독립 모듈로 추가한다 (기존 `fred_client.py`, `ecos_client.py`, `market_data.py` 패턴을 따름).
- 기존 코드는 임의로 삭제·리팩터링하지 않는다. 변경이 필요하면 먼저 이유를 설명하고 진행한다.
- 새 기능 작업 전 프로젝트 구조를 먼저 검토하고, 기존 구조를 최대한 유지한다.
- 작업 후에는 README.md / MEMORY.md / CHANGELOG.md를 함께 갱신한다.
- (2026-07-11 배포 결정으로 git 저장소를 초기화함. 이후 커밋 메시지는 CHANGELOG.md 기록과 함께 실제 git 커밋으로도 남긴다.)

## 탭 구성

| 탭 | 내용 | 출처 |
|---|---|---|
| 📈 시장 | KOSPI, KOSDAQ, Nasdaq, Dow | Yahoo Finance |
| 🔥 물가 | Core CPI, Core PCE, WTI 유가, 기대인플레이션(BEI) | FRED |
| 👷 고용 | NFP, 실업률, 평균시급, 신규실업수당청구 | FRED |
| 🏭 경기·연준 | 한국 경기종합지수, ISM 서비스 PMI(수동), FOMC 점도표(수동) | ECOS / ISM / 연준 |
| 💵 금리 | 2Y·10Y 국채금리, Fed 정책금리, 스프레드 | FRED |
| 📐 가치평가 | Shiller PE, 버핏지수 근사치, 반도체 버블 지수 | multpl.com / FRED / Yahoo Finance |
| 🧠 인간지표 | 디시인사이드 국내주식 갤러리 감성 워드클라우드, VIX, MOVE Index | FRED / DCInside(자체 스크래핑) / Yahoo Finance |
| 📰 뉴스 | 어제자 경제 뉴스 Top 10 (클릭 시 원문 이동) | 네이버 뉴스 랭킹(자체 스크래핑) |

## 알려진 한계

- ISM PMI, FOMC 점도표: 저작권/비정형 데이터라 무료 API가 없어 수동 입력 방식.
- 버핏지수: FRED에서 Wilshire5000 지수가 단종되어 S&P500/GDP로 근사 산출(절대 수치 아님, 자체 장기평균 대비 상대값).
- 인간지표(디시인사이드): AI 감성분석이 아닌 단순 키워드 사전 매칭 휴리스틱. 참고용.
- 뉴스 Top 10: 네이버가 카테고리별 통합 조회수 랭킹을 공개 API로 제공하지 않아, 언론사별 실제 조회순위 데이터에 경제 키워드 매칭을 적용해 근사함. 완전한 전체 매체 통합 순위가 아님.
