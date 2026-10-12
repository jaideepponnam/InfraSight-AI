import random
import time
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import SQLAlchemyError

from infrasight.ingestion import repositories
from infrasight.ingestion.errors import (
    SourceError,
    SourceLockLostError,
    TransientSourceError,
)
from infrasight.ingestion.loader import load_batch
from infrasight.ingestion.schemas import RunCounts, RunResult
from infrasight.ingestion.sources.base import ExtractionWindow

logger = structlog.get_logger(__name__)


class ETLPipeline:
    def __init__(
        self, engine, settings, loader=load_batch, sleeper=time.sleep, jitter=random.random
    ):
        self.engine, self.settings, self.loader = engine, settings, loader
        self.sleeper, self.jitter = sleeper, jitter

    def _fetch(self, source, window, cursor):
        for attempt in range(self.settings.etl_source_max_attempts):
            try:
                batch = source.extract_batch(window, cursor, self.settings.etl_batch_size)
                if len(batch.events) > self.settings.etl_batch_size:
                    raise SourceError("Source exceeded requested batch bound")
                if not batch.done and (not batch.events or batch.next_cursor == cursor):
                    raise SourceError("Source did not make extraction progress")
                for envelope in batch.events:
                    if (
                        not isinstance(envelope.source_event_id, str)
                        or not envelope.source_event_id.strip()
                    ):
                        raise SourceError("Envelope requires a stable event identity")
                    if envelope.canonical_observed_at.tzinfo is None:
                        raise SourceError("Envelope requires a timezone-aware canonical timestamp")
                return batch
            except TransientSourceError:
                if attempt + 1 == self.settings.etl_source_max_attempts:
                    raise
                delay = min(
                    self.settings.etl_retry_max_seconds,
                    self.settings.etl_retry_base_seconds * 2**attempt * (1 + self.jitter()),
                )
                logger.warning(
                    "source_retry",
                    source_id=source.source_id,
                    attempt=attempt + 1,
                    delay_seconds=delay,
                )
                self.sleeper(delay)

    def _window(self, source, progress, start, end, now):
        if (start is None) != (end is None):
            raise ValueError("Explicit runs require both start and end")
        if start is not None:
            window = ExtractionWindow(start, end)
            if not source.supports_history:
                raise ValueError(
                    "Live sources require a current cycle; use stored events for replay"
                )
            if (
                source.completed_until(window.start) != window.start
                or source.completed_until(window.end) != window.end
            ):
                raise ValueError("Explicit window boundaries must align to source intervals")
        else:
            cutoff = source.completed_until(now)
            watermark = progress["watermark"] if progress else None
            start = (
                watermark - timedelta(seconds=self.settings.etl_overlap_seconds)
                if watermark
                else cutoff - timedelta(seconds=self.settings.etl_initial_lookback_seconds)
            )
            if source.available_from is not None:
                start = max(start, source.available_from)
            if start >= cutoff:
                raise ValueError("No completed source interval is available")
            end = min(cutoff, start + timedelta(seconds=self.settings.etl_max_window_seconds))
            if source.supports_history:
                end = source.completed_until(end)
            window = ExtractionWindow(start, end)
        if (window.end - window.start).total_seconds() > self.settings.etl_max_window_seconds:
            raise ValueError("Extraction window exceeds configured maximum")
        if window.end > now:
            raise ValueError("Future extraction windows are not allowed")
        return window

    def run_cycle(self, source, start=None, end=None, now=None) -> RunResult:
        now = now or datetime.now(UTC)
        # No run is created before exclusive session-level ownership is acquired.
        with repositories.source_lock(self.engine, source.source_id, self.settings) as lock:
            with self.engine.begin() as connection:
                progress = repositories.read_progress(connection, source.source_id)
                window = self._window(source, progress, start, end, now)
                run_id = repositories.start_run(connection, source.source_id, window, progress)
                lock.assert_held()
            before = progress["watermark"] if progress else None
            counts = RunCounts()
            cursor = progress["cursor"] if source.supports_cursor and progress else None
            tokens = structlog.contextvars.bind_contextvars(
                etl_run_id=str(run_id), source_id=source.source_id
            )
            try:
                logger.info(
                    "etl_started",
                    window_start=window.start.isoformat(),
                    window_end=window.end.isoformat(),
                )
                while True:
                    lock.assert_held()
                    batch = self._fetch(source, window, cursor)
                    with self.engine.begin() as connection:
                        delta = self.loader(
                            connection,
                            run_id,
                            source.source_id,
                            source.provider,
                            window,
                            batch.events,
                        )
                        next_counts = counts.add(delta)
                        repositories.record_batch(connection, run_id, next_counts)
                        lock.assert_held()
                    counts = next_counts  # Only committed batch counts become authoritative.
                    cursor = batch.next_cursor
                    logger.info("etl_batch_committed", **delta.database_values())
                    if batch.done:
                        break
                with self.engine.begin() as connection:
                    after = repositories.finalize_run(
                        connection, run_id, source.source_id, window, progress, cursor, counts
                    )
                    lock.assert_held()
                logger.info(
                    "etl_succeeded", **counts.database_values(), watermark=after.isoformat()
                )
                return RunResult(
                    run_id,
                    source.source_id,
                    "SUCCEEDED",
                    window.start,
                    window.end,
                    counts,
                    before,
                    after,
                )
            except BaseException as exc:
                code = (
                    "SOURCE_UNAVAILABLE"
                    if isinstance(exc, TransientSourceError)
                    else "SOURCE_ERROR"
                    if isinstance(exc, SourceError)
                    else "SOURCE_LOCK_LOST"
                    if isinstance(exc, SourceLockLostError)
                    else "DATABASE_ERROR"
                    if isinstance(exc, SQLAlchemyError)
                    else "PIPELINE_ERROR"
                )
                logger.error(
                    "etl_failed",
                    error_code=code,
                    error_type=type(exc).__name__,
                    **counts.database_values(),
                )
                recovered = None
                try:
                    with self.engine.begin() as connection:
                        persisted = repositories.read_run(connection, run_id)
                        counts = RunCounts(
                            **{
                                field: persisted["records_" + field]
                                for field in counts.__dataclass_fields__
                            }
                        )
                        if persisted["status"] == "SUCCEEDED":
                            # A commit acknowledgement or later logging can fail after
                            # PostgreSQL committed. Never rewrite a completed run as FAILED.
                            recovered = RunResult(
                                run_id,
                                source.source_id,
                                "SUCCEEDED",
                                window.start,
                                window.end,
                                counts,
                                before,
                                persisted["watermark_after"],
                            )
                        else:
                            repositories.fail_run(connection, run_id, code, type(exc).__name__)
                except Exception as audit_exc:
                    logger.error(
                        "etl_failure_audit_unavailable", error_type=type(audit_exc).__name__
                    )
                if not isinstance(exc, Exception):
                    raise
                if recovered is not None:
                    return recovered
                return RunResult(
                    run_id,
                    source.source_id,
                    "FAILED",
                    window.start,
                    window.end,
                    counts,
                    before,
                    before,
                    code,
                )
            finally:
                structlog.contextvars.reset_contextvars(**tokens)
