"""Compare structured answers and bounded regular expressions independently."""

import json
import math
from decimal import Decimal

import regex
from pydantic import JsonValue

from .models import Difference, DomainError, Judgment


def unwrap_fence(text: str, language: str = "json") -> str:
    """Remove only a single complete Markdown fence surrounding an artifact."""
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].lower() in {"```", f"```{language}"}:
        if lines[-1] == "```" and not any(x.startswith("```") for x in lines[1:-1]):
            return "\n".join(lines[1:-1])
    return stripped


def parse_json(text: str) -> JsonValue:
    """Parse strict JSON, rejecting duplicate keys and non-finite numbers."""

    def unique(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}")

    def finite(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("JSON number exceeds the finite numeric range.")
        return number

    return json.loads(
        unwrap_fence(text),
        object_pairs_hook=unique,
        parse_constant=reject,
        parse_float=finite,
    )


def leaf_count(value: JsonValue) -> int:
    """Count scalar leaves and empty containers as comparable units."""
    if isinstance(value, dict):
        return sum(leaf_count(v) for v in value.values()) or 1
    if isinstance(value, list):
        return sum(leaf_count(v) for v in value) or 1
    return 1


def compare_json(expected: JsonValue, actual: JsonValue) -> Judgment:
    """Score corresponding leaves while preserving types and array positions."""
    differences: list[Difference] = []

    def mismatch(path: str, reason: str, left: JsonValue, right: JsonValue) -> None:
        differences.append(
            Difference(path=path, reason=reason, expected=left, actual=right)
        )

    def walk(left: JsonValue, right: JsonValue, path: str) -> tuple[int, int]:
        if isinstance(left, dict) and isinstance(right, dict):
            if not left and not right:
                return 1, 1
            matched = total = 0
            for key in sorted(left.keys() | right.keys()):
                child = f"{path}[{json.dumps(key, ensure_ascii=False)}]"
                if key not in right:
                    total += leaf_count(left[key])
                    mismatch(child, "missing", left[key], None)
                elif key not in left:
                    total += leaf_count(right[key])
                    mismatch(child, "extra", None, right[key])
                else:
                    good, count = walk(left[key], right[key], child)
                    matched += good
                    total += count
            return matched, total
        if isinstance(left, list) and isinstance(right, list):
            if not left and not right:
                return 1, 1
            matched = total = 0
            for index in range(max(len(left), len(right))):
                child = f"{path}[{index}]"
                if index >= len(right):
                    total += leaf_count(left[index])
                    mismatch(child, "missing", left[index], None)
                elif index >= len(left):
                    total += leaf_count(right[index])
                    mismatch(child, "extra", None, right[index])
                else:
                    good, count = walk(left[index], right[index], child)
                    matched += good
                    total += count
            return matched, total
        numeric = type(left) in (int, float) and type(right) in (int, float)
        equal = (
            Decimal(str(left)) == Decimal(str(right))
            if numeric
            else type(left) is type(right) and left == right
        )
        count = max(leaf_count(left), leaf_count(right))
        if not equal:
            mismatch(
                path, "value" if type(left) is type(right) else "type", left, right
            )
        return (count if equal else 0), count

    matched, total = walk(expected, actual, "$")
    return Judgment(
        verdict="pass" if matched == total else "fail",
        score=matched / total,
        matched=matched,
        total=total,
        differences=differences,
    )


def validate_regex(pattern: str) -> None:
    """Reject invalid expressions before saving a recipe."""
    if not pattern:
        raise DomainError("regex_invalid", "A regular expression is required.")
    try:
        regex.compile(pattern)
    except regex.error as exc:
        raise DomainError("regex_invalid", f"Invalid expression: {exc.msg}") from exc


def score_regex(pattern: str, output: str, timeout: float = 0.05) -> Judgment:
    """Return a binary match or a separate bounded-execution error."""
    validate_regex(pattern)
    try:
        passed = regex.search(pattern, output, timeout=timeout) is not None
    except TimeoutError:
        return Judgment(
            verdict="evaluation_error", analysis={"reason": "regex_timeout"}
        )
    return Judgment(
        verdict="pass" if passed else "fail",
        score=float(passed),
        matched=int(passed),
        total=1,
    )
