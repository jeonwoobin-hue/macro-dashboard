"""전체 상장종목 검색 캐시.
네이버 자동완성 API는 이 환경에서 접근이 막혀 있어, 시가총액 페이지를 전수 크롤링해
이름/코드로 즉시 검색 가능한 로컬 캐시(JSON)를 만든다. 크롤링은 87페이지 안팎이라
1~2분 걸리므로 백그라운드 스레드로 실행하고 진행 상태를 폴링할 수 있게 한다."""
import json
import threading
from datetime import datetime

from stockanalyzer.config import DATA_DIR
from stockanalyzer.crawler.market_cap import fetch_all_listed_stocks

UNIVERSE_PATH = DATA_DIR / "stock_universe.json"

_lock = threading.Lock()
_state = {"status": "idle", "logs": [], "error": None}  # idle | building | done | error


def get_build_status() -> dict:
    with _lock:
        return {**_state, "logs": list(_state["logs"])}


def load_universe() -> dict | None:
    if not UNIVERSE_PATH.exists():
        return None
    return json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))


def search(query: str, limit: int = 15) -> list:
    """캐시된 종목 목록에서 이름/코드에 query가 포함된 항목을 찾는다.
    이름이 query로 '시작'하는 항목을 우선순위로 정렬한다."""
    universe = load_universe()
    if not universe or not query:
        return []
    q = query.strip().lower()
    matches = [
        s for s in universe["stocks"]
        if q in s["name"].lower() or q in s["code"]
    ]
    matches.sort(key=lambda s: (not s["name"].lower().startswith(q), s["name"]))
    return matches[:limit]


def _log(message: str):
    with _lock:
        _state["logs"].append(message)


def start_build_async():
    """이미 빌드 중이면 False, 아니면 백그라운드 스레드로 시작하고 True."""
    with _lock:
        if _state["status"] == "building":
            return False
        _state["status"] = "building"
        _state["logs"] = []
        _state["error"] = None

    thread = threading.Thread(target=_build_and_store, daemon=True)
    thread.start()
    return True


def _build_and_store():
    try:
        stocks = fetch_all_listed_stocks(log=_log)
        payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), "stocks": stocks}
        UNIVERSE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with _lock:
            _state["status"] = "done"
        _log(f"완료: 총 {len(stocks)}종목 캐시됨")
    except Exception as exc:
        with _lock:
            _state["status"] = "error"
            _state["error"] = str(exc)
        _log(f"오류 발생: {exc}")
