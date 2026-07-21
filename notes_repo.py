"""notes_ocr.py가 생성한 notes_index.json(손글씨 노트 OCR 결과)을 대시보드에서 쓰기 좋은
형태로 읽어온다. 배치로 미리 만들어둔 JSON을 그대로 읽기만 하므로(종목 심리분석 탭과 동일한
패턴) 이 모듈은 외부 API를 호출하지 않는다."""
import json
import os
from pathlib import Path

import pandas as pd

INDEX_PATH = os.path.join(os.path.dirname(__file__), "notes_index.json")

# notes_ocr.py가 저장한 리사이즈 썸네일(1600px) 폴더. 저장소에 함께 커밋되므로 로컬/배포
# 환경 모두에서 동작한다. 그래도 혹시 파일이 없는 케이스에 대비해 존재 여부는 항상 확인한다.
NOTES_IMAGE_DIR = os.path.join(os.path.dirname(__file__), "notes_images")

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

NOTES_COLUMNS = ["file", "note_date", "weekday", "title", "summary", "tags", "key_points", "source", "image_file"]


def load_notes() -> pd.DataFrame:
    """notes_index.json을 DataFrame으로 읽는다. 파일이 아직 없으면 빈 DataFrame을 반환한다."""
    if not os.path.exists(INDEX_PATH):
        return pd.DataFrame(columns=NOTES_COLUMNS)

    with open(INDEX_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    rows = [{"file": file, **data} for file, data in raw.items()]
    df = pd.DataFrame(rows, columns=NOTES_COLUMNS)
    df["note_date"] = pd.to_datetime(df["note_date"], errors="coerce")
    df["tags"] = df["tags"].apply(lambda t: t if isinstance(t, list) else [])
    df["key_points"] = df["key_points"].apply(lambda k: k if isinstance(k, list) else [])
    return df.sort_values("note_date", ascending=False, na_position="last").reset_index(drop=True)


def note_image_path(image_file: str | None) -> str | None:
    """썸네일 경로. image_file이 없거나(구버전 레코드) 파일이 실제로 없으면 None."""
    if not image_file or pd.isna(image_file):
        return None
    path = Path(NOTES_IMAGE_DIR) / image_file
    return str(path) if path.exists() else None
