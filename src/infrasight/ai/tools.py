from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from infrasight.ai.provider import AIError
from infrasight.analytics.schemas import (
    Comparison,
    CpuThreshold,
    Pressure,
    Scope,
    Underutilization,
    Window,
)
from infrasight.api.schemas import (
    ComparisonParameters,
    CpuParameters,
    PressureParameters,
    ResourceParameters,
    UnderutilizedParameters,
    WindowParameters,
)


class StrictScope(Scope):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StrictWindow(WindowParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StrictCpu(CpuParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StrictPressure(PressureParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StrictUnderutilized(UnderutilizedParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StrictResource(ResourceParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StrictComparison(ComparisonParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


@dataclass(frozen=True)
class Tool:
    description: str
    arguments: type[BaseModel]
    method: str
    query_model: type[BaseModel] | None = None
    lookback: int | None = None


TOOLS = {
    "get_overview": Tool(
        "Fleet health counts, freshness, resource averages, observed cost and coverage.",
        StrictWindow,
        "overview",
        Window,
    ),
    "get_server_health": Tool(
        "Server status for the whole filtered fleet, including prod/dev/staging: "
        "fleet_summary contains complete health counts; rows are bounded examples only. "
        "STALE and NO_DATA are separate states.",
        StrictScope,
        "health",
    ),
    "get_high_cpu_servers": Tool(
        "Servers with CPU strictly above threshold within the requested UTC window; "
        "includes breach counts.",
        StrictCpu,
        "high_cpu_breaches",
        CpuThreshold,
    ),
    "get_top_resource_usage": Tool(
        "Rank currently fresh servers by CPU, memory or storage percent. No "
        "arbitrary sort expressions.",
        StrictResource,
        "resource",
    ),
    "get_cost_summary": Tool(
        "Observed interval cost for one currency, coverage and highest-cost servers. "
        "Never a forecast or currency conversion.",
        StrictWindow,
        "cost_summary",
        Window,
    ),
    "compare_cost": Tool(
        "Compare equivalent periods with coverage quality. With a selected window, "
        "compare the same UTC period one day earlier by default.",
        StrictComparison,
        "comparison",
    ),
    "get_region_usage": Tool(
        "Regional current health counts and resource averages plus selected-period "
        "costs. Percentages are not capacity.",
        StrictWindow,
        "regions",
        Window,
    ),
    "get_underutilized_servers": Tool(
        "Cost-optimization candidates with sample/coverage minima, low CPU/memory, "
        "no critical condition and fresh health. Shutdown safety or savings are not guaranteed.",
        StrictUnderutilized,
        "underutilized",
        Underutilization,
        24,
    ),
    "get_cpu_pressure": Tool(
        "Sustained CPU pressure: fraction of observations strictly above threshold, "
        "with minimum samples and coverage.",
        StrictPressure,
        "sustained_cpu_pressure",
        Pressure,
        24,
    ),
    "get_critical_servers": Tool(
        "Latest fresh CRITICAL servers; excludes STALE/NO_DATA. Bounded results.",
        StrictScope,
        "critical_servers",
    ),
}


class ToolRegistry:
    def __init__(self, service, settings, context):
        self.service, self.settings, self.context = service, settings, context

    def schemas(self):
        schemas = []
        for name, tool in TOOLS.items():
            schema = tool.arguments.model_json_schema()
            # Keep the complete typed contract visible; execution still freezes context.
            context_defaults = {
                "as_of": self.context.model_dump(mode="json")["reference_time"],
                "freshness_seconds": self.context.freshness_seconds
                or self.settings.analytics_freshness_seconds,
                "currency": self.context.currency,
            }
            if self.context.source_id is not None:
                context_defaults["source_id"] = self.context.source_id
            if self.context.start is not None:
                serialized = self.context.model_dump(mode="json")
                context_defaults.update(start=serialized["start"], end=serialized["end"])
            if self.context.min_samples is not None:
                context_defaults["min_samples"] = self.context.min_samples
            for field, value in context_defaults.items():
                if field in schema["properties"]:
                    schema["properties"][field]["default"] = value
            schema.pop("title", None)
            for field in schema["properties"].values():
                field.pop("title", None)
            schema["properties"]["limit"]["maximum"] = self.settings.ai_max_result_rows
            schema["properties"]["limit"]["default"] = min(10, self.settings.ai_max_result_rows)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description,
                        "parameters": schema,
                    },
                }
            )
        return schemas

    def execute(self, name, arguments):
        tool = TOOLS.get(name)
        if tool is None:
            raise AIError("AI_UNKNOWN_TOOL")
        fleet_summary = None
        try:
            args = tool.arguments.model_validate_json(arguments)
            provided = args.model_dump(exclude_unset=True)
            if "limit" in provided and provided["limit"] > self.settings.ai_max_result_rows:
                raise ValueError("AI result bound exceeded")
            for field, value in (
                ("as_of", self.context.reference_time),
                ("source_id", self.context.source_id),
                ("currency", self.context.currency),
            ):
                if field in provided and value is not None and provided[field] != value:
                    raise ValueError("Tool arguments conflict with request context")
            values = args.model_dump()
            values["as_of"] = self.context.reference_time
            if self.context.source_id is not None:
                values["source_id"] = self.context.source_id
            if "currency" in values:
                values["currency"] = self.context.currency
            values["freshness_seconds"] = (
                self.context.freshness_seconds or self.settings.analytics_freshness_seconds
            )
            values["limit"] = min(
                values["limit"],
                self.settings.ai_max_result_rows,
                self.settings.analytics_max_results,
            )
            if "min_samples" in values and self.context.min_samples is not None:
                values["min_samples"] = self.context.min_samples
            if isinstance(args, WindowParameters) and self.context.start is not None:
                for field in ("start", "end"):
                    if field in provided and provided[field] != getattr(self.context, field):
                        raise ValueError("Tool window conflicts with request context")
                    values[field] = getattr(self.context, field)
            args = tool.arguments.model_validate(values)
            if tool.method == "comparison":
                if self.context.start is not None:
                    if any(
                        field in provided
                        for field in (
                            "mode",
                            "current_start",
                            "current_end",
                            "previous_start",
                            "previous_end",
                        )
                    ):
                        raise ValueError("Comparison window is fixed by request context")
                    query = Comparison(
                        **{k: v for k, v in values.items() if k in Scope.model_fields},
                        currency=self.context.currency,
                        current_start=self.context.start,
                        current_end=self.context.end,
                        previous_start=self.context.start - timedelta(days=1),
                        previous_end=self.context.end - timedelta(days=1),
                        min_coverage=args.min_coverage,
                    )
                    report = self.service.compare_cost(query)
                else:
                    report = self.service.api_comparison(args)
            elif tool.method == "resource":
                query = Scope(**{k: v for k, v in values.items() if k in Scope.model_fields})
                method = {
                    "cpu": self.service.top_cpu,
                    "memory": self.service.top_memory,
                    "storage": self.service.top_storage,
                }[args.resource]
                report = method(query)
            else:
                query = args.query(tool.query_model, tool.lookback) if tool.query_model else args
                report = getattr(self.service, tool.method)(query)
                if name == "get_server_health":
                    # Reuse approved aggregate SQL with exactly the same cohort/reference.
                    # Counts never come from the bounded detail rows.
                    totals = self.service.fleet_totals(query).model_dump(mode="json")
                    fleet_summary = totals["rows"][0]
        except (ValidationError, ValueError) as exc:
            raise AIError("AI_INVALID_TOOL_ARGUMENTS") from exc
        except AIError:
            raise
        except Exception as exc:
            raise AIError("AI_ANALYTICS_UNAVAILABLE", 503) from exc
        result = report.model_dump(mode="json")
        if fleet_summary is not None:
            result["fleet_summary"] = fleet_summary
        if len(result["rows"]) > values["limit"]:
            raise AIError("AI_RESULT_LIMIT_EXCEEDED")
        result["row_limit"] = values["limit"]
        result["result_may_be_truncated"] = len(result["rows"]) >= values["limit"]
        return result


def metadata(result: dict[str, Any]):
    """Expose backend-supplied evidence; never calculate new business measures."""
    coverage, freshness = [], {"threshold_seconds": result["parameters"]["freshness_seconds"]}
    summary_rows = [result["fleet_summary"]] if "fleet_summary" in result else []
    for row in [*summary_rows, *result["rows"]]:
        selected = {k: v for k, v in row.items() if "coverage" in k and not isinstance(v, dict)}
        if selected:
            coverage.append(selected)
        for field in ("coverage", "period_cost", "current", "previous"):
            if isinstance(row.get(field), dict):
                coverage.append(
                    {
                        "kind": field,
                        **{
                            k: v
                            for k, v in row[field].items()
                            if "coverage" in k
                            or k in ("expected_server_count", "reporting_server_count")
                        },
                    }
                )
        for field in (
            "latest_telemetry_timestamp",
            "healthy_servers",
            "warning_servers",
            "critical_servers",
            "stale_servers",
            "no_data_servers",
        ):
            if field in row:
                freshness.setdefault("summaries", []).append({field: row[field]})
        if "effective_health" in row:
            freshness.setdefault("servers", []).append(
                {
                    "server_id": row["server_id"],
                    "effective_health": row["effective_health"],
                    "observed_at": row.get("observed_at"),
                    "completion_age_seconds": row.get("completion_age_seconds"),
                }
            )
    return freshness, coverage
