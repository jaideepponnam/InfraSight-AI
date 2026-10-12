from infrasight.ingestion.schemas import TelemetryRecord


# Policy v1: storage does not participate. Threshold changes require an explicit policy change.
def classify_health(record: TelemetryRecord) -> str:
    if (
        record.server_status == "FAILED"
        or max(record.cpu_usage_percent, record.memory_usage_percent) >= 90
    ):
        return "CRITICAL"
    if (
        record.server_status == "DEGRADED"
        or max(record.cpu_usage_percent, record.memory_usage_percent) >= 80
    ):
        return "WARNING"
    return "HEALTHY"


def metric_values(record: TelemetryRecord) -> dict:
    fields = (
        "observed_at",
        "cpu_usage_percent",
        "memory_usage_percent",
        "storage_usage_percent",
        "network_mbps",
        "uptime_seconds",
        "server_status",
        "estimated_cost",
        "currency",
        "interval_seconds",
    )
    return {
        **{field: getattr(record, field) for field in fields},
        "resource_health": classify_health(record),
    }
