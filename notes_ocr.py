"""손글씨 경제공부 노트(사진)를 Gemini Vision으로 OCR·구조화해 notes_index.json에 누적 저장한다.

264장을 한 번에 처리하다 중간에 실패해도 이미 처리한 파일은 다시 부르지 않도록
(파일명 키로) 매 SAVE_EVERY장마다 인덱스를 디스크에 저장한다.

사용법:
    python notes_ocr.py "C:\\Users\\admine\\Desktop\\도바오 raw\\경제공부raw"
    python notes_ocr.py "<폴더>" --limit 5          # 소량 테스트
    python notes_ocr.py "<폴더>" --force             # 이미 처리한 파일도 재처리
"""
import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

GEMINI_MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
MAX_RETRIES = 2
RETRY_STATUS_CODES = {500, 503}
RATE_LIMIT_BACKOFFS = [15, 30, 60, 90]  # 429(분당 쿼터)는 짧은 재시도로 회복되지 않아 훨씬 길게 대기
SAVE_EVERY = 5
MAX_DIM = 1600
JPEG_QUALITY = 85
IMAGES_DIR = Path(__file__).parent / "notes_images"

TAGS = [
    "Fed정책/금리",
    "수익률곡선/침체신호",
    "인플레이션",
    "유동성/신용/M2",
    "달러/환율/원자재",
    "밸류에이션/버블",
    "노동시장/AI생산성",
    "지정학/정책불확실성",
    "IPO/자금조달",
    "기타",
]

PROMPT = f"""당신은 채권 트레이더를 위한 리서치 어시스턴트입니다. 첨부된 이미지는 사용자가
손글씨로 정리한 거시경제/시장 공부 노트 한 페이지입니다. 내용을 읽고 아래 JSON 형식으로만
응답하세요 (다른 텍스트 없이):

{{
  "note_date": "YYYY-MM-DD 형식의 노트에 적힌 날짜 (없거나 읽을 수 없으면 null)",
  "weekday": "노트에 적힌 요일 (예: 화요일, 없으면 null)",
  "title": "이 노트 내용을 한 줄로 요약한 제목 (15자 내외)",
  "summary": "노트에 실제로 적힌 주장·수치·결론을 그대로 2~3문장으로 옮겨 적으세요. 반드시 노트 안의 구체적인 내용(숫자, 인과관계, 결론)으로 문장을 채우세요.",
  "tags": ["아래 태그 목록 중 이 노트에 해당하는 것만 1~3개 선택"],
  "key_points": ["핵심 불릿 포인트 2~5개, 각 1문장. 역시 노트에 적힌 구체적 내용을 그대로 옮길 것"],
  "source": "노트에 인용된 출처/애널리스트/기관명이 있으면 (예: Torsten Slok, Apollo), 없으면 null"
}}

summary와 key_points를 쓸 때 절대 하지 말아야 할 것: "이 노트는 ~에 대해 다룹니다", "~를 분석합니다", "~의 위험성을 경고합니다"처럼
노트가 "무엇을 이야기하는 노트인지"를 메타적으로 설명하지 마세요. 대신 그 노트가 실제로 주장하는 내용 자체를
(마치 노트를 쓴 사람이 직접 정리한 것처럼) 단정문으로 옮겨 적으세요.
나쁜 예: "미국 국채 스프레드 역전과 실업률의 역사적 상관관계를 분석한 차트입니다."
좋은 예: "미 10년물-3개월물 금리 스프레드가 역전된 뒤 정상화(uninversion)되는 시점에 실업률 급등과 경기침체가 뒤따랐다."

선택 가능한 태그 목록: {", ".join(TAGS)}
"""


def _resize_jpeg_bytes(path: Path) -> bytes:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_DIM:
        scale = MAX_DIM / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def _save_thumbnail(path: Path, jpeg_bytes: bytes) -> str:
    """리사이즈된 이미지를 notes_images/에 저장한다(대시보드 배포판에도 함께 커밋되는 폴더).
    반환값(파일명)을 notes_index.json에 같이 저장해 어느 노트가 어느 썸네일을 쓰는지 연결한다."""
    IMAGES_DIR.mkdir(exist_ok=True)
    out_name = path.stem + ".jpg"
    (IMAGES_DIR / out_name).write_bytes(jpeg_bytes)
    return out_name


def _call_gemini_vision(image_b64: str, api_key: str) -> dict:
    body = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                ]
            }
        ]
    }
    total_attempts = MAX_RETRIES + len(RATE_LIMIT_BACKOFFS)
    rate_limit_hits = 0
    for attempt in range(total_attempts + 1):
        try:
            resp = requests.post(GEMINI_URL, params={"key": api_key}, json=body, timeout=60)
        except requests.exceptions.RequestException:
            if attempt < total_attempts:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise requests.HTTPError("Gemini API 요청 실패 (네트워크 오류)") from None
        if resp.status_code == 200:
            break
        if resp.status_code == 429:
            if "PerDay" in resp.text or "generate_content_free_tier_requests" in resp.text:
                # 분당 한도가 아니라 일일 쿼터 소진 — 몇 초/몇 분 기다려도 풀리지 않으므로
                # 배치 전체를 즉시 중단시켜 몇 시간짜리 무의미한 재시도를 막는다.
                raise RuntimeError("DAILY_QUOTA_EXCEEDED: " + resp.text[:300])
            if rate_limit_hits < len(RATE_LIMIT_BACKOFFS):
                wait = RATE_LIMIT_BACKOFFS[rate_limit_hits]
                rate_limit_hits += 1
                print(f"    (429 레이트리밋, {wait}초 대기 후 재시도 {rate_limit_hits}/{len(RATE_LIMIT_BACKOFFS)})")
                time.sleep(wait)
                continue
        if resp.status_code in RETRY_STATUS_CODES and attempt < total_attempts:
            time.sleep(2.0 * (attempt + 1))
            continue
        raise requests.HTTPError(f"Gemini API 요청 실패 (status {resp.status_code})") from None

    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text.strip())

    valid_tags = [t for t in data.get("tags") or [] if t in TAGS]
    data["tags"] = valid_tags or ["기타"]
    return data


def _load_index(out_path: Path) -> dict:
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_index(out_path: Path, index: dict) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="노트 사진을 OCR/구조화해 notes_index.json에 저장")
    parser.add_argument("folder", help="노트 사진(jpg/png)이 들어있는 폴더 경로")
    parser.add_argument("--out", default="notes_index.json", help="출력 JSON 경로")
    parser.add_argument("--limit", type=int, default=None, help="테스트용: 앞에서 N개만 처리")
    parser.add_argument("--force", action="store_true", help="이미 처리된 파일도 재처리")
    parser.add_argument("--sleep", type=float, default=4.5, help="호출 간 대기(초), 레이트리밋 방지")
    parser.add_argument(
        "--only-list", default=None,
        help="파일명(한 줄에 하나)이 담긴 텍스트 파일 경로. 지정하면 폴더 전체가 아니라 이 목록에 있는 "
             "파일만 대상으로 한다 (예: 프롬프트를 바꾼 뒤 예전에 처리한 파일만 --force로 재처리할 때)",
    )
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("GEMINI_API_KEY가 .env에 없습니다.", file=sys.stderr)
        sys.exit(1)

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"폴더를 찾을 수 없습니다: {folder}", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    )

    if args.only_list:
        only_path = Path(args.only_list)
        wanted = {line.strip() for line in only_path.read_text(encoding="utf-8").splitlines() if line.strip()}
        files = [p for p in files if p.name in wanted]
        print(f"--only-list 적용: {len(wanted)}개 중 폴더에서 {len(files)}개 파일을 찾음")

    if args.limit:
        files = files[: args.limit]

    out_path = Path(args.out)
    index = _load_index(out_path)

    todo = [p for p in files if args.force or p.name not in index]
    print(f"전체 {len(files)}개 중 처리 대상 {len(todo)}개 (이미 처리됨: {len(files) - len(todo)}개)")

    errors = []
    processed_since_save = 0
    for i, path in enumerate(todo, 1):
        try:
            jpeg_bytes = _resize_jpeg_bytes(path)
            image_b64 = base64.b64encode(jpeg_bytes).decode("ascii")
            data = _call_gemini_vision(image_b64, api_key)
            data["image_file"] = _save_thumbnail(path, jpeg_bytes)
            index[path.name] = data
            processed_since_save += 1
            print(f"[{i}/{len(todo)}] {path.name} -> {data.get('note_date')} | {data.get('title')}")
        except RuntimeError as e:
            if str(e).startswith("DAILY_QUOTA_EXCEEDED"):
                _save_index(out_path, index)
                print(f"\n일일 쿼터 소진으로 중단합니다 ({i-1}/{len(todo)}건 처리 후). "
                      f"내일 같은 명령을 다시 실행하면 이어서 처리됩니다.", file=sys.stderr)
                sys.exit(2)
            errors.append((path.name, str(e)))
            print(f"[{i}/{len(todo)}] {path.name} -> 실패: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            errors.append((path.name, str(e)))
            print(f"[{i}/{len(todo)}] {path.name} -> 실패: {e}", file=sys.stderr)

        if processed_since_save >= SAVE_EVERY:
            _save_index(out_path, index)
            processed_since_save = 0

        time.sleep(args.sleep)

    _save_index(out_path, index)
    print(f"완료. 총 {len(index)}건 저장됨 -> {out_path}")
    if errors:
        print(f"실패 {len(errors)}건:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")


if __name__ == "__main__":
    main()
