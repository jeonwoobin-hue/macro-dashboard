"""프로젝트 전역 설정값."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "stock_data.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

REQUEST_DELAY_SEC = 0.4  # 네이버 서버 부하를 줄이기 위한 요청 간 지연시간
REQUEST_TIMEOUT_SEC = 10

TOP_N_STOCKS = 10          # 시가총액 상위 N개 종목
SUPPLY_DEMAND_PAGES = 4    # frgn.naver 페이지 수 (약 1페이지 = 거래일 20일치)
PRICE_HISTORY_PAGES = 4    # sise_day.naver 페이지 수
BOARD_PAGES = 5            # 종목토론실 페이지 수 (약 1페이지 = 게시글 20개)

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
