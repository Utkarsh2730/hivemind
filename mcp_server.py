"""MCP server for Company Brain: use a company's brain from Claude Desktop, Cursor or any MCP client.

It talks to a running Company Brain site over HTTP, so it works with the hosted version.

Setup (Claude Desktop, claude_desktop_config.json):
  {"mcpServers": {"company-brain": {"command": "python3", "args": ["/path/to/mcp_server.py"],
     "env": {"BRAIN_URL": "https://your-site.onrender.com", "BRAIN_WORKSPACE": "your-workspace-slug",
             "BRAIN_KEY": "your-private-key"}}}}
Requires: pip install mcp
"""
import json
import os
import urllib.error
import urllib.request

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

BASE = os.environ.get("BRAIN_URL", "http://localhost:8000").rstrip("/")
SLUG = os.environ.get("BRAIN_WORKSPACE", "demo")
KEY = os.environ.get("BRAIN_KEY", "")

server = _Server("company-brain", instructions=(
    "Company Brain holds this company's people, teams, projects, tools, docs, tickets, chats and decisions as a "
    "knowledge graph. Use ask_company for questions (who owns/knows what, why decisions were made), "
    "write_prd / write_sprint_plan for planning documents, and add_to_brain to record new knowledge. "
    "Keep the [KEY] citations in answers so people can check the sources."))


def _call(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{BASE}/api/w/{SLUG}{path}", headers={"X-Workspace-Key": KEY,
                                                                       "Content-Type": "application/json"})
    if body is not None:
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail")
        except Exception:
            detail = None
        raise RuntimeError(detail if isinstance(detail, str) else f"Company Brain returned HTTP {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Company Brain at {BASE}: {e.reason}")


def _with_sources(text: str, citations: list) -> str:
    if not citations:
        return text
    lines = [f"[{c['key']}] {c['title']} ({c.get('author') or c.get('kind')}, {c.get('date') or ''})" for c in citations]
    return text + "\n\nSources:\n" + "\n".join(lines)


@server.tool()
def ask_company(question: str) -> str:
    """Ask the company brain a question, e.g. who owns a project, who knows a system, why a decision was made,
    what is blocked, or where the knowledge risks are. Returns an answer with [KEY] citations and the sources."""
    r = _call("/ask", {"question": question[:400]})
    return _with_sources(r["answer"], r.get("citations", []))


@server.tool()
def list_projects() -> str:
    """List the company's projects (use the key with write_prd / write_sprint_plan)."""
    m = _call("/meta")
    return "\n".join(f"{p['key']}: {p['name']}" for p in m.get("projects", [])) or "No projects yet."


@server.tool()
def write_prd(project: str, goal: str = "") -> str:
    """Write a PRD for a project from the company's decisions, tickets, blockers and experts.
    project: a project key from list_projects (e.g. project:checkout) or its name. goal: optional."""
    r = _call("/generate", {"kind": "prd", "project": _project_key(project), "goal": goal[:300]})
    return r["markdown"]


@server.tool()
def write_sprint_plan(project: str, weeks: int = 2, goal: str = "") -> str:
    """Write a prioritised sprint plan (blockers first, owners from assignees and experts) for a project.
    project: a project key from list_projects or its name. weeks: 1-4."""
    r = _call("/generate", {"kind": "sprint", "project": _project_key(project), "weeks": max(1, min(int(weeks), 4)),
                            "goal": goal[:300]})
    return r["markdown"]


@server.tool()
def add_to_brain(text: str, author: str = "", kind: str = "message", title: str = "") -> str:
    """Record new company knowledge (kind: message, doc, meeting or ticket). It is linked to people, projects
    and tools automatically, and a decision that replaces an older one marks the old one outdated."""
    r = _call("/knowledge", {"text": text[:4000], "author": author[:60], "kind": kind, "title": title[:200]})
    out = f"Added {r['source']}, linked to {len(r['mentions'])} people/projects/tools."
    if r.get("decision"):
        out += f" New decision {r['decision']['key']}: {r['decision']['title']}."
    if r.get("superseded"):
        out += f" Marked {', '.join(r['superseded'])} as outdated."
    return out


def _project_key(project: str) -> str:
    if project.startswith("project:"):
        return project
    for p in _call("/meta").get("projects", []):
        if p["name"].lower() == project.strip().lower():
            return p["key"]
    raise RuntimeError(f"No project named '{project}'. Use list_projects to see them.")


if __name__ == "__main__":
    server.run()
