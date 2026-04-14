"""Unit test configuration — override DB fixtures to be no-ops."""

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """No-op: unit tests don't need an event loop."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """No-op: unit tests don't need a database."""
    yield
