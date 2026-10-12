import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import Connection, Engine, create_engine, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.pool import NullPool

from infrasight.db.models import EtlRun, IngestionState
from infrasight.ingestion.errors import SourceBusyError, SourceLockLostError
from infrasight.ingestion.schemas import RunCounts
from infrasight.ingestion.sources.base import ExtractionWindow

logger = structlog.get_logger(__name__)


def advisory_lock_key(source_id: str) -> int:
    digest = hashlib.blake2b(("InfraSight-AI:source:" + source_id).encode(), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@dataclass
class SourceLock:
    connection: Connection
    key: int
    backend_pid: int

    def assert_held(self):
        if self.connection.closed or self.connection.invalidated:
            raise SourceLockLostError("Dedicated lock connection is unavailable")
        owned = self.connection.scalar(
            text(
                "SELECT pg_backend_pid() = :pid AND EXISTS (SELECT 1 FROM pg_locks "
                "WHERE pid = pg_backend_pid() AND locktype = 'advisory' AND granted "
                "AND objsubid = 1 AND classid::bigint = :high AND objid::bigint = :low)"
            ),
            {
                "pid": self.backend_pid,
                "high": (self.key >> 32) & 0xFFFFFFFF,
                "low": self.key & 0xFFFFFFFF,
            },
        )
        if not owned:
            raise SourceLockLostError("Source advisory lock ownership was lost")


@contextmanager
def source_lock(engine: Engine, source_id: str, settings):
    # A physically dedicated session: it never returns a locked session to a shared pool.
    lock_engine = create_engine(
        engine.url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
    )
    connection = None
    acquired = False
    key = advisory_lock_key(source_id)
    try:
        connection = lock_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        acquired = bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))
        if not acquired:
            raise SourceBusyError(f"Source {source_id} already has an active cycle")
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
        logger.info("source_lock_acquired", source_id=source_id)
        yield SourceLock(connection, key, pid)
    finally:
        if acquired and connection is not None:
            try:
                if not connection.invalidated:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            except Exception as exc:
                logger.warning(
                    "source_lock_release_failed", source_id=source_id, error_type=type(exc).__name__
                )
                connection.invalidate()
        if connection is not None:
            connection.close()  # NullPool physically closes the session on every exit path.
        lock_engine.dispose()


def read_progress(connection, source_id):
    return (
        connection.execute(
            select(IngestionState.__table__).where(IngestionState.source_id == source_id)
        )
        .mappings()
        .one_or_none()
    )


def start_run(connection, source_id, window: ExtractionWindow, progress):
    run_id = connection.scalar(
        insert(EtlRun)
        .values(
            source_id=source_id,
            status="QUEUED",
            requested_window_start=window.start,
            requested_window_end=window.end,
            cursor_before=progress["cursor"] if progress else None,
            watermark_before=progress["watermark"] if progress else None,
        )
        .returning(EtlRun.id)
    )
    connection.execute(
        update(EtlRun)
        .where(EtlRun.id == run_id)
        .values(status="RUNNING", started_at=datetime.now(UTC), heartbeat_at=datetime.now(UTC))
    )
    return run_id


def record_batch(connection, run_id, counts: RunCounts):
    connection.execute(
        update(EtlRun)
        .where(EtlRun.id == run_id)
        .values(**counts.database_values(), heartbeat_at=datetime.now(UTC))
    )


def finalize_run(connection, run_id, source_id, window, progress, cursor, counts):
    before = progress["watermark"] if progress else None
    advances = before is None or window.end > before
    watermark = window.end if advances else before
    committed_cursor = cursor if advances else progress["cursor"]
    statement = pg_insert(IngestionState).values(
        source_id=source_id,
        watermark=watermark,
        cursor=committed_cursor,
        last_successful_run_id=run_id,
        updated_at=datetime.now(UTC),
    )
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[IngestionState.source_id],
            set_={
                "watermark": watermark,
                "cursor": committed_cursor,
                "last_successful_run_id": run_id,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    connection.execute(
        update(EtlRun)
        .where(EtlRun.id == run_id)
        .values(
            status="SUCCEEDED",
            finished_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
            watermark_after=watermark,
            cursor_after=committed_cursor,
            **counts.database_values(),
        )
    )
    return watermark


def read_run(connection, run_id):
    return connection.execute(select(EtlRun.__table__).where(EtlRun.id == run_id)).mappings().one()


def fail_run(connection, run_id, code, error_type):
    connection.execute(
        update(EtlRun)
        .where(EtlRun.id == run_id, EtlRun.status == "RUNNING")
        .values(
            status="FAILED",
            finished_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
            error_code=code,
            error_message="ETL cycle failed; inspect correlated structured logs",
            error_details={"error_type": error_type},
        )
    )
