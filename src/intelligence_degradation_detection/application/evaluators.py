"""Select independent evaluation strategies through a small explicit registry."""

from typing import Protocol

from ..domain.models import Call, GroupInput, Judgment, Kind
from ..domain.scoring import compare_json, parse_json, score_regex


class Evaluator(Protocol):
    """Evaluate completed calls without sending additional model requests."""

    def evaluate(self, recipe: GroupInput, calls: list[Call]) -> Judgment:
        """Return evidence and a verdict for one frozen recipe."""
        ...


class ComparisonEvaluator:
    """Apply structured or binary comparison rules to one response."""

    def evaluate(self, recipe: GroupInput, calls: list[Call]) -> Judgment:
        """Preserve a malformed answer as a format failure, not an API failure."""
        text = calls[0].output.text
        if recipe.comparison_mode == "regex":
            return score_regex(recipe.regex_pattern, text)
        expected = parse_json(recipe.expected_json)
        try:
            actual = parse_json(text)
        except (ValueError, RecursionError):
            return Judgment(verdict="format_error", score=0, total=1)
        return compare_json(expected, actual)


class HumanEvaluator:
    """Leave visual and free-form evaluations for explicit human review."""

    def evaluate(self, recipe: GroupInput, calls: list[Call]) -> Judgment:
        """Avoid inventing an automatic quality score for subjective output."""
        return Judgment()


def evaluation_registry(modeltrace: Evaluator) -> dict[Kind, Evaluator]:
    """Compose the finite set of detectors once during application startup."""
    return {
        Kind.COMPARISON: ComparisonEvaluator(),
        Kind.PELICAN: HumanEvaluator(),
        Kind.OTHER: HumanEvaluator(),
        Kind.MODELTRACE: modeltrace,
    }
