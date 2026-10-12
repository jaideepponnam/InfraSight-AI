from html import escape

import altair as alt
import streamlit as st

from infrasight.dashboard.helpers import COLORS, badge, money, number, percent


def html(content):
    st.html(content)


def panel_title(title, meta=""):
    html(
        f'<div class="panel-heading"><strong>{escape(title)}</strong>'
        f"<span>{escape(meta)}</span></div>"
    )


def kpis(items):
    cards = []
    for label, value, note, color in items:
        cards.append(
            f'<div class="kpi"><div class="kpi-label">{escape(label)}</div>'
            f'<div class="kpi-number" style="color:{color}">{escape(str(value))}</div>'
            f'<div class="kpi-foot">{escape(note)}</div></div>'
        )
    html(f'<div class="kpi-grid" style="--kpi-count:{len(items)}">' + "".join(cards) + "</div>")


def meters(data):
    elements = []
    for label, field, color in [
        ("CPU", "average_cpu_percent", "#4589ff"),
        ("Memory", "average_memory_percent", "#6DBFCC"),
        ("Storage", "average_storage_percent", "#879FCD"),
    ]:
        value = number(data.get(field))
        width = max(0, min(100, value)) if value is not None else 0
        elements.append(
            f'<div class="meter-row"><div class="meter-head"><span>{label}</span>'
            f'<b>{percent(value)}</b></div><div class="meter-track">'
            f'<div class="meter-fill" style="width:{width}%;background:{color}"></div></div></div>'
        )

    html("".join(elements))


def info_rows(rows):
    html(
        "".join(
            f'<div class="info-row"><span>{escape(label)}</span><b>{escape(str(value))}</b></div>'
            for label, value in rows
        )
    )


def empty(message):
    html(f'<div class="empty-state">{escape(message)}</div>')


def chart_style(chart):
    return (
        chart.properties(background="transparent")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor="#91a4b7",
            titleColor="#91a4b7",
            gridColor="#26394c",
            domain=False,
            tickColor="#26394c",
            labelFontSize=11,
            titleFontSize=11,
        )
        .configure_legend(labelColor="#9fb4ca", titleColor="#9fb4ca", labelFontSize=11)
    )


def health_chart(data):
    rows = [
        {"Health": label, "Servers": data.get(field, 0)}
        for label, field in [
            ("HEALTHY", "healthy_servers"),
            ("WARNING", "warning_servers"),
            ("CRITICAL", "critical_servers"),
            ("STALE", "stale_servers"),
            ("NO_DATA", "no_data_servers"),
        ]
        if data.get(field, 0)
    ]
    if not rows:
        empty("No reporting observations in this scope.")
        return
    base = (
        alt.Chart(alt.Data(values=rows))
        .mark_arc(innerRadius=65, outerRadius=95, cornerRadius=2)
        .encode(
            theta=alt.Theta("Servers:Q"),
            color=alt.Color(
                "Health:N",
                scale=alt.Scale(
                    domain=list(COLORS)[:5], range=[COLORS[k] for k in list(COLORS)[:5]]
                ),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["Health:N", "Servers:Q"],
        )
    )
    center = (
        alt.Chart(alt.Data(values=[{"count": str(data.get("inventory_servers", 0))}]))
        .mark_text(color="#f4f7fb", fontSize=33, fontWeight=600)
        .encode(text="count:N")
    )
    st.altair_chart(chart_style((base + center).properties(height=235)), width="stretch")


def regional_chart(rows):
    sources = {r["source_id"] for r in rows}
    values = []
    for row in rows:
        for state, field in [
            ("HEALTHY", "healthy_servers"),
            ("WARNING", "warning_servers"),
            ("CRITICAL", "critical_servers"),
            ("STALE", "stale_servers"),
            ("NO_DATA", "no_data_servers"),
        ]:
            values.append(
                {
                    "Region": row["region_code"]
                    if len(sources) == 1
                    else row["region_code"] + " · " + row["source_id"],
                    "Source": row["source_id"],
                    "Health": state,
                    "Servers": row[field],
                }
            )
    if not values:
        empty("No regions found for these filters.")
        return
    chart = (
        alt.Chart(alt.Data(values=values))
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("Servers:Q", title="Servers"),
            y=alt.Y("Region:N", title=None, axis=alt.Axis(labelOverlap=False, labelLimit=200)),
            color=alt.Color(
                "Health:N",
                scale=alt.Scale(
                    domain=list(COLORS)[:5], range=[COLORS[k] for k in list(COLORS)[:5]]
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=["Region:N", "Source:N", "Health:N", "Servers:Q"],
        )
        .properties(height=180)
    )
    st.altair_chart(chart_style(chart), width="stretch")


def allocation_chart(rows, currency):
    sources = {r["source_id"] for r in rows}
    values = [
        {
            "Region": r["region_code"]
            if len(sources) == 1
            else r["region_code"] + " · " + r["source_id"],
            "Source": r["source_id"],
            "Cost": str(r["period_cost"]["estimated_cost"]),
            "Exact cost": money(r["period_cost"]["estimated_cost"], currency, 8),
        }
        for r in rows
        if number(r.get("period_cost", {}).get("estimated_cost")) is not None
    ]
    if not values:
        empty("No priced observations for this period and currency.")
        return
    # Monetary values remain strings. Vega uses quantitative geometry; tooltips stay exact.
    chart = (
        alt.Chart(alt.Data(values=values))
        .mark_bar(size=30, color="#4589FF", cornerRadiusEnd=4)
        .encode(
            x=alt.X("Cost:Q", title=f"Observed interval cost · {currency}"),
            y=alt.Y("Region:N", title=None, sort="-x"),
            tooltip=["Region:N", "Source:N", "Exact cost:N"],
        )
    )
    st.altair_chart(chart_style(chart.properties(height=195)), width="stretch")


def candidate_cards(rows, currency):
    if not rows:
        empty("No candidates meet the selected cost, coverage and health criteria.")
        return
    for offset in range(0, min(len(rows), 6), 3):
        for column, row in zip(st.columns(3), rows[offset : offset + 3], strict=False):
            with column:
                html(
                    '<div class="optimization-card"><div class="opt-label">Optimization '
                    "candidate</div>"
                    f'<div class="opt-server">{escape(row["server_name"])}</div>'
                    f'<div class="opt-detail">{escape(row["region_code"])} · '
                    f"{escape(row['environment'])}</div>"
                    f'<div class="opt-cost">{money(row["estimated_cost"], currency)}</div>'
                    '<div class="opt-detail">CPU '
                    f"{percent(row['average_cpu_percent'])} &nbsp; · &nbsp; "
                    f"Memory {percent(row['average_memory_percent'])}<br>"
                    f"Observation coverage {percent(row['coverage_fraction'], True)}</div>"
                    f'<div style="margin-top:12px">{badge(row["latest_health"])}</div></div>'
                )


def table(data, **options):
    """Native interactive table with restrained semantic status colors."""
    import pandas as pd

    frame = pd.DataFrame(data)
    status = next((c for c in ("Health", "Status") if c in frame.columns), None)
    display = (
        frame.style.map(
            lambda value: "color: " + COLORS.get(str(value), "#8ba0b7") + "; font-weight: 600",
            subset=[status],
        )
        if status
        else frame
    )
    options.setdefault("row_height", 32)
    options.setdefault("height", min(432, max(112, 36 + len(frame) * 32)))
    st.dataframe(display, **options)
