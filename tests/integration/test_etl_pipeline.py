from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from infrasight.db.models import (
    DataQualityRejection,
    EtlRun,
    InfrastructureMetric,
    RawTelemetry,
    Server,
)
from infrasight.ingestion import repositories
from infrasight.ingestion.errors import SourceBusyError, SourceError, TransientSourceError
from infrasight.ingestion.loader import load_batch
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.sources.base import SourceBatch
from infrasight.ingestion.sources.host import HostMetricsSource
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.ingestion.sources.stored import StoredHostTelemetrySource

pytestmark = pytest.mark.integration
START = datetime(2026, 10, 11, 19, 30, tzinfo=UTC)
END = START + timedelta(minutes=2)


@pytest.fixture
def source_id():
    return "etl-test-" + uuid4().hex


@pytest.fixture
def pipeline(etl_engine, settings):
    return ETLPipeline(etl_engine, settings.model_copy(update={"etl_batch_size": 100}))


def simulator(source_id, count=75, malformed=0):
    return SimulatedCloudTelemetrySource(count, 7, 30, malformed, source_id)


def totals(engine, source_id):
    with engine.connect() as connection:
        return {
            "raw": connection.scalar(
                select(func.count())
                .select_from(RawTelemetry)
                .where(RawTelemetry.source_id == source_id)
            ),
            "metrics": connection.scalar(
                select(func.count())
                .select_from(InfrastructureMetric)
                .join(Server)
                .where(Server.source_id == source_id)
            ),
            "rejections": connection.scalar(
                select(func.count())
                .select_from(DataQualityRejection)
                .join(EtlRun)
                .where(EtlRun.source_id == source_id)
            ),
        }


def progress(engine, source_id):
    with engine.connect() as connection:
        return repositories.read_progress(connection, source_id)


class FixedSource:
    provider = "simulated"
    supports_history = True
    supports_cursor = False
    available_from = None

    def __init__(self, source_id, events):
        self.source_id, self.events = source_id, events

    def completed_until(self, now):
        return now

    def extract_batch(self, window, cursor, batch_size):
        events = [e for e in self.events if window.start <= e.canonical_observed_at < window.end]
        offset = cursor["offset"] if cursor else 0
        stop = min(len(events), offset + batch_size)
        return SourceBatch(tuple(events[offset:stop]), {"offset": stop}, stop == len(events))


def test_full_simulator_replay_and_incremental_counts(pipeline, etl_engine, source_id):
    source = simulator(source_id, malformed=0.01)
    first = pipeline.run_cycle(source, START, END)
    assert first.status == "SUCCEEDED"
    assert (
        first.counts.extracted,
        first.counts.accepted,
        first.counts.inserted,
        first.counts.duplicated,
        first.counts.rejected,
    ) == (300, 297, 297, 0, 3)
    assert totals(etl_engine, source_id) == {"raw": 300, "metrics": 297, "rejections": 3}
    second = pipeline.run_cycle(source, START, END)
    assert (second.counts.inserted, second.counts.duplicated, second.counts.rejected) == (0, 297, 3)
    assert totals(etl_engine, source_id) == {"raw": 300, "metrics": 297, "rejections": 6}
    third = pipeline.run_cycle(source, now=END + timedelta(seconds=60))
    assert third.window_start == END - timedelta(seconds=60)
    assert third.counts.extracted == 300
    assert third.counts.inserted > 0 and third.counts.duplicated > 0
    assert progress(etl_engine, source_id)["watermark"] == END + timedelta(seconds=60)
    assert totals(etl_engine, source_id)["raw"] == 450
    with etl_engine.connect() as connection:
        for result in (first, second, third):
            row = (
                connection.execute(select(EtlRun.__table__).where(EtlRun.id == result.run_id))
                .mappings()
                .one()
            )
            assert row["records_extracted"] == row["records_accepted"] + row["records_rejected"]
            assert row["records_accepted"] == row["records_inserted"] + row["records_duplicated"]


def test_invalid_timestamp_reaches_raw_and_rejections(pipeline, etl_engine, source_id):
    result = pipeline.run_cycle(simulator(source_id, malformed=0.1), START, END)
    assert result.status == "SUCCEEDED" and result.counts.rejected == 30
    with etl_engine.connect() as connection:
        rows = connection.execute(
            select(RawTelemetry.payload, DataQualityRejection.validation_errors)
            .join(DataQualityRejection)
            .where(DataQualityRejection.etl_run_id == result.run_id)
        ).all()
        malformed = [r for r in rows if r.payload.get("observed_at") == "invalid-timestamp"]
        assert malformed and all(
            any(e["field"] == "observed_at" for e in r.validation_errors) for r in malformed
        )


def test_duplicate_events_and_duplicate_observations(pipeline, etl_engine, source_id):
    event = simulator(source_id)._event(START, 30, 0)
    other_id = replace(event, source_event_id=event.source_event_id + ":different")
    source = FixedSource(source_id, [event, event, other_id])
    result = pipeline.run_cycle(source, START, END)
    assert (
        result.counts.extracted,
        result.counts.accepted,
        result.counts.inserted,
        result.counts.duplicated,
    ) == (3, 3, 1, 2)
    assert totals(etl_engine, source_id) == {"raw": 2, "metrics": 1, "rejections": 0}


def test_existing_raw_payload_is_authoritative(pipeline, etl_engine, source_id):
    event = simulator(source_id)._event(START, 30, 0)
    source = FixedSource(source_id, [event])
    assert pipeline.run_cycle(source, START, END).counts.inserted == 1
    changed = replace(event, payload={**event.payload, "cpu_usage_percent": "99.00"})
    replay = pipeline.run_cycle(FixedSource(source_id, [changed]), START, END)
    assert replay.counts.duplicated == 1
    with etl_engine.connect() as connection:
        raw = connection.scalar(
            select(RawTelemetry.payload).where(RawTelemetry.source_id == source_id)
        )
        assert raw["cpu_usage_percent"] == event.payload["cpu_usage_percent"]


def test_duplicate_invalid_events_count_attempts_without_duplicate_evidence(
    pipeline, etl_engine, source_id
):
    event = simulator(source_id)._event(START, 30, 0)
    bad = replace(event, payload={**event.payload, "cpu_usage_percent": "125"})
    result = pipeline.run_cycle(FixedSource(source_id, [bad, bad]), START, END)
    assert result.counts.extracted == result.counts.rejected == 2
    assert result.counts.inserted == result.counts.accepted == 0
    assert totals(etl_engine, source_id) == {"raw": 1, "metrics": 0, "rejections": 1}


def test_incremental_cycle_only_inserts_new_observations(etl_engine, settings, source_id):
    settings = settings.model_copy(
        update={"etl_initial_lookback_seconds": 60, "etl_overlap_seconds": 30}
    )
    pipeline = ETLPipeline(etl_engine, settings)
    source = simulator(source_id, count=2)
    first = pipeline.run_cycle(source, now=END)
    assert first.window_start == END - timedelta(seconds=60)
    second = pipeline.run_cycle(source, now=END + timedelta(seconds=30))
    assert (second.counts.inserted, second.counts.duplicated) == (2, 2)
    assert totals(etl_engine, source_id)["metrics"] == 6


def test_older_replay_preserves_inventory_and_watermark(pipeline, etl_engine, source_id):
    source = simulator(source_id, count=1)
    old = source._event(START, 30, 0)
    new = source._event(START + timedelta(seconds=60), 30, 0)
    new = replace(
        new, payload={**new.payload, "server_name": "current-name", "region_code": "us-east"}
    )
    old = replace(
        old, payload={**old.payload, "server_name": "old-name", "region_code": "us-south"}
    )
    fixed = FixedSource(source_id, [old, new])
    first = pipeline.run_cycle(fixed, START + timedelta(seconds=60), START + timedelta(seconds=90))
    replay = pipeline.run_cycle(fixed, START, START + timedelta(seconds=30))
    assert replay.watermark_after == first.watermark_after
    with etl_engine.connect() as connection:
        server = (
            connection.execute(select(Server.__table__).where(Server.source_id == source_id))
            .mappings()
            .one()
        )
        assert server["server_name"] == "current-name"
        assert server["first_seen_at"] == START
        assert server["last_seen_at"] == new.canonical_observed_at


class FailSecondBatch:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.source_id, self.provider = wrapped.source_id, wrapped.provider
        self.supports_history, self.supports_cursor = True, False
        self.available_from = None
        self.calls = 0

    def completed_until(self, now):
        return self.wrapped.completed_until(now)

    def extract_batch(self, window, cursor, batch_size):
        self.calls += 1
        if self.calls == 2:
            raise SourceError("secret must not enter error fields")
        return self.wrapped.extract_batch(window, cursor, batch_size)


def test_source_failure_preserves_prior_batch_and_does_not_advance(etl_engine, settings, source_id):
    settings = settings.model_copy(update={"etl_batch_size": 3})
    pipeline = ETLPipeline(etl_engine, settings)
    source = simulator(source_id, count=3)
    failed = pipeline.run_cycle(FailSecondBatch(source), START, START + timedelta(seconds=60))
    assert failed.status == "FAILED" and failed.counts.inserted == 3
    assert totals(etl_engine, source_id)["metrics"] == 3
    assert progress(etl_engine, source_id) is None
    retry = pipeline.run_cycle(source, START, START + timedelta(seconds=60))
    assert (retry.counts.inserted, retry.counts.duplicated) == (3, 3)
    with etl_engine.connect() as connection:
        message = connection.scalar(select(EtlRun.error_message).where(EtlRun.id == failed.run_id))
        assert "secret" not in message


def test_batch_write_and_counter_rollback(etl_engine, settings, source_id):
    calls = 0

    def failing_loader(*args):
        nonlocal calls
        calls += 1
        result = load_batch(*args)
        if calls == 2:
            raise OperationalError("injected", {}, Exception("secret"))
        return result

    pipeline = ETLPipeline(
        etl_engine, settings.model_copy(update={"etl_batch_size": 3}), loader=failing_loader
    )
    result = pipeline.run_cycle(simulator(source_id, count=3), START, START + timedelta(seconds=60))
    assert result.status == "FAILED" and result.error_code == "DATABASE_ERROR"
    assert result.counts.extracted == result.counts.inserted == 3
    assert totals(etl_engine, source_id) == {"raw": 3, "metrics": 3, "rejections": 0}
    assert progress(etl_engine, source_id) is None
    with repositories.source_lock(etl_engine, source_id, settings) as lock:
        lock.assert_held()


def test_finalization_failure_rolls_back_progress_and_success(
    etl_engine, settings, source_id, monkeypatch
):
    original = repositories.finalize_run

    def fail_after_writes(*args):
        original(*args)
        raise RuntimeError("injected finalization failure")

    monkeypatch.setattr(repositories, "finalize_run", fail_after_writes)
    result = ETLPipeline(etl_engine, settings).run_cycle(simulator(source_id, count=2), START, END)
    assert result.status == "FAILED" and result.counts.inserted == 8
    assert progress(etl_engine, source_id) is None
    with etl_engine.connect() as connection:
        assert (
            connection.scalar(select(EtlRun.status).where(EtlRun.id == result.run_id)) == "FAILED"
        )


def test_source_lock_is_held_after_batch_commits(etl_engine, settings, source_id):
    source = simulator(source_id, count=3)
    original = source.extract_batch
    observed = []

    def checking_source(window, cursor, size):
        with etl_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            same = connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": repositories.advisory_lock_key(source_id)},
            )
            assert same is False
            other_key = repositories.advisory_lock_key(source_id + "-other")
            assert connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": other_key})
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": other_key})
        observed.append(cursor)
        return original(window, cursor, size)

    source.extract_batch = checking_source
    pipeline = ETLPipeline(etl_engine, settings.model_copy(update={"etl_batch_size": 3}))
    assert pipeline.run_cycle(source, START, START + timedelta(seconds=60)).status == "SUCCEEDED"
    assert len(observed) == 2
    assert observed[1] == {"offset": 3, "window_end": "2026-10-11T19:31:00.000000+00:00"}


def test_busy_source_creates_no_run_and_other_sources_work(etl_engine, settings, source_id):
    pipeline = ETLPipeline(etl_engine, settings)
    with repositories.source_lock(etl_engine, source_id, settings) as lock:
        with pytest.raises(SourceBusyError):
            pipeline.run_cycle(simulator(source_id, count=1), START, END)
        assert (
            pipeline.run_cycle(simulator(source_id + "-other", count=1), START, END).status
            == "SUCCEEDED"
        )
        lock.assert_held()
    with etl_engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(EtlRun).where(EtlRun.source_id == source_id)
            )
            == 0
        )
    assert pipeline.run_cycle(simulator(source_id, count=1), START, END).status == "SUCCEEDED"


def test_invalid_window_releases_lock(etl_engine, settings, source_id):
    pipeline = ETLPipeline(etl_engine, settings)
    with pytest.raises(ValueError):
        pipeline.run_cycle(simulator(source_id, count=1), END, START)
    with repositories.source_lock(etl_engine, source_id, settings) as lock:
        lock.assert_held()


def test_transient_source_failure_retries_then_succeeds(etl_engine, settings, source_id):
    source = simulator(source_id, count=1)
    original = source.extract_batch
    attempts = 0

    def fetch(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientSourceError("temporary")
        return original(*args)

    source.extract_batch = fetch
    result = ETLPipeline(etl_engine, settings, sleeper=lambda _: None).run_cycle(source, START, END)
    assert result.status == "SUCCEEDED" and attempts == 2


def test_failed_incremental_run_keeps_existing_watermark(etl_engine, settings, source_id):
    source = simulator(source_id, count=3)
    pipeline = ETLPipeline(etl_engine, settings.model_copy(update={"etl_batch_size": 3}))
    first = pipeline.run_cycle(source, START, END)
    failed = pipeline.run_cycle(FailSecondBatch(source), now=END + timedelta(seconds=60))
    assert failed.status == "FAILED"
    assert progress(etl_engine, source_id)["watermark"] == first.watermark_after


def test_host_capture_and_stored_replay(etl_engine, settings, source_id):
    from types import SimpleNamespace
    from unittest.mock import Mock

    collector = Mock()
    collector.cpu_percent.return_value = 12.5
    collector.virtual_memory.return_value = SimpleNamespace(percent=50)
    collector.disk_usage.return_value = SimpleNamespace(percent=25)
    collector.net_io_counters.return_value = SimpleNamespace(bytes_sent=100, bytes_recv=100)
    collector.boot_time.return_value = START.timestamp() - 120
    ticks = iter([0, 1.2])
    host_settings = settings.model_copy(update={"host_source_id": source_id})
    source = HostMetricsSource(
        host_settings,
        collector,
        sleeper=lambda _: None,
        monotonic=lambda: next(ticks),
        clock=lambda: START,
    )
    source.capture()
    pipeline = ETLPipeline(etl_engine, host_settings)
    result = pipeline.run_cycle(source, now=START + timedelta(seconds=2))
    assert result.counts.inserted == 1
    replay = pipeline.run_cycle(
        StoredHostTelemetrySource(etl_engine, source_id), result.window_start, result.window_end
    )
    assert replay.counts.inserted == 0 and replay.counts.duplicated == 1
    assert totals(etl_engine, source_id)["metrics"] == 1


def test_post_commit_error_cannot_mark_success_failed(etl_engine, settings, source_id, monkeypatch):
    from infrasight.ingestion import pipeline as module

    original = module.logger.info

    def failing_log(event, **fields):
        if event == "etl_succeeded":
            raise RuntimeError("injected post-commit logging failure")
        return original(event, **fields)

    monkeypatch.setattr(module.logger, "info", failing_log)
    result = ETLPipeline(etl_engine, settings).run_cycle(simulator(source_id, count=1), START, END)
    assert result.status == "SUCCEEDED"
    assert progress(etl_engine, source_id)["watermark"] == END
    with etl_engine.connect() as connection:
        assert (
            connection.scalar(select(EtlRun.status).where(EtlRun.id == result.run_id))
            == "SUCCEEDED"
        )
