"""버튼으로 시작하는 백그라운드 작업(크롤링)의 상태를 스레드-세이프하게 관리하는 범용 헬퍼.

Streamlit은 스크립트를 동기적으로 실행하므로, 오래 걸리는 크롤링을 버튼 클릭 핸들러에서 그냥
블로킹으로 부르면 그동안 같은 서버(컨테이너)의 다른 방문자 요청도 전부 멈춘다(실측 확인됨 —
MEMORY.md "종목 심리분석 탭" 섹션 참고). 대신 이 클래스로 백그라운드 스레드에서 돌리고, 상태는
프로세스 전역(모듈 수준) 딕셔너리에 저장해 여러 세션이 폴링으로 안전하게 공유해서 읽는다.

주의: 백그라운드 스레드 안에서는 st.* 함수를 절대 호출하지 않는다(Streamlit 위젯은 스레드
안전하지 않음). 이 클래스의 상태 딕셔너리(순수 파이썬 dict + threading.Lock)만 갱신하고,
화면 렌더링/폴링은 app.py의 @st.fragment(run_every=...)가 메인 스레드에서 담당한다.
"""
import threading


class AsyncJob:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"status": "idle", "logs": [], "error": None}  # idle | running | done | error

    def status(self) -> dict:
        with self._lock:
            return {**self._state, "logs": list(self._state["logs"])}

    def log(self, message: str):
        with self._lock:
            self._state["logs"].append(message)

    def start(self, target, *args, **kwargs) -> bool:
        """이미 실행 중이면 아무 것도 안 하고 False. 아니면 target(*args, **kwargs)을 백그라운드
        스레드로 시작하고 True. target은 진행 로그를 남기려면 self.log를 인자로 받아 직접 호출해야 한다."""
        with self._lock:
            if self._state["status"] == "running":
                return False
            self._state = {"status": "running", "logs": [], "error": None}

        def _run():
            try:
                target(*args, **kwargs)
                with self._lock:
                    self._state["status"] = "done"
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._state["status"] = "error"
                    self._state["error"] = str(exc)

        threading.Thread(target=_run, daemon=True).start()
        return True
