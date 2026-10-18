"""Web app for the company brain.

Local:  .venv/bin/python server.py   then open http://localhost:8000
Online: the host sets PORT; the app listens on 0.0.0.0 (see render.yaml).
"""
import os
import threading
import time
from collections import defaultdict, deque

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import brain_agent
import brain_ingest
import company_data as cd
from graph_db import backend, get_graph

app = FastAPI(title="Company Brain")
HERE = os.path.dirname(os.path.abspath(__file__))

# Public demo protection: per-visitor rate limits, size caps, and a write lock.
LIMITS = {"ask": (8, 60), "ingest": (5, 60), "reset": (2, 60)}  # (requests, seconds)
_hits = defaultdict(deque)
_write_lock = threading.Lock()


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
        raise HTTPException(429, f"Too many requests. Please wait a minute and try again.")
    q.append(now)


class Ask(BaseModel):
    question: str = Field(max_length=400)


class Ingest(BaseModel):
    author: str = Field(max_length=40)
    text: str = Field(max_length=600)
    channel: str = Field(default="#general", max_length=30)


@app.on_event("startup")
def ensure_graph():
    try:
        empty = not get_graph().ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    except Exception:
        empty = True
    if empty:
        brain_ingest.build()


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    people = get_graph().ro_query("MATCH (p:Person) RETURN p.key, p.name, p.role ORDER BY p.name").result_set
    return {
        "claude": brain_agent.has_credentials(),
        "backend": backend(),
        "questions": cd.DEMO_QUESTIONS,
        "demo_ingest": cd.DEMO_INGEST,
        "people": [{"key": k, "name": n, "role": r} for k, n, r in people],
    }


@app.get("/api/graph")
def graph():
    g = get_graph()
    nodes = g.ro_query(
        "MATCH (n) RETURN n.key, labels(n)[0], coalesce(n.name, n.title), n.kind, n.status, "
        "coalesce(n.role, n.summary, n.text, ''), n.date").result_set
    edges = g.ro_query("MATCH (a)-[r]->(b) RETURN a.key, type(r), b.key").result_set
    return {
        "nodes": [dict(id=k, type=t, name=n, kind=kind, status=st, detail=d, date=dt)
                  for k, t, n, kind, st, d, dt in nodes],
        "edges": [dict(source=a, rel=r, target=b) for a, r, b in edges],
    }


@app.post("/api/ask")
def ask(body: Ask, request: Request):
    _rate_limit(request, "ask")
    try:
        return brain_agent.answer(body.question)
    except Exception as e:  # e.g. API credits exhausted: fall back to answering from the graph directly
        try:
            res = brain_agent.answer(body.question, mode="graph")
            res["answer"] += "\n\n(The AI model was unavailable, so this answer came straight from the company map.)"
            return res
        except Exception:
            return {"answer": f"Something went wrong: {e}", "mode": "error", "citations": [], "trace": [],
                    "highlight": [], "cited": []}


@app.post("/api/ingest")
def ingest(body: Ingest, request: Request):
    _rate_limit(request, "ingest")
    valid = {p[0] for p in cd.PEOPLE}
    if body.author not in valid:
        raise HTTPException(400, "Unknown author")
    with _write_lock:
        live = get_graph().ro_query("MATCH (s:Source) WHERE s.key STARTS WITH 'LIVE-' RETURN count(s)").result_set[0][0]
        if live >= 50:  # keep the shared public demo tidy
            brain_ingest.build()
        return brain_ingest.ingest("message", body.author, body.text, body.channel)


@app.post("/api/reset")
def reset(request: Request):
    _rate_limit(request, "reset")
    with _write_lock:
        brain_ingest.build()
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)
