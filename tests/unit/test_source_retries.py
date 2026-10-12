import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from infrasight.ingestion.errors import SourceError, TransientSourceError
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.repositories import advisory_lock_key
from infrasight.ingestion.sources.base import ExtractionWindow, SourceBatch


def test_advisory_key_is_stable_across_processes():
    code = (
        "from infrasight.ingestion.repositories import advisory_lock_key; "
        "print(advisory_lock_key('simulated-cloud'))"
    )
    expected = str(advisory_lock_key("simulated-cloud"))
    for seed in ("1", "123"):
        output = subprocess.check_output(
            [sys.executable, "-c", code], text=True, env={**os.environ, "PYTHONHASHSEED": seed}
        )
        assert output.strip() == expected
    assert advisory_lock_key("host-local") != advisory_lock_key("simulated-cloud")
    assert -(2**63) <= int(expected) < 2**63


def test_transient_retry_reuses_cursor_and_is_bounded(settings):
    source = Mock(source_id="test-source")
    source.extract_batch.side_effect = [
        TransientSourceError(),
        TransientSourceError(),
        SourceBatch((), {"offset": 0}, True),
    ]
    sleeps = []
    pipeline = ETLPipeline(None, settings, sleeper=sleeps.append, jitter=lambda: 0)
    start = datetime(2026, 10, 11, tzinfo=UTC)
    window = ExtractionWindow(start, start + timedelta(seconds=30))
    cursor = {"opaque": "token"}
    assert pipeline._fetch(source, window, cursor).done
    assert len(sleeps) == 2
    assert all(call.args[1] == cursor for call in source.extract_batch.call_args_list)
    source.extract_batch.side_effect = TransientSourceError()
    source.extract_batch.reset_mock()
    with pytest.raises(TransientSourceError):
        pipeline._fetch(source, window, cursor)
    assert source.extract_batch.call_count == settings.etl_source_max_attempts


def test_permanent_failure_is_not_retried(settings):
    source = Mock(source_id="test-source")
    source.extract_batch.side_effect = SourceError()
    pipeline = ETLPipeline(None, settings, sleeper=lambda _: pytest.fail("Unexpected retry"))
    start = datetime(2026, 10, 11, tzinfo=UTC)
    with pytest.raises(SourceError):
        pipeline._fetch(source, ExtractionWindow(start, start + timedelta(seconds=30)), None)
    assert source.extract_batch.call_count == 1
