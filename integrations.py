"""Connections between a company brain and the tools the company already uses.

In:
  - Slack app (Events API): messages in channels the bot is in are added as they happen.
  - Slack history import (Web API) and Slack export ZIP (parsed in the browser).
  - Incoming webhook per workspace: Jira, Linear, GitHub, or anything via Zapier / Make / n8n (generic JSON).
Out:
  - Slack slash command: /brain <question> answers in Slack with sources.
  - Notifications to Slack, Discord, Microsoft Teams or Google Chat when decisions are made or replaced,
    and on demand ("Send to channel") for answers, PRDs and sprint plans.

Secrets (Slack bot token, signing secret, notification URL) live on the workspace's registry node and are never
sent back to the browser in full.
"""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request

from graph_db import registry

# ---------------- settings ----------------

FIELDS = ["slack_token", "slack_signing_secret", "notify_url", "notify_decisions", "inbound_token"]
NOTIFY_HOSTS = ("hooks.slack.com", "discord.com", "discordapp.com", "chat.googleapis.com")
NOTIFY_SUFFIXES = (".webhook.office.com", ".logic.azure.com")  # Microsoft Teams (incoming webhook / workflows)


def get_settings(slug: str) -> dict:
    rows = registry().ro_query("MATCH (w:Workspace {slug: $s}) RETURN " + ", ".join(f"w.{f}" for f in FIELDS),
                               {"s": slug}).result_set
    if not rows:
        return {}
    return {f: v for f, v in zip(FIELDS, rows[0])}


def _set(slug: str, **values):
    sets = ", ".join(f"w.{k} = ${k}" for k in values)
    registry().query(f"MATCH (w:Workspace {{slug: $s}}) SET {sets}", {"s": slug, **values})


def valid_notify_url(url: str) -> bool:
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in NOTIFY_HOSTS or host.endswith(NOTIFY_SUFFIXES))


def update_settings(slug: str, slack_token=None, slack_signing_secret=None, notify_url=None, notify_decisions=None):
    vals = {}
    if slack_token is not None:
        if slack_token and not slack_token.startswith("xoxb-"):
            raise ValueError("The Slack bot token starts with xoxb-.")
        vals["slack_token"] = slack_token.strip()
    if slack_signing_secret is not None:
        vals["slack_signing_secret"] = slack_signing_secret.strip()
    if notify_url is not None:
        if notify_url and not valid_notify_url(notify_url):
            raise ValueError("Use an https incoming-webhook URL from Slack, Discord, Microsoft Teams or Google Chat.")
        vals["notify_url"] = notify_url.strip()
    if notify_decisions is not None:
        vals["notify_decisions"] = bool(notify_decisions)
    if vals:
        _set(slug, **vals)
    return public_settings(slug)


def inbound_token(slug: str, rotate: bool = False) -> str:
    tok = get_settings(slug).get("inbound_token")
    if rotate or not tok:
        tok = secrets.token_urlsafe(18)
        _set(slug, inbound_token=tok)
    return tok


def public_settings(slug: str) -> dict:
    s = get_settings(slug)
    mask = lambda v: (v[:5] + "…" + v[-4:]) if v and len(v) > 12 else ("set" if v else "")
    host = urllib.parse.urlparse(s.get("notify_url") or "").hostname or ""
    return {
        "slack_token": mask(s.get("slack_token")),
        "slack_signing_secret": "set" if s.get("slack_signing_secret") else "",
        "notify_url": host,
        "notify_platform": platform_of(s.get("notify_url") or ""),
        "notify_decisions": s.get("notify_decisions") is not False,
        "inbound_token": inbound_token(slug),
    }


# ---------------- outgoing ----------------

def platform_of(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    if "slack" in host:
        return "slack"
    if "discord" in host:
        return "discord"
    if "googleapis" in host:
        return "google_chat"
    if host.endswith(NOTIFY_SUFFIXES):
        return "teams"
    return ""


def to_chat_text(markdown: str, platform: str) -> str:
    """Our Markdown -> what each chat app renders."""
    t = markdown
    if platform in ("slack", "google_chat"):
        t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", t)            # bold
        t = re.sub(r"~~(.+?)~~", r"~\1~", t)                # strike
        t = re.sub(r"^#{1,3}\s+(.*)$", r"*\1*", t, flags=re.M)  # headings
        t = re.sub(r"^\s*[-*]\s+", "• ", t, flags=re.M)
    return t


def _post_json(url: str, payload: dict, headers=None, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode() or "{}"
    try:
        return json.loads(body)
    except ValueError:
        return {"raw": body}


def send(url: str, markdown: str, title: str = "") -> None:
    if not valid_notify_url(url):
        raise ValueError("Notification URL is not an allowed chat webhook.")
    platform = platform_of(url)
    text = to_chat_text((f"**{title}**\n" if title else "") + markdown, platform)
    if platform == "discord":
        for i in range(0, len(text), 1900):  # Discord limit is 2000 characters per message
            _post_json(url, {"content": text[i:i + 1900]})
    elif platform == "teams":
        _post_json(url, {"text": text[:24000]})
    else:  # slack, google chat
        _post_json(url, {"text": text[:39000]})


def notify(slug: str, markdown: str, title: str = "", kind: str = "manual") -> bool:
    """Post to the workspace's chat channel. kind='decision' respects the 'notify on decisions' switch."""
    s = get_settings(slug)
    if not s.get("notify_url") or (kind == "decision" and s.get("notify_decisions") is False):
        return False
    try:
        send(s["notify_url"], markdown, title)
        return True
    except Exception as e:  # notifications must never break ingestion
        print("notify failed:", e)
        return False


def notify_change(slug: str, change: dict, link: str = "") -> None:
    """Announce a new decision (and any decision it replaced) in the background."""
    d = change.get("decision")
    if not d:
        return
    msg = f"New decision **{d['key']}**: {d['title']}"
    if change.get("superseded"):
        msg += f"\nThis replaces {', '.join(change['superseded'])}, which is now marked outdated."
    msg += f"\nSource: [{change['source']}]" + (f" · {link}" if link else "")
    threading.Thread(target=notify, args=(slug, msg, "Company Brain", "decision"), daemon=True).start()


# ---------------- Slack ----------------

def verify_slack(signing_secret: str, headers, body: bytes) -> bool:
    ts = headers.get("x-slack-request-timestamp", "")
    sig = headers.get("x-slack-signature", "")
    if not (signing_secret and ts.isdigit() and sig) or abs(time.time() - int(ts)) > 300:
        return False
    base = b"v0:" + ts.encode() + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


SLACK_API = "https://slack.com/api/"
_name_cache: dict = {}


def slack_api(token: str, method: str, params: dict | None = None) -> dict:
    url = SLACK_API + method + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    if not data.get("ok"):
        raise ValueError(f"Slack error: {data.get('error', 'unknown')}")
    return data


def slack_name(token: str, kind: str, ident: str) -> str:
    """Resolve a Slack user or channel ID to a readable name (cached). Falls back to the ID."""
    key = (kind, ident)
    if key in _name_cache:
        return _name_cache[key]
    name = ident
    try:
        if kind == "user":
            u = slack_api(token, "users.info", {"user": ident})["user"]
            name = u.get("real_name") or u.get("profile", {}).get("real_name") or u.get("name") or ident
        else:
            name = "#" + slack_api(token, "conversations.info", {"channel": ident})["channel"]["name"]
    except Exception:
        pass
    _name_cache[key] = name
    return name


def clean_slack_text(text: str, token: str = "") -> str:
    def user(m):
        return "@" + (slack_name(token, "user", m.group(1)) if token else m.group(1))
    text = re.sub(r"<@([UW][A-Z0-9]+)(?:\|[^>]+)?>", user, text or "")
    text = re.sub(r"<#C[A-Z0-9]+\|([^>]+)>", r"#\1", text)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()


def slack_event_to_source(event: dict, token: str) -> dict | None:
    """A Slack message event -> a knowledge item, or None for bot posts, edits and joins."""
    if event.get("type") != "message" or event.get("subtype") or event.get("bot_id") or not event.get("text"):
        return None
    text = clean_slack_text(event["text"], token)
    if len(text) < 3:
        return None
    return {"kind": "message", "text": text[:4000],
            "author": slack_name(token, "user", event.get("user", "")) if token else event.get("user", ""),
            "channel": slack_name(token, "channel", event.get("channel", "")) if token else "",
            "date": time.strftime("%Y-%m-%d", time.gmtime(float(event.get("ts", time.time()))))}


def slack_history(token: str, max_channels: int = 5, per_channel: int = 150) -> list[dict]:
    """Recent messages from public channels the bot is a member of."""
    chans = [c for c in slack_api(token, "conversations.list", {"types": "public_channel", "limit": 200,
                                                                 "exclude_archived": "true"})["channels"]
             if c.get("is_member")][:max_channels]
    out = []
    for c in chans:
        _name_cache[("channel", c["id"])] = "#" + c["name"]
        msgs = slack_api(token, "conversations.history", {"channel": c["id"], "limit": per_channel})["messages"]
        for m in msgs:
            src = slack_event_to_source({**m, "type": "message", "channel": c["id"]}, token)
            if src:
                out.append(src)
    return out


def slack_manifest(base_url: str, slug: str, company: str) -> dict:
    """A Slack app manifest with this workspace's URLs filled in (Slack: Create app -> From a manifest)."""
    return {
        "display_information": {"name": "Company Brain", "description": f"Ask {company}'s company brain",
                                "background_color": "#0b0b12"},
        "features": {"bot_user": {"display_name": "Company Brain", "always_online": True},
                     "slash_commands": [{"command": "/brain", "url": f"{base_url}/slack/{slug}/command",
                                         "description": "Ask the company brain", "usage_hint": "Who owns checkout?",
                                         "should_escape": False}]},
        "oauth_config": {"scopes": {"bot": ["commands", "channels:history", "channels:read", "users:read",
                                            "chat:write"]}},
        "settings": {"event_subscriptions": {"request_url": f"{base_url}/slack/{slug}/events",
                                             "bot_events": ["message.channels"]},
                     "org_deploy_enabled": False, "socket_mode_enabled": False, "token_rotation_enabled": False},
    }


# ---------------- incoming webhooks (Jira, Linear, GitHub, generic) ----------------

def _adf_text(node) -> str:
    """Jira Cloud sends rich text as Atlassian Document Format; flatten it."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return " ".join(_adf_text(c) for c in node.get("content", []))
    if isinstance(node, list):
        return " ".join(_adf_text(c) for c in node)
    return ""


def parse_inbound(payload: dict, headers=None) -> tuple[str, list[dict]]:
    """Recognise the sender and turn its payload into knowledge items. Returns (platform, items)."""
    headers = headers or {}
    today = time.strftime("%Y-%m-%d")

    # Jira
    if "webhookEvent" in payload and ("issue" in payload or "comment" in payload):
        issue = payload.get("issue") or {}
        f = issue.get("fields") or {}
        key = re.sub(r"[^A-Z0-9-]", "", (issue.get("key") or "").upper())[:20]
        items = []
        if issue and payload["webhookEvent"].startswith("jira:issue"):
            status = ((f.get("status") or {}).get("statusCategory") or {}).get("key", "")
            items.append({"kind": "ticket", "key": key, "title": f.get("summary", ""),
                          "text": _adf_text(f.get("description")) or f.get("summary", ""),
                          "author": (f.get("reporter") or {}).get("displayName", ""),
                          "assignee": (f.get("assignee") or {}).get("displayName", ""),
                          "status": {"done": "done", "indeterminate": "in_progress"}.get(status, "todo"),
                          "date": (f.get("created") or today)[:10]})
        if payload.get("comment"):
            c = payload["comment"]
            items.append({"kind": "message", "channel": "#jira",
                          "text": f"On {key}: {_adf_text(c.get('body'))}".strip(),
                          "author": (c.get("author") or {}).get("displayName", ""), "date": (c.get("created") or today)[:10]})
        return "jira", items

    # Linear
    if payload.get("type") in ("Issue", "Comment") and isinstance(payload.get("data"), dict) and "action" in payload:
        d = payload["data"]
        if payload["type"] == "Issue":
            state = ((d.get("state") or {}).get("type") or "")
            return "linear", [{"kind": "ticket", "key": re.sub(r"[^A-Z0-9-]", "", (d.get("identifier") or "").upper())[:20],
                               "title": d.get("title", ""), "text": d.get("description") or d.get("title", ""),
                               "author": (d.get("creator") or {}).get("name", ""),
                               "assignee": (d.get("assignee") or {}).get("name", ""),
                               "status": {"completed": "done", "started": "in_progress", "canceled": "done"}.get(state, "todo"),
                               "date": (d.get("createdAt") or today)[:10]}]
        issue = (d.get("issue") or {}).get("identifier", "")
        return "linear", [{"kind": "message", "channel": "#linear", "text": f"On {issue}: {d.get('body', '')}".strip(),
                           "author": (d.get("user") or {}).get("name", ""), "date": (d.get("createdAt") or today)[:10]}]

    # GitHub webhooks
    gh_event = headers.get("x-github-event", "")
    if gh_event in ("issues", "issue_comment", "pull_request") or ("repository" in payload and "sender" in payload):
        repo = (payload.get("repository") or {}).get("name", "")
        if "comment" in payload and payload.get("issue"):
            n = payload["issue"]["number"]
            return "github", [{"kind": "message", "channel": f"#{repo}",
                               "text": f"On GH-{n} in {repo}: {payload['comment'].get('body', '')}",
                               "author": (payload["comment"].get("user") or {}).get("login", ""), "date": today}]
        if payload.get("pull_request"):
            pr = payload["pull_request"]
            return "github", [{"kind": "doc", "key": f"PR-{pr['number']}", "title": f"PR #{pr['number']}: {pr.get('title', '')}",
                               "text": f"{repo}: {pr.get('body') or pr.get('title', '')}", "author": (pr.get("user") or {}).get("login", ""),
                               "date": (pr.get("created_at") or today)[:10]}]
        if payload.get("issue"):
            it = payload["issue"]
            return "github", [{"kind": "ticket", "key": f"GH-{it['number']}", "title": it.get("title", ""),
                               "text": f"{repo}: {it.get('body') or it.get('title', '')}",
                               "author": (it.get("user") or {}).get("login", ""),
                               "assignee": (it.get("assignee") or {}).get("login", ""),
                               "status": "done" if it.get("state") == "closed" else ("in_progress" if it.get("assignee") else "todo"),
                               "date": (it.get("created_at") or today)[:10]}]
        return "github", []

    # Generic (Zapier, Make, n8n, scripts): one item or {"items": [...]}
    raw = payload.get("items") if isinstance(payload.get("items"), list) else [payload]
    items = []
    for o in raw[:200]:
        if not isinstance(o, dict):
            continue
        text = o.get("text") or o.get("content") or o.get("body") or o.get("message") or ""
        if not str(text).strip():
            continue
        kind = str(o.get("kind") or o.get("type") or "message").lower()
        items.append({"kind": kind if kind in ("doc", "ticket", "message", "meeting") else "message",
                      "text": str(text)[:4000], "title": str(o.get("title") or "")[:200],
                      "author": str(o.get("author") or o.get("user") or o.get("from") or "")[:60],
                      "channel": str(o.get("channel") or o.get("source") or "")[:40],
                      "status": str(o.get("status") or "")[:20], "assignee": str(o.get("assignee") or "")[:60],
                      "key": str(o.get("key") or o.get("id") or "")[:20], "date": str(o.get("date") or today)[:10]})
    return "generic", items
