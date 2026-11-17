from fitting_room.outcomes import Status, classify, tally


def result(reward=None, exc_type=None, msg="", reward_valid=True):
    r = {"reward_valid": reward_valid, "exception_info": None, "verifier_result": None}
    if reward is not None:
        r["verifier_result"] = {"rewards": {"reward": reward}}
    if exc_type:
        r["exception_info"] = {"exception_type": exc_type, "exception_message": msg}
    return r


def test_pass_and_fail():
    assert classify(result(1.0)).status is Status.PASS
    assert classify(result(0.0)).status is Status.FAIL


def test_unreachable_endpoint_is_infrastructure_error_and_excluded_from_pass_rate():
    # What Harbor records when the agent cannot reach its model endpoint for the whole trial.
    unreachable = result(
        exc_type="NetworkConnectionError",
        msg="Connection refused: http://host.docker.internal:18080/v1",
        reward_valid=False,
    )
    outcomes = [classify(result(1.0)), classify(result(0.0)), classify(unreachable)]
    assert outcomes[2].status is Status.INFRA_ERROR
    t = tally(outcomes)
    assert (t.passed, t.failed, t.infra_errors) == (1, 1, 1)
    assert t.pass_rate == 0.5  # not 1/3


def test_setup_failures_are_infrastructure_errors():
    for exc in ("SandboxBuildFailedError", "EnvironmentStartTimeoutError", "ApiRateLimitError"):
        assert classify(result(exc_type=exc)).status is Status.INFRA_ERROR


def test_agent_timeout_counts_as_model_failure():
    out = classify(result(0.0, exc_type="AgentTimeoutError"))
    assert out.status is Status.FAIL and out.exception_type == "AgentTimeoutError"


def test_unknown_exception_type_is_infrastructure_error():
    assert classify(result(0.0, exc_type="KeyError")).status is Status.INFRA_ERROR


def test_missing_reward_is_infrastructure_error():
    assert classify(result()).status is Status.INFRA_ERROR


def test_multiple_rewards_pass_only_if_all_full():
    r = {"verifier_result": {"rewards": {"a": 1.0, "b": 0.5}}}
    assert classify(r).status is Status.FAIL
    assert classify({"verifier_result": {"rewards": {"a": 1, "b": 1}}}).status is Status.PASS


def test_pass_rate_none_when_nothing_scored():
    assert tally([classify(result(exc_type="SandboxBuildFailedError"))]).pass_rate is None
