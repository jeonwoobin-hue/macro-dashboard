"""
sentiment_data.json의 긍정/부정 키워드로 워드클라우드 PNG를 미리 만들어 저장한다.

배포 서버(Streamlit Cloud)에서 반복적으로 발생한 Segmentation fault의 유력한
원인 중 하나로 matplotlib(워드클라우드가 내부적으로 사용) 관련 네이티브 코드가
매 요청마다 실시간으로 실행되는 점을 의심하여, 이 과정을 로컬 사전 생성 +
정적 이미지 파일 방식으로 분리했다. app.py는 이 결과물(PNG)만 읽으며
wordcloud/matplotlib를 임포트하지 않는다.

사용법 (sentiment_scraper.py 실행 후):
    python sentiment_scraper.py
    python wordcloud_gen.py
"""
import json
import os

from wordcloud import WordCloud

KOREAN_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NanumGothic-Regular.ttf")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "wordclouds")
SENTIMENT_DATA_PATH = "sentiment_data.json"


def make_png(keywords: list[dict], colormap: str, path: str) -> bool:
    freqs = {k["keyword"]: k["count"] for k in keywords}
    if not freqs:
        if os.path.exists(path):
            os.remove(path)
        return False
    wc = WordCloud(
        font_path=KOREAN_FONT_PATH,
        width=800,
        height=500,
        background_color="white",
        colormap=colormap,
        prefer_horizontal=0.9,
        max_words=20,
        min_font_size=8,
    ).generate_from_frequencies(freqs)
    wc.to_file(path)
    return True


def main():
    with open(SENTIMENT_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for i, (label, bucket) in enumerate(data["buckets"].items()):
        pos_path = os.path.join(OUTPUT_DIR, f"bucket_{i}_positive.png")
        neg_path = os.path.join(OUTPUT_DIR, f"bucket_{i}_negative.png")
        made_pos = make_png(bucket["positive_keywords"], "Greens", pos_path)
        made_neg = make_png(bucket["negative_keywords"], "Reds", neg_path)
        print(f"[{i}] {label}: positive={'OK' if made_pos else 'skip'} negative={'OK' if made_neg else 'skip'}")


if __name__ == "__main__":
    main()
