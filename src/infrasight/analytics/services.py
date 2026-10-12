from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

from infrasight.analytics.repository import AnalyticsRepository
from infrasight.analytics.schemas import (
    AnalyticsReport,
    Comparison,
    Scope,
    Underutilization,
    Window,
)


class AnalyticsService:
    def __init__(self, database, settings=None):
        self.database, self.settings = database, settings

    def scope(self, **values):
        if self.settings is not None:
            values.setdefault("freshness_seconds", self.settings.analytics_freshness_seconds)
        return Scope(**values)

    @contextmanager
    def _repository(self):
        if hasattr(self.database, "execute"):
            yield AnalyticsRepository(self.database)
        else:
            # Multiple comparison statements see one data snapshot. No semantic GUCs are used.
            with self.database.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                with connection.begin():
                    yield AnalyticsRepository(connection)

    def _validate(self, query):
        supplied_freshness = "freshness_seconds" in query.model_fields_set
        query = type(query).model_validate(query.model_dump())
        if self.settings is not None and not supplied_freshness:
            query.freshness_seconds = self.settings.analytics_freshness_seconds
        max_days = self.settings.analytics_max_window_days if self.settings else 7
        max_results = self.settings.analytics_max_results if self.settings else 100
        if query.limit > max_results:
            raise ValueError("Result limit exceeds configured bound")
        windows = [(query.start, query.end)] if isinstance(query, Window) else []
        if isinstance(query, Comparison):
            windows = [
                (query.current_start, query.current_end),
                (query.previous_start, query.previous_end),
            ]
        if any((end - start).total_seconds() > max_days * 86400 for start, end in windows):
            raise ValueError("Window exceeds configured bound")
        return query

    def _report(self, query, method, *args, warnings=None):
        query = self._validate(query)
        with self._repository() as repository:
            rows = getattr(repository, method)(query, *args)
        notices = list(warnings or [])
        if any(row.get("overlap_detected") for row in rows):
            notices.append(
                "Overlapping observation intervals detected; cost estimates require review."
            )
        return AnalyticsReport(
            reference_time=query.as_of,
            window_start=getattr(query, "start", None),
            window_end=getattr(query, "end", None),
            currency=getattr(query, "currency", None),
            rows=rows,
            parameters=query.model_dump(),
            warnings=notices,
        )

    def health(self, query):
        return self._report(query, "health")

    def fleet_totals(self, query):
        return self._report(query, "totals")

    def regional_health(self, query):
        return self._report(query, "regional_health")

    def critical_servers(self, query):
        return self._report(query, "critical")

    def top_cpu(self, query):
        return self._report(query, "top_resource", "cpu_usage_percent")

    def top_memory(self, query):
        return self._report(query, "top_resource", "memory_usage_percent")

    def high_cpu_breaches(self, query):
        return self._report(query, "breaches")

    def sustained_cpu_pressure(self, query):
        return self._report(query, "pressure")

    def underutilized(self, query: Underutilization):
        return self._report(
            query,
            "underutilized",
            warnings=[
                "Optimization candidates require workload review; shutdown safety and "
                "savings are not guaranteed."
            ],
        )

    def highest_cost_servers(self, query: Window):
        return self._report(query, "top_cost")

    def fleet_costs(self, query: Window):
        return self._report(query, "fleet_costs")

    def compare_cost(self, query: Comparison):
        query = self._validate(query)
        base = {key: getattr(query, key) for key in Scope.model_fields}
        with self._repository() as repository:
            current = repository.period_cost(
                Window(
                    **base,
                    start=query.current_start,
                    end=query.current_end,
                    currency=query.currency,
                )
            )
            previous = repository.period_cost(
                Window(
                    **base,
                    start=query.previous_start,
                    end=query.previous_end,
                    currency=query.currency,
                )
            )
        current_amount, previous_amount = current["estimated_cost"], previous["estimated_cost"]
        equal = query.current_end - query.current_start == query.previous_end - query.previous_start
        if current["overlap_detected"] or previous["overlap_detected"]:
            quality = "OVERLAPPING_INTERVALS"
        elif not equal:
            quality = "UNEQUAL_DURATION"
        elif current_amount is None or previous_amount is None:
            quality = "UNKNOWN_COST"
        elif any(
            p["cost_coverage_fraction"] is None or p["cost_coverage_fraction"] < query.min_coverage
            for p in (current, previous)
        ):
            quality = "INSUFFICIENT_COVERAGE"
        else:
            quality = "COMPARABLE"
        difference = (
            current_amount - previous_amount
            if current_amount is not None and previous_amount is not None
            else None
        )
        percentage, direction = None, "UNDETERMINED"
        if quality == "COMPARABLE":
            direction = (
                "INCREASE" if difference > 0 else "DECREASE" if difference < 0 else "UNCHANGED"
            )
            if previous_amount > 0:
                percentage = difference / previous_amount * Decimal(100)
            elif current_amount > 0:
                direction = "INCREASE_FROM_ZERO"
        return AnalyticsReport(
            reference_time=query.as_of,
            window_start=query.current_start,
            window_end=query.current_end,
            currency=query.currency,
            parameters=query.model_dump(),
            rows=[
                {
                    "current": current,
                    "previous": previous,
                    "difference": difference,
                    "percentage_change": percentage,
                    "direction": direction,
                    "quality": quality,
                }
            ],
            warnings=[]
            if quality == "COMPARABLE"
            else ["Cost comparison is incomplete or not equivalent; inspect coverage and windows."],
        )

    def compare_completed_days(self, scope: Scope, currency="USD"):
        today = scope.as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.compare_cost(
            Comparison(
                **scope.model_dump(),
                currency=currency,
                current_start=today - timedelta(days=1),
                current_end=today,
                previous_start=today - timedelta(days=2),
                previous_end=today - timedelta(days=1),
            )
        )

    def compare_today(self, scope: Scope, currency="USD", equivalent_elapsed=True):
        today = scope.as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = scope.as_of - today
        if elapsed.total_seconds() <= 0:
            raise ValueError("No elapsed UTC period is available; compare completed days instead")
        yesterday = today - timedelta(days=1)
        previous_end = yesterday + elapsed if equivalent_elapsed else today
        return self.compare_cost(
            Comparison(
                **scope.model_dump(),
                currency=currency,
                current_start=today,
                current_end=scope.as_of,
                previous_start=yesterday,
                previous_end=previous_end,
                allow_unequal_duration=not equivalent_elapsed,
            )
        )

    def top_storage(self, query):
        return self._report(query, "top_resource", "storage_usage_percent")

    def health_page(self, query):
        query = self._validate(query)
        with self._repository() as repository:
            rows = repository.health_page(query)
            total = repository.health_count(query)
        return {
            "data": rows,
            "meta": {
                "reference_time": query.as_of,
                "freshness_seconds": query.freshness_seconds,
                "filters": query.model_dump(),
                "pagination": {"offset": query.offset, "limit": query.limit, "total": total},
            },
        }

    def overview(self, query):
        query = self._validate(query)
        leader_query = query.model_copy(update={"limit": 1})
        # Four fixed queries share one snapshot, independent of fleet size.
        with self._repository() as repository:
            totals = repository.totals(query)[0]
            cpu = repository.top_resource(leader_query, "cpu_usage_percent")
            cost = repository.period_cost(query)
            leaders = repository.top_cost(leader_query)
        totals.update(
            observed_cost=cost["estimated_cost"],
            currency=query.currency,
            coverage=cost,
            highest_cpu_server=cpu[0] if cpu else None,
            highest_cost_server=leaders[0] if leaders else None,
        )
        return AnalyticsReport(
            reference_time=query.as_of,
            window_start=query.start,
            window_end=query.end,
            currency=query.currency,
            rows=[totals],
            parameters=query.model_dump(),
            warnings=["Overlapping intervals require review."] if cost["overlap_detected"] else [],
        )

    def regions(self, query):
        query = self._validate(query)
        with self._repository() as repository:
            rows = repository.regional_health(query)
            costs = repository.region_costs(query)
        cost_map = {(r["source_id"], r["region_code"]): r for r in costs}
        for row in rows:
            row["period_cost"] = cost_map.get(
                (row["source_id"], row["region_code"]),
                {
                    "estimated_cost": None,
                    "currency": query.currency,
                    "coverage_fraction": None,
                    "cost_coverage_fraction": None,
                },
            )
        return AnalyticsReport(
            reference_time=query.as_of,
            window_start=query.start,
            window_end=query.end,
            currency=query.currency,
            rows=rows,
            parameters=query.model_dump(),
        )

    def cost_summary(self, query):
        query = self._validate(query)
        with self._repository() as repository:
            cost = repository.period_cost(query)
            cost["top_cost_servers"] = repository.top_cost(query)
        return AnalyticsReport(
            reference_time=query.as_of,
            window_start=query.start,
            window_end=query.end,
            currency=query.currency,
            rows=[cost],
            parameters=query.model_dump(),
            warnings=["Overlapping intervals require review."] if cost["overlap_detected"] else [],
        )

    def api_comparison(self, params):
        base = {k: getattr(params, k) for k in Scope.model_fields}
        supplied = [
            params.current_start,
            params.current_end,
            params.previous_start,
            params.previous_end,
        ]
        if params.mode == "explicit":
            return self.compare_cost(
                Comparison(
                    **base,
                    currency=params.currency,
                    current_start=params.current_start,
                    current_end=params.current_end,
                    previous_start=params.previous_start,
                    previous_end=params.previous_end,
                    min_coverage=params.min_coverage,
                )
            )
        if any(v is not None for v in supplied):
            raise ValueError("Explicit windows require explicit comparison mode")
        today = params.as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        if params.mode == "completed_days":
            current_start, current_end = today - timedelta(days=1), today
            previous_start, previous_end = today - timedelta(days=2), current_start
        else:
            current_start, current_end = today, params.as_of
            previous_start = today - timedelta(days=1)
            previous_end = (
                previous_start + (params.as_of - today)
                if params.mode == "equivalent_elapsed"
                else today
            )
        return self.compare_cost(
            Comparison(
                **base,
                currency=params.currency,
                current_start=current_start,
                current_end=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                min_coverage=params.min_coverage,
                allow_unequal_duration=params.mode == "today_vs_yesterday",
            )
        )
