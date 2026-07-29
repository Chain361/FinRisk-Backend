"""Shared pytest lifecycle cleanup."""

import pytest

from src.database import _pool


@pytest.fixture(scope="session", autouse=True)
def close_database_pool():
    """Stop psycopg pool workers before pytest terminates the interpreter."""
    yield
    _pool.close(timeout=30)
