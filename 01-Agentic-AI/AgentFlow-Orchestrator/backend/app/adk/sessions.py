"""ADK session service configuration.

Uses DatabaseSessionService with SQLite for persistent sessions.
This allows execution state to survive restarts.
"""

from google.adk.sessions import DatabaseSessionService

from app.core.config import settings

# Singleton session service instance
# Uses the same SQLite database as platform tables
_session_service: DatabaseSessionService | None = None


def get_session_service() -> DatabaseSessionService:
    """Get the singleton ADK DatabaseSessionService instance.

    Uses SQLite for persistence — sessions and state survive restarts.
    """
    global _session_service
    if _session_service is None:
        _session_service = DatabaseSessionService(
            db_url=settings.db_url_sync,
        )
    return _session_service