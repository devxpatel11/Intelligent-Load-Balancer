"""Unit tests for the analyze tool."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from netbalance.analyze import read_attempts_from_csv


def test_read_attempts_from_csv() -> None:
    """Test reading attempts from a CSV file."""
    csv_content = """request_id,policy,scenario,repetition,started_offset_s,latency_ms,ok,backend_id,error_code
req-1,rr,default,1,0.005,25.5,true,s1,
req-2,rr,default,1,0.015,15.2,false,,OVERLOADED
req-3,rr,default,1,0.025,30.0,true,s2,
"""
    # Write to a temporary string buffer
    buf = io.StringIO()
    buf.write(csv_content)
    buf.seek(0)
    # We need to simulate a file. We'll use a temporary file.
    # But for simplicity, we can pass the string buffer to the function if we modify it to accept a file-like object.
    # However, our function expects a Path. Let's create a temporary file.
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        temp_path = Path(f.name)

    try:
        attempts = read_attempts_from_csv(temp_path)
        assert len(attempts) == 3
        # Check first attempt
        assert attempts[0].request_id == "req-1"
        assert attempts[0].policy == "rr"
        assert attempts[0].scenario == "default"
        assert attempts[0].repetition == 1
        assert attempts[0].started_offset_s == 0.005
        assert attempts[0].latency_ms == 25.5
        assert attempts[0].ok is True
        assert attempts[0].backend_id == "s1"
        assert attempts[0].error_code is None
        # Check second attempt
        assert attempts[1].request_id == "req-2"
        assert attempts[1].ok is False
        assert attempts[1].error_code == "OVERLOADED"
        assert attempts[1].backend_id is None
        # Check third attempt
        assert attempts[2].request_id == "req-3"
        assert attempts[2].ok is True
        assert attempts[2].backend_id == "s2"
        assert attempts[2].error_code is None
    finally:
        temp_path.unlink()


def test_read_attempts_from_csv_with_wrong_columns() -> None:
    """Test reading a CSV with wrong columns (should warn but still try to parse)."""
    csv_content = """request_id,policy,scenario,repetition,started_offset_s,latency_ms,ok,backend_id
req-1,rr,default,1,0.005,25.5,true,s1
"""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        temp_path = Path(f.name)

    try:
        # We expect a warning to be printed to stderr, but the function should still return the attempts.
        attempts = read_attempts_from_csv(temp_path)
        assert len(attempts) == 1
        assert attempts[0].request_id == "req-1"
    finally:
        temp_path.unlink()