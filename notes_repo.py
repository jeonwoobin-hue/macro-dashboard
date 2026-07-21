"""notes_ocr.py가 생성한 notes_index.json(손글씨 노트 OCR 결과)을 대시보드에서 쓰기 좋은
형태로 읽어온다. 배치로 미리 만들어둔 JSON을 그대로 읽기만 하므로(종목 심리분석 탭과 동일한
패턴) 이 모듈은 외부 API를 호출하지 않는다."""
import json
import os
from pathlib import Path

import pandas as pd

INDEX_PATH = os.path.join(os.path.dirname(__file__), "notes_index.json")

# 원본 사진 폴더. 로컬 개발 환경에만 존재하고 배포 환경(Streamlit Cloud)에는 없을 수 있으므로,
# 이미지 표시는 항상 파일 존재 여부를 먼저 확인하고 없으면 조용히 생략한다.
NOTES_IMAGE_DIR = os.getenv("NOTES_IMAGE_DIR", r"C:\Users\admine\Desktop\도바오 raw\경제공부raw")

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

NOTES_COLUMNS = ["file", "note_date", "weekday", "title", "summary", "tags", "key_points", "source"]


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


def note_image_path(file: str) -> str | None:
    """원본 사진 경로. 로컬에 실제로 파일이 있을 때만 경로를 반환한다."""
    path = Path(NOTES_IMAGE_DIR) / file
    return str(path) if path.exists() else None
