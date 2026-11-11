"""Exercise meaningful structured comparison and regex boundary cases."""

import pytest

from intelligence_degradation_detection.domain.models import DomainError
from intelligence_degradation_detection.domain.scoring import (
    compare_json,
    parse_json,
    score_regex,
    unwrap_fence,
)


@pytest.mark.parametrize(
    "expected,actual,score",
    [
        ({"a": 1, "b": [2, 3]}, {"b": [2, 3], "a": 1}, 1),
        ([1, 2], [2, 1], 0),
        ({"a": 1, "b": 2}, {"a": 1}, 0.5),
        ({"a": 1}, {"a": 1, "b": 2}, 0.5),
        ({"x": {"a": 1, "b": 2}}, {"x": []}, 0),
        ({}, {}, 1),
        ([], [], 1),
        ({}, [], 0),
        (True, 1, 0),
        (1, 1.0, 1),
        ("1", 1, 0),
        ({"x": [1, 2, 3]}, {"x": [1, 5, 3]}, 2 / 3),
    ],
)
def test_structured_score(expected, actual, score: float) -> None:
    """Preserve order and type semantics while awarding partial leaf credit."""
    result = compare_json(expected, actual)
    assert result.score == pytest.approx(score)
    assert bool(result.differences) is (score != 1)


@pytest.mark.parametrize(
    "text",
    [
        '{"a":1,"a":2}',
        "[NaN]",
        "[Infinity]",
        "[1e999]",
        'Some explanation {"a":1}',
        "```json\n{}\n```\ntrailing",
    ],
)
def test_invalid_json_is_not_guessed(text: str) -> None:
    """Reject malformed or ambiguous answers rather than extracting a lucky substring."""
    with pytest.raises(ValueError):
        parse_json(text)


def test_complete_fence_only() -> None:
    """Accept a whole fenced answer and preserve embedded fence-like content."""
    assert parse_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert unwrap_fence("before\n```json\n{}\n```").startswith("before")


def test_regex_binary_validation_and_timeout() -> None:
    """Distinguish a mismatch from invalid or computationally excessive regex rules."""
    assert score_regex(r"^OK$", "OK").score == 1
    assert score_regex(r"^OK$", "NO").score == 0
    with pytest.raises(DomainError, match="Invalid expression"):
        score_regex("[", "anything")
    assert (
        score_regex(r"(a|aa)+$", "a" * 10000 + "!", timeout=0.001).verdict
        == "evaluation_error"
    )
