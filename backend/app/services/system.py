import sqlite3

from backend.app.repositories.database import check_database


def get_health() -> tuple[dict, int]:
    try:
        check_database()
    except (sqlite3.Error, OSError):
        return {"status": "degraded", "api": "ready", "database": "unavailable"}, 503
    return {"status": "ok", "api": "ready", "database": "ready"}, 200
