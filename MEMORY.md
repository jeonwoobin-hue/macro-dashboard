# 프로젝트 메모리 (결정사항 / 맥락 기록)

이 파일은 README(사용법)와 별개로, "왜 이렇게 만들었는지"를 남기는 엔지니어링 노트다.
새 기능을 추가하기 전에 관련 있는 항목이 있는지 먼저 확인할 것.

## 데이터 소스 결정

- **FRED를 1차 출처로 통일**: BLS/BEA/Treasury 원자료를 무료 API로 일관되게 제공해서, 지표마다 다른 출처를 쓰는 것보다 효율적이라고 판단.
- **ISM 서비스 PMI**: 저작권 문제로 FRED가 2016년 이후 ISM 시리즈를 제공하지 않음. 무료 API 대안 없음 → `manual_ism_pmi.csv` 수동 입력 + 앱 내 `st.data_editor`로 편집. 2018-01~2026-06 히스토리는 서브에이전트가 prnewswire 공식 발표 헤드라인 수치를 웹서치로 수집해 채움. **주의**: ISM은 매년 1월에 전년 12월 수치를 소급 수정하는데, 최초 발표된 헤드라인 수치를 우선 사용함(수정치 아님). 예: 2025년 12월 최초 54.4 → 이후 53.8로 수정됐지만 54.4를 채택.
- **FOMC 점도표**: SEP는 PDF/이미지 위주라 API 없음 → `manual_fomc.csv` 수동 입력. federalreserve.gov의 `fomcprojtabl{date}.htm` 페이지는 HTML 표로 제공되어 수동 조회는 쉬움.
- **한국 경기종합지수**: 한국은행 ECOS API 사용. 통계표 코드 `901Y067`(8.1.2. 경기종합지수), 항목 코드 `I16E`=선행지수순환변동치, `I16D`=동행지수순환변동치. 원지수(`I16A`/`I16B`)가 아니라 순환변동치를 쓴 이유: 투자자가 보는 건 추세 제거된 경기 국면 전환점이지 트렌드 레벨이 아님. ECOS는 `sample`을 인증키로 쓰면 최대 10건까지 무인증 테스트 가능(개발 중 구조 파악에 활용).
- **버핏지수**: FRED의 Wilshire5000 시가총액 지수(`WILL5000PRFC`, `WILL5000INDFC` 등)가 전부 단종(404/400). 대안으로 Yahoo Finance `^GSPC`(S&P500, 1985~) / FRED `GDP`(분기, ffill로 월별화)로 근사 산출. **절대 수치가 아니라 자체 장기평균=100으로 지수화한 상대값**이라는 점을 UI에 명시해야 함.
- **경제 뉴스 Top 10 (news_client.py)**: 네이버는 카테고리별(예: 경제) 통합 조회수 랭킹을 공개 API로 제공하지 않는다. 확인한 사실들:
  - `news.naver.com/main/ranking/popularDay.naver?sid1=101`의 `sid1` 파라미터는 **실질적으로 무시됨**(같은 언론사·같은 날짜면 sid1 유무와 무관하게 결과 동일) — 카테고리 필터가 아니라 그냥 무시되는 죽은 파라미터. 이 페이지는 언론사(84개) 각각의 "그 언론사 전체에서 가장 많이 본 기사" 리스트를 보여줄 뿐, 특정 카테고리로 필터링되지 않음.
  - 언론사가 경제지(매일경제, 한국경제 등)라고 해도 그 언론사의 최다조회 1위 기사가 경제 기사라는 보장이 없음(연예/사건사고 기사가 더 많이 클릭되는 경우가 흔함). "경제지 화이트리스트 + 1위 기사만 사용" 방식은 시도했으나 실패(예: 한국경제 1위가 특정 유튜버 식당 폐업 기사였음).
  - `finance.naver.com/news/news_list.naver?mode=RANK`는 애초에 금융 전문 섹션이라 카테고리 오염이 없지만, **`date` 파라미터가 동작하지 않음**(항상 최근 실시간 랭킹만 반환) — "어제 날짜 기준"이 필요하면 이 엔드포인트는 쓸 수 없음.
  - 최종 채택: `popularDay.naver?date=YYYYMMDD`(날짜 파라미터는 정상 동작 확인됨)로 84개 언론사의 전체 랭킹 리스트(1~5위 각각)를 모두 가져온 뒤, 경제 키워드 사전(`ECONOMIC_KEYWORDS`)으로 제목을 필터링하고, 조회순위(rank) 오름차순 + 언론사당 1건으로 중복 제거해 Top N을 근사. 완벽한 "전체 매체 통합 조회수 순위"는 아니지만 실제 조회순위 데이터 기반 + 경제 관련성 필터를 결합한 합리적인 근사치.
  - **키워드 오탐 교훈 반복**: "경기"(경기침체/경기부양 등에서 쓰는 "경기") 단일 키워드가 "경기도"(지명)에 오매칭됨 → "금"/"은" 사례와 동일한 패턴. `경기침체`,`경기회복`,`경기부양`,`경기전망`,`경기지표`처럼 구체적인 복합어로 교체해서 해결. **새 키워드 사전을 만들 때마다 지명/인명과 겹치는 짧은 단어는 반드시 의심할 것.**
- **Shiller PE**: 공식 무료 API 없음. `multpl.com/shiller-pe/table/by-month`가 서버 렌더링 HTML 표라 `requests` + `pandas.read_html`(lxml/bs4/html5lib 필요)로 스크래핑 가능. 서브에이전트가 1995-01~2026-07(379개월) 수집, `manual_shiller_pe.csv`에 저장. 닷컴버블 피크(1999-12, 44.19)로 검증됨.
- **반도체 버블 지수**: Stooq는 봇 탐지(JS proof-of-work)로 막혀서 우회하지 않음(정책상 캡차/봇탐지 우회 금지). 대신 Yahoo Finance 비공식 공개 차트 API(`query1.finance.yahoo.com/v8/finance/chart/{symbol}`)를 사용 — 일반적인 데이터 엔드포인트 GET 요청이라 봇탐지 우회에 해당하지 않는다고 판단. `^SOX`(PHLX 반도체지수, 1994~) 하나로 닷컴버블 구간(1995~2002)과 현재 랠리(2019~)를 각각 시작월=100으로 지수화해 겹쳐 비교.
- **한국/미국 지수(시장 탭)**: Yahoo Finance 티커 `^KS11`(KOSPI), `^KQ11`(KOSDAQ), `^IXIC`(Nasdaq), `^DJI`(Dow). 일봉(`interval=1d`) 사용.
- **VIX**: FRED `VIXCLS`로 충분히 커버됨(정량적 공포지수, 20/30 기준선이 통념).
- **MOVE Index(채권판 VIX)**: FRED에는 없음(ICE BofA 소유의 독점 지수). Yahoo Finance `^MOVE` 티커로 2002-11~현재 전체 히스토리 확보 가능. **주의**: 이 심볼은 `interval=1mo`(월봉) 요청 시 비정상적으로 딱 1개 행만 반환하는 버그성 동작이 있음(다른 심볼은 정상). 원인 불명이라 그냥 `interval=1d`(일봉)로 우회해서 사용 — 다른 종목에서 월봉이 이상하게 나오면 이 케이스를 의심할 것.

## 인간지표(디시인사이드) 크롤링 메모

- 대상: `gall.dcinside.com/mgallery/board/lists/?id=krstock`. 로그인 불필요, 공개 게시판. curl로 저장하면 인코딩이 깨지므로 반드시 `requests` + `response.encoding='utf-8'`로 처리(또는 파일 저장 후 Read 도구로 확인 — 터미널 자체가 한글을 못 그리는 것일 뿐 실제 문자열은 정상인 경우가 많음).
- 게시글 시간은 `td.gall_date`의 `title` 속성에 `YYYY-MM-DD HH:MM:SS` 정확한 값이 들어있음(표시 텍스트는 "HH:MM"이나 "YY.MM.DD"로 축약돼서 title 속성을 써야 함).
- 공지/광고 행은 `tr[data-type="icon_notice"]`로 걸러냄.
- **매우 활발한 갤러리**: 분당 5개 이상 게시글. 하루(21시간 윈도우) 전체를 커버하려면 약 400페이지(약 2만 건) 필요. 매번 스크래핑하면 느리므로 `sentiment_raw_posts.json`에 원본을 캐싱하고, 같은 날짜면 재사용, 분류 로직(키워드 사전 등)만 반복 튜닝 가능하도록 `scrape_raw()`/`build_output()`을 분리해둠.
- **시간대 버킷 버그(수정됨)**: 버킷 경계를 "자정 기준 분"이 아니라 "window_start(09:00) 기준 오프셋 분"으로 계산해야 함. 처음에 자정 기준으로 잘못 계산해서 21:30~06:00 구간이 통째로 비는 버그가 있었음.
- **키워드 오탐 버그(수정됨)**: 금/은(원자재) 의도로 넣은 한 글자 키워드 "금"/"은"이 조사(은/는)와 흔한 단어("지금","자금" 등)에 광범위하게 서브스트링 매칭되어 결과를 오염시킴. 한 글자 키워드는 위험하다는 교훈 — 새 키워드 추가 시 최소 2글자 이상으로.
- 감성분류는 **키워드 사전 매칭 휴리스틱**이며 AI 감성분석이 아님. 분류율(전체 게시글 대비 긍정/부정 판정 비율)이 2~4% 수준으로 낮음 — 슬랭 위주라 사전에 없는 표현이 대부분. 정교화하려면 사전 확장이 우선.

## UI/차트 관련 결정

- `st.line_chart`/`st.bar_chart`(네이티브)는 y축이 기본적으로 0에서 시작해서, 좁은 범위 데이터(PMI 53~55, 점도표 3.1~3.8 등)가 거의 평평하게 보이는 문제가 있었음 → Altair로 전환하고 `scale=alt.Scale(zero=False)` 적용.
- **줌/브러시 기능, 두 번째 시도에서 성공**: 처음엔 `alt.selection_interval(encodings=["x"])` + 별도 미니맵 차트를 만들어 메인 차트의 `scale=alt.Scale(domain=brush)`로 바인딩하는 "브러시 내비게이터" 패턴을 썼는데, 초기(미선택) 상태에서 도메인이 잘못 계산되어 값이 틀어져 보이는 버그가 있어 되돌렸었음(2026-07-11 오전). 이후 사용자가 확대 기능을 다시 요청해서, 이번엔 **`alt.selection_interval(bind="scales", encodings=["x"])`를 차트에 `add_params`만 하는 방식**(별도 미니맵/도메인 재바인딩 없음, Vega-Lite 내장 pan/zoom)으로 재구현 — 초기 렌더링은 항상 정상 도메인으로 그려지고, 스크롤/드래그로 확대·이동할 때만 뷰가 바뀌므로 이전 버그가 재발하지 않음. **교훈: Altair/Vega-Lite에서 확대·축소가 필요하면 `scale(domain=selection)`으로 직접 바인딩하지 말고 `bind="scales"`를 쓸 것.**
- 다중 시리즈 차트의 범례는 `legend=alt.Legend(orient="top-left", ...)`로 차트 내부에 오버레이. 기본(오른쪽 바깥) 배치는 범례 있는 차트만 플롯 영역이 좁아져 같은 행의 다른 카드와 크기가 안 맞는 문제가 있었음.
- 3~4개 차트를 한 행에 배치할 때는 `st.container(key="scrollrow_xxx")` + CSS(`flex-wrap: nowrap; overflow-x: auto`)로 가로 스크롤 처리. **모바일 대응**: 이 CSS를 `@media (min-width: 768px) { ... }`로 감싸서 768px 미만(휴대폰)에서는 규칙 자체가 적용되지 않게 함 — Streamlit 기본 flex-wrap:wrap 동작으로 자연스럽게 세로 스택. 별도 모바일 전용 레이아웃을 새로 짤 필요 없이, 강제 가로스크롤 규칙만 넓은 화면으로 한정하는 것으로 충분했음.
- ~~한글 폰트가 필요한 곳(워드클라우드)은 시스템에 기본 설치된 `C:\Windows\Fonts\malgun.ttf` 사용~~ → **버그였음**: Streamlit Community Cloud(Linux)에는 이 경로가 없어서 `OSError: cannot open resource`로 앱 전체가 죽었음(배포 후 실제로 발생). 2026-07-11 수정: 오픈소스 나눔고딕(OFL 라이선스, google/fonts 저장소)을 `fonts/NanumGothic-Regular.ttf`로 리포에 직접 번들링하고, `os.path.join(os.path.dirname(__file__), "fonts", ...)` 상대경로로 참조하도록 변경. **교훈: 로컬 전용 절대경로(OS별 시스템 폰트, 특정 드라이브 경로 등)는 클라우드 배포 시 반드시 깨진다 — 리소스 파일은 항상 프로젝트 안에 번들링하고 상대경로로 참조할 것.**

## 보안 관련 결정

- **API 키를 브라우저로 보내지 않기**: `st.text_input(..., type="password", value=secret_key)`처럼 시크릿 값을 기본값으로 넣으면, 화면에는 점(····)으로 가려지지만 **실제 값은 그대로 프론트엔드로 전송됨**(개발자도구로 열람 가능). Streamlit Cloud에 배포해 앱을 공유한 뒤 실제로 지적받은 문제. 수정: `get_secret()`으로 키를 이미 구했으면 `text_input` 자체를 렌더링하지 않고 "✅ 연결됨" 문구만 표시 — 키 값이 아예 클라이언트로 전송되지 않도록 함(로컬에서 `.env`로 실행할 때도 동일하게 적용되어, 로컬 사이드바에서도 더 이상 키를 직접 볼 수 없음 — 필요하면 `.env` 파일을 직접 확인).
- **예외 메시지를 통한 키 유출도 함께 차단**: `fred_client.py`/`ecos_client.py`는 API 키를 URL(쿼리스트링 또는 경로)에 그대로 넣어 요청함. `requests`의 `HTTPError` 기본 메시지는 요청 URL 전체를 포함하므로, 처리되지 않은 예외가 Streamlit 화면에 그대로 노출되면 그 안에 키가 포함될 수 있었음. 두 클라이언트 모두 `raise_for_status()`를 try/except로 감싸서 URL이 빠진 메시지로 다시 raise하도록 수정.
- **일반 원칙**: 이 프로젝트처럼 "Secrets에 키를 넣고 방문자와 URL만 공유"하는 배포 형태에서는, 서버가 아는 값이 클라이언트로 왕복하는 모든 경로(위젯 기본값, 에러 메시지, 로그 출력 등)를 잠재적 유출 지점으로 의심할 것.

## API 호출 한도(rate limit) 대응

- **배경**: 앱을 지인들에게 공유하기 시작하면서, FRED·한국은행 ECOS 둘 다 분당 호출 횟수 제한이 있어 동시 접속이 늘면 429(Too Many Requests)를 받을 수 있다는 우려가 제기됨. 경제지표는 보통 하루 한 번만 갱신되므로 캐시를 길게 잡아도 신선도 손해가 거의 없다는 게 핵심 전제.
- **캐시 TTL 확대**: `app.py`의 `get_series`/`get_ecos_series`/`get_yahoo_series`/`get_news` 캐시를 1시간 → 6시간(`CACHE_TTL_SECONDS` 상수)으로 늘림. 값을 상수 하나로 통일해서 나중에 조정하기 쉽게 함.
- **429 재시도**: 신규 `http_utils.py`의 `get_with_retry()`가 `fred_client.py`/`ecos_client.py`의 모든 요청을 감쌈. 429를 받으면 `Retry-After` 헤더가 있으면 그 값을, 없으면 지수 백오프(1s, 2s, 4s, 8s + 지터)로 최대 4회 재시도. 그래도 계속 429면 예외를 그대로 올려서(단, API 키는 이미 메시지에서 빠져 있음) 호출부가 에러를 인지할 수 있게 함 — 무한 대기는 아님.
- **검증 방법**: 실제 429를 인위적으로 재현하기 어려워서, `unittest.mock.patch`로 `requests.get`을 모킹해 "두 번은 429, 세 번째는 200" 시나리오와 "계속 429" 시나리오 둘 다 유닛 테스트로 확인함(둘 다 로컬에서 직접 실행, 커밋에는 포함 안 함 — 필요하면 재현 스니펫은 이 대화 기록 참고).

## 배포 트러블슈팅

- **`requirements.txt`에 버전을 안 박아두면 위험하다**: 처음 배포 시 `streamlit`, `pandas`, `wordcloud` 등을 버전 없이 적어뒀더니, Streamlit Cloud가 배포 시점에 최신 버전들을 새로 조합해 설치하면서 numpy와 wordcloud/pandas/matplotlib 계열 바이너리(C 확장) 간 ABI 비호환이 발생 → 앱 시작 직후 `Segmentation fault`로 즉시 죽음(Python 예외/트레이스백조차 없이 네이티브 크래시라 원인 파악이 어려웠음). 로그에서 `/app/scripts/run-streamlit.sh: line 9: <PID> Segmentation fault`처럼 파이썬 트레이스백 없이 바로 죽으면 십중팔구 이 패턴.
  - 해결: 로컬에서 실제로 정상 동작하는 정확한 버전 조합을 `pip freeze`로 뽑아서 `requirements.txt`에 전부 `==`로 고정(streamlit, pandas, numpy, pillow, matplotlib, pyarrow, altair, wordcloud, lxml, beautifulsoup4 등 전이 의존성까지 명시적으로). 로컬 Python 버전(3.14)과 배포 서버 Python 버전이 같아서 그대로 이식 가능했음.
  - **교훈: 배포용 `requirements.txt`는 항상 버전을 고정할 것.** 버전 미고정은 "지금은 되는데 나중에 재배포하면 깨질 수 있는" 잠재적 시한폭탄이다.
- **버전 고정 후에도 `Segmentation fault`가 간헐적으로 재발함 (2026-07-11, 미해결 가능성 있음)**: `requirements.txt`를 안 건드린 채로도 재배포 시 몇 분간 로딩되다가 결국 `Segmentation fault`로 죽는 현상이 반복됨. 두 가지를 의심하고 있음:
  1. 앱이 매 세션마다 FRED·ECOS·Yahoo Finance·네이버뉴스·디시인사이드 등 외부 API를 ~20회 순차 호출(각 `timeout=15`)하는데, 배포 서버 IP가 일부 사이트에서 느리게 응답/차단당해 타임아웃이 누적되며 "3분 넘게 로딩"으로 보였을 가능성.
  2. `wordcloud`가 내부적으로 `matplotlib`을 불러오는데, 컨테이너가 매번 새로 뜨는 배포 환경에서는 기본 폰트캐시 경로 쓰기가 느리거나 문제를 일으킬 수 있음 → `MPLCONFIGDIR`을 `tempfile.gettempdir()` 기반 경로로 명시 지정해서 완화 시도(2026-07-11 커밋). **다만 로컬에서 콜드캐시로 재현했을 때 import는 0.35초에 불과해 이 가설이 얼마나 실제 원인인지는 확신 없음.**
  - 세그폴트는 Python 예외로 안 잡히고 트레이스백도 안 남아서 원인 특정이 어려움. 이 문제가 계속되면 다음으로 시도할 것: (a) 탭별로 실제 클릭 전까지는 데이터를 안 불러오는 지연 로딩 구조로 변경(현재는 `st.tabs()` 특성상 매 실행마다 8개 탭 전부의 코드가 돌아감), (b) 외부 요청 타임아웃을 15초보다 훨씬 짧게 줄이고 실패를 조용히 무시하도록 방어적으로 수정, (c) Streamlit Cloud 유료 티어로 리소스 한도를 늘려보기.
- **`MPLCONFIGDIR` 지정 후에도 네 번째 세그폴트 발생 (2026-07-13)** → matplotlib을 배포 런타임에서 아예 제거하는 방향으로 전환. `wordcloud`(내부적으로 matplotlib 사용)를 `app.py`에서 완전히 뺐다:
  - 신규 `wordcloud_gen.py`(로컬 전용 스크립트)가 `sentiment_data.json`을 읽어 워드클라우드 PNG 8장을 `wordclouds/bucket_{0..3}_{positive,negative}.png`로 미리 생성해 저장.
  - `app.py`는 `from wordcloud import WordCloud` 자체를 삭제하고, `wordclouds/` 폴더의 정적 PNG 파일을 `st.image(경로)`로 읽기만 함. `MPLCONFIGDIR` 설정 코드도 더 이상 필요 없어져서 함께 제거.
  - `requirements.txt`에서 `wordcloud`, `matplotlib`(및 그 전이 의존성)를 제거 — 배포 환경에는 이제 matplotlib이 설치조차 안 됨. `wordcloud`는 `wordcloud_gen.py`를 로컬에서 돌릴 때만 `pip install wordcloud`로 별도 설치.
  - **아직 100% 확신은 없음** — 이게 진짜 근본 원인이었는지는 다음 배포에서 세그폴트가 재발하는지로 판단할 것. 만약 이후에도 재발하면 위 (a)(외부 API 순차 호출 부담) 쪽을 다음으로 의심할 차례.
  - **교훈: 배포 런타임에서 결과가 매번 똑같이 나오는 무거운 네이티브 라이브러리 작업(이미지 렌더링 등)은 굳이 실시간으로 돌리지 말고, 로컬에서 미리 만들어 정적 파일로 커밋하는 편이 훨씬 안전하다.**
- **matplotlib/wordcloud 제거 후에도 재발 (2026-07-16, 다섯 번째)**: `requirements.txt`/코드 모두 안 건드린 순수 데이터 갱신 커밋(`daily sentiment data refresh`)이 GitHub Actions에서 push되고 Streamlit Cloud가 `Pulling code changes`로 자동 재배포한 직후 `Segmentation fault`가 재발함. 워드클라우드 PNG도 Pillow로 직접 열어 정상 확인 → 파일 손상은 아님. `app.py`가 `st.tabs()`로 8개 탭을 만드는데, **`st.tabs()`는 화면에 안 보이는 탭이어도 매 rerun마다 안의 코드를 전부 실행**한다는 게 핵심 단서 — 재배포 직후 캐시가 완전히 빈 상태에서 첫 방문자의 스크립트 실행 한 번에 8개 탭 몫(FRED·ECOS·Yahoo 합쳐 ~20건, 각 timeout=15초)의 외부 API 호출이 전부 몰리는 게 유력한 트리거로 지목됨(직전까지 미해결로 남겨뒀던 가설 (a)).
  - 조치 두 가지를 함께 적용:
    1. **탭 지연 로딩**: `st.tabs()` → `st.segmented_control()` + `if active_tab == "...":` 분기로 전환(`app.py`). 선택된 탭 하나만 코드가 실행되므로, 재배포 직후에도 한 번에 최대 1개 탭 분량만 호출됨. 탭 모양이 밑줄 탭에서 알약형 버튼으로 바뀌는 시각적 트레이드오프 있음(사용자 확인 후 선택).
    2. **발표주기 기반 캐시**: `CACHE_TTL_SECONDS`를 6시간→24시간으로 확대(FRED/ECOS/뉴스 — 대부분 월 1회/주 1회 발표라 하루 한 번 확인이면 충분). 시장 탭(KOSPI/KOSDAQ/Nasdaq/Dow)만 예외로 `market_cache_bucket()` 헬퍼로 "장중이면 시간 단위, 장마감/휴장 중이면 마지막 종가로 캐시 고정" — 공휴일 캘린더는 안 쓰고 요일+로컬 거래시간대 근사치만 사용(사용자 선택).
  - **아직 100% 확신은 아님** — 재배포 직후 콜드 캐시 부담을 줄이는 방향이 맞다는 정황은 확실하지만(순수 데이터 커밋에도 재발했으므로 의존성 버전 문제는 배제됨), 다음 재배포에서도 재발하는지로 최종 검증할 것. 만약 이후에도 재발하면 외부 요청 timeout 자체를 15초보다 짧게 줄이는 조치를 다음 후보로 고려.

## 종목 심리분석 탭 (별도 프로젝트 SentiStock 통합)

- **배경**: 사용자가 별도로 만든 개별종목 심리분석 프로젝트(`SentiStock.zip`)를 "종목 심리분석" 탭으로 추가해달라고 요청. 원본은 Flask 웹앱(`stockanalyzer/webapp/`) + SQLite DB + 네이버 금융 실시간 크롤러 + `kiwipiepy`(형태소 분석) + `matplotlib`(차트) 구조로, 이 대시보드(Streamlit)와 완전히 다른 프레임워크였음. 사용자가 "기존 버전 훼손 금지, 마음에 안 들면 원복"이라고 명시해서 `feature/stock-sentiment-tab` 브랜치에서 작업(머지 전까지 main 미변경).
- **범위 결정**: 전체 기능(종목 검색/비교/업종분석/실시간 재크롤링 버튼)이 아니라 **핵심 결과만 표시**하는 쪽으로 사용자가 선택. 이유: `kiwipiepy`를 배포 런타임에 추가하면 [[deploy_segfault_recurrence]]에서 5번 겪은 것과 같은 카테고리(무거운 네이티브 패키지)의 리스크를 새로 짊어지게 됨.
- **아키텍처**: `app.py`는 `stockanalyzer` 패키지를 **import하지 않고** `data/latest_run.json`(사전 계산된 결과)만 `json.load()`로 읽는다. 크롤링·감성분석(`kiwipiepy` 사용)·추천/상관관계 계산은 전부 `run_stock_pipeline.py`(로컬/CI 전용, 배포 런타임에서 절대 실행 안 됨)가 담당하고 `requirements-stock.txt`(kiwipiepy/matplotlib 포함, 메인 `requirements.txt`에는 없음)로 별도 설치. 매일 `update_stock_sentiment.yml`(GH Actions, 기존 감성데이터 갱신과 1시간 띄운 00:00 UTC)이 이 스크립트를 돌려 `data/latest_run.json`/`data/stock_data.db`를 커밋 — [[gemini_ai_interpretation_feature]]의 AI해석 캐시 사전생성과 동일한 패턴("무거운/네이티브 작업은 오프라인에서, 배포 앱은 결과만 읽기").
- **원본에서 가져온 것**: `stockanalyzer/{config,storage,report,main}.py`, `analysis/{sentiment,recommend,correlate}.py`, `crawler/{common,community,fundamentals,market_cap,price,supply_demand}.py`. **제외한 것**: `webapp/`(Flask 전용), `compare_state.py`/`sector_state.py`/`universe.py`(검색·비교·업종분석 — 범위 밖), `crawler/sector.py`/`news.py`, `scripts/`(사전 확장용 오프라인 도구).
- **주의할 것**: `report.py`는 모듈 최상단에서 `matplotlib`을 import한다 — `app.py`에서 절대 `from stockanalyzer import report`를 하면 안 됨(배포 런타임에 matplotlib이 딸려 들어와서 세그폴트 재발 위험). `GROUP_COLORS`처럼 report.py에 있는 작은 상수가 필요하면 app.py에 직접 복제(`STOCK_GROUP_COLORS`)해서 쓸 것 — 이미 그렇게 해둠.

**2026-07-20, "전체 기능 이식"으로 확장**: 사용자가 위 MVP(핵심 결과만 표시)로는 부족하다며 원본의
검색·비교·업종분석·"지금 다시 분석" 실시간 트리거까지 전부 요청. 이번엔 `kiwipiepy`를 메인
`requirements.txt`에도 추가(라이브 검색/비교/업종분석이 배포 앱에서 직접 크롤링+감성분석을 돌려야
해서 불가피 — 사용자에게 리스크 고지 후 진행). 다만 **함수 내부에서 지연 import**하는 패턴을
지켰다: `app.py` 최상단이 아니라 각 버튼의 `if st.button(...):` 블록 안에서만
`from stockanalyzer.live import ...` 등을 import하므로, 실제로 버튼을 누르기 전까지는 kiwipiepy가
로드되지 않는다(모든 방문자가 매 rerun마다 로드하는 게 아님). `stockanalyzer/live.py`를 새로
만들어 main.py의 run_pipeline()을 report.py(matplotlib) 없이 재구현했고, `sector_recommend.py`도
원본의 `report.plot_*` 호출을 제거했다 — "지금 다시 분석"/업종분석 라이브 경로에서도 matplotlib은
여전히 안 들어온다.

로컬에서 실제로 다 돌려봄(전체 상장종목 목록 만들기 → 삼성전자 검색·비교분석 1일 실행) — 정상
동작 확인. 단, **중요한 트레이드오프 하나 발견**: Streamlit은 스크립트 실행이 동기적이라, 이
라이브 크롤링(특히 인기 종목 비교/전체 재분석)이 도는 동안 **같은 컨테이너의 다른 방문자 세션도
전부 멈춘다**(`/_stcore/health` 폴링조차 응답 못 받는 걸 콘솔에서 확인). 원본 Flask 버전은 정확히
이 문제를 피하려고 백그라운드 스레드+폴링 구조를 썼는데, Streamlit으로 옮기며 구현을 단순화하려고
동기 블로킹(`st.status`)으로 대체하면서 그 이점을 잃었다. 삼성전자처럼 게시글이 아주 많은 종목은
1일 비교조차 max_pages(1000페이지) 안에서 기간을 다 못 채울 정도로 오래 걸림(`covered_full_window:
false`로 표시됨) — 이런 경우 몇 분간 앱 전체가 멈출 수 있다. 병목을 없애려면 `threading` +
`st.session_state` + `st.fragment(run_every=...)` 폴링으로 다시 비동기화해야 하는데, 아직 안 함
(사용자에게 필요성 확인 후 진행 예정).

**2026-07-20, 스레드 기반 비동기화 적용**: 위 블로킹 문제를 실제로 고쳤다.
- `stockanalyzer/async_job.py`: 범용 `AsyncJob` 클래스(스레드로 target 실행 + 락으로 보호된
  status/logs 딕셔너리). 백그라운드 스레드 안에서는 `st.*`를 절대 호출하지 않는다(스레드 안전하지
  않음) — 순수 dict만 갱신하고, 렌더링은 항상 메인 스레드의 폴링 프래그먼트가 담당.
- `stockanalyzer/jobs.py`: `pipeline_job`/`compare_job`/`sector_job`/`universe_job` 4개
  `AsyncJob` 인스턴스만 있는 아주 가벼운 모듈(kiwipiepy 등 무거운 걸 전혀 import 안 함) — app.py의
  `@st.fragment(run_every=2)` 폴링 함수들이 탭을 열 때마다(버튼 클릭 전이라도) 이 모듈만 가볍게
  import해서 `.status()`를 확인한다. 실제 크롤링 함수(`run_pipeline_and_save` 등, kiwipiepy
  체인을 끌고 오는 `stockanalyzer.live`)는 버튼 클릭 핸들러 안에서만 지연 import — **상태 확인과
  무거운 실행 로직을 별도 모듈로 분리한 게 핵심**이다(처음엔 한 모듈에 같이 뒀다가, 폴링 프래그먼트가
  2초마다 kiwipiepy를 로드해버리는 걸 뒤늦게 발견해서 분리함).
- 버튼 클릭 → `job.start(run_fn, ...)`으로 스레드만 시작하고 즉시 반환(안 막힘) → 같은 탭이든
  다른 탭이든 폴링 프래그먼트가 `status()`를 읽어 진행 로그 표시 → 완료 감지 시(이전 폴링에서
  "running"이었다가 이번에 "done") 관련 `st.cache_data` 캐시를 `.clear()`하고 `st.rerun()`(기본
  `scope="app"`라 프래그먼트 안에서 불러도 전체 페이지가 새로고침됨).
- 로컬 재검증: "지금 다시 분석" 클릭 직후 곧바로 다른 탭(시장)으로 전환해도 즉시 정상 응답 —
  더 이상 전체가 멈추지 않음. 완료 시 최신 데이터로 자동 갱신되는 것도 확인.
- **한계**: 파이썬 GIL 때문에 100% 완벽하게 논블로킹은 아니다 — 크롤링 스레드가 `requests.get`/
  `time.sleep` 같은 I/O 구간에서는 GIL을 놓아 메인 스레드가 잘 돌지만, BeautifulSoup/lxml 파싱처럼
  짧게 CPU를 쓰는 구간에서는 GIL을 붙잡아 순간적으로 다른 요청이 지연될 수 있다(테스트 중 콘솔에
  `/_stcore/health` 실패가 간헐적으로 남음). 그래도 실제 사용자 상호작용(탭 전환 등)은 즉시
  반응했으므로, 완전한 블로킹이었던 이전보다는 실질적으로 크게 개선된 상태 — 진짜 프로세스 분리
  없이 파이썬 스레딩으로 갈 수 있는 현실적 한계로 보면 됨.

## 미해결/다음에 고려할 것

- `zoom_chart` 함수명이 기능과 안 맞음(브러시 제거 후에도 이름 유지 중). 다음에 대규모로 손댈 일이 생기면 이름 정리 고려.
- 인간지표 감성사전은 슬랭 커버리지가 낮음. 실제 오탐/누락 사례를 모아 사전 확장 필요.
- ~~git 저장소 미초기화 상태~~ → 2026-07-11, Streamlit Community Cloud 배포를 위해 `git init` 완료. `.gitignore`에 `.env`, `__pycache__/`, `sentiment_raw_posts.json`, `.claude/` 반영함. 저장소 사용자 정보는 repo-local로만 설정(`git config user.name/email`, `--global` 아님).
- **API 키 로딩 이중화**: `app.py`의 `get_secret()` 헬퍼가 `st.secrets`(Streamlit Cloud 배포 시) → `os.getenv`(.env, 로컬 실행 시) 순으로 확인. Streamlit Cloud에 배포하면 앱 소유자가 Secrets에 키를 등록해두면 방문자(친구 등)가 별도로 API 키를 입력하지 않아도 자동으로 채워짐.
