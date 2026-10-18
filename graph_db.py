"""FalkorDB connection.

Online (FalkorDB Cloud or any FalkorDB server): set FALKORDB_HOST, FALKORDB_PORT, and optionally
FALKORDB_USERNAME, FALKORDB_PASSWORD, FALKORDB_SSL=true.
Local development on macOS: leave FALKORDB_HOST unset to use embedded FalkorDB (falkordblite).
"""
import os

GRAPH_NAME = os.environ.get("FALKORDB_GRAPH", "company_brain")
_db = None


def backend() -> str:
    return "FalkorDB server" if os.environ.get("FALKORDB_HOST") else "embedded FalkorDB"


def get_graph():
    global _db
    if _db is None:
        host = os.environ.get("FALKORDB_HOST")
        if host:
            from falkordb import FalkorDB
            _db = FalkorDB(
                host=host,
                port=int(os.environ.get("FALKORDB_PORT", 6379)),
                username=os.environ.get("FALKORDB_USERNAME") or None,
                password=os.environ.get("FALKORDB_PASSWORD") or None,
                ssl=os.environ.get("FALKORDB_SSL", "").lower() in ("1", "true", "yes"),
            )
        else:
            from redislite.falkordb_client import FalkorDB
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "falkor.db")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _db = FalkorDB(path)
    return _db.select_graph(GRAPH_NAME)
