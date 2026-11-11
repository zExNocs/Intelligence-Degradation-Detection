"""Interpret five-field Unix cron expressions in explicit IANA time zones."""

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import CroniterBadCronError, CroniterBadDateError, croniter

from ..domain.models import DomainError, timestamp


def next_occurrences(
    expression: str, timezone: str, count: int = 1, after: float | None = None
) -> list[float]:
    """Compute future occurrences while preserving Unix weekday semantics."""
    if len(expression.split()) != 5:
        raise DomainError("cron_invalid", "Use a five-field cron expression.")
    try:
        iterator = croniter(
            expression,
            datetime.fromtimestamp(
                after if after is not None else timestamp(), ZoneInfo(timezone)
            ),
            max_years_between_matches=5,
        )
        return [iterator.get_next(datetime).timestamp() for _ in range(count)]
    except (CroniterBadCronError, CroniterBadDateError, ValueError) as exc:
        raise DomainError(
            "cron_invalid",
            "The cron expression has no valid occurrence within five years.",
        ) from exc
