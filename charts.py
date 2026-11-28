"""Accessible Plotly charts with explicit, session-scoped light/dark palettes."""
from __future__ import annotations

from html import escape
import pandas as pd
import plotly.graph_objects as go
from theme import palette

CHART_CONFIG = {"displayModeBar": False, "responsive": True, "scrollZoom": False}
FONT_FAMILY = 'Inter, "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif'


def _base(fig: go.Figure, height: int = 320, hovermode: str = "closest",
          theme: str = "light") -> go.Figure:
    p = palette(theme)
    fig.update_layout(
        template="none", height=height,
        margin=dict(l=8, r=12, t=25, b=26),
        paper_bgcolor=p["card"], plot_bgcolor=p["card"],
        font=dict(family=FONT_FAMILY, size=12, color=p["muted"]),
        hovermode=hovermode,
        hoverlabel=dict(bgcolor=p["ink"], font_size=12,
                        font_color=p["card"], bordercolor=p["ink"]),
        showlegend=False, barmode="group", bargap=.35,
        barcornerradius=4,
    )
    fig.update_xaxes(
        showgrid=False, zeroline=False, fixedrange=True,
        tickfont=dict(size=11, color=p["muted"]),
        linecolor=p["line"], showline=True, ticklen=8, tickcolor=p["card"],
        automargin=True,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=p["grid"], gridwidth=1, zeroline=False,
        fixedrange=True, range=[0, 105], tickvals=[0, 25, 50, 75, 100],
        ticktext=["0%", "25%", "50%", "75%", "100%"], ticksuffix="%", tickfont=dict(size=11, color=p["muted"]),
        automargin=True,
    )
    return fig


def _mastery_line(fig: go.Figure, threshold: int, theme: str) -> None:
    fig.add_hline(y=threshold, line_dash="dash", line_width=1.4,
                  line_color=palette(theme)["benchmark"], layer="above")


def score_bar_chart(df: pd.DataFrame, dim: str, threshold: int,
                    group_by_batch: bool = False, height: int = 320,
                    theme: str = "light") -> go.Figure:
    """Consistent 0–100% scale, strong contrast, explicit mastery reference."""
    p = palette(theme)
    d = df.copy()
    d["exam_date"] = pd.to_datetime(d["exam_date"])
    axis_title = None
    if dim in ("Weekly", "Monthly"):
        period = "W" if dim == "Weekly" else "M"
        d["bucket"] = d["exam_date"].dt.to_period(period).dt.start_time
        g = d.groupby("bucket", sort=True)["score"].mean().reset_index()
        fmt = "%d %b" if dim == "Weekly" else "%b %Y"
        labels = g["bucket"].dt.strftime(fmt).tolist()
        full_labels = labels
        values = g["score"].tolist()
    elif dim == "By Exam":
        g = (d.groupby(["exam_id", "exam_date", "exam_name"], sort=True)["score"]
             .mean().reset_index().sort_values(["exam_date", "exam_id"]))
        labels = [f"{i:02d}" for i in range(1, len(g) + 1)]
        full_labels = [escape(f"{r.exam_name} · {r.exam_date:%d %b %Y}")
                       for r in g.itertuples()]
        values = g["score"].tolist()
        axis_title = "Exam sequence · oldest → newest"
    else:
        subjects = sorted(d["subject"].unique())
        if group_by_batch and d["batch"].nunique() > 1:
            colors = [p["accent"], p["peer"], p["amber"], p["coral"], p["blue"]]
            fig = go.Figure()
            for i, batch in enumerate(sorted(d["batch"].unique())):
                series = d[d["batch"] == batch].groupby("subject")["score"].mean()
                fig.add_trace(go.Bar(
                    name=escape(batch), x=subjects,
                    y=[float(series.get(subject, float("nan"))) for subject in subjects],
                    marker_color=colors[i % len(colors)],
                    hovertemplate="%{x}<br><b>%{y:.1f}%</b><extra>" + escape(batch) + "</extra>",
                ))
            fig = _base(fig, height + 35, theme=theme)
            fig.update_layout(
                showlegend=True, margin=dict(b=70),
                legend=dict(orientation="h", y=-.22, x=0,
                            font=dict(size=10, color=p["muted"]),
                            traceorder="normal", bgcolor="rgba(0,0,0,0)"),
            )
            fig.update_xaxes(tickvals=subjects,
                             ticktext=[s.replace(" ", "<br>") for s in subjects])
            _mastery_line(fig, threshold, theme)
            return fig
        g = d.groupby("subject", sort=True)["score"].mean().reset_index()
        labels = g["subject"].tolist()
        full_labels = [escape(label) for label in labels]
        values = g["score"].tolist()

    colors = [p["green"] if v >= threshold else p["coral"] for v in values]
    fig = go.Figure(go.Bar(
        x=labels, y=values, marker_color=colors, customdata=full_labels,
        hovertemplate="%{customdata}<br><b>%{y:.1f}%</b><extra></extra>",
    ))
    if len(labels) <= 8:
        fig.update_traces(
            text=[f"{v:.0f}%" for v in values], textposition="outside",
            textfont=dict(size=11, color=p["ink"]), cliponaxis=False,
        )
    fig = _base(fig, height, theme=theme)
    # Sparse labels avoid cramped ticks at phone widths, without hiding bars.
    step = max(1, (len(labels) + 5) // 6)
    indices = list(range(0, len(labels), step))
    if labels and len(labels) - 1 not in indices:
        if len(indices) > 1 and len(labels) - 1 - indices[-1] < step:
            indices[-1] = len(labels) - 1
        else:
            indices.append(len(labels) - 1)
    fig.update_xaxes(tickmode="array", tickangle=0, tickvals=[labels[i] for i in indices],
                     ticktext=[escape(labels[i]).replace("Social Studies", "Social<br>Studies")
                               for i in indices],
                     title=dict(text=axis_title, font=dict(size=10, color=p["muted"])))
    _mastery_line(fig, threshold, theme)
    return fig


def area_trend_chart(df: pd.DataFrame, subject: str, benchmark: float | None,
                     benchmark_label: str = "", height: int = 320,
                     theme: str = "light") -> go.Figure:
    """Honest fixed scale and straight segments: no misleading spline overshoot."""
    p = palette(theme)
    d = df.copy()
    d["exam_date"] = pd.to_datetime(d["exam_date"])
    if subject and subject != "All Subjects":
        d = d[d["subject"] == subject]
    g = d.groupby("exam_date")["score"].mean().sort_index()
    fig = go.Figure()
    if not g.empty:
        fig.add_trace(go.Scatter(
            x=g.index, y=g.values, mode="lines+markers", name="Average score",
            line=dict(color=p["accent"], width=2.8, shape="linear"),
            marker=dict(size=6, color=p["accent"], line=dict(width=1.5, color=p["card"])),
            fill="tozeroy",
            fillcolor="rgba(170,155,255,0.10)" if theme == "dark" else "rgba(91,75,216,0.07)",
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.1f}%</b><extra></extra>",
        ))
    fig = _base(fig, height, theme=theme)
    fig.update_xaxes(tickformat="%d %b", nticks=5)
    if benchmark is not None:
        fig.add_hline(
            y=float(benchmark), line_dash="dash", line_color=p["coral"], line_width=1.5,
            annotation_text=escape(benchmark_label), annotation_position="bottom right",
            annotation_font=dict(size=10, color=p["coral-text"]),
            annotation_bgcolor=p["card"], annotation_borderpad=3,
        )
    return fig


def student_comparison_chart(summary: pd.DataFrame, student_id: int,
                             theme: str = "light") -> go.Figure:
    """Ranked horizontal bars. Explicit marks stay legible even on tiny bars."""
    p = palette(theme)
    d = summary.dropna(subset=["score"]).sort_values(
        ["score", "student_name", "student_id"], ascending=[False, True, True]
    ).copy()
    ids = [f"student-{sid}" for sid in d["student_id"]]
    labels = [
        escape(f"{r.student_name} · {r.batch}")
        + (" (You)" if r.student_id == student_id else "")
        for r in d.itertuples()
    ]
    fig = go.Figure(go.Bar(
        x=d["score"], y=ids, orientation="h",
        marker_color=[p["accent"] if sid == student_id else p["peer"]
                      for sid in d["student_id"]],
        text=[f"{score:.1f}%" for score in d["score"]],
        textposition="outside", textfont=dict(size=11, color=p["ink"]), cliponaxis=False,
        customdata=labels,
        hovertemplate="%{customdata}<br><b>%{x:.1f}%</b><extra></extra>",
    ))
    fig = _base(fig, height=max(340, 54 * len(d) + 85), theme=theme)
    fig.update_yaxes(
        type="category", range=None, autorange="reversed",
        categoryorder="array", categoryarray=ids,
        showticklabels=False, tickvals=None, ticktext=None, ticksuffix=None,
        showgrid=False, showline=False, title=None,
    )
    fig.update_xaxes(
        type="linear", range=[0, 117], autorange=False,
        tickvals=[0, 25, 50, 75, 100], ticksuffix="%",
        showgrid=True, gridcolor=p["grid"], showline=False,
    )
    fig.update_layout(margin=dict(l=5, r=5, t=30, b=25), bargap=.64)
    for ident, label in zip(ids, labels):
        fig.add_annotation(
            x=0, y=ident, xref="x", yref="y", text=label,
            showarrow=False, xanchor="left", yshift=20,
            font=dict(size=11, color=p["ink"] if " (You)" in label else p["muted"]),
        )
    return fig
