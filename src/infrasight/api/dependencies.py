from fastapi import Request

from infrasight.analytics.services import AnalyticsService
from infrasight.api.schemas import Envelope


def analytics(request: Request):
    return AnalyticsService(request.app.state.engine, request.app.state.settings)


def report_response(request, report, single=False):
    return Envelope.model_validate(
        {
            "data": (report.rows[0] if report.rows else {}) if single else report.rows,
            "meta": {
                "request_id": request.state.request_id,
                "reference_time": report.reference_time,
                "window_start": report.window_start,
                "window_end": report.window_end,
                "currency": report.currency,
                "freshness_seconds": report.parameters.get("freshness_seconds"),
                "parameters": report.parameters,
                "warnings": report.warnings,
            },
        }
    )


def result_response(request, result):
    return Envelope.model_validate(
        {
            "data": result["data"],
            "meta": {**result.get("meta", {}), "request_id": request.state.request_id},
        }
    )
