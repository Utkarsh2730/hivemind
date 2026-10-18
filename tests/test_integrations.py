"""Slack, incoming webhooks and notifications. Outgoing HTTP is captured, never sent."""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import urllib.parse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("ANTHROPIC_API_KEY", None)
if not os.environ.get("FALKORDB_HOST"):
    os.environ.setdefault("BRAIN_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import integrations as I  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

SECRET = "test-signing-secret"


@pytest.fixture(autouse=True)
def fresh_limits():
    server._hits.clear()  # rate limits are per IP; every test client shares one


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def sent(monkeypatch):
    """Capture everything that would be posted to Slack/Discord/Teams."""
    out = []
    monkeypatch.setattr(I, "_post_json", lambda url, payload, headers=None, timeout=10: out.append((url, payload)) or {"ok": True})
    return out


@pytest.fixture
def ws(client):
    w = client.post("/api/workspaces", json={"name": "Hooks Co"}).json()
    h = {"X-Workspace-Key": w["key"]}
    client.post(f"/api/w/{w['slug']}/entities", headers=h,
                json={"people": [{"name": "Dana Lee"}], "projects": [{"name": "Billing", "uses": ["Postgres"]}]})
    client.post(f"/api/w/{w['slug']}/connections", headers=h,
                json={"slack_signing_secret": SECRET, "notify_url": "https://hooks.slack.com/services/T0/B0/xyz"})
    conn = client.get(f"/api/w/{w['slug']}/connections", headers=h).json()
    return {**w, "h": h, "conn": conn}


def signed(body: bytes, secret=SECRET, ts=None):
    ts = str(int(ts or time.time()))
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig, "Content-Type": "application/json"}


def wait_for(cond, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_notify_url_allowlist():
    assert I.valid_notify_url("https://hooks.slack.com/services/a/b/c")
    assert I.valid_notify_url("https://discord.com/api/webhooks/1/abc")
    assert I.valid_notify_url("https://acme.webhook.office.com/webhookb2/x")
    assert not I.valid_notify_url("http://hooks.slack.com/services/a")
    assert not I.valid_notify_url("https://localhost/x")
    assert not I.valid_notify_url("https://evil.example.com/hooks.slack.com")


def test_chat_formatting():
    assert I.to_chat_text("**Bold** and ~~old~~\n## Head\n- item", "slack") == "*Bold* and ~old~\n*Head*\n• item"


def test_slack_signature():
    body = b'{"a":1}'
    h = {k.lower(): v for k, v in signed(body).items()}
    assert I.verify_slack(SECRET, h, body)
    assert not I.verify_slack("other", h, body)
    old = {k.lower(): v for k, v in signed(body, ts=time.time() - 600).items()}
    assert not I.verify_slack(SECRET, old, body)


def test_connections_hide_secrets(ws):
    c = ws["conn"]
    assert c["slack_signing_secret"] == "set" and "xyz" not in json.dumps(c)
    assert c["notify_platform"] == "slack" and c["inbound_url"].endswith(c["inbound_token"])
    assert c["slack_manifest"]["features"]["slash_commands"][0]["url"].endswith(f"/slack/{ws['slug']}/command")


def test_slack_url_verification_and_bad_signature(client, ws):
    body = json.dumps({"type": "url_verification", "challenge": "abc"}).encode()
    assert client.post(f"/slack/{ws['slug']}/events", content=body, headers=signed(body)).json() == {"challenge": "abc"}
    assert client.post(f"/slack/{ws['slug']}/events", content=body, headers=signed(body, "wrong")).status_code == 401


def test_slack_message_becomes_knowledge_and_announces_decision(client, ws, sent):
    ev = {"type": "event_callback", "event": {"type": "message", "user": "U123", "channel": "C1", "ts": str(time.time()),
                                              "text": "We decided to move Billing from Postgres to CockroachDB."}}
    body = json.dumps(ev).encode()
    assert client.post(f"/slack/{ws['slug']}/events", content=body, headers=signed(body)).status_code == 200
    meta = lambda: client.get(f"/api/w/{ws['slug']}/meta", headers=ws["h"]).json()["counts"]
    assert wait_for(lambda: meta().get("Source") == 1 and meta().get("Decision") == 1)
    assert wait_for(lambda: any("New decision" in p.get("text", "") for _, p in sent))
    # bot messages and edits are ignored
    for e in [{"bot_id": "B1"}, {"subtype": "message_changed"}]:
        b = json.dumps({"type": "event_callback", "event": {"type": "message", "text": "hello there", **e}}).encode()
        client.post(f"/slack/{ws['slug']}/events", content=b, headers=signed(b))
    time.sleep(0.3)
    assert meta()["Source"] == 1


def test_slash_command_answers_in_channel(client, ws, sent):
    h = ws["h"]
    client.post(f"/api/w/{ws['slug']}/knowledge", headers=h,
                json={"kind": "ticket", "text": "Billing invoices fail on Postgres timeouts.", "author": "Dana Lee",
                      "assignee": "Dana Lee", "status": "in_progress"})
    form = urllib.parse.urlencode({"text": "Who owns Billing?", "response_url": "https://hooks.slack.com/commands/T/1/x"}).encode()
    hdr = {**signed(form), "Content-Type": "application/x-www-form-urlencoded"}
    r = client.post(f"/slack/{ws['slug']}/command", content=form, headers=hdr).json()
    assert r["response_type"] == "ephemeral"
    assert wait_for(lambda: any(p.get("response_type") == "in_channel" for _, p in sent))
    reply = next(p for _, p in sent if p.get("response_type") == "in_channel")["text"]
    assert "Billing" in reply and "Sources" in reply
    bad = urllib.parse.urlencode({"text": "x", "response_url": "https://evil.example.com/"}).encode()
    assert client.post(f"/slack/{ws['slug']}/command", content=bad,
                       headers={**signed(bad), "Content-Type": "application/x-www-form-urlencoded"}).status_code == 400


def test_inbound_webhooks(client, ws):
    url = urllib.parse.urlparse(ws["conn"]["inbound_url"]).path
    assert client.post(f"/hooks/{ws['slug']}/wrong", json={"text": "x"}).status_code == 404
    jira = {"webhookEvent": "jira:issue_created", "issue": {"key": "BIL-7", "fields": {
        "summary": "Invoice PDF broken", "status": {"statusCategory": {"key": "indeterminate"}},
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "PDFs render blank for Billing."}]}]},
        "reporter": {"displayName": "Dana Lee"}, "assignee": {"displayName": "Sam Roy"}, "created": "2026-10-01T10:00:00"}}}
    assert client.post(url, json=jira).json()["platform"] == "jira"
    linear = {"action": "create", "type": "Issue", "data": {"identifier": "ENG-12", "title": "Speed up search",
              "description": "Search on Billing is slow.", "state": {"type": "started"}, "creator": {"name": "Dana Lee"}}}
    assert client.post(url, json=linear).json()["platform"] == "linear"
    gh = {"action": "opened", "issue": {"number": 9, "title": "Crash", "body": "Crash on start", "state": "open",
          "user": {"login": "octo"}}, "repository": {"name": "app"}, "sender": {"login": "octo"}}
    assert client.post(url, json=gh, headers={"X-GitHub-Event": "issues"}).json()["platform"] == "github"
    generic = {"items": [{"text": "Teams call: Notion is our source of truth for specs.", "author": "Dana Lee", "channel": "Teams"}]}
    assert client.post(url, json=generic).json()["added"] == 1
    src = client.post(f"/api/w/{ws['slug']}/ask", headers=ws["h"], json={"question": "Invoice PDF broken"}).json()
    assert "BIL-7" in src["answer"]


def test_share_and_demo_protection(client, ws, sent):
    r = client.post(f"/api/w/{ws['slug']}/share", headers=ws["h"], json={"title": "Sprint plan", "markdown": "## Goal\n**Ship**"})
    assert r.status_code == 200 and sent[-1][1]["text"].startswith("*Sprint plan*")
    assert client.post("/api/w/demo/connections", json={"notify_url": "https://hooks.slack.com/x"}).status_code == 403
    assert client.post(f"/api/w/{ws['slug']}/connections", headers=ws["h"],
                       json={"notify_url": "https://example.com/hook"}).status_code == 400
