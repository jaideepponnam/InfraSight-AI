from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from html import escape

DEMO_REFERENCE = datetime(2026, 10, 11, 19, 33, tzinfo=UTC)
DEMO_START = DEMO_REFERENCE - timedelta(minutes=3)
COLORS = {
    "HEALTHY": "#42BE85",
    "WARNING": "#F1C21B",
    "CRITICAL": "#FA6C73",
    "STALE": "#C7A66A",
    "NO_DATA": "#7E93AB",
    "LIVE": "#42BE85",
    "SNAPSHOT": "#78BEEE",
    "PARTIAL": "#F1C21B",
    "SUCCEEDED": "#42BE85",
    "FAILED": "#FA6C73",
    "RUNNING": "#4589FF",
    "QUEUED": "#7E93AB",
}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(value, currency="USD", digits=4):
    value = number(value)
    if value is None:
        return "Unknown"
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + abs(value.adjusted()) + digits + 5)
        rounded = value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{currency or 'Unknown currency'} {rounded:,.{digits}f}"


def percent(value, fraction=False):
    value = number(value)
    if value is None:
        return "—"
    if fraction:
        value *= 100
    return f"{value:.1f}%"


def timestamp(value):
    if not value:
        return "No observation"
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            return "Unknown timezone"
        return date.astimezone(UTC).strftime("%d %b %Y · %H:%M:%S UTC")
    except ValueError:
        return "Unknown timestamp"


def badge(status):
    color = COLORS.get(status, "#7E93AB")
    label = escape(str(status).replace("_", " "))
    return (
        f'<span class="status-badge" style="color:{color};border-color:{color}44">'
        f'<i style="background:{color}"></i>{label}</span>'
    )


def freshness(data, mode):
    if not data.get("servers_with_observations"):
        return "NO_DATA"
    if not data.get("reporting_servers"):
        return "STALE"
    if data.get("stale_servers", 0) or data.get("no_data_servers", 0):
        return "PARTIAL"
    return "SNAPSHOT" if mode != "Live · last hour" else "LIVE"


def params(
    mode,
    source,
    region=None,
    environment=None,
    freshness_seconds=120,
    start=None,
    end=None,
    reference=None,
    now=None,
):
    now = now or datetime.now(UTC)
    if mode == "Historical demo":
        reference, start, end = DEMO_REFERENCE, DEMO_START, DEMO_REFERENCE
    elif mode == "Live · last hour":
        reference, end, start = now, now, now - timedelta(hours=1)
    if start is None or end is None or reference is None or not start < end <= reference:
        raise ValueError("Use start < end <= reference, in UTC")
    if (end - start).total_seconds() > 7 * 86400:
        raise ValueError("Select a window of seven days or less")
    return {
        "source_id": source,
        "region_code": region,
        "environment": environment,
        "as_of": reference.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "freshness_seconds": freshness_seconds,
        "currency": "USD",
        "limit": 10,
    }


def scope(query):
    return {
        k: v
        for k, v in query.items()
        if k in {"source_id", "region_code", "environment", "as_of", "freshness_seconds"}
    }


def fleet_rows(rows):
    return [
        {
            "Server": r.get("server_name"),
            "External ID": r.get("external_server_id"),
            "Region": r.get("region_code"),
            "Environment": r.get("environment"),
            "Health": r.get("effective_health", "NO_DATA"),
            "CPU": percent(r.get("cpu_usage_percent")),
            "Memory": percent(r.get("memory_usage_percent")),
            "Storage": percent(r.get("storage_usage_percent")),
            "Interval cost": money(r.get("estimated_cost"), r.get("currency"), 8),
            "Observed (UTC)": timestamp(r.get("observed_at")),
        }
        for r in rows
    ]
