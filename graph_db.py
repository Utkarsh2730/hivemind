"""FalkorDB connection. Every company workspace is its own graph (cb_<slug>), so tenants never share data.

Online (FalkorDB Cloud or any FalkorDB server): set FALKORDB_HOST, FALKORDB_PORT, and optionally
FALKORDB_USERNAME, FALKORDB_PASSWORD, FALKORDB_SSL=true.
Local development on macOS: leave FALKORDB_HOST unset to use embedded FalkorDB (falkordblite).
"""
import contextlib
import contextvars
import os

_db = None
_workspace = contextvars.ContextVar("workspace", default="demo")
REGISTRY_GRAPH = "cb_registry"


def backend() -> str:
    return "FalkorDB Cloud" if os.environ.get("FALKORDB_HOST") else "embedded FalkorDB"


def get_db():
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
    return _db


def current_workspace() -> str:
    return _workspace.get()


@contextlib.contextmanager
def workspace(slug: str):
    tok = _workspace.set(slug)
    try:
        yield
    finally:
        _workspace.reset(tok)


def get_graph(slug: str | None = None):
    return get_db().select_graph(f"cb_{slug or _workspace.get()}")


def registry():
    return get_db().select_graph(REGISTRY_GRAPH)
