from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from app.core.base_client import BaseClient


def test_parse_retry_after_delta_seconds():
    assert BaseClient._parse_retry_after("5") == 5.0
    assert BaseClient._parse_retry_after("0") == 0.0
    assert BaseClient._parse_retry_after("  12  ") == 12.0


def test_parse_retry_after_absent_or_garbage():
    assert BaseClient._parse_retry_after(None) is None
    assert BaseClient._parse_retry_after("") is None
    assert BaseClient._parse_retry_after("soon") is None


def test_parse_retry_after_http_date_future():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    val = BaseClient._parse_retry_after(format_datetime(future))
    assert val is not None
    assert 20.0 <= val <= 31.0


def test_parse_retry_after_http_date_in_past_is_clamped_to_zero():
    assert BaseClient._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
