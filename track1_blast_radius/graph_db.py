"""FalkorDB connection. Uses embedded FalkorDB (falkordblite) unless FALKORDB_HOST is set."""
import os

GRAPH_NAME = "codegraph"
_db = None


def get_graph():
    global _db
    if _db is None:
        host = os.environ.get("FALKORDB_HOST")
        if host:
            from falkordb import FalkorDB
            _db = FalkorDB(host=host, port=int(os.environ.get("FALKORDB_PORT", 6379)))
        else:
            from redislite.falkordb_client import FalkorDB
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "falkor.db")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _db = FalkorDB(path)
    return _db.select_graph(GRAPH_NAME)
