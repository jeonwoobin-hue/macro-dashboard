"""PER/PBR(가치) + 수급(외국인·기관 순매수)을 결합한 종목 그룹화 및 추천 로직."""
import pandas as pd


def _percentile_rank_ascending(series: pd.Series) -> pd.Series:
    """값이 작을수록(저평가/약세) 높은 점수(0~100)를 받도록 백분위 점수화."""
    return (1 - series.rank(pct=True, na_option="bottom")) * 100


def build_value_supply_table(fundamentals_df: pd.DataFrame, supply_recent_df: pd.DataFrame) -> pd.DataFrame:
    """
    fundamentals_df: columns [code, name, per, pbr]
    supply_recent_df: columns [code, supply_value_sum] (최근 N일 외국인+기관 순매수 거래대금 추정 합)
    -> code, name, per, pbr, value_score, supply_score, total_score, group 컬럼을 가진 DataFrame 반환
    """
    df = fundamentals_df.merge(supply_recent_df, on="code", how="left")
    df["supply_value_sum"] = df["supply_value_sum"].fillna(0)

    per_score = _percentile_rank_ascending(df["per"])
    pbr_score = _percentile_rank_ascending(df["pbr"])
    df["value_score"] = (per_score + pbr_score) / 2

    df["supply_score"] = df["supply_value_sum"].rank(pct=True, na_option="bottom") * 100

    df["total_score"] = df["value_score"] * 0.5 + df["supply_score"] * 0.5

    value_median = df["value_score"].median()
    supply_median = df["supply_score"].median()

    def _group(row):
        cheap = row["value_score"] >= value_median
        strong_supply = row["supply_score"] >= supply_median
        if cheap and strong_supply:
            return "저평가·수급강세 (추천)"
        if cheap and not strong_supply:
            return "저평가·수급약세 (관망)"
        if not cheap and strong_supply:
            return "고평가·수급강세 (주의)"
        return "고평가·수급약세 (비추천)"

    df["group"] = df.apply(_group, axis=1)
    df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
    return df
