"""
Gemini API로 경제지표 해석(지표 분석·거시적 해석·정책적 함의)을 생성한다.

같은 지표라도 매 페이지 로드마다 새로 생성하면 비용과 지연이 쌓이므로,
"이 지표가 마지막으로 해석된 시점의 캐시 키(보통 최신 발표일)"를 함께
저장해두고, 그 키가 바뀌었을 때만(=지표가 실제로 새로 발표됐을 때만)
다시 호출한다. 그 외에는 캐시된 해석을 그대로 재사용한다.
"""
import json
import os
import time

import requests

GEMINI_MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
CACHE_PATH = "ai_analysis_cache.json"
MAX_RETRIES = 2
RETRY_STATUS_CODES = {429, 500, 503}

PROMPT_TEMPLATE = """당신은 거시경제 전문 애널리스트입니다. 아래 경제지표 발표 내용을 참고해
주식 투자자 관점에서 짧고 명확하게 해석해주세요.

지표명: {name}
{context}

다른 텍스트 없이 아래 JSON 형식으로만 응답하세요:
{{"지표_분석": "...", "거시적_해석": "...", "정책적_함의": "..."}}

각 항목은 2~3문장, 한국어로 작성하세요. 지표_분석은 이번 발표치가 전월/전 발표 대비
어떻게 변했는지 사실 위주로, 거시적_해석은 이게 경기 국면에서 어떤 의미인지,
정책적_함의는 연준 통화정책(금리)에 주는 시사점을 다루세요.
"""


def _load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _call_gemini(prompt: str, api_key: str) -> dict:
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(
                GEMINI_URL,
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30,
            )
        except requests.exceptions.RequestException:
            # 네트워크 예외 메시지에도 api_key가 포함된 URL이 그대로 들어있을 수 있어 감춘다.
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise requests.HTTPError("Gemini API 요청 실패 (네트워크 오류)") from None
        if resp.status_code == 200:
            break
        if resp.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
            time.sleep(1.5 * (attempt + 1))
            continue
        # 원본 예외 메시지에는 api_key가 포함된 URL이 그대로 들어있어 화면에 노출될 수 있으므로 감춘다.
        raise requests.HTTPError(f"Gemini API 요청 실패 (status {resp.status_code})") from None

    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def get_indicator_analysis(indicator_key: str, name: str, context: str, cache_key: str, api_key: str) -> dict | None:
    """cache_key(보통 최신 발표일)가 이전에 저장된 값과 같으면 캐시를 그대로 쓰고,
    다르면(=새로 발표됨) Gemini를 한 번 호출해 새로 생성한다."""
    cache = _load_cache()
    cached = cache.get(indicator_key)
    if cached and cached.get("cache_key") == cache_key:
        return cached["analysis"]

    if not api_key:
        return cached["analysis"] if cached else None

    prompt = PROMPT_TEMPLATE.format(name=name, context=context)
    try:
        analysis = _call_gemini(prompt, api_key)
    except Exception as e:  # noqa: BLE001
        return cached["analysis"] if cached else {"오류": f"해석 생성 실패: {e}"}

    cache[indicator_key] = {"cache_key": cache_key, "analysis": analysis}
    _save_cache(cache)
    return analysis
