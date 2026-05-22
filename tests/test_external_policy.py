"""Tests for external call retry / rate-limit helpers."""

from __future__ import annotations

import pytest

from src.services.external_policy import _get_retry_after_seconds, is_quota_exhausted


def test_is_quota_exhausted_gemini_free_tier_message() -> None:
    exc = Exception(
        "429 RESOURCE_EXHAUSTED. quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_free_tier_requests"
    )
    assert is_quota_exhausted(exc) is True


def test_is_quota_exhausted_transient_429() -> None:
    exc = Exception("429 Too Many Requests")
    assert is_quota_exhausted(exc) is False


def test_get_retry_after_parses_gemini_retry_in_seconds() -> None:
    exc = Exception("Please retry in 52.955958285s.")
    assert _get_retry_after_seconds(exc) == pytest.approx(52.955958285)
