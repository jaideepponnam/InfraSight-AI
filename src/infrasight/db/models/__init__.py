"""Import all domain models to register their migration metadata."""

from infrasight.db.models.data_quality_rejection import DataQualityRejection
from infrasight.db.models.etl_run import EtlRun
from infrasight.db.models.infrastructure_metric import InfrastructureMetric
from infrasight.db.models.ingestion_state import IngestionState
from infrasight.db.models.raw_telemetry import RawTelemetry
from infrasight.db.models.region import Region
from infrasight.db.models.server import Server

__all__ = [
    "Region",
    "Server",
    "EtlRun",
    "RawTelemetry",
    "InfrastructureMetric",
    "DataQualityRejection",
    "IngestionState",
]
