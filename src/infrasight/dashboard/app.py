"""Run with: streamlit run src/infrasight/dashboard/app.py"""

import re
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

import streamlit as st

from infrasight.dashboard.client import APIClient, APIError
from infrasight.dashboard.components import (
    allocation_chart,
    candidate_cards,
    empty,
    health_chart,
    html,
    info_rows,
    kpis,
    meters,
    panel_title,
    regional_chart,
    table,
)
from infrasight.dashboard.config import DashboardSettings
from infrasight.dashboard.helpers import (
    DEMO_REFERENCE,
    DEMO_START,
    badge,
    fleet_rows,
    freshness,
    money,
    params,
    percent,
    scope,
    timestamp,
)

PAGES = ["Overview", "Infrastructure", "Cost Analytics", "AI Analyst", "Data Pipeline"]
SUGGESTIONS = [
    "How is our infrastructure doing?",
    "Which servers are expensive but underutilized?",
    "Which region has the most critical infrastructure?",
    "Which servers exceeded 80% CPU?",
    "Did infrastructure cost increase versus the previous period?",
]
TITLES = {
    "Overview": (
        "Infrastructure intelligence",
        "A unified view of fleet health, utilization and observed cost.",
    ),
    "Infrastructure": (
        "Infrastructure",
        "Fleet health & resource intelligence",
    ),
    "Cost Analytics": (
        "Cost Analytics",
        "Cost visibility & optimization opportunities",
    ),
    "AI Analyst": (
        "AI Analyst",
        "Evidence-grounded infrastructure intelligence",
    ),
    "Data Pipeline": (
        "Data Pipeline",
        "Ingestion reliability & processing audit",
    ),
}


def error_view(error):
    if error.status == 429:
        st.warning(
            "AI analysis is temporarily rate limited. Existing infrastructure "
            "analytics remain available. Please retry shortly.",
            icon=":material/schedule:",
        )
    else:
        st.error(error.message, icon=":material/info:")
    if error.request_id:
        st.caption(f"Support reference · {error.request_id}")


def read(client, endpoint, query):
    try:
        return client.get("/api/v1/" + endpoint, query)
    except APIError as error:
        error_view(error)
        return None


def section(title, meta=""):
    container = st.container(border=True, key="panel_" + re.sub(r"\W+", "_", title.lower()))
    with container:
        panel_title(title, meta)
    return container


def comparison_params(query):
    end = datetime.fromisoformat(query["end"])
    start = datetime.fromisoformat(query["start"])
    return {
        **scope(query),
        "currency": query["currency"],
        "mode": "explicit",
        "current_start": start.isoformat(),
        "current_end": end.isoformat(),
        "previous_start": (start - timedelta(days=1)).isoformat(),
        "previous_end": (end - timedelta(days=1)).isoformat(),
    }


def comparison_panel(result, currency):
    if not result:
        return
    data = result["data"]
    info_rows(
        [
            ("Selected period", money(data["current"]["estimated_cost"], currency)),
            ("Previous equivalent period", money(data["previous"]["estimated_cost"], currency)),
            (
                "Current priced coverage",
                percent(data["current"].get("cost_coverage_fraction"), True),
            ),
            (
                "Previous priced coverage",
                percent(data["previous"].get("cost_coverage_fraction"), True),
            ),
        ]
    )
    if data["quality"] == "COMPARABLE":
        color = "#42be85" if data["direction"] == "DECREASE" else "#f1c21b"
        change = percent(data.get("percentage_change"))
        html(
            f'<div class="context-note" style="border-color:{color}">'
            f"{escape(data['direction'].replace('_', ' '))} · {change} · "
            f"{money(data['difference'], currency)} versus the equivalent period</div>"
        )
    else:
        st.caption(
            "Comparison is unavailable or incomplete. Prior-period coverage must be "
            "sufficient before interpreting a trend."
        )


def overview(client, query, data, mode):
    kpis(
        [
            ("Total servers", data["inventory_servers"], "Registered inventory", "#e6edf5"),
            ("Healthy", data["healthy_servers"], "Fresh at selected reference", "#42be85"),
            ("Warning", data["warning_servers"], "Requires attention", "#f1c21b"),
            ("Critical", data["critical_servers"], "Immediate investigation", "#fa6c73"),
            (
                "Telemetry coverage",
                percent(data["coverage"]["coverage_fraction"], True),
                "Observation time coverage",
                "#78beee",
            ),
            (
                "Observed cost",
                money(data["observed_cost"], query["currency"]),
                "Selected observation intervals",
                "#e6edf5",
            ),
        ]
    )
    left, middle, right = st.columns([1.1, 1, 1.1])
    with left, section("Resource utilization", "Fresh-server averages"):
        meters(data)
        st.caption(
            "Utilization percentages describe reporting servers, not absolute "
            "infrastructure capacity."
        )
    with middle, section("Infrastructure health", "At reference time"):
        health_chart(data)
    with right, section("Telemetry & cost coverage", "Selected period"):
        coverage = data["coverage"]
        info_rows(
            [
                ("Reporting servers", f"{data['reporting_servers']} / {data['inventory_servers']}"),
                ("Expected inventory", coverage["expected_server_count"]),
                ("Observations", coverage["observation_count"]),
                ("Telemetry coverage", percent(coverage["coverage_fraction"], True)),
                ("Priced-time coverage", percent(coverage["cost_coverage_fraction"], True)),
            ]
        )
        st.caption(
            "Coverage measures observed time across the expected fleet. It is "
            "separate from the count of reporting servers."
        )
    regions = read(client, "analytics/regions", query)
    left, right = st.columns([1.6, 1])
    with left, section("Regional overview", "Health by region"):
        if regions:
            regional_chart(regions["data"])
            st.caption("Healthy • Warning • Critical • Stale • No data")
    with right, section("Observed cost comparison", "Equivalent UTC periods"):
        comparison_panel(
            read(client, "analytics/cost-comparison", comparison_params(query)), query["currency"]
        )
    left, right = st.columns([1.6, 1])
    with left, section("Operational insights", "From selected telemetry"):
        cpu = data.get("highest_cpu_server")
        cost = data.get("highest_cost_server")
        insights = [
            (
                "!",
                f"{data['critical_servers']} critical servers",
                "Fresh critical conditions at the selected reference time.",
            ),
            (
                "↗",
                f"{data['reporting_servers']} reporting servers",
                f"{data['stale_servers']} stale · {data['no_data_servers']} without observations.",
            ),
            (
                "$",
                cost["server_name"] if cost else "No priced server observations",
                money(cost["estimated_cost"], query["currency"])
                if cost
                else "No highest-cost server can be established.",
            ),
            (
                "▥",
                cpu["server_name"] if cpu else "No fresh CPU observation",
                f"Highest current CPU · {percent(cpu['cpu_usage_percent'])}"
                if cpu
                else "Current resource ranking needs fresh telemetry.",
            ),
        ]
        for symbol, title, detail in insights:
            html(
                f'<div class="insight"><span class="insight-symbol">{symbol}</span>'
                f'<div><div class="insight-title">{escape(title)}</div>'
                f'<div class="insight-detail">{escape(detail)}</div></div></div>'
            )
    with right, section("Pipeline freshness", "Most recent successful cycle"):
        run = read(
            client, "etl/runs", {"source_id": query["source_id"], "status": "SUCCEEDED", "limit": 1}
        )
        if run and run["data"]:
            latest = run["data"][0]
            html(badge(latest["status"]))
            info_rows(
                [
                    ("Last success", timestamp(latest["finished_at"])),
                    ("Watermark", timestamp(latest["watermark_after"])),
                    ("Inserted", latest["records_inserted"]),
                    ("Rejected", latest["records_rejected"]),
                ]
            )
        else:
            empty("No successful cycle found for this source.")


def infrastructure(client, query):
    fleet, pressure, resources = st.tabs(["Server fleet", "Health & pressure", "Resource leaders"])
    with fleet:
        a, b, c = st.columns([2, 1, 1])
        search = a.text_input(
            "Search this page", placeholder="Server name or external ID", key="fleet_search"
        )
        health = b.selectbox(
            "Effective health",
            ["All", "HEALTHY", "WARNING", "CRITICAL", "STALE", "NO_DATA"],
            key="fleet_health",
        )
        page = c.number_input(
            "Page", value=1, min_value=1, max_value=2001, step=1, key="fleet_page"
        )
        result = read(
            client,
            "analytics/server-health",
            {
                **scope(query),
                "health": None if health == "All" else health,
                "limit": 50,
                "offset": (page - 1) * 50,
            },
        )
        if result:
            rows = [
                r
                for r in result["data"]
                if search.lower()
                in f"{r.get('server_name', '')} {r.get('external_server_id', '')}".lower()
            ]
            with section(
                "Server fleet", f"{result['meta']['pagination']['total']} servers · page {page}"
            ):
                if rows:
                    table(fleet_rows(rows), hide_index=True, width="stretch", height=390)
                    st.caption(
                        "Interval cost is the latest recorded observation cost. Stale "
                        "measurements remain labeled STALE. Search applies to this page."
                    )
                    names = {r["server_id"]: r["server_name"] for r in rows}
                    selected = st.selectbox(
                        "Inspect a server",
                        list(names),
                        index=None,
                        format_func=names.get,
                        placeholder="Select a server for details",
                        key="server_detail",
                    )
                    if selected:
                        result = read(client, f"servers/{selected}", scope(query))
                        if result:
                            details = result["data"]
                            latest = details.get("latest_telemetry") or {}
                            html(badge(latest.get("effective_health", "NO_DATA")))
                            info_rows(
                                [
                                    ("Server", details["server_name"]),
                                    (
                                        "Region / environment",
                                        f"{details['region_code']} / {details['environment']}",
                                    ),
                                    ("Observed", timestamp(latest.get("observed_at"))),
                                    (
                                        "Latest interval cost",
                                        money(
                                            latest.get("estimated_cost"), latest.get("currency"), 8
                                        ),
                                    ),
                                ]
                            )
                else:
                    empty("No servers match this page and filter selection.")
    with pressure:
        left, right = st.columns(2)
        with left, section("Critical servers", "Fresh CRITICAL state"):
            result = read(
                client,
                "analytics/server-health",
                {**scope(query), "health": "CRITICAL", "limit": 20},
            )
            if result and result["data"]:
                table(fleet_rows(result["data"]), hide_index=True, width="stretch")
            elif result:
                empty("No fresh CRITICAL servers at this reference time.")
        with right, section("High CPU observations", "Strictly greater than 80%"):
            result = read(
                client, "analytics/high-cpu", {k: v for k, v in query.items() if k != "min_samples"}
            )
            if result and result["data"]:
                table(
                    [
                        {
                            "Server": r["server_name"],
                            "Region": r["region_code"],
                            "Peak CPU": percent(r["peak_cpu_percent"]),
                            "Breaches": r["breach_count"],
                        }
                        for r in result["data"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
            elif result:
                empty("No qualifying CPU breaches in this observation window.")
        with section("Sustained CPU pressure", "Coverage-qualified observations"):
            result = read(client, "analytics/cpu-pressure", query)
            if result and result["data"]:
                table(
                    [
                        {
                            "Server": r["server_name"],
                            "Region": r["region_code"],
                            "Avg CPU": percent(r["average_cpu_percent"]),
                            "Breach fraction": percent(r["breach_fraction"], True),
                            "Coverage": percent(r["coverage_fraction"], True),
                            "Samples": r["observation_count"],
                        }
                        for r in result["data"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
            elif result:
                empty("No servers meet the selected sample, coverage and breach criteria.")
        st.caption(
            "Pressure defaults: CPU >80%, at least 50% of observations in breach "
            "and 80% time coverage. The sample minimum is shown in the context "
            "settings."
        )
    with resources:
        resource = (
            st.segmented_control(
                "Resource", ["CPU", "Memory", "Storage"], default="CPU", key="leader_resource"
            )
            or "CPU"
        )
        result = read(
            client,
            "analytics/top-resource-usage",
            {**scope(query), "resource": resource.lower(), "limit": 10},
        )
        with section("Resource leaders", f"Top 10 · {resource} · fresh observations"):
            if result and result["data"]:
                table(fleet_rows(result["data"]), hide_index=True, width="stretch")
            elif result:
                empty("No fresh observations available for this ranking.")


def costs(client, query, data, minimum):
    comparison = read(client, "analytics/cost-comparison", comparison_params(query))
    kpis(
        [
            (
                "Observed cost",
                money(data["observed_cost"], query["currency"]),
                "Selected interval costs",
                "#e6edf5",
            ),
            (
                "Known-cost coverage",
                percent(data["coverage"]["cost_coverage_fraction"], True),
                "Priced observation time",
                "#78beee",
            ),
            (
                "Reporting servers",
                data["coverage"]["reporting_server_count"],
                "Servers with period observations",
                "#e6edf5",
            ),
        ]
    )
    left, right = st.columns([1.4, 1])
    with left, section("Cost allocation by region", "Observed spend; no currency conversion"):
        result = read(client, "analytics/regions", query)
        if result:
            allocation_chart(result["data"], query["currency"])
    with right, section("Equivalent-period comparison", "Same UTC window one day earlier"):
        comparison_panel(comparison, query["currency"])
    with section("Highest-cost servers", "Top 10 · selected observation window"):
        result = read(client, "analytics/cost-summary", query)
        if result and result["data"]["top_cost_servers"]:
            table(
                [
                    {
                        "Server": r["server_name"],
                        "Region": r["region_code"],
                        "Environment": r["environment"],
                        "Observed cost": money(r["estimated_cost"], query["currency"], 8),
                        "Priced-time coverage": percent(r["cost_coverage_fraction"], True),
                    }
                    for r in result["data"]["top_cost_servers"]
                ],
                hide_index=True,
                width="stretch",
            )
        elif result:
            empty("No priced observations in this window.")
    with section("Cost optimization", "Workload review required"):
        html(
            '<div class="context-note">Prioritize investigation, not automatic shutdown. '
            "Candidates are screened using observed utilization, coverage, cost and health. "
            "Projected savings are not available.</div>"
        )
        result = read(client, "analytics/underutilized", {**query, "min_samples": minimum})
        if result:
            candidate_cards(result["data"], query["currency"])
            st.caption(
                "Showing up to six cards from the bounded result. CPU <10%, memory "
                "<20%, 80% coverage, no CRITICAL observation, and fresh HEALTHY state."
            )
    st.caption(
        "Environment filters scope the complete workspace. A multi-environment "
        "cost allocation is not exposed by the current API, so no allocation "
        "totals are invented."
    )


def analyst(client, query, mode, overview_data):
    html(
        '<div class="analyst-hero"><span class="analyst-seal">EVIDENCE-BACKED ANALYSIS</span>'
        '<h2>Your infrastructure, explained.</h2><div class="page-sub">Move '
        "from telemetry to decisions. "
        "Ask a question about health, resource pressure or cloud cost.</div></div>"
    )
    st.caption("Suggested investigations")
    with st.container(key="ai_suggestions"):
        columns = st.columns(2)
        for index, question in enumerate(SUGGESTIONS):
            if columns[index % 2].button(
                question, key=f"suggest_{index}", width="stretch"
            ):
                st.session_state["analyst_question"] = question
    if query["region_code"] or query["environment"]:
        st.info(
            "AI scope uses source, time and currency. Specify region or environment "
            "in the question; these filters are not applied automatically by the AI "
            "endpoint."
        )
    with st.form("analyst_submit"):
        question = st.text_area(
            "Business question",
            key="analyst_question",
            height=100,
            placeholder="Which servers are expensive but underutilized?",
            max_chars=2000,
        )
        submitted = st.form_submit_button(
            "Analyze infrastructure", type="primary", icon=":material/auto_awesome:"
        )
    if submitted:
        if not question.strip():
            st.warning("Enter a question to begin an analysis.")
        else:
            body = {
                "question": question,
                "source_id": query["source_id"],
                "reference_time": query["as_of"],
                "start": query["start"],
                "end": query["end"],
                "currency": query["currency"],
                "freshness_seconds": query["freshness_seconds"],
                "min_samples": query["min_samples"],
            }
            try:
                with st.spinner("Reviewing approved analytics evidence…"):
                    st.session_state["analyst_result"] = {
                        "response": client.ask(body),
                        "context": dict(query),
                        "telemetry_state": freshness(overview_data, mode),
                    }
            except APIError as error:
                st.session_state.pop("analyst_result", None)
                error_view(error)
    stored = st.session_state.get("analyst_result")
    if stored:
        result = stored["response"]
        evidence = result["evidence"]
        if any(
            stored["context"].get(k) != query.get(k)
            for k in ("source_id", "region_code", "environment", "currency", "start", "end")
        ):
            st.info(
                "This saved answer belongs to an earlier context. Submit a new question "
                "to analyze the current selection."
            )
        with section("Analyst assessment", "Grounded in approved analytics"):
            html(
                '<div class="answer-title">Analysis</div>'
                + badge(stored.get("telemetry_state", "SNAPSHOT"))
            )
            st.markdown(result["answer"], unsafe_allow_html=False)
            html(
                '<div class="answer-title">Tools used</div>'
                + "".join(
                    f'<span class="tool-badge">{escape(tool)}</span>'
                    for tool in evidence["tools_used"]
                )
            )
            info_rows(
                [
                    ("Reference time", timestamp(evidence["reference_time"])),
                    ("Window", timestamp(evidence["window"].get("start"))
                     + " → " + timestamp(evidence["window"].get("end"))),
                    ("Freshness", stored.get("telemetry_state", "SNAPSHOT")),
                    ("Currency", evidence["currency"]),
                ]
            )
            st.caption("Coverage details are available in the evidence below.")
        with st.expander("Evidence & approved tools", expanded=False):
            st.write("Tools used", ", ".join(evidence["tools_used"]))
            info_rows(
                [
                    ("Reference time", timestamp(evidence["reference_time"])),
                    ("Window start", timestamp(evidence["window"].get("start"))),
                    ("Window end", timestamp(evidence["window"].get("end"))),
                    ("Currency", evidence["currency"]),
                    (
                        "Freshness threshold",
                        f"{evidence['freshness']['threshold_seconds']} seconds",
                    ),
                ]
            )
            st.json(
                {"freshness": evidence["freshness"], "coverage": evidence["coverage"]},
                expanded=False,
            )
            for tool in evidence["tool_results"]:
                st.markdown(f"**{tool['tool']}** · {tool['returned_rows']} result rows")
                for warning in tool.get("warnings", []):
                    st.caption(warning)
                st.json(tool["result"], expanded=False)
            st.caption(f"Request reference · {result['request_id']}")
    else:
        with section("Trusted by design", "Read-only analytics"):
            info_rows(
                [
                    ("Telemetry state", freshness(overview_data, mode)),
                    ("Reference", timestamp(query["as_of"])),
                    ("Currency", query["currency"]),
                ]
            )
            st.caption(
                "Answers are generated only after an explicit submission. Evidence "
                "remains available for review."
            )


def pipeline(client, query, settings):
    html(
        '<div class="pipeline-flow"><b>Raw telemetry</b> → <b>Validation</b> → '
        '<b>Transformation</b> → <b>PostgreSQL analytics</b></div>'
    )
    result = read(client, "etl/runs", {"source_id": query["source_id"], "limit": 50})
    if result:
        runs = result["data"]
        if runs:
            latest = runs[0]
            html(badge(latest["status"]))
            kpis(
                [
                    (label, latest[field], "Latest ingestion cycle", color)
                    for label, field, color in [
                        ("Extracted", "records_extracted", "#e6edf5"),
                        ("Accepted", "records_accepted", "#78beee"),
                        ("Inserted", "records_inserted", "#e6edf5"),
                        ("Duplicates", "records_duplicated", "#a5b9d1"),
                        ("Rejected", "records_rejected", "#f1c21b"),
                    ]
                ]
            )
            with section(
                "Recent ingestion cycles",
                f"{result['meta']['pagination']['total']} audit runs · latest 50",
            ):
                table(
                    [
                        {
                            "Run": r["run_id"][:8],
                            "Source": r["source_id"],
                            "Status": r["status"],
                            "Extracted": r["records_extracted"],
                            "Accepted": r["records_accepted"],
                            "Inserted": r["records_inserted"],
                            "Duplicates": r["records_duplicated"],
                            "Rejected": r["records_rejected"],
                            "Started": timestamp(r["started_at"]),
                            "Finished": timestamp(r["finished_at"]),
                            "Watermark": timestamp(r["watermark_after"]),
                        }
                        for r in runs
                    ],
                    hide_index=True,
                    width="stretch",
                    height=min(432, max(112, 36 + len(runs) * 32)),
                )
                selected = st.selectbox(
                    "Inspect cycle", [r["run_id"] for r in runs], index=None, key="run_detail"
                )
                if selected:
                    detail = read(client, f"etl/runs/{selected}", {})
                    if detail:
                        st.json(detail["data"], expanded=False)
        else:
            empty("No ingestion cycles recorded for the selected source.")
    if settings.admin_key:
        with section("Run an ingestion cycle", "Administrative operation"):
            st.caption(
                "Execute one synchronous cycle. Replaying the selected historical "
                "window demonstrates idempotency."
            )
            with st.form("trigger_etl"):
                adapter = st.selectbox("Approved source adapter", ["simulator", "host"])
                replay = st.checkbox("Replay the selected window", value=False)
                confirmed = st.checkbox(
                    "I confirm this will run ingestion and add an audit record."
                )
                submitted = st.form_submit_button(
                    "Execute ETL cycle", type="primary", icon=":material/play_arrow:"
                )
            if submitted:
                if not confirmed:
                    st.warning("Confirm the operation before starting ingestion.")
                else:
                    body = {"source": adapter}
                    if replay:
                        body.update(start=query["start"], end=query["end"])
                    try:
                        with st.spinner("Ingestion cycle running…"):
                            outcome = client.trigger(body)
                        if outcome["data"]["status"] == "SUCCEEDED":
                            st.success("Cycle completed. Refresh to review its audit record.")
                        else:
                            st.warning(
                                "Cycle completed with a failure. Review the recorded run status."
                            )
                        st.json(outcome["data"], expanded=True)
                    except APIError as error:
                        error_view(error)
    else:
        st.caption("Administrative ingestion controls are disabled in this read-only workspace.")


def main():
    st.set_page_config(
        page_title="InfraSight · Infrastructure Intelligence", page_icon="◈", layout="wide"
    )
    html(f"<style>{Path(__file__).with_name('theme.css').read_text(encoding='utf-8')}</style>")
    try:
        settings = DashboardSettings()
    except ValueError:
        st.error("Dashboard configuration needs attention. Check the server-side API settings.")
        st.stop()
    if "api_client" not in st.session_state:
        st.session_state["api_client"] = APIClient(settings)
    client = st.session_state["api_client"]
    with st.sidebar:
        html(
            '<div class="brand"><span class="brand-mark">◈</span>InfraSight<span '
            'style="color:#729fdb"> AI</span></div>'
            '<div class="brand-sub">INFRASTRUCTURE INTELLIGENCE</div><div '
            'class="nav-label">WORKSPACE</div>'
        )
        page = st.radio("Navigation", PAGES, label_visibility="collapsed", key="navigation")
        html('<div class="nav-label">ANALYSIS CONTEXT</div>')
        mode = st.selectbox(
            "Reference mode", ["Historical demo", "Live · last hour", "Custom UTC"], key="mode"
        )
        auto = st.toggle("Auto-refresh · 25 seconds", value=True, key="auto_refresh")
        with st.expander("Assessment settings"):
            fresh = st.number_input(
                "Freshness threshold (seconds)", value=120, min_value=1, max_value=86400
            )
            minimum = st.number_input(
                "Minimum assessment samples",
                value=4 if mode == "Historical demo" else 20,
                min_value=1,
                max_value=10000,
                key=f"samples_{mode}",
            )
            currency = st.selectbox("Currency", ["USD", "EUR", "GBP"])
            st.caption(
                "Historical demo uses 4 samples for its three-minute window. Production "
                "assessment defaults use 20."
            )
        start = end = reference = None
        if mode == "Custom UTC":
            start_text = st.text_input("Window start (UTC)", value=DEMO_START.isoformat())
            end_text = st.text_input(
                "Window end / reference (UTC)", value=DEMO_REFERENCE.isoformat()
            )
            try:
                start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
                end = reference = datetime.fromisoformat(end_text.replace("Z", "+00:00"))
                if start.tzinfo is None or end.tzinfo is None:
                    raise ValueError("Timezone required")
            except ValueError:
                st.error("Enter timezone-aware ISO timestamps.")
                st.stop()
        html(
            '<div class="side-foot">CLOUD OPERATIONS<br>UTC reporting · evidence-led decisions<br>'
            '<span style="color:#53718e">InfraSight-AI / Analytics workspace</span></div>'
        )
    with st.container(key="context_bar"):
        cols = st.columns([1.45, 1, 1, 1, 0.65, 0.5])
        choice = cols[0].selectbox(
            "Source",
            ["Simulated cloud", "Comparison scenario", "Local host", "All sources"],
            key="source",
        )
        source = {
            "Simulated cloud": "simulated-cloud",
            "Comparison scenario": "simulated-cloud-phase4-comparison",
            "Local host": "host-local",
            "All sources": None,
        }[choice]
        region = cols[1].selectbox(
            "Region", ["All regions", "us-south", "us-east", "eu-de", "local"], key="region"
        )
        environment = cols[2].selectbox(
            "Environment", ["All environments", "prod", "staging", "dev"], key="environment"
        )
        reference_label = (
            "11 Oct · 19:33 UTC"
            if mode == "Historical demo"
            else ("Current UTC" if mode == "Live · last hour" else "Custom UTC")
        )
        for column, label, value in [
            (cols[3], "REFERENCE", reference_label),
            (cols[4], "FRESHNESS", f"{fresh}s"),
        ]:
            with column:
                html(
                    f'<div class="context-value"><label>{label}</label>'
                    f"<div>{escape(value)}</div></div>"
                )
        cols[5].button(
            "", icon=":material/refresh:", help="Refresh analytics", width="stretch"
        )

    def render():
        try:
            query = params(
                mode,
                source,
                None if region == "All regions" else region,
                None if environment == "All environments" else environment,
                fresh,
                start,
                end,
                reference,
            )
        except ValueError:
            st.error("Choose a valid UTC window of seven days or less.")
            return
        query["currency"] = currency
        result = read(client, "analytics/overview", query)
        if not result:
            empty(
                "This workspace will populate when the analytics service is reachable "
                "and authenticated."
            )
            return
        data = result["data"]
        title, subtitle = TITLES[page]
        state = freshness(data, mode)
        html(
            '<div class="page-title"><div><div class="eyebrow">'
            f"Cloud operations / {escape(page)}</div>"
            f'<h1>{title}</h1><div class="page-sub">{subtitle}</div></div>{badge(state)}</div>'
        )
        html(
            '<div class="meta-line">'
            f"<span>LAST UPDATED <b>{datetime.now(UTC).strftime('%H:%M:%S UTC')}</b></span>"
            "<span>LATEST TELEMETRY <b>"
            f"{escape(timestamp(data['latest_telemetry_timestamp']))}</b></span>"
            f"<span>REFERENCE <b>{escape(timestamp(query['as_of']))}</b></span></div>"
        )
        if mode == "Historical demo":
            html(
                '<div class="context-note">HISTORICAL SNAPSHOT · 11 Oct 2026, 19:30–19:33 UTC. '
                "Health freshness is evaluated at the selected reference, not at "
                "wall-clock time.</div>"
            )
        if state in {"STALE", "NO_DATA", "PARTIAL"}:
            st.info(
                "Current telemetry is incomplete or stale. Last recorded healthy "
                "measurements are not counted as current HEALTHY."
            )
        if page == "Overview":
            overview(client, query, data, mode)
        else:
            query["min_samples"] = minimum
            if page == "Infrastructure":
                infrastructure(client, query)
            elif page == "Cost Analytics":
                # min_samples only belongs to the optimization query, not cost/region endpoints.
                sample = query.pop("min_samples")
                costs(client, query, data, sample)
            elif page == "AI Analyst":
                analyst(client, query, mode, data)
            else:
                pipeline(client, query, settings)

    if page == "AI Analyst":
        render()
    else:
        st.fragment(run_every="25s" if auto else None)(render)()


if __name__ == "__main__":
    main()
