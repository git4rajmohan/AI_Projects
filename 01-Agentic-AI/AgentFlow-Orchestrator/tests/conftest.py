"""Test configuration and fixtures."""

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

# Use a temporary test database so we don't pollute the real one
_TEST_DB_PATH = "data/test_agentos.db"


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True, scope="function")
async def init_test_db():
    """Initialize the test database before each test function.

    This ensures tables exist for API tests that use ASGITransport
    (which does NOT trigger FastAPI's lifespan startup event).
    Uses a temporary test database file to avoid polluting the real DB.
    """
    # Point the app at the test database
    from app.core.config import settings
    original_db_path = settings.db_path
    settings.db_path = _TEST_DB_PATH

    # Also patch the engine/session that were already created at import time
    from app.db import database
    original_engine = database.engine
    original_factory = database.async_session_factory

    database.engine = create_async_engine(
        f"sqlite+aiosqlite:///{_TEST_DB_PATH}",
        echo=False,
        future=True,
    )
    database.async_session_factory = async_sessionmaker(
        database.engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create all tables
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    # Cleanup: drop tables and restore original engine
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await database.engine.dispose()

    # Restore originals
    database.engine = original_engine
    database.async_session_factory = original_factory
    settings.db_path = original_db_path

    # Remove test DB file
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)


@pytest_asyncio.fixture
async def test_db():
    """Create an in-memory test database (for direct unit tests)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()