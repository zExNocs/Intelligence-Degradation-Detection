"""Validate the pinned fingerprint contract across actual accepted output counts."""

import pytest

from intelligence_degradation_detection.adapters.modeltrace import ModelTraceEvaluator
from intelligence_degradation_detection.domain.models import (
    Call,
    GroupInput,
    Kind,
    Output,
    Status,
    TargetInput,
)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_selected_count_uses_corresponding_calibration(
    fingerprint: ModelTraceEvaluator, count: int
) -> None:
    """Each selected challenge is used once with its matching calibrated query count."""
    selected = fingerprint.challenges[:count]
    recipe = GroupInput(
        name="Calibration",
        kind=Kind.MODELTRACE,
        challenge_ids=[item.id for item in selected],
        expected_identity="gpt",
        targets=[TargetInput(account_id="fixture", model="fixture-model")],
    )
    calls = [
        Call(
            run_id="fixture",
            account_id="fixture",
            prompt=item.prompt,
            challenge_id=item.id,
            expected_count=item.expected_count,
            status=Status.COMPLETED,
            output=Output(
                text=" ".join(str(1 + i % 355) for i in range(item.expected_count))
            ),
        )
        for item in selected
    ]
    result = fingerprint.evaluate(recipe, calls)
    assert result.analysis["used_outputs"] == count
    assert result.analysis["calibration"]["queries"] == str(count)
    assert result.verdict in {"consistent", "suspected_mismatch"}
    assert len(result.analysis["results"]) == len(fingerprint.models) == 18
    calls[-1].status = Status.FAILED
    incomplete = fingerprint.evaluate(recipe, calls)
    assert incomplete.verdict == "incomplete"


def test_fixed_challenges_and_unusable_outputs(
    fingerprint: ModelTraceEvaluator,
) -> None:
    """Do not produce identity alerts from refusals or empty responses."""
    assert [item.expected_count for item in fingerprint.challenges] == [294, 311, 329]
    recipe = GroupInput(
        name="Refusal",
        kind=Kind.MODELTRACE,
        challenge_ids=[fingerprint.challenges[0].id],
        expected_identity="gpt",
        targets=[TargetInput(account_id="fixture", model="fixture-model")],
    )
    result = fingerprint.evaluate(
        recipe,
        [
            Call(
                run_id="fixture",
                account_id="fixture",
                prompt="fixed",
                status=Status.COMPLETED,
                output=Output(text="I cannot provide that."),
            )
        ],
    )
    assert result.verdict == "incomplete"
