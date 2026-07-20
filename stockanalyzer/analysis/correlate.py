"""커뮤니티(종목토론실) 감성과 실제 주가 수익률 비교 분석.
'긍정적인 여론이 실제 상승으로 이어지는가'를 검증하기 위해
일자별 평균 감성점수와 익일(또는 N일 후) 수익률의 상관관계 및 괴리 사례를 계산한다."""
import pandas as pd


def build_sentiment_return_table(board_df: pd.DataFrame, price_df: pd.DataFrame, forward_days: int = 1) -> pd.DataFrame:
    """
    board_df: columns [code, date, sentiment_score]  (게시글 단위)
    price_df: columns [code, date, close]  (날짜 오름차순 정렬 가정하지 않음, 내부에서 정렬)
    -> code, date, avg_sentiment, post_count, close, forward_return(%) 컬럼을 가진 DataFrame
    """
    daily_sentiment = (
        board_df.groupby(["code", "date"])["sentiment_score"]
        .agg(avg_sentiment="mean", post_count="count")
        .reset_index()
    )

    price_df = price_df.sort_values(["code", "date"]).copy()
    price_df["future_close"] = price_df.groupby("code")["close"].shift(-forward_days)
    price_df["forward_return"] = (price_df["future_close"] / price_df["close"] - 1) * 100

    merged = daily_sentiment.merge(price_df[["code", "date", "close", "forward_return"]], on=["code", "date"], how="inner")
    return merged.dropna(subset=["forward_return"])


def compute_correlation_by_stock(sentiment_return_df: pd.DataFrame) -> pd.DataFrame:
    """종목별 (평균 감성점수 vs 익일 수익률) 피어슨 상관계수 계산."""
    rows = []
    for code, g in sentiment_return_df.groupby("code"):
        if len(g) >= 3 and g["avg_sentiment"].std() > 0:
            corr = g["avg_sentiment"].corr(g["forward_return"])
        else:
            corr = None
        rows.append({"code": code, "n_days": len(g), "sentiment_return_corr": corr})
    return pd.DataFrame(rows)


def find_divergence_cases(sentiment_return_df: pd.DataFrame, sentiment_threshold: float = 0.5, return_threshold: float = 0.0) -> pd.DataFrame:
    """여론은 긍정적인데 실제 주가는 하락(또는 그 반대)한 괴리 사례를 추출한다."""
    df = sentiment_return_df.copy()

    bullish_but_fell = df[(df["avg_sentiment"] >= sentiment_threshold) & (df["forward_return"] < return_threshold)]
    bearish_but_rose = df[(df["avg_sentiment"] <= -sentiment_threshold) & (df["forward_return"] > return_threshold)]

    bullish_but_fell = bullish_but_fell.assign(divergence_type="여론 긍정 → 실제 하락")
    bearish_but_rose = bearish_but_rose.assign(divergence_type="여론 부정 → 실제 상승")

    return pd.concat([bullish_but_fell, bearish_but_rose], ignore_index=True)
