"""종목 심리분석 탭용 데이터 갱신 스크립트 (로컬/CI 전용, Streamlit 배포 런타임에서는 실행 안 함).

네이버 금융에서 시가총액 상위 종목의 PER/PBR·수급·시세·종목토론실을 크롤링해
data/stock_data.db에 누적 저장하고, 추천/상관관계 분석 결과를 data/latest_run.json에 쓴다.
"종목 심리분석" 탭(app.py)은 이 latest_run.json을 읽기만 하므로, 이 스크립트를 실행해야
탭 내용이 최신화된다 — requirements-stock.txt(kiwipiepy 등)가 별도로 필요하다(main requirements.txt에는
포함하지 않음: 배포 런타임에 무거운 네이티브 패키지를 넣지 않기 위함, deploy_segfault_recurrence 메모 참고).

실행: pip install -r requirements-stock.txt && python run_stock_pipeline.py
"""
import json

from stockanalyzer.config import DATA_DIR
from stockanalyzer.main import run_pipeline


def main() -> None:
    result = run_pipeline()
    (DATA_DIR / "latest_run.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n저장 완료: {DATA_DIR / 'latest_run.json'}")


if __name__ == "__main__":
    main()
