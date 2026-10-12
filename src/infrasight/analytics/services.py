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
        query = type(query).model_validate(query.model_dump())
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
