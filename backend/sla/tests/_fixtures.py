from datetime import datetime, timezone


def aware(year, month, day, hour=12, minute=0):
    """Convenience for tz-aware UTC datetime in tests."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
