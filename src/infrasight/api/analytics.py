from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from infrasight.analytics.schemas import (
    CpuThreshold,
    HealthQuery,
    Pressure,
    Underutilization,
    Window,
)
from infrasight.analytics.services import AnalyticsService
from infrasight.api.dependencies import analytics, report_response, result_response
from infrasight.api.schemas import (
    ComparisonEnvelope,
    ComparisonParameters,
    CostEnvelope,
    CpuParameters,
    Envelope,
    OverviewEnvelope,
    PressureParameters,
    RegionalEnvelope,
    ResourceParameters,
    UnderutilizedParameters,
    WindowParameters,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])
options = {"response_model": Envelope, "response_model_exclude_unset": True}


@router.get(
    "/overview",
    summary="Fleet health and observed period cost",
    **{**options, "response_model": OverviewEnvelope},
)
def overview(
    request: Request,
    params: Annotated[WindowParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(request, service.overview(params.query(Window)), single=True)


@router.get(
    "/server-health",
    summary="Freshness-aware server health, including STALE and NO_DATA",
    **options,
)
def health(
    request: Request,
    params: Annotated[HealthQuery, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return result_response(request, service.health_page(params))


@router.get("/high-cpu", summary="Servers strictly above a CPU percentage threshold", **options)
def high_cpu(
    request: Request,
    params: Annotated[CpuParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(request, service.high_cpu_breaches(params.query(CpuThreshold)))


@router.get(
    "/top-resource-usage",
    summary="Rank current servers by an approved resource percentage",
    **options,
)
def resources(
    request: Request,
    params: Annotated[ResourceParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    from infrasight.analytics.schemas import Scope

    query = service.scope(
        **{
            k: v
            for k, v in params.model_dump(exclude_unset=True).items()
            if k in Scope.model_fields and k != "as_of"
        },
        as_of=params.as_of,
    )
    method = {"cpu": service.top_cpu, "memory": service.top_memory, "storage": service.top_storage}[
        params.resource
    ]
    return report_response(request, method(query))


@router.get(
    "/regions",
    summary="Regional current health and selected-period cost",
    **{**options, "response_model": RegionalEnvelope},
)
def regions(
    request: Request,
    params: Annotated[WindowParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(request, service.regions(params.query(Window)))


@router.get(
    "/cost-summary",
    summary="Exact observed cost, coverage, and highest-cost servers",
    **{**options, "response_model": CostEnvelope},
)
def costs(
    request: Request,
    params: Annotated[WindowParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(request, service.cost_summary(params.query(Window)), single=True)


@router.get(
    "/cost-comparison",
    summary="UTC period comparison with explicit quality and coverage",
    **{**options, "response_model": ComparisonEnvelope},
)
def comparison(
    request: Request,
    params: Annotated[ComparisonParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(request, service.api_comparison(params), single=True)


@router.get(
    "/underutilized", summary="Cost-optimization candidates; savings are not guaranteed", **options
)
def underutilized(
    request: Request,
    params: Annotated[UnderutilizedParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(
        request, service.underutilized(params.query(Underutilization, lookback=24))
    )


@router.get(
    "/cpu-pressure", summary="Sustained CPU pressure with minimum samples and coverage", **options
)
def pressure(
    request: Request,
    params: Annotated[PressureParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(
        request, service.sustained_cpu_pressure(params.query(Pressure, lookback=24))
    )


@router.get(
    "/average-health",
    summary="Duration-weighted recorded health mix in a bounded window",
    **options,
)
def average_health(
    request: Request,
    params: Annotated[WindowParameters, Query()],
    service: Annotated[AnalyticsService, Depends(analytics)],
):
    return report_response(request, service.average_health(params.query(Window)))
