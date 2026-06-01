"""Planned-work tunables (Sprint 11B Batch 2).

Both values are conservative defaults that 11A deliberately left
un-pinned to a hard number; they live here so the Celery task, the
management command, and the lifecycle helpers share one source.
"""

# How far ahead the daily generator materializes occurrences (and spawns
# their operational tickets). 14 days = two weeks of look-ahead.
DEFAULT_GENERATION_DAYS_AHEAD = 14

# Hard ceiling on the per-request `generate` action horizon. Bounds the
# number of occurrences + operational tickets a single API call can
# materialize (the management command / Celery task use the default).
MAX_GENERATION_DAYS_AHEAD = 365

# An occurrence is MISSED once `planned_date + grace < today`. The
# one-day grace tolerates same-day-late completion without flipping a
# still-actionable occurrence to MISSED.
DEFAULT_MISSED_GRACE_DAYS = 1
