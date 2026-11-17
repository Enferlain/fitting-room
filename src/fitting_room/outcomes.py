"""Trial outcomes: pass / fail / infrastructure error (spec: benchmark-runs).

A trial that broke for reasons outside the model (image build, sandbox start, endpoint
unreachable, auth, rate limits...) is an *infrastructure error*: it is excluded from
pass rate and listed separately. The boundary follows Harbor's own error policy table
(``has_valid_reward``), with one deliberate difference: exception types Harbor does not
know are treated as infrastructure errors, so a bug in one of our adapters can never be
scored as a model failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from harbor.models.trial.error_policy import ERROR_POLICIES


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INFRA_ERROR = "infra_error"


@dataclass(frozen=True)
class Outcome:
    status: Status
    reward: float | None
    exception_type: str | None = None
    exception_message: str | None = None


def _reward(result: dict) -> float | None:
    rewards = ((result.get("verifier_result") or {}).get("rewards")) or {}
    value = rewards.get("reward")
    if value is None and rewards:
        # Multiple labelled rewards: the trial passes only if all of them are full marks.
        values = [v for v in rewards.values() if isinstance(v, int | float)]
        value = min(values) if values else None
    return float(value) if value is not None else None


def is_infrastructure_exception(exception_type: str) -> bool:
    policy = ERROR_POLICIES.get(exception_type)
    return policy is None or not policy.has_valid_reward


def classify(result: dict) -> Outcome:
    """Classify one Harbor trial result (the parsed result.json)."""
    exc = result.get("exception_info") or None
    exc_type = exc.get("exception_type") if exc else None
    exc_msg = exc.get("exception_message") if exc else None
    reward = _reward(result)

    if exc_type and is_infrastructure_exception(exc_type):
        return Outcome(Status.INFRA_ERROR, None, exc_type, exc_msg)
    if result.get("reward_valid") is False and not exc_type:
        return Outcome(Status.INFRA_ERROR, None, None, "reward marked invalid by Harbor")
    if reward is None:
        # A finished trial with no reward at all is a harness/verifier problem, not a score.
        return Outcome(Status.INFRA_ERROR, None, exc_type, exc_msg or "no reward recorded")
    status = Status.PASS if reward >= 1.0 else Status.FAIL
    return Outcome(status, reward, exc_type, exc_msg)


def classify_trial_dir(trial_dir: Path) -> Outcome:
    return classify(json.loads((trial_dir / "result.json").read_text()))


@dataclass(frozen=True)
class Tally:
    passed: int
    failed: int
    infra_errors: int

    @property
    def scored(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float | None:
        """Pass rate over scored trials only; infrastructure errors are excluded."""
        return self.passed / self.scored if self.scored else None


def tally(outcomes: list[Outcome]) -> Tally:
    return Tally(
        passed=sum(o.status is Status.PASS for o in outcomes),
        failed=sum(o.status is Status.FAIL for o in outcomes),
        infra_errors=sum(o.status is Status.INFRA_ERROR for o in outcomes),
    )
