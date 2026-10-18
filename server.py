"""Company Brain web app: a public demo company plus private workspaces any company can register.

Local:  .venv/bin/python server.py   then open http://localhost:8000
Online: the host sets PORT; the app listens on 0.0.0.0 (see render.yaml).
"""
import json
import os
import queue
import threading
import time
from collections import defaultdict, deque

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import brain_agent
import brain_docs
import brain_github
import brain_ingest
import company_data as cd
import workspaces
from graph_db import backend, get_graph, workspace

from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    ensure_demo()
    yield


app = FastAPI(title="Company Brain", lifespan=lifespan)
HERE = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

# ---------- public-demo protection ----------
LIMITS = {"generate": (4, 60), "ask": (8, 60), "write": (20, 60), "import": (4, 60), "reset": (2, 60), "create": (3, 600)}
MAX_SOURCES, MAX_ENTITIES = 2000, 1500
_hits = defaultdict(deque)
_locks = defaultdict(threading.Lock)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _rate_limit(request: Request, bucket: str):
    n, window = LIMITS[bucket]
    q = _hits[(bucket, _client_ip(request))]
    now = time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
    q.append(now)


def ws(slug: str, x_workspace_key: str = Header(default="")) -> dict:
    """Resolve the workspace and check its access key (the demo is open)."""
    w = workspaces.get(slug)
    if not w:
        raise HTTPException(404, "Workspace not found.")
    if not workspaces.check_key(slug, x_workspace_key):
        raise HTTPException(401, "This workspace is private. Open it with its access link.")
    return w


# ---------- models ----------
class NewWorkspace(BaseModel):
    name: str = Field(min_length=2, max_length=60)


class Generate(BaseModel):
    kind: str = Field(pattern="^(prd|sprint)$")
    project: str = Field(max_length=80)
    goal: str = Field(default="", max_length=300)
    weeks: int = Field(default=2, ge=1, le=4)


class GitHubImport(BaseModel):
    repo: str = Field(max_length=200)


class Keys(BaseModel):
    keys: list[str] = Field(max_length=400)


class Ask(BaseModel):
    question: str = Field(max_length=400)


class Message(BaseModel):
    author: str = Field(default="", max_length=60)
    text: str = Field(min_length=1, max_length=4000)
    channel: str = Field(default="", max_length=40)
    kind: str = Field(default="message", max_length=10)
    title: str = Field(default="", max_length=200)
    date: str = Field(default="", max_length=10)
    status: str = Field(default="", max_length=20)
    assignee: str = Field(default="", max_length=60)
    key: str = Field(default="", max_length=20)


class Entities(BaseModel):
    people: list[dict] = Field(default_factory=list, max_length=300)
    teams: list[str] = Field(default_factory=list, max_length=100)
    projects: list[dict] = Field(default_factory=list, max_length=200)
    systems: list[dict] = Field(default_factory=list, max_length=300)


class Bulk(BaseModel):
    sources: list[Message] = Field(max_length=200)


# ---------- pages ----------
def ensure_demo():
    try:
        with workspace("demo"):
            empty = not get_graph().ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    except Exception:
        empty = True
    if empty:
        brain_ingest.build_demo()


@app.get("/")
def landing():
    return FileResponse(os.path.join(HERE, "static", "landing.html"))


@app.get("/w/{slug}")
def app_page(slug: str):
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/healthz")
def health():
    return {"ok": True}


# ---------- workspace API ----------
@app.post("/api/workspaces")
def create_workspace(body: NewWorkspace, request: Request):
    _rate_limit(request, "create")
    try:
        return workspaces.create(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/w/{slug}/meta")
def meta(w: dict = Depends(ws)):
    with workspace(w["slug"]):
        g = get_graph()
        people = g.ro_query("MATCH (p:Person) RETURN p.key, p.name, p.role ORDER BY p.name").result_set
        counts = brain_ingest.counts()
        questions = cd.DEMO_QUESTIONS if w["demo"] else brain_agent.suggestions()
        projects = brain_docs.projects()
    return {
        "workspace": w,
        "claude": brain_agent.has_credentials(),
        "backend": backend(),
        "questions": questions,
        "demo_ingest": cd.DEMO_INGEST if w["demo"] else None,
        "people": [{"key": k, "name": n, "role": r or ""} for k, n, r in people],
        "counts": counts,
        "projects": [{"key": p["key"], "name": p["name"]} for p in projects],
    }


MAP_LIMIT = 450  # above this many nodes the map shows people/projects/tools/decisions + the newest items


def _graph_payload(node_rows, edge_rows, truncated=False, total=0):
    keys = {r[0] for r in node_rows}
    return {
        "nodes": [dict(id=k, type=t, name=n, kind=kind, status=st, detail=(d or "")[:400], date=dt)
                  for k, t, n, kind, st, d, dt in node_rows],
        "edges": [dict(source=a, rel=r, target=b) for a, r, b in edge_rows if a in keys and b in keys],
        "truncated": truncated, "total": total or len(node_rows),
    }


NODE_RET = "RETURN n.key, labels(n)[0], coalesce(n.name, n.title), n.kind, n.status, coalesce(n.role, n.summary, n.text, ''), n.date"


@app.get("/api/w/{slug}/graph")
def graph(w: dict = Depends(ws)):
    with workspace(w["slug"]):
        g = get_graph()
        total = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
        if total <= MAP_LIMIT:
            nodes = g.ro_query("MATCH (n) " + NODE_RET).result_set
            edges = g.ro_query("MATCH (a)-[r]->(b) RETURN a.key, type(r), b.key").result_set
            return _graph_payload(nodes, edges, total=total)
        nodes = g.ro_query("MATCH (n) WHERE NOT n:Source " + NODE_RET + " LIMIT 300").result_set
        nodes += g.ro_query("MATCH (n:Source) WITH n ORDER BY n.date DESC LIMIT 120 " + NODE_RET).result_set
        keys = [r[0] for r in nodes]
        edges = g.ro_query("MATCH (a)-[r]->(b) WHERE a.key IN $k AND b.key IN $k RETURN a.key, type(r), b.key", {"k": keys}).result_set
        return _graph_payload(nodes, edges, truncated=True, total=total)


@app.post("/api/w/{slug}/graph/focus")
def graph_focus(body: Keys, w: dict = Depends(ws)):
    """The nodes behind an answer plus their direct neighbours (used when the full map is too big)."""
    with workspace(w["slug"]):
        g = get_graph()
        nodes = g.ro_query("MATCH (c) WHERE c.key IN $k OPTIONAL MATCH (c)--(nb) WITH collect(DISTINCT c) + collect(DISTINCT nb) AS ns "
                           "UNWIND ns AS n WITH DISTINCT n WHERE n IS NOT NULL " + NODE_RET + " LIMIT 400", {"k": body.keys}).result_set
        keys = [r[0] for r in nodes]
        edges = g.ro_query("MATCH (a)-[r]->(b) WHERE a.key IN $k AND b.key IN $k RETURN a.key, type(r), b.key", {"k": keys}).result_set
    return _graph_payload(nodes, edges)


@app.post("/api/w/{slug}/ask")
def ask(body: Ask, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "ask")
    company = w["name"].replace(" (demo)", "")
    with workspace(w["slug"]):
        try:
            return brain_agent.answer(body.question, company=company)
        except Exception as e:  # e.g. API credits exhausted: answer straight from the graph instead
            try:
                res = brain_agent.answer(body.question, mode="graph")
                res["answer"] += "\n\n(The AI model was unavailable, so this answer came straight from the company map.)"
                return res
            except Exception:
                return {"answer": f"Something went wrong: {e}", "mode": "error", "citations": [], "trace": [],
                        "highlight": [], "cited": []}


@app.post("/api/w/{slug}/generate")
def generate(body: Generate, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "generate")
    with workspace(w["slug"]):
        try:
            return brain_docs.generate(body.kind, body.project, body.goal, body.weeks,
                                       company=w["name"].replace(" (demo)", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/w/{slug}/ask/stream")
def ask_stream(body: Ask, request: Request, w: dict = Depends(ws)):
    """Server-sent events: one 'step' event per graph tool as it runs, then the final 'answer'."""
    _rate_limit(request, "ask")
    company = w["name"].replace(" (demo)", "")
    events: queue.Queue = queue.Queue()

    def run():
        with workspace(w["slug"]):
            on_step = lambda step, keys: events.put(("step", {**step, "keys": keys[:60]}))
            try:
                res = brain_agent.answer(body.question, company=company, on_step=on_step)
            except Exception as e:
                try:
                    res = brain_agent.answer(body.question, mode="graph", on_step=on_step)
                    res["answer"] += "\n\n(The AI model was unavailable, so this answer came straight from the company map.)"
                except Exception:
                    res = {"answer": f"Something went wrong: {e}", "mode": "error", "citations": [], "trace": [],
                           "highlight": [], "cited": []}
            events.put(("answer", res))

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while True:
            try:
                kind, data = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
            if kind == "answer":
                break

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/w/{slug}/import/github")
def import_github(body: GitHubImport, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "import")
    if w["demo"]:
        raise HTTPException(403, "Create your own workspace to import a repository.")
    with workspace(w["slug"]), _locks[w["slug"]]:
        _check_capacity(100)
        try:
            return brain_github.import_repo(body.repo)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/w/{slug}/delete")
def delete_item(body: Keys, request: Request, w: dict = Depends(ws)):
    """Delete items (docs/tickets/messages) or mark decisions as 'not a decision'."""
    _rate_limit(request, "write")
    if w["demo"] and any(k in {s["key"] for s in cd.SOURCES} or k in {d[0] for d in cd.DECISIONS} for k in body.keys):
        raise HTTPException(403, "The demo's original data can't be deleted. Use Reset instead.")
    out = []
    with workspace(w["slug"]), _locks[w["slug"]]:
        for k in body.keys[:50]:
            try:
                out.append(brain_ingest.remove_decision(k) if k.startswith("DEC-") else brain_ingest.delete_source(k))
            except ValueError as e:
                out.append({"key": k, "error": str(e)})
    return {"results": out}


def _check_capacity(add_sources=0):
    c = brain_ingest.counts()
    if c.get("Source", 0) + add_sources > MAX_SOURCES:
        raise HTTPException(400, f"This workspace is full ({MAX_SOURCES} items max in the hosted demo).")
    if sum(v for k, v in c.items() if k in ("Person", "Team", "Project", "System")) > MAX_ENTITIES:
        raise HTTPException(400, "Too many people/projects/systems for the hosted demo.")


@app.post("/api/w/{slug}/knowledge")
def add_one(body: Message, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "write")
    with workspace(w["slug"]), _locks[w["slug"]]:
        if w["demo"]:  # keep the shared demo tidy
            live = get_graph().ro_query("MATCH (s:Source) WHERE NOT s.key IN $k RETURN count(s)",
                                        {"k": [s["key"] for s in cd.SOURCES]}).result_set[0][0]
            if live >= 50:
                brain_ingest.build_demo()
        _check_capacity(1)
        return brain_ingest.add_knowledge(body.kind, body.text, author=body.author, title=body.title,
                                          date_=body.date, channel=body.channel, status=body.status,
                                          assignee=body.assignee, key=body.key)


@app.post("/api/w/{slug}/import")
def import_sources(body: Bulk, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "import")
    if w["demo"]:
        raise HTTPException(403, "Create your own workspace to import files.")
    with workspace(w["slug"]), _locks[w["slug"]]:
        _check_capacity(len(body.sources))
        return brain_ingest.bulk_import([s.model_dump() for s in body.sources])


@app.post("/api/w/{slug}/entities")
def add_entities(body: Entities, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "write")
    if w["demo"]:
        raise HTTPException(403, "Create your own workspace to add your team.")
    with workspace(w["slug"]), _locks[w["slug"]]:
        _check_capacity()
        return brain_ingest.add_entities(body.people, body.teams, body.projects, body.systems)


@app.post("/api/w/{slug}/reset")
def reset(request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "reset")
    with _locks[w["slug"]]:
        if w["demo"]:
            brain_ingest.build_demo()
        else:
            with workspace(w["slug"]):
                brain_ingest.init_graph(wipe=True)
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)
