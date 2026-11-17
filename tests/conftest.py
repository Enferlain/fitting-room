import pytest


@pytest.fixture(autouse=True)
def no_network_quota_check(monkeypatch):
    """Never hit the real z.ai quota endpoint from tests."""
    from fitting_room.miner import classify

    monkeypatch.setattr(classify, "quota_percent", lambda timeout=30: 0)
