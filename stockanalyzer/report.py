"""분석 결과를 차트(PNG)와 마크다운 리포트로 출력한다."""
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from stockanalyzer.config import REPORT_DIR

plt.rcParams["font.family"] = "Malgun Gothic"  # Windows 한글 폰트
plt.rcParams["axes.unicode_minus"] = False

GROUP_COLORS = {
    "저평가·수급강세 (추천)": "#2e7d32",
    "저평가·수급약세 (관망)": "#9e9e9e",
    "고평가·수급강세 (주의)": "#f9a825",
    "고평가·수급약세 (비추천)": "#c62828",
}


def plot_recommendation_scatter(rec_df: pd.DataFrame, run_tag: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 6))
    for group, g in rec_df.groupby("group"):
        ax.scatter(
            g["per"], g["pbr"], s=120,
            c=GROUP_COLORS.get(group, "#333333"), label=group, edgecolors="white",
        )
        for _, row in g.iterrows():
            ax.annotate(row["name"], (row["per"], row["pbr"]), fontsize=9, xytext=(5, 5), textcoords="offset points")
    ax.set_xlabel("PER (배)")
    ax.set_ylabel("PBR (배)")
    ax.set_title("PER vs PBR — 가치평가 · 수급 그룹")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    path = REPORT_DIR / f"per_pbr_scatter_{run_tag}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path)


def plot_total_score_bar(rec_df: pd.DataFrame, run_tag: str) -> str:
    df = rec_df.sort_values("total_score", ascending=True)
    colors = [GROUP_COLORS.get(g, "#333333") for g in df["group"]]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(df["name"], df["total_score"], color=colors)
    ax.set_xlabel("종합 점수 (가치 50% + 수급 50%)")
    ax.set_title("종목별 종합 추천 점수")
    fig.tight_layout()
    path = REPORT_DIR / f"total_score_bar_{run_tag}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path)


def plot_sentiment_correlation_bar(corr_df: pd.DataFrame, name_map: dict, run_tag: str) -> str:
    df = corr_df.dropna(subset=["sentiment_return_corr"]).copy()
    if df.empty:
        return ""
    df["name"] = df["code"].map(name_map)
    df = df.sort_values("sentiment_return_corr")
    colors = ["#2e7d32" if v >= 0 else "#c62828" for v in df["sentiment_return_corr"]]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(df["name"], df["sentiment_return_corr"], color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("상관계수 (커뮤니티 감성 vs 익일 수익률)")
    ax.set_title("종목토론실 여론과 실제 주가의 상관관계")
    fig.tight_layout()
    path = REPORT_DIR / f"sentiment_correlation_{run_tag}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path)


def write_markdown_report(rec_df: pd.DataFrame, corr_df: pd.DataFrame,
                           name_map: dict, chart_paths: list, run_tag: str) -> str:
    lines = []
    lines.append(f"# 종목 분석 리포트 ({run_tag})\n")
    lines.append(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    lines.append("## 1. 종목 추천 (PER·PBR 가치평가 + 외국인/기관 수급)\n")
    lines.append("| 순위 | 종목명 | PER | PBR | 가치점수 | 수급점수 | 종합점수 | 그룹 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, row in rec_df.reset_index(drop=True).iterrows():
        lines.append(
            f"| {i+1} | {row['name']} | {row['per']:.2f} | {row['pbr']:.2f} | "
            f"{row['value_score']:.1f} | {row['supply_score']:.1f} | {row['total_score']:.1f} | {row['group']} |"
        )
    lines.append("")

    lines.append("## 2. 커뮤니티(종목토론실) 여론 vs 실제 수익률 상관관계\n")
    lines.append("양수(+)면 '긍정 여론일수록 실제로도 올랐다', 음수(-)면 '여론과 실제 결과가 반대로 움직였다'는 의미입니다.\n")
    lines.append("| 종목명 | 관측일수 | 상관계수 |")
    lines.append("|---|---|---|")
    for _, row in corr_df.iterrows():
        name = name_map.get(row["code"], row["code"])
        corr_val = "N/A" if pd.isna(row["sentiment_return_corr"]) else f"{row['sentiment_return_corr']:.2f}"
        lines.append(f"| {name} | {row['n_days']} | {corr_val} |")
    lines.append("")

    lines.append("## 3. 차트\n")
    for p in chart_paths:
        if p:
            lines.append(f"![chart]({p})\n")

    content = "\n".join(lines)
    path = REPORT_DIR / f"report_{run_tag}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
