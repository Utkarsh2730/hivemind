"""Generate a PRD or a sprint plan for a project from the company graph.

The graph supplies the facts (owners, decisions and why, open tickets, blockers, who knows which system).
Claude writes the document when a key is set; otherwise a template fills it from the same facts.
Every fact carries its source key, e.g. [DEC-4] or [PAY-52].
"""
import json
import os
from datetime import date, timedelta

import brain_tools as T
from graph_db import get_graph


def _q(query, params=None):
    res = get_graph().ro_query(query, params or {})
    cols = [h[1] for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


def projects():
    return _q("MATCH (p:Project) OPTIONAL MATCH (s:Source)-[:MENTIONS]->(p) "
              "RETURN p.key AS key, p.name AS name, count(s) AS sources ORDER BY sources DESC, name")


def project_context(project_key: str) -> dict:
    """Everything the graph knows about one project, with source keys on every fact."""
    p = _q("MATCH (p:Project {key: $k}) OPTIONAL MATCH (t:Team)-[:OWNS]->(p) OPTIONAL MATCH (l:Person)-[:LEADS]->(p) "
           "RETURN p.name AS name, p.status AS status, t.name AS team, t.key AS team_key, l.name AS lead, l.role AS lead_role",
           {"k": project_key})
    if not p:
        raise ValueError("Project not found.")
    ctx = {"project": p[0]}
    ctx["systems"] = _q("MATCH (:Project {key: $k})-[:USES]->(s) RETURN s.key AS key, s.name AS name", {"k": project_key})
    sys_keys = [s["key"] for s in ctx["systems"]]
    ctx["team_members"] = _q("MATCH (m:Person)-[:MEMBER_OF]->(:Team {key: $t}) RETURN m.name AS name, m.role AS role",
                             {"t": p[0]["team_key"] or ""})
    ctx["decisions"] = _q(
        "MATCH (d:Decision)-[:AFFECTS]->(e) WHERE e.key = $k OR e.key IN $s "
        "OPTIONAL MATCH (m:Person)-[:MADE]->(d) OPTIONAL MATCH (d)-[:DECIDED_IN]->(src) "
        "OPTIONAL MATCH (n:Decision)-[:SUPERSEDES]->(d) OPTIONAL MATCH (d)-[:AFFECTS]->(sx:System) "
        "RETURN DISTINCT d.key AS key, collect(DISTINCT sx.key) AS systems, d.title AS title, d.summary AS summary, d.date AS date, d.status AS status, "
        "collect(DISTINCT m.name) AS made_by, collect(DISTINCT src.key) AS sources, n.key AS replaced_by "
        "ORDER BY date", {"k": project_key, "s": sys_keys})
    # Tickets about the project, plus anything blocking them (even in other projects).
    team_key = p[0]["team_key"] or ""
    tkeys = [r["key"] for r in _q("MATCH (t:Source {kind: 'ticket'})-[:MENTIONS]->(:Project {key: $k}) RETURN t.key AS key",
                                  {"k": project_key})]
    # The team's tickets about this project's systems, when this project is the best match for the ticket's tools.
    uses = {r["p"]: set(r["s"]) for r in _q("MATCH (p:Project)-[:USES]->(s) RETURN p.key AS p, collect(s.key) AS s")}
    for r in _q("MATCH (t:Source {kind: 'ticket'})-[:MENTIONS]->(s:System), (t)-[:ASSIGNED_TO]->(:Person)-[:MEMBER_OF]->(:Team {key: $team}) "
                "WHERE s.key IN $s MATCH (t)-[:MENTIONS]->(all:System) RETURN t.key AS key, collect(DISTINCT all.key) AS systems",
                {"s": sys_keys, "team": team_key}):
        overlap = {pk: len(ss & set(r["systems"])) for pk, ss in uses.items()}
        if overlap.get(project_key, 0) >= max(overlap.values(), default=0):
            tkeys.append(r["key"])
    ctx["tickets"] = _q(
        "MATCH (t:Source) WHERE t.key IN $keys "
        "OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a) OPTIONAL MATCH (b:Source)-[:BLOCKS]->(t) "
        "OPTIONAL MATCH (t)-[:BLOCKS]->(x:Source) "
        "RETURN t.key AS key, t.title AS title, t.status AS status, t.text AS text, a.name AS assignee, "
        "t.date AS date, collect(DISTINCT b.key) AS blocked_by, collect(DISTINCT x.key) AS blocks ORDER BY date",
        {"keys": list(dict.fromkeys(tkeys))})
    known = {t["key"] for t in ctx["tickets"]}
    for t in list(ctx["tickets"]):
        for b in t["blocked_by"]:
            if b not in known:
                known.add(b)
                ctx["tickets"] += _q(
                    "MATCH (t:Source {key: $b}) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a) OPTIONAL MATCH (t)-[:BLOCKS]->(x) "
                    "RETURN t.key AS key, t.title AS title, t.status AS status, t.text AS text, a.name AS assignee, "
                    "t.date AS date, [] AS blocked_by, collect(x.key) AS blocks", {"b": b})
    ctx["sources"] = _q(
        "MATCH (s:Source)-[:MENTIONS]->(e) WHERE e.key = $k OR e.key IN $s OPTIONAL MATCH (a:Person)-[:AUTHORED]->(s) "
        "RETURN DISTINCT s.key AS key, s.kind AS kind, s.title AS title, s.date AS date, a.name AS author, s.text AS text "
        "ORDER BY date DESC LIMIT 25", {"k": project_key, "s": sys_keys})
    ctx["experts"] = []
    for s in ctx["systems"]:
        r = json.loads(T.who_knows(s["name"]))
        top = r.get("experts", [])[:2]
        ctx["experts"].append({"system": s["name"], "key": s["key"],
                               "people": [{"name": e["name"], "role": e.get("role"), "score": e["score"],
                                           "evidence": [x["key"] for x in e["evidence"][:3]]} for e in top]})
    return ctx


# ---------------- helpers ----------------

def _cite(keys):
    return " ".join(f"[{k}]" for k in keys if k)


def _first_sentence(text, n=160):
    t = (text or "").strip().replace("\n", " ")
    cut = t.split(". ")[0]
    return (cut[:n] + "...") if len(cut) > n else cut.rstrip(".") + "."


def _owner_for(ticket, ctx):
    if ticket.get("assignee"):
        return ticket["assignee"]
    text = (ticket.get("title", "") + " " + ticket.get("text", "")).lower()
    for e in ctx["experts"]:
        if e["system"].lower() in text and e["people"]:
            return e["people"][0]["name"]
    return ctx["project"]["lead"] or "Unassigned"


def _priority(ticket):
    if ticket["status"] == "blocked" or ticket["blocks"]:
        return "P0"
    if ticket["status"] == "in_progress":
        return "P1"
    return "P2"


def _risks(ctx):
    risks = []
    for t in ctx["tickets"]:
        if t["status"] != "done" and t["blocks"]:
            risks.append(f"**{t['key']} ({t['title']})** is still {t['status'].replace('_', ' ')} and blocks "
                         f"{', '.join(t['blocks'])}. {_cite([t['key']] + t['blocks'])}")
    for e in ctx["experts"]:
        if len(e["people"]) == 1:
            p = e["people"][0]
            risks.append(f"Only **{p['name']}** has hands-on evidence on {e['system']}, so knowledge of it depends "
                         f"on one person. {_cite(p['evidence'])}")
    for d in ctx["decisions"]:
        if d["status"] == "superseded" and d["replaced_by"]:
            risks.append(f"The earlier decision \"{d['title']}\" was replaced by {d['replaced_by']}. Make sure work "
                         f"and docs built on the old decision are updated. {_cite([d['key'], d['replaced_by']])}")
    return risks


def _open_items(ctx):
    items = [t for t in ctx["tickets"] if t["status"] != "done"]
    # Recent active decisions without a ticket become rollout items.
    ticketed = " ".join(t["text"] or "" for t in ctx["tickets"])
    for d in ctx["decisions"]:
        # Only technical decisions (ones that touch a system) need rollout work.
        if d["status"] == "active" and d["systems"] and d["key"] not in ticketed \
                and d["date"] >= (date.today() - timedelta(days=120)).isoformat():
            items.append({"key": d["key"], "title": f"Plan and roll out: {d['title']}", "status": "todo",
                          "text": d["summary"], "assignee": (d["made_by"] or [None])[0], "blocked_by": [], "blocks": [],
                          "decision": True})
    order = {"P0": 0, "P1": 1, "P2": 2}
    # Within a priority, work that unblocks others comes first.
    return sorted(items, key=lambda t: (order[_priority(t)], 0 if t["blocks"] else 1))


# ---------------- template writers (no API key) ----------------

def template_prd(ctx, goal):
    p = ctx["project"]
    active = [d for d in ctx["decisions"] if d["status"] == "active"]
    replaced = [d for d in ctx["decisions"] if d["status"] != "active"]
    title = goal.strip() or p["name"]
    L = [f"# PRD: {title}", "",
         f"**Project:** {p['name']} · **Owning team:** {p['team'] or 'n/a'} · **Lead:** {p['lead'] or 'n/a'} · "
         f"**Status:** {p['status']} · **Date:** {date.today().isoformat()}", "",
         "## 1. Summary"]
    if goal.strip():
        L.append(f"Goal: **{goal.strip()}**. This document collects what the company already knows about "
                 f"{p['name']}, so the team can start from facts instead of rediscovering them.")
    else:
        L.append(f"This document collects what the company already knows about {p['name']}: the decisions made "
                 f"so far, the open work, who owns it and who knows it best.")
    L += ["", "## 2. Background"]
    for s in ctx["sources"][:6]:
        same = (s["text"] or "").startswith((s["title"] or "").rstrip(".").rstrip())
        head = "" if same else f"{s['title']}: "
        L.append(f"- {head}{_first_sentence(s['text'])} ({s['author'] or 'unknown'}, {s['date']}) [{s['key']}]")
    if not ctx["sources"]:
        L.append("- No sources mention this project yet. Add docs or messages to enrich this section.")
    L += ["", "## 3. Decisions already made"]
    for d in active:
        L.append(f"- **{d['title']}** ({d['date']}, by {', '.join(d['made_by']) or 'n/a'}): {d['summary']} "
                 f"{_cite([d['key']] + d['sources'])}")
    for d in replaced:
        L.append(f"- Replaced: ~~{d['title']}~~ ({d['date']}), superseded by {d['replaced_by']}. {_cite([d['key']])}")
    if not ctx["decisions"]:
        L.append("- No recorded decisions yet.")
    L += ["", "## 4. Goals"]
    if goal.strip():
        L.append(f"- {goal.strip()}")
    for t in _open_items(ctx)[:5]:
        L.append(f"- {t['title']} {_cite([t['key']])}")
    L += ["", "## 5. Scope", "**In scope**"]
    for t in _open_items(ctx):
        L.append(f"- {t['title']}: {_first_sentence(t['text'], 120)} {_cite([t['key']])}")
    L += ["", "**Out of scope (to confirm)**",
          "- Reversing current decisions without a new review. " + _cite([d["key"] for d in active][:3]), "",
          "## 6. Technical approach"]
    for s in ctx["systems"]:
        related = [d for d in active if d["title"] and s["name"].lower() in (d["title"] + d["summary"]).lower()]
        L.append(f"- **{s['name']}**" + (f": {related[0]['title']} {_cite([related[0]['key']])}" if related else ""))
    if not ctx["systems"]:
        L.append("- No systems recorded for this project yet.")
    L += ["", "## 7. People"]
    L.append(f"- **Lead:** {p['lead'] or 'n/a'}" + (f" ({p['lead_role']})" if p.get("lead_role") else ""))
    if ctx["team_members"]:
        L.append(f"- **Team ({p['team']}):** " + ", ".join(m["name"] for m in ctx["team_members"]))
    for e in ctx["experts"]:
        if e["people"]:
            L.append(f"- **Ask about {e['system']}:** " + ", ".join(x["name"] for x in e["people"]) + " "
                     + _cite(e["people"][0]["evidence"][:2]))
    L += ["", "## 8. Risks and dependencies"]
    L += [f"- {r}" for r in _risks(ctx)] or ["- No risks found in the graph."]
    L += ["", "## 9. Success metrics",
          "- To be defined with the lead. Suggested: delivery of the P0/P1 items above, and no open blockers.", "",
          "## 10. Open questions"]
    unassigned = [t for t in _open_items(ctx) if not t.get("assignee")]
    for t in unassigned[:3]:
        L.append(f"- Who owns \"{t['title']}\"? {_cite([t['key']])}")
    L.append(f"- Confirm goals, scope and metrics with {p['lead'] or 'the project lead'}.")
    return "\n".join(L)


def template_sprint(ctx, goal, weeks):
    p = ctx["project"]
    items = _open_items(ctx)
    start = date.today()
    end = start + timedelta(weeks=weeks) - timedelta(days=1)
    top = next((t for t in items if _priority(t) == "P0"), items[0] if items else None)
    if goal.strip():
        sprint_goal = goal.strip()
    elif top and _priority(top) == "P0":
        sprint_goal = f"Unblock {p['name']} by finishing \"{top['title']}\""
    elif top:
        sprint_goal = f"Move {p['name']} forward: deliver \"{top['title']}\""
    else:
        sprint_goal = f"Plan the next milestone for {p['name']}"
    L = [f"# Sprint plan: {p['name']}", "",
         f"**Sprint:** {start.isoformat()} to {end.isoformat()} ({weeks} week{'s' if weeks > 1 else ''}) · "
         f"**Lead:** {p['lead'] or 'n/a'} · **Team:** {p['team'] or 'n/a'}", "",
         f"## Sprint goal", f"{sprint_goal}." + (f" {_cite([top['key']])}" if top and not goal.strip() else ""), "",
         "## Backlog (prioritised from the graph)",
         "| # | Item | Owner | Priority | Why | Source |", "|---|---|---|---|---|---|"]
    for i, t in enumerate(items, 1):
        pr = _priority(t)
        why = ("Blocks " + ", ".join(t["blocks"])) if t["blocks"] else \
              ("Currently blocked" if t["status"] == "blocked" else
               ("Recent decision, not yet planned" if t.get("decision") else t["status"].replace("_", " ")))
        L.append(f"| {i} | {t['title']} | {_owner_for(t, ctx)} | {pr} | {why} | [{t['key']}] |")
    if not items:
        L.append("| - | No open items found. Add tickets or decisions for this project. | | | | |")
    L += ["", "## Plan by week"]
    if items:
        per = -(-len(items) // weeks)  # ceil: items are already in priority order
        for w in range(weeks):
            chunk = items[w * per:(w + 1) * per]
            if chunk:
                L.append(f"**Week {w + 1}:** " + ", ".join(f"{t['title']} [{t['key']}]" for t in chunk))
    else:
        L.append("**Week 1:** Discovery: collect requirements and create tickets.")
    L += ["", "## Risks"]
    L += [f"- {r}" for r in _risks(ctx)] or ["- No risks found in the graph."]
    L += ["", "## Who to ask"]
    for e in ctx["experts"]:
        if e["people"]:
            L.append(f"- {e['system']}: " + ", ".join(x["name"] for x in e["people"]) + " " + _cite(e["people"][0]["evidence"][:2]))
    L += ["", "## Definition of done",
          "- Code reviewed and merged, tests passing.",
          "- The related ticket is updated, and any new decision is posted so the brain stays current."]
    return "\n".join(L)


# ---------------- Claude writer ----------------

PROMPTS = {
    "prd": ("Write a product requirements document (PRD) in Markdown with these sections: Summary, Background, "
            "Decisions already made, Goals, Non-goals, Scope (in/out), Requirements (numbered, with acceptance criteria), "
            "Technical approach, People (lead, team, who to ask about each system), Risks and dependencies, "
            "Success metrics, Open questions."),
    "sprint": ("Write a sprint plan in Markdown with these sections: Sprint goal, Backlog as a table "
               "(# | Item | Owner | Priority P0-P2 | Estimate S/M/L | Why | Source), Plan by week, Risks, "
               "Who to ask, Definition of done. Prioritise blockers first, then in-progress work, then new work. "
               "Assign owners from ticket assignees or from the people with hands-on evidence for that system."),
}


def _claude_write(kind, ctx, goal, weeks, company):
    import anthropic
    instructions = PROMPTS[kind] + (f" The sprint is {weeks} week(s) starting {date.today().isoformat()}." if kind == "sprint" else "")
    prompt = (
        f"Company: {company}\nProject facts from the company knowledge graph (JSON):\n{json.dumps(ctx, default=str)[:60000]}\n\n"
        f"Goal from the user (may be empty): {goal or '(none given)'}\n\n{instructions}\n\n"
        "Rules: use only facts from the JSON. Cite every fact with its key in square brackets, e.g. [DEC-4] or [PAY-52]. "
        "Where you must add something the graph doesn't contain (estimates, metrics, requirements detail), mark it "
        "'(proposed)'. Name people exactly as in the JSON. Be concise and practical. Start with a # title."
    )
    client = anthropic.Anthropic()
    with client.messages.stream(
        model="claude-opus-5-5", max_tokens=16000,
        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("declined")
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def generate(kind: str, project_key: str, goal: str = "", weeks: int = 2, company: str = "the company") -> dict:
    if kind not in PROMPTS:
        raise ValueError("Unknown document type.")
    weeks = max(1, min(int(weeks or 2), 4))
    ctx = project_context(project_key)
    mode = "template"
    text = None
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        try:
            text, mode = _claude_write(kind, ctx, goal, weeks, company), "claude"
        except Exception as e:
            print("Claude document generation failed, using template:", e)
    if not text:
        text = template_prd(ctx, goal) if kind == "prd" else template_sprint(ctx, goal, weeks)
    import re
    from brain_agent import citations
    cited = list(dict.fromkeys(re.findall(r"\[([A-Z]{2,5}-\d+)\]", text)))
    highlight = cited + [project_key] + [s["key"] for s in ctx["systems"]]
    return {"markdown": text, "mode": mode, "citations": citations(cited), "highlight": highlight, "cited": cited,
            "title": ctx["project"]["name"]}
