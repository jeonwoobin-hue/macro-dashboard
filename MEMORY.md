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
- 3~4개 차트를 한 행에 배치할 때는 `st.container(key="scrollrow_xxx")` + CSS(`flex-wrap: nowrap; overflow-x: auto`)로 가로 스크롤 처리.
- ~~한글 폰트가 필요한 곳(워드클라우드)은 시스템에 기본 설치된 `C:\Windows\Fonts\malgun.ttf` 사용~~ → **버그였음**: Streamlit Community Cloud(Linux)에는 이 경로가 없어서 `OSError: cannot open resource`로 앱 전체가 죽었음(배포 후 실제로 발생). 2026-07-11 수정: 오픈소스 나눔고딕(OFL 라이선스, google/fonts 저장소)을 `fonts/NanumGothic-Regular.ttf`로 리포에 직접 번들링하고, `os.path.join(os.path.dirname(__file__), "fonts", ...)` 상대경로로 참조하도록 변경. **교훈: 로컬 전용 절대경로(OS별 시스템 폰트, 특정 드라이브 경로 등)는 클라우드 배포 시 반드시 깨진다 — 리소스 파일은 항상 프로젝트 안에 번들링하고 상대경로로 참조할 것.**

## 보안 관련 결정

- **API 키를 브라우저로 보내지 않기**: `st.text_input(..., type="password", value=secret_key)`처럼 시크릿 값을 기본값으로 넣으면, 화면에는 점(····)으로 가려지지만 **실제 값은 그대로 프론트엔드로 전송됨**(개발자도구로 열람 가능). Streamlit Cloud에 배포해 앱을 공유한 뒤 실제로 지적받은 문제. 수정: `get_secret()`으로 키를 이미 구했으면 `text_input` 자체를 렌더링하지 않고 "✅ 연결됨" 문구만 표시 — 키 값이 아예 클라이언트로 전송되지 않도록 함(로컬에서 `.env`로 실행할 때도 동일하게 적용되어, 로컬 사이드바에서도 더 이상 키를 직접 볼 수 없음 — 필요하면 `.env` 파일을 직접 확인).
- **예외 메시지를 통한 키 유출도 함께 차단**: `fred_client.py`/`ecos_client.py`는 API 키를 URL(쿼리스트링 또는 경로)에 그대로 넣어 요청함. `requests`의 `HTTPError` 기본 메시지는 요청 URL 전체를 포함하므로, 처리되지 않은 예외가 Streamlit 화면에 그대로 노출되면 그 안에 키가 포함될 수 있었음. 두 클라이언트 모두 `raise_for_status()`를 try/except로 감싸서 URL이 빠진 메시지로 다시 raise하도록 수정.
- **일반 원칙**: 이 프로젝트처럼 "Secrets에 키를 넣고 방문자와 URL만 공유"하는 배포 형태에서는, 서버가 아는 값이 클라이언트로 왕복하는 모든 경로(위젯 기본값, 에러 메시지, 로그 출력 등)를 잠재적 유출 지점으로 의심할 것.

## 배포 트러블슈팅

- **`requirements.txt`에 버전을 안 박아두면 위험하다**: 처음 배포 시 `streamlit`, `pandas`, `wordcloud` 등을 버전 없이 적어뒀더니, Streamlit Cloud가 배포 시점에 최신 버전들을 새로 조합해 설치하면서 numpy와 wordcloud/pandas/matplotlib 계열 바이너리(C 확장) 간 ABI 비호환이 발생 → 앱 시작 직후 `Segmentation fault`로 즉시 죽음(Python 예외/트레이스백조차 없이 네이티브 크래시라 원인 파악이 어려웠음). 로그에서 `/app/scripts/run-streamlit.sh: line 9: <PID> Segmentation fault`처럼 파이썬 트레이스백 없이 바로 죽으면 십중팔구 이 패턴.
  - 해결: 로컬에서 실제로 정상 동작하는 정확한 버전 조합을 `pip freeze`로 뽑아서 `requirements.txt`에 전부 `==`로 고정(streamlit, pandas, numpy, pillow, matplotlib, pyarrow, altair, wordcloud, lxml, beautifulsoup4 등 전이 의존성까지 명시적으로). 로컬 Python 버전(3.14)과 배포 서버 Python 버전이 같아서 그대로 이식 가능했음.
  - **교훈: 배포용 `requirements.txt`는 항상 버전을 고정할 것.** 버전 미고정은 "지금은 되는데 나중에 재배포하면 깨질 수 있는" 잠재적 시한폭탄이다.

## 미해결/다음에 고려할 것

- `zoom_chart` 함수명이 기능과 안 맞음(브러시 제거 후에도 이름 유지 중). 다음에 대규모로 손댈 일이 생기면 이름 정리 고려.
- 인간지표 감성사전은 슬랭 커버리지가 낮음. 실제 오탐/누락 사례를 모아 사전 확장 필요.
- ~~git 저장소 미초기화 상태~~ → 2026-07-11, Streamlit Community Cloud 배포를 위해 `git init` 완료. `.gitignore`에 `.env`, `__pycache__/`, `sentiment_raw_posts.json`, `.claude/` 반영함. 저장소 사용자 정보는 repo-local로만 설정(`git config user.name/email`, `--global` 아님).
- **API 키 로딩 이중화**: `app.py`의 `get_secret()` 헬퍼가 `st.secrets`(Streamlit Cloud 배포 시) → `os.getenv`(.env, 로컬 실행 시) 순으로 확인. Streamlit Cloud에 배포하면 앱 소유자가 Secrets에 키를 등록해두면 방문자(친구 등)가 별도로 API 키를 입력하지 않아도 자동으로 채워짐.
