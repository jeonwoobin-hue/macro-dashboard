"""업종분석 전용 가치점수/수급점수 산출 로직 (Z-score + 정규분포 CDF 기반).

원래 사용자가 요청한 산식은 가치점수 6개 지표(ROE·EPS성장률·PER·PBR·EV/EBITDA·부채비율),
수급점수 4개 지표(외국인·기관·연기금 순매수 강도 + 거래대금 팽창비율)였다. 다만 EV/EBITDA·FCF와
연기금 순매수는 네이버 금융에서 안정적으로 크롤링 가능한 형태로 노출되지 않아(사용자 확인 후 결정)
각각 제외하고, 남은 지표들의 가중치를 비례 재조정했다.

기존 recommend.py의 build_value_supply_table(PER/PBR 단순 버전)은 '종목 심리분석'(시가총액 top10)
파이프라인에서 그대로 쓰이고 있어 건드리지 않고, 이 모듈은 '업종분석' 전용으로 분리한다."""
import math

import pandas as pd

# 원래 EV/EBITDA(15%) 포함 6개 지표였으나 제외 후 나머지를 100/85로 비례 재조정
VALUE_WEIGHTS = {
    "roe": 20 / 85,
    "eps_growth": 20 / 85,
    "per": 15 / 85,
    "pbr": 15 / 85,
    "debt_ratio": 15 / 85,
}
VALUE_REVERSE = {"per", "pbr", "debt_ratio"}  # 낮을수록 고득점(역방향)

# 원래 연기금 순매수 강도(15%) 포함 4개 지표였으나 크롤링 불가로 제외 후 100/85로 재조정
SUPPLY_WEIGHTS = {
    "foreign_strength": 35 / 85,
    "inst_strength": 35 / 85,
    "turnover_expansion": 15 / 85,
}

TWIN_BUY_BONUS = 5
TWIN_BUY_MIN_DAYS = 3

VALUE_SCORE_RATIO = 0.6
SUPPLY_SCORE_RATIO = 0.4


def _winsorize(s: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    lo, hi = s.quantile(lower), s.quantile(upper)
    return s.clip(lower=lo, upper=hi)


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _score_metric(df: pd.DataFrame, col: str, reverse: bool, zero_mask: pd.Series | None = None) -> pd.Series:
    """윈저라이즈 -> peer 그룹(현재 분석 대상 전체) 기준 Z-score -> 정규분포 CDF로 0~100점 환산.
    결측치 및 zero_mask로 지정된 값(PER/PBR 적자·N/A)은 최하점(0점) 처리한다."""
    s = df[col].astype(float)
    valid = s.dropna()
    if len(valid) < 2 or valid.std(ddof=0) == 0:
        scores = pd.Series(50.0, index=df.index)
    else:
        w = _winsorize(s)
        z = (w - w.mean()) / w.std(ddof=0)
        if reverse:
            z = -z
        scores = z.map(lambda v: _norm_cdf(v) * 100 if pd.notna(v) else None)
    scores = scores.where(s.notna(), 0.0)
    if zero_mask is not None:
        scores = scores.where(~zero_mask, 0.0)
    return scores.astype(float)


def build_advanced_value_supply_table(rows: list) -> pd.DataFrame:
    """
    rows: [{code, name, per, pbr, roe, eps_growth, debt_ratio,
            foreign_strength, inst_strength, turnover_expansion,
            twin_buy_days, manually_added}, ...]
    -> 가치점수/수급점수/종합점수/그룹 컬럼이 추가된 DataFrame.
    """
    df = pd.DataFrame(rows)

    per_bad = df["per"].isna() | (df["per"] < 0)
    pbr_bad = df["pbr"].isna() | (df["pbr"] < 0)

    value_scores = {
        col: _score_metric(
            df, col, reverse=col in VALUE_REVERSE,
            zero_mask=per_bad if col == "per" else (pbr_bad if col == "pbr" else None),
        )
        for col in VALUE_WEIGHTS
    }
    df["value_score"] = sum(value_scores[c] * w for c, w in VALUE_WEIGHTS.items())

    supply_scores = {col: _score_metric(df, col, reverse=False) for col in SUPPLY_WEIGHTS}
    df["supply_score"] = sum(supply_scores[c] * w for c, w in SUPPLY_WEIGHTS.items())

    if "twin_buy_days" in df:
        bonus = (df["twin_buy_days"].fillna(0) >= TWIN_BUY_MIN_DAYS) * TWIN_BUY_BONUS
        df["supply_score"] = (df["supply_score"] + bonus).clip(upper=100)

    df["total_score"] = df["value_score"] * VALUE_SCORE_RATIO + df["supply_score"] * SUPPLY_SCORE_RATIO

    value_median = df["value_score"].median()
    supply_median = df["supply_score"].median()

    def _group(row):
        cheap = row["value_score"] >= value_median
        strong = row["supply_score"] >= supply_median
        if cheap and strong:
            return "저평가·수급강세 (추천)"
        if cheap and not strong:
            return "저평가·수급약세 (관망)"
        if not cheap and strong:
            return "고평가·수급강세 (주의)"
        return "고평가·수급약세 (비추천)"

    df["group"] = df.apply(_group, axis=1)
    return df.sort_values("total_score", ascending=False).reset_index(drop=True)
