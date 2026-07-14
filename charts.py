import altair as alt
import pandas as pd


def zoom_chart(
    data: pd.DataFrame,
    x: str,
    y: str,
    color: str | None = None,
    color_domain: list[str] | None = None,
    color_range: list[str] | None = None,
    y_title: str = "",
    x_type: str = "T",
    x_sort: list[str] | None = None,
    mark: str = "line",
    rule_y: float | None = None,
    rule_label: str = "",
    height: int = 300,
):
    """라인/바 차트를 만든다 (툴팁 포함)."""
    x_field = f"{x}:{x_type}"
    y_field = f"{y}:Q"

    tooltip = [alt.Tooltip(x_field, title=x)]
    color_enc = alt.value("#4C78A8")
    if color:
        scale = alt.Scale(domain=color_domain, range=color_range) if color_domain else alt.Undefined
        legend = alt.Legend(title=None, orient="top-left", direction="vertical")
        color_enc = alt.Color(f"{color}:N", scale=scale, legend=legend)
        tooltip.append(alt.Tooltip(f"{color}:N", title=""))
    tooltip.append(alt.Tooltip(y_field, format=".2f"))

    base = alt.Chart(data).mark_bar() if mark == "bar" else alt.Chart(data).mark_line(point=False)
    chart = base.encode(
        x=alt.X(x_field, title="", sort=x_sort if x_sort is not None else alt.Undefined),
        y=alt.Y(y_field, title=y_title, scale=alt.Scale(zero=False)),
        color=color_enc,
        tooltip=tooltip,
    ).properties(height=height)

    if rule_y is not None:
        rule_df = pd.DataFrame({"y": [rule_y], "label": [rule_label]})
        rule = alt.Chart(rule_df).mark_rule(color="gray", strokeDash=[4, 4]).encode(
            y="y:Q", tooltip=alt.Tooltip("label:N", title="")
        )
        chart = chart + rule

    # 마우스 스크롤로 확대, 드래그로 이동 (더블클릭으로 원래대로).
    # scale 도메인을 selection 값에 직접 바인딩하지 않고 Vega-Lite 내장 pan/zoom을
    # 사용하므로, 과거에 있었던 "초기 미선택 상태에서 축이 틀어지는" 문제가 없다.
    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    return chart.add_params(zoom)
