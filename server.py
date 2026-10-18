"""Hivemind web app: a public demo company plus private workspaces any company can register.

Local:  .venv/bin/python server.py   then open http://localhost:8000
Online: the host sets PORT; the app listens on 0.0.0.0 (see render.yaml).
"""
import asyncio
import json
import os
import queue
import threading
import time
import urllib.parse
from collections import defaultdict, deque

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import brain_agent
import brain_docs
import brain_github
import integrations
import brain_ingest
import company_data as cd
import workspaces
from graph_db import backend, get_graph, workspace

from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    ensure_demo()
    yield


app = FastAPI(title="Hivemind", lifespan=lifespan)
HERE = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

# ---------- public-demo protection ----------
LIMITS = {"webhook": (60, 60), "slack": (120, 60), "share": (10, 60), "generate": (4, 60), "ask": (8, 60), "write": (20, 60), "import": (4, 60), "reset": (2, 60), "create": (3, 600)}
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


class Connections(BaseModel):
    slack_token: str | None = Field(default=None, max_length=200)
    slack_signing_secret: str | None = Field(default=None, max_length=100)
    notify_url: str | None = Field(default=None, max_length=500)
    notify_decisions: bool | None = None


class Share(BaseModel):
    title: str = Field(default="", max_length=200)
    markdown: str = Field(max_length=30000)


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
        "notify": "" if w["demo"] else integrations.public_settings(w["slug"])["notify_platform"],
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
        change = brain_ingest.add_knowledge(body.kind, body.text, author=body.author, title=body.title,
                                            date_=body.date, channel=body.channel, status=body.status,
                                            assignee=body.assignee, key=body.key)
    if not w["demo"]:
        integrations.notify_change(w["slug"], change, _public_base(request) + f"/w/{w['slug']}")
    return change


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


# ---------- connections: Slack, webhooks, notifications ----------

def _public_base(request: Request) -> str:
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"


def _no_demo(w):
    if w["demo"]:
        raise HTTPException(403, "Create your own workspace to connect Slack and other tools.")


@app.get("/api/w/{slug}/connections")
def get_connections(request: Request, w: dict = Depends(ws)):
    base = _public_base(request)
    if w["demo"]:
        return {"demo": True, "base": base}
    s = integrations.public_settings(w["slug"])
    return {**s, "demo": False, "base": base,
            "slack_events_url": f"{base}/slack/{w['slug']}/events",
            "slack_command_url": f"{base}/slack/{w['slug']}/command",
            "inbound_url": f"{base}/hooks/{w['slug']}/{s['inbound_token']}",
            "slack_manifest": integrations.slack_manifest(base, w["slug"], w["name"])}


@app.post("/api/w/{slug}/connections")
def set_connections(body: Connections, request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "write")
    _no_demo(w)
    try:
        integrations.update_settings(w["slug"], body.slack_token, body.slack_signing_secret, body.notify_url,
                                     body.notify_decisions)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_connections(request, w)


@app.post("/api/w/{slug}/connections/rotate")
def rotate_inbound(request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "write")
    _no_demo(w)
    integrations.inbound_token(w["slug"], rotate=True)
    return get_connections(request, w)


@app.post("/api/w/{slug}/connections/test")
def test_notify(request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "share")
    _no_demo(w)
    s = integrations.get_settings(w["slug"])
    if not s.get("notify_url"):
        raise HTTPException(400, "Add a channel webhook URL first.")
    try:
        integrations.send(s["notify_url"], f"Hivemind for **{w['name']}** is connected. Decisions and shared "
                                           f"answers will appear here.\n{_public_base(request)}/w/{w['slug']}")
    except Exception as e:
        raise HTTPException(400, f"The chat app rejected the message: {e}")
    return {"ok": True}


@app.post("/api/w/{slug}/share")
def share(body: Share, request: Request, w: dict = Depends(ws)):
    """Send an answer, PRD or sprint plan to the connected chat channel."""
    _rate_limit(request, "share")
    _no_demo(w)
    s = integrations.get_settings(w["slug"])
    if not s.get("notify_url"):
        raise HTTPException(400, "Connect a channel first (menu, then Connections).")
    try:
        integrations.send(s["notify_url"], body.markdown, body.title)
    except Exception as e:
        raise HTTPException(400, f"The chat app rejected the message: {e}")
    return {"ok": True, "platform": integrations.platform_of(s["notify_url"])}


@app.post("/api/w/{slug}/slack/import")
def slack_import(request: Request, w: dict = Depends(ws)):
    _rate_limit(request, "import")
    _no_demo(w)
    token = integrations.get_settings(w["slug"]).get("slack_token")
    if not token:
        raise HTTPException(400, "Add the Slack bot token first.")
    try:
        items = integrations.slack_history(token)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with workspace(w["slug"]), _locks[w["slug"]]:
        _check_capacity(len(items))
        res = brain_ingest.bulk_import(items[:200])
    res["read"] = len(items)
    return res


def _ingest_items(slug: str, items: list[dict], link: str) -> dict:
    with workspace(slug), _locks[slug]:
        _check_capacity(len(items))
        out = {"added": 0, "decisions": []}
        for it in sorted(items, key=lambda x: x.get("date") or ""):
            ch = brain_ingest.add_knowledge(it.get("kind", "message"), it.get("text", ""), author=it.get("author", ""),
                                            title=it.get("title", ""), date_=it.get("date", ""),
                                            channel=it.get("channel", ""), status=it.get("status", ""),
                                            assignee=it.get("assignee", ""), key=it.get("key", ""))
            out["added"] += 1
            if ch["decision"]:
                out["decisions"].append(ch["decision"]["key"])
                integrations.notify_change(slug, ch, link)
    return out


@app.post("/hooks/{slug}/{token}")
async def inbound_webhook(slug: str, token: str, request: Request):
    """Jira, Linear, GitHub, Zapier/Make/n8n or any JSON: {"text": ..., "author": ..., "channel": ...}."""
    _rate_limit(request, "webhook")
    w = workspaces.get(slug)
    expected = integrations.get_settings(slug).get("inbound_token") if w and not w["demo"] else None
    if not expected or not secrets_equal(token, expected):
        raise HTTPException(404, "Unknown webhook.")
    body = await request.body()
    if len(body) > 200_000:
        raise HTTPException(413, "Payload too large.")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "Send JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Send a JSON object.")
    platform, items = integrations.parse_inbound(payload, {k.lower(): v for k, v in request.headers.items()})
    items = [i for i in items if (i.get("text") or "").strip()]
    if not items:
        return {"ok": True, "platform": platform, "added": 0}
    res = await asyncio.to_thread(_ingest_items, slug, items, _public_base(request) + f"/w/{slug}")
    return {"ok": True, "platform": platform, **res}


def secrets_equal(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


async def _slack_request(slug: str, request: Request) -> tuple[dict, bytes]:
    _rate_limit(request, "slack")
    w = workspaces.get(slug)
    if not w or w["demo"]:
        raise HTTPException(404, "Unknown workspace.")
    body = await request.body()
    secret = integrations.get_settings(slug).get("slack_signing_secret")
    if not integrations.verify_slack(secret, {k.lower(): v for k, v in request.headers.items()}, body):
        raise HTTPException(401, "Bad Slack signature.")
    return w, body


@app.post("/slack/{slug}/events")
async def slack_events(slug: str, request: Request):
    w, body = await _slack_request(slug, request)
    payload = json.loads(body or b"{}")
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    if request.headers.get("x-slack-retry-num"):
        return {"ok": True}  # we already accepted the original delivery
    token = integrations.get_settings(slug).get("slack_token") or ""
    event = payload.get("event") or {}

    def work():
        src = integrations.slack_event_to_source(event, token)
        if src:
            _ingest_items(slug, [src], f"{_public_base(request)}/w/{slug}")
    threading.Thread(target=work, daemon=True).start()  # Slack wants a reply within 3 seconds
    return {"ok": True}


@app.post("/slack/{slug}/command")
async def slack_command(slug: str, request: Request):
    w, body = await _slack_request(slug, request)
    form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode()).items()}
    question = (form.get("text") or "").strip()[:400]
    response_url = form.get("response_url", "")
    if not question:
        return JSONResponse({"response_type": "ephemeral", "text": "Ask a question, e.g. `/hivemind who owns checkout?`"})
    if urllib.parse.urlparse(response_url).hostname not in ("hooks.slack.com",):
        raise HTTPException(400, "Bad response_url.")
    base = _public_base(request)

    def work():
        with workspace(slug):
            try:
                r = brain_agent.answer(question, company=w["name"])
            except Exception:
                r = brain_agent.answer(question, mode="graph")
        srcs = "\n".join(f"• [{c['key']}] {c['title']} ({c.get('author') or c['kind']}, {c.get('date') or ''})"
                         for c in r["citations"][:6])
        text = integrations.to_chat_text(f"**Q: {question}**\n{r['answer']}" + (f"\n\n**Sources**\n{srcs}" if srcs else "")
                                         + f"\n<{base}/w/{slug}?ask={urllib.parse.quote(question)}|Open in Hivemind>", "slack")
        try:
            integrations._post_json(response_url, {"response_type": "in_channel", "text": text[:39000]})
        except Exception as e:
            print("slack response failed:", e)
    threading.Thread(target=work, daemon=True).start()
    return JSONResponse({"response_type": "ephemeral", "text": f"Looking that up: _{question}_"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)
