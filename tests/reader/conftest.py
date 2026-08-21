import pytest

from nanonerd.reader import pipeline


@pytest.fixture(autouse=True)
def no_live_anthropic_client(monkeypatch):
    """Keep the fidelity judge off the network: it never gets a real client."""
    monkeypatch.setattr(pipeline, "fidelity_client", lambda: None)
