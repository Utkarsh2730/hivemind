"""Core behaviour tests. Run: .venv/bin/python -m pytest -q"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile  # noqa: E402

os.environ.pop("ANTHROPIC_API_KEY", None)  # tests exercise the graph-only path deterministically
if not os.environ.get("FALKORDB_HOST"):  # embedded DB: use a throwaway file, never the dev database
    os.environ["BRAIN_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import brain_agent  # noqa: E402
import brain_docs  # noqa: E402
import brain_ingest as B  # noqa: E402
import brain_insights  # noqa: E402
import workspaces  # noqa: E402
from graph_db import get_graph, workspace  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def demo():
    B.build_demo()


@pytest.fixture
def ws():
    w = workspaces.create("Test Co")
    with workspace(w["slug"]):
        yield w


def test_workspaces_are_isolated(ws):
    B.add_knowledge("message", "Secret plan for Project Zeus.", author="Ann")
    assert B.counts().get("Source") == 1
    with workspace("demo"):
        assert not get_graph().ro_query("MATCH (s:Source) WHERE s.text CONTAINS 'Zeus' RETURN s").result_set


def test_access_keys(ws):
    assert workspaces.check_key(ws["slug"], ws["key"])
    assert not workspaces.check_key(ws["slug"], "wrong")
    assert not workspaces.check_key(ws["slug"], "")
    assert workspaces.check_key("demo", "")


def test_people_are_not_duplicated(ws):
    B.add_entities(people=[{"name": "Arjun"}])
    assert B.resolve_person("Arjun Rao", create=True) == B.resolve_person("arjun") == B.resolve_person("Arjun R.")
    B.add_entities(people=[{"name": "Arjun Rao", "role": "Staff Engineer"}])
    assert B.counts()["Person"] == 1


def test_mentions_and_tools_link_without_ai(ws):
    r = B.add_knowledge("message", "@priya Redis is slow again on the Kafka consumers.", author="Sam")
    assert {"person:priya", "system:redis", "system:kafka"} <= set(r["mentions"])


def test_not_every_message_is_a_decision(ws):
    for text in ["PR approved, thanks!", "We'll look into it next week.", "Should we use Redis?"]:
        assert B.add_knowledge("message", text, author="Sam")["decision"] is None


def test_new_decision_supersedes_old_and_can_be_undone(ws):
    B.add_entities(projects=[{"name": "Billing", "uses": ["Postgres"]}])
    d1 = B.add_knowledge("meeting", "We decided to use Postgres for Billing.", author="Ann", date_="2026-01-01")["decision"]
    r2 = B.add_knowledge("message", "We're moving Billing from Postgres to DynamoDB.", author="Ann", date_="2026-02-01")
    assert r2["superseded"] == [d1["key"]]
    assert B.remove_decision(r2["decision"]["key"])["restored"] == [d1["key"]]
    status = get_graph().ro_query("MATCH (d:Decision {key: $k}) RETURN d.status", {"k": d1["key"]}).result_set[0][0]
    assert status == "active"


def test_delete_source_removes_its_decision(ws):
    r = B.add_knowledge("meeting", "We decided to use Stripe for invoices.", author="Ann")
    out = B.delete_source(r["source"])
    assert out["decisions_removed"] == [r["decision"]["key"]]
    assert B.counts().get("Source", 0) == 0


def test_demo_answers_cite_sources():
    with workspace("demo"):
        r = brain_agent.answer("Who should I ask about Kafka consumer lag?", mode="graph")
        assert "Tomas" in r["answer"] and "DOC-3" in r["cited"]
        r = brain_agent.answer("What changed about customer login, and why?", mode="graph")
        assert {"DEC-3", "DEC-4"} <= set(r["cited"])


def test_sprint_plan_puts_blockers_first():
    with workspace("demo"):
        md = brain_docs.generate("sprint", "project:checkout")["markdown"]
    rows = [l for l in md.splitlines() if l.startswith("| 1 ") or l.startswith("| 2 ")]
    assert "PAY-52" in rows[0] and "GRW-7" in rows[1]


def test_prd_has_all_sections():
    with workspace("demo"):
        md = brain_docs.generate("prd", "project:auth", goal="Finish the Keycloak migration")["markdown"]
    for h in ["Summary", "Decisions already made", "Scope", "People", "Risks", "Open questions"]:
        assert h in md
    assert "[DEC-4]" in md


def test_insights_use_graph_algorithms():
    with workspace("demo"):
        i = brain_insights.insights()
    assert i["key_connectors"] and i["central_topics"]
    assert any(t["key"] == "PAY-52" for t in i["stalled"])


def test_api_end_to_end():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    w = c.post("/api/workspaces", json={"name": "API Co"}).json()
    h = {"X-Workspace-Key": w["key"]}
    assert c.get(f"/api/w/{w['slug']}/meta").status_code == 401
    assert c.post(f"/api/w/{w['slug']}/entities", headers=h,
                  json={"people": [{"name": "Lee Park"}], "projects": [{"name": "Billing", "lead": "Lee Park", "uses": ["Stripe"]}]}).status_code == 200
    r = c.post(f"/api/w/{w['slug']}/knowledge", headers=h, json={"kind": "ticket", "text": "Stripe webhooks fail for Billing.",
                                                                  "author": "Lee Park", "status": "in_progress", "assignee": "Lee"}).json()
    assert r["source"].startswith("TKT-")
    doc = c.post(f"/api/w/{w['slug']}/generate", headers=h, json={"kind": "sprint", "project": "project:billing"}).json()
    assert r["source"] in doc["markdown"]
    stream = c.post(f"/api/w/{w['slug']}/ask/stream", headers=h, json={"question": "Who owns Billing?"}).text
    assert "event: step" in stream and "event: answer" in stream
    assert c.post("/api/w/demo/delete", json={"keys": ["DOC-1"]}).status_code == 403
