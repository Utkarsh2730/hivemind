"""Company brain agent. Claude plans over graph tools; without credentials a rule-based planner runs the
same tools so the demo still works ("graph-only mode").

CLI: python brain_agent.py "Who should I ask about Kafka consumer lag?"
"""
import json
import os
import re
import sys

import brain_tools as T
from graph_db import get_graph

CITE_RE = re.compile(r"\[((?:[A-Z]{2,5})-\d+)\]")

SYSTEM = """You are the Company Brain for {company}. Company knowledge (people, teams, projects, systems,
docs, tickets, chat messages, meeting notes and decisions) lives in a FalkorDB graph.

Rules:
- Answer only from tool results. If the graph does not contain the answer, say so plainly.
- For risks, bus factor, key people or "what should leadership worry about", use company_insights.
- Prefer the specialised tools: decision_trail for why/what-changed questions, who_knows for who-to-ask
  questions (it separates hands-on knowledge from formal ownership), entity_profile for ownership, status,
  tickets and blockers, search_knowledge for anything else. Use run_cypher only when those cannot answer.
- Distinguish active from superseded decisions and always state the current one.
- Cite every factual claim with the source or decision key in square brackets, e.g. [DOC-1] [DEC-4] [MSG-4].
- Be concise: 3-7 short sentences or bullets. Name people with their role.

Graph schema:
{schema}"""


def _claude_answer(question: str, company: str):
    import anthropic
    from anthropic import beta_tool

    @beta_tool
    def search_knowledge(query: str) -> str:
        """Full-text and entity search over docs, tickets, chat messages, meeting notes and decisions.

        Args:
            query: Natural-language search terms.
        """
        return T.search_knowledge(query)

    @beta_tool
    def entity_profile(name: str) -> str:
        """Everything the graph knows about a person, team, project or system: role, team, ownership, lead,
        status, systems used, tickets (with assignees and blockers), decisions and recent sources.

        Args:
            name: Entity name, e.g. "Payments Gateway", "Tomas", "Kafka", "Platform".
        """
        return T.entity_profile(name)

    @beta_tool
    def who_knows(topic: str) -> str:
        """Rank people by evidence of hands-on knowledge of a system or project (authored sources, assigned
        tickets, being named by colleagues, decisions made), plus the formal owners for contrast.

        Args:
            topic: A system or project name, e.g. "Kafka".
        """
        return T.who_knows(topic)

    @beta_tool
    def decision_trail(topic: str) -> str:
        """Decisions about a topic in date order with who made them, the source documents, and which decision
        superseded which.

        Args:
            topic: A project, system or subject, e.g. "customer login" or "ledger".
        """
        return T.decision_trail(topic)

    @beta_tool
    def company_insights() -> str:
        """Company-wide knowledge risks from graph algorithms: key connectors (betweenness centrality), central
        topics (PageRank), systems only one person knows, stalled or blocking tickets, and unconnected knowledge."""
        import brain_insights
        return T._record("company_insights", {"scope": "whole company"}, brain_insights.insights())

    @beta_tool
    def run_cypher(query: str) -> str:
        """Run a read-only openCypher query against the graph (MATCH/RETURN only).

        Args:
            query: The Cypher query.
        """
        return T.run_cypher(query)

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5-5",
        max_tokens=16000,
        system=SYSTEM.format(company=company, schema=T.SCHEMA),
        thinking={"type": "adaptive"},
        output_config={"effort": os.environ.get("BRAIN_EFFORT", "medium")},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=[search_knowledge, entity_profile, who_knows, decision_trail, company_insights, run_cypher],
        messages=[{"role": "user", "content": question}],
    )
    final = None
    for message in runner:
        final = message
    if final is None:
        return "No answer was produced."
    if final.stop_reason == "refusal":
        return "The request was declined."
    return "".join(b.text for b in final.content if b.type == "text").strip()


# ---------------- graph-only planner ----------------

def _fmt_people(ps):
    return ", ".join(f"{p['name']}" for p in ps)


def _offline_answer(question: str) -> str:
    q = question.lower()
    if re.search(r"\b(risk|risks|bus factor|single point|key people|critical people|insight|worry|stalled|silo)", q):
        import brain_insights
        text, keys = brain_insights.insights_text()
        T._record("company_insights", {"scope": "whole company"}, {"keys": [{"key": k} for k in keys]})
        return text
    if re.search(r"\b(who)\b.*\b(ask|know|knows|expert|help)\b|\bexpert", q):
        r = json.loads(T.who_knows(question))
        if "error" not in r and r["experts"]:
            top = r["experts"][0]
            ev = " ".join(f"[{e['key']}]" for e in top["evidence"][:4])
            role = ", ".join(x for x in (top.get("role"), top.get("team")) if x)
            text = (f"Ask **{top['name']}**{f' ({role})' if role else ''}. They have the strongest hands-on "
                    f"evidence on {r['topic'][0]['name']} {ev}.")
            others = [f"{e['name']}" + (f" ({e['role']})" if e.get("role") else "") for e in r["experts"][1:3]]
            if others:
                text += f"\n\nAlso knowledgeable: {'; '.join(others)}."
            owners = sorted({o["name"] for o in r["formal_owners"]})
            if owners and owners != [top["name"]]:
                text += (f"\n\nFormal owners of related projects: {', '.join(owners)}. "
                         f"Knowing a system and owning it are not always the same person.")
            return text
    if re.search(r"\b(block|blocked|blocking|unblock)", q):
        r = json.loads(T.entity_profile(question))
        if "blocked_by" in r and r["blocked_by"]:
            b = r["blocked_by"][0]
            p = r["profile"][0]
            return (f"{r['entity']['name']} ({p['status'].replace('_', ' ')}, led by {p['lead']}) is blocked by **{b['key']}: "
                    f"{b['title']}** ({b['status'].replace('_', ' ')}) [{b['key']}] [{b['blocks']}]. "
                    f"{b['assignee']} is assigned and can unblock it.")
    if re.search(r"\b(why|decid|decision|chose|choose|changed|change|history)", q):
        r = json.loads(T.decision_trail(question))
        if r["decisions"]:
            lines = []
            for d in r["decisions"]:
                cites = " ".join(f"[{s['key']}]" for s in d["sources"])
                status = "current" if d["status"] == "active" else "outdated"
                rep = f" Later replaced by {d['superseded_by'][0]['key']}." if d["superseded_by"] else ""
                lines.append(f"- **{d['title']}** ({d['date']}, {status}) by {_fmt_people(d['made_by'])}. "
                             f"{d['summary']} [{d['key']}] {cites}{rep}")
            return "Here is how this was decided, oldest first:\n" + "\n".join(lines)
    if re.search(r"\b(own|owns|owner|lead|working on|status)\b", q):
        r = json.loads(T.entity_profile(question))
        if "profile" in r and r["entity"]["type"] == "Project":
            p = r["profile"][0]
            open_t = [t for t in r["tickets"] if t["status"] != "done"][:6]
            tk = "; ".join(f"{t['title']} ({t['status'].replace('_', ' ')}{', ' + t['assignee'] if t['assignee'] else ''}) [{t['key']}]"
                           for t in open_t)
            owner = f"owned by the {p['owning_team']} team" if p.get("owning_team") else "not assigned to a team yet"
            lead = f" and led by {p['lead']}" if p.get("lead") else ""
            return f"**{r['entity']['name']}** is {owner}{lead}. Status: {p['status']}. Tickets: {tk or 'none'}."
    r = json.loads(T.search_knowledge(question))
    if not r["sources"]:
        return "I couldn't find anything in the company graph about that."
    lines = [f"- {s['title']} ({s['kind']}, {s['author']}, {s['date']}) [{s['key']}]" for s in r["sources"][:5]]
    return "Most relevant knowledge:\n" + "\n".join(lines)


def has_credentials():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def citations(keys):
    rows = get_graph().ro_query(
        "MATCH (n) WHERE n.key IN $k AND (n:Source OR n:Decision) "
        "OPTIONAL MATCH (a:Person)-[:AUTHORED]->(n) "
        "RETURN n.key, labels(n)[0], coalesce(n.kind, 'decision'), n.title, coalesce(n.text, n.summary), n.date, "
        "a.name, n.status, n.channel", {"k": keys}).result_set
    by = {r[0]: dict(key=r[0], label=r[1], kind=r[2], title=r[3], text=r[4], date=r[5], author=r[6],
                     status=r[7], channel=r[8]) for r in rows}
    return [by[k] for k in keys if k in by]


def answer(question: str, mode: str = "auto", company: str = "this company", on_step=None) -> dict:
    """on_step(step, keys) is called as each graph tool runs, so the UI can show progress live."""
    use_claude = has_credentials() if mode == "auto" else mode == "claude"
    with T.Trace(on_step) as tr:
        text = _claude_answer(question, company) if use_claude else _offline_answer(question)
    cited = list(dict.fromkeys(CITE_RE.findall(text)))
    return {
        "answer": text,
        "mode": "claude" if use_claude else "graph-only",
        "citations": citations(cited),
        "trace": tr.steps,
        "highlight": list(dict.fromkeys(cited + tr.keys)),
        "cited": cited,
    }


if __name__ == "__main__":
    res = answer(" ".join(sys.argv[1:]) or "Who should I ask about Kafka consumer lag?")
    print(f"[{res['mode']}]\n{res['answer']}\n")
    for s in res["trace"]:
        print(" ->", s["tool"], json.dumps(s["args"]), f"({s['found']} nodes)")
    for c in res["citations"]:
        print(f" [{c['key']}] {c['title']} - {c['author'] or ''} {c['date']}")


def suggestions(limit: int = 5) -> list[str]:
    """Starter questions generated from what is actually in the workspace graph."""
    g = get_graph()
    q = []
    top_sys = g.ro_query("MATCH (s:Source)-[:MENTIONS]->(x:System) RETURN x.name, count(s) AS c ORDER BY c DESC LIMIT 1").result_set
    proj = g.ro_query("MATCH (p:Project) OPTIONAL MATCH (s:Source)-[:MENTIONS]->(p) "
                      "RETURN p.name, count(s) AS c ORDER BY c DESC LIMIT 2").result_set
    dec = g.ro_query("MATCH (d:Decision)-[:AFFECTS]->(e) RETURN e.name, count(d) AS c ORDER BY c DESC LIMIT 1").result_set
    blocked = g.ro_query("MATCH (b:Source)-[:BLOCKS]->(s)-[:MENTIONS]->(p:Project) RETURN p.name LIMIT 1").result_set
    if dec:
        q.append(f"Why did we decide what we did about {dec[0][0]}, and who made that call?")
    if top_sys:
        q.append(f"Who should I ask about {top_sys[0][0]}?")
    if blocked:
        q.append(f"Why is {blocked[0][0]} blocked and who can unblock it?")
    for name, _ in proj:
        q.append(f"Who owns {name} and what are they working on?")
    if g.ro_query("MATCH (s:Source) RETURN count(s)").result_set[0][0] >= 3:
        q.append("Where are our biggest knowledge risks?")
    return q[:limit]
