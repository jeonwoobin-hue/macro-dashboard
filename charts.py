import altair as alt
import pandas as pd
import streamlit as st


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


# Vega-Lite의 bind="scales" 확대는 마우스 휠 이벤트만 지원하고(공식 문서 확인됨) 터치
# 핀치 제스처는 지원하지 않는다. 모바일에서도 확실히 동작하는 대안으로, "최신 데이터
# 기준 표시 구간"을 좁히는 버튼(➕/➖)을 제공한다.
ZOOM_LEVELS = [1.0, 0.5, 0.25, 0.1]  # 전체 → 50% → 25% → 10%, 항상 최신 쪽을 기준으로 좁힘


def _zoom_state_key(key: str) -> str:
    return f"_zoom_lvl_{key}"


def zoom_buttons(key: str) -> float:
    """➕/➖ 버튼으로 표시 구간 배율을 조절하고, 현재 배율(1.0=전체)을 반환한다."""
    state_key = _zoom_state_key(key)
    idx = st.session_state.get(state_key, 0)

    b1, b2, _ = st.columns([1, 1, 6])
    with b1:
        if st.button("➕", key=f"{key}_zin", help="최근 구간 확대", disabled=idx == len(ZOOM_LEVELS) - 1):
            idx = min(idx + 1, len(ZOOM_LEVELS) - 1)
            st.session_state[state_key] = idx
    with b2:
        if st.button("➖", key=f"{key}_zout", help="축소(전체 기간)", disabled=idx == 0):
            idx = max(idx - 1, 0)
            st.session_state[state_key] = idx

    return ZOOM_LEVELS[idx]


def _apply_zoom_window(data: pd.DataFrame, x: str, fraction: float) -> pd.DataFrame:
    if fraction >= 1.0 or data.empty:
        return data
    x_max, x_min = data[x].max(), data[x].min()
    cutoff = x_max - (x_max - x_min) * fraction
    windowed = data[data[x] >= cutoff]
    return windowed if len(windowed) >= 2 else data


def render_zoomable_chart(data: pd.DataFrame, x: str, y: str, key: str, **kwargs):
    """zoom_chart()를 ➕/➖ 확대·축소 버튼과 함께 렌더링한다(시간축 전용)."""
    fraction = zoom_buttons(key)
    windowed = _apply_zoom_window(data, x, fraction)
    st.altair_chart(zoom_chart(windowed, x=x, y=y, **kwargs), width="stretch")
