"""라이브 작업(지금 다시 분석/비교분석/업종분석/전종목목록 빌드) 상태 객체.

stockanalyzer.live(실제 크롤링·kiwipiepy 감성분석 로직)를 전혀 import하지 않는 아주 가벼운
모듈이다 — app.py의 폴링 프래그먼트는 매 2초마다 이 모듈만 import해서 `.status()`를 확인해야
하는데, 만약 여기서 stockanalyzer.live를 끌고 오면 "종목 심리분석" 탭을 열기만 해도(버튼을
누르기 전부터) kiwipiepy가 로드돼버린다. 그래서 상태 객체(AsyncJob)와 실제 실행 로직을
분리했다 — 무거운 실행 함수(run_pipeline_and_save 등)는 버튼 클릭 핸들러에서
`from stockanalyzer.live import ...`로 그 시점에만 지연 import한다.
"""
from stockanalyzer.async_job import AsyncJob

pipeline_job = AsyncJob()
compare_job = AsyncJob()
sector_job = AsyncJob()
universe_job = AsyncJob()
