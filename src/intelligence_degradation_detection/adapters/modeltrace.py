"""Isolate the pinned third-party inference core from host application APIs."""

import hashlib
import json
from importlib.resources import files

from modeltrace_vendor.fingerprint import analyze_global_outputs
from pydantic import JsonValue, TypeAdapter

from ..domain.models import Call, Challenge, DomainError, GroupInput, Judgment, Status


class ModelTraceEvaluator:
    """Load a verified bank and invoke inference without upstream networking."""

    def __init__(self) -> None:
        """Verify frozen artifacts before accepting any fingerprint task."""
        package = files("modeltrace_vendor")
        manifest = json.loads(
            package.joinpath("UPSTREAM.json").read_text(encoding="utf-8")
        )
        for path, digest in manifest["sha256"].items():
            if (
                hashlib.sha256(package.joinpath(path).read_bytes()).hexdigest()
                != digest
            ):
                raise RuntimeError(
                    "The pinned ModelTrace snapshot failed integrity verification."
                )
        self.version: str = manifest["sha256"]["data/unified_bank.json"]
        self.bank = json.loads(
            package.joinpath("data/unified_bank.json").read_text(encoding="utf-8")
        )
        self.challenges = TypeAdapter(list[Challenge]).validate_json(
            package.joinpath("data/challenges.json").read_bytes()
        )
        self.models: list[dict[str, str]] = [
            {"id": item["id"], "family": item["family"]} for item in self.bank["models"]
        ]

    def selected(self, identities: list[str]) -> list[Challenge]:
        """Resolve unique selected challenge identities or reject the recipe."""
        if not identities or len(set(identities)) != len(identities):
            raise DomainError(
                "challenge_invalid", "Select one to three unique challenges."
            )
        by_id = {item.id: item for item in self.challenges}
        if any(identity not in by_id for identity in identities):
            raise DomainError(
                "challenge_invalid", "An unknown fingerprint challenge was selected."
            )
        return [by_id[identity] for identity in identities]

    def evaluate(self, recipe: GroupInput, calls: list[Call]) -> Judgment:
        """Use actual accepted output count and suppress incomplete identity alerts."""
        usable = [
            {"text": call.output.text, "expected_count": call.expected_count}
            for call in calls
            if call.status == Status.COMPLETED
        ]
        try:
            raw = analyze_global_outputs(usable, self.bank)
        except ValueError:
            return Judgment(
                verdict="incomplete",
                analysis={
                    "reason": "no_valid_fingerprint_output",
                    "bank_version": self.version,
                },
            )
        analysis = TypeAdapter(dict[str, JsonValue]).validate_python(raw)
        analysis["bank_version"] = self.version
        complete = raw["used_outputs"] == len(recipe.challenge_ids) and len(
            usable
        ) == len(recipe.challenge_ids)
        verdict = "reference"
        if not complete:
            verdict = "incomplete"
        elif recipe.expected_identity:
            matched = (
                raw["prediction"] == recipe.expected_identity
                or raw["family_prediction"] == recipe.expected_identity
            )
            verdict = "consistent" if matched else "suspected_mismatch"
        return Judgment(verdict=verdict, analysis=analysis)
