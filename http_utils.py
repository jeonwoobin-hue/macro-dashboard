"""
외부 API 호출 공통 유틸리티. 429(Too Many Requests) 응답 시
지수 백오프로 재시도해서, 여러 사람이 동시에 앱을 쓰다가 API
호출 한도를 넘겨도 바로 에러로 죽지 않고 잠깐 기다렸다가
재시도하도록 한다.

한 번의 페이지 로드에서 FRED/ECOS로 십여 건의 요청이 거의 동시에
나가는데, 지인들이 한꺼번에 접속하면 캐시가 비어있는 상태에서 이
요청들이 짧은 시간에 몰려 발신 IP가 어뷰징으로 오인돼 차단(403)
당한 적이 있다. 요청 사이에 약간의 지연을 둬서 그 burst를 완화한다.
"""
import random
import time

import requests

MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 20.0
THROTTLE_MIN_SECONDS = 0.3
THROTTLE_MAX_SECONDS = 0.8


def get_with_retry(url: str, **kwargs) -> requests.Response:
    """requests.get()과 동일하게 쓰되, 429/일시적 네트워크 오류 시 지수 백오프로 재시도한다.

    매 호출 전 짧게 대기해 같은 세션 내 연속 요청이 한꺼번에 몰리지 않도록 한다.
    """
    time.sleep(random.uniform(THROTTLE_MIN_SECONDS, THROTTLE_MAX_SECONDS))
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, **kwargs)
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt == MAX_RETRIES:
                raise
            time.sleep(_backoff_delay(attempt))
            continue

        if resp.status_code == 429 and attempt < MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.strip().isdigit() else _backoff_delay(attempt)
            time.sleep(wait)
            continue

        return resp

    # 이론상 도달하지 않지만, 방어적으로 마지막 예외를 올린다.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("get_with_retry: 재시도 로직 이상 종료")


def _backoff_delay(attempt: int) -> float:
    delay = min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_MAX_SECONDS)
    return delay + random.uniform(0, delay * 0.3)
