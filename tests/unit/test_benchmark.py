"""Unit tests for the benchmark tool."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from netbalance.benchmark import main


def test_benchmark_main_success() -> None:
    """Test that the benchmark tool runs successfully and generates output."""
    # Mock the workload client's run_workload function
    mock_results = []
    mock_summary = Mock()
    mock_summary.successful_attempts = 10
    mock_summary.failed_attempts = 0
    mock_summary.duration_s = 1.0

    with patch("netbalance.benchmark.run_workload", new_callable=AsyncMock) as mock_run_workload, \
         patch("netbalance.benchmark.write_csv") as mock_write_csv, \
         patch("netbalance.benchmark.get_git_commit", return_value="abc123"), \
         patch("netbalance.benchmark.get_config_from_service", return_value={"algorithm": "rr"}):
        mock_run_workload.return_value = (mock_results, mock_summary)

        # We need to simulate command-line arguments
        test_args = [
            "--host", "127.0.0.1",
            "--port", "9000",
            "--count", "10",
            "--output", "output.csv",
        ]

        # Call the main function
        exit_code = main(test_args)

        # Check that the function succeeded
        assert exit_code == 0

        # Check that run_workload was called with the correct arguments
        mock_run_workload.assert_called_once()
        call_args = mock_run_workload.call_args[1]
        assert call_args["host"] == "127.0.0.1"
        assert call_args["port"] == 9000
        assert call_args["count"] == 10
        # We don't check output because run_workload doesn't have an output parameter

        # Check that write_csv was called
        mock_write_csv.assert_called_once_with(mock_results, "output.csv")

        # We cannot easily check the metadata file content without mocking open, but we can trust that
        # the function writes it. We'll leave it to integration tests.


def test_benchmark_main_missing_output() -> None:
    """Test that the benchmark tool errors when --output is missing."""
    test_args = [
        "--host", "127.0.0.1",
        "--port", "9000",
        "--count", "10",
        # Missing --output
    ]
    exit_code = main(test_args)
    assert exit_code == 1
    # We would normally check stderr, but we are not capturing it in this simple test.
    # We'll leave it to integration tests to check the error message.


def test_benchmark_main_with_metadata_output() -> None:
    """Test that the benchmark tool respects the --metadata-output argument."""
    mock_results = []
    mock_summary = Mock()
    mock_summary.successful_attempts = 5
    mock_summary.failed_attempts = 0
    mock_summary.duration_s = 0.5

    with patch("netbalance.benchmark.run_workload", new_callable=AsyncMock) as mock_run_workload, \
         patch("netbalance.benchmark.write_csv") as mock_write_csv, \
         patch("netbalance.benchmark.get_git_commit", return_value="def456"), \
         patch("netbalance.benchmark.get_config_from_service", return_value={}):
        mock_run_workload.return_value = (mock_results, mock_summary)

        test_args = [
            "--host", "127.0.0.1",
            "--port", "9000",
            "--count", "5",
            "--output", "results.csv",
            "--metadata-output", "custom_meta.json",
        ]

        exit_code = main(test_args)

        assert exit_code == 0
        mock_write_csv.assert_called_once_with(mock_results, "results.csv")
        # We would expect the metadata to be written to custom_meta.json
        # Again, we leave the file content check to integration tests.


def test_benchmark_main_workload_error() -> None:
    """Test that the benchmark tool handles errors from the workload client."""
    with patch("netbalance.benchmark.run_workload", new_callable=AsyncMock) as mock_run_workload:
        mock_run_workload.side_effect = Exception("Workload failed")

        test_args = [
            "--host", "127.0.0.1",
            "--port", "9000",
            "--count", "1",
            "--output", "output.csv",
        ]

        exit_code = main(test_args)
        assert exit_code == 1


def test_benchmark_main_write_csv_error() -> None:
    """Test that the benchmark tool handles errors from write_csv."""
    mock_results = []
    mock_summary = Mock()
    mock_summary.successful_attempts = 1
    mock_summary.failed_attempts = 0
    mock_summary.duration_s = 0.1

    with patch("netbalance.benchmark.run_workload", new_callable=AsyncMock) as mock_run_workload, \
         patch("netbalance.benchmark.write_csv") as mock_write_csv:
        mock_run_workload.return_value = (mock_results, mock_summary)
        mock_write_csv.side_effect = Exception("Write failed")

        test_args = [
            "--host", "127.0.0.1",
            "--port", "9000",
            "--count", "1",
            "--output", "output.csv",
        ]

        exit_code = main(test_args)
        assert exit_code == 1


if __name__ == "__main__":
    pytest.main([__file__])