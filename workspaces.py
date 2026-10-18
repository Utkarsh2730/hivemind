"""Company workspaces. Each company gets its own FalkorDB graph and a secret access key.
Only a SHA-256 hash of the key is stored."""
import hashlib
import hmac
import re
import secrets
import time

import brain_ingest
from graph_db import registry, workspace

MAX_WORKSPACES = 500
DEMO = {"slug": "demo", "name": "Lumen Pay (demo)", "demo": True}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _init_registry():
    try:
        registry().query("CREATE INDEX FOR (w:Workspace) ON (w.slug)")
    except Exception:
        pass


def create(name: str) -> dict:
    name = re.sub(r"\s+", " ", name).strip()[:60]
    if len(name) < 2:
        raise ValueError("Company name is too short.")
    _init_registry()
    r = registry()
    if r.ro_query("MATCH (w:Workspace) RETURN count(w)").result_set[0][0] >= MAX_WORKSPACES:
        raise ValueError("This demo has reached its workspace limit.")
    base = brain_ingest.slugify(name)[:24] or "company"
    slug = f"{base}-{secrets.token_hex(2)}"
    key = secrets.token_urlsafe(18)
    r.query("CREATE (:Workspace {slug: $s, name: $n, key_hash: $h, created: $t})",
            {"s": slug, "n": name, "h": _hash(key), "t": time.time()})
    with workspace(slug):
        brain_ingest.init_graph(wipe=True)
    return {"slug": slug, "name": name, "key": key}


def get(slug: str) -> dict | None:
    if slug == "demo":
        return DEMO
    if not re.fullmatch(r"[a-z0-9-]{3,40}", slug or ""):
        return None
    try:
        rows = registry().ro_query("MATCH (w:Workspace {slug: $s}) RETURN w.name", {"s": slug}).result_set
    except Exception:
        return None
    return {"slug": slug, "name": rows[0][0], "demo": False} if rows else None


def check_key(slug: str, key: str) -> bool:
    if slug == "demo":
        return True
    rows = registry().ro_query("MATCH (w:Workspace {slug: $s}) RETURN w.key_hash", {"s": slug}).result_set
    return bool(rows and key and hmac.compare_digest(rows[0][0], _hash(key)))
