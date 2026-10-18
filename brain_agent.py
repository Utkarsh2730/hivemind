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

SYSTEM = f"""You are the Company Brain for Lumen Pay. Company knowledge (people, teams, projects, systems,
docs, tickets, chat messages, meeting notes and decisions) lives in a FalkorDB graph.

Rules:
- Answer only from tool results. If the graph does not contain the answer, say so plainly.
- Prefer the specialised tools: decision_trail for why/what-changed questions, who_knows for who-to-ask
  questions (it separates hands-on knowledge from formal ownership), entity_profile for ownership, status,
  tickets and blockers, search_knowledge for anything else. Use run_cypher only when those cannot answer.
- Distinguish active from superseded decisions and always state the current one.
- Cite every factual claim with the source or decision key in square brackets, e.g. [DOC-1] [DEC-4] [MSG-4].
- Be concise: 3-7 short sentences or bullets. Name people with their role.

Graph schema:
{T.SCHEMA}"""


def _claude_answer(question: str):
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
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": os.environ.get("BRAIN_EFFORT", "medium")},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=[search_knowledge, entity_profile, who_knows, decision_trail, run_cypher],
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
    if re.search(r"\b(who)\b.*\b(ask|know|knows|expert|help)\b|\bexpert", q):
        r = json.loads(T.who_knows(question))
        if "error" not in r and r["experts"]:
            top = r["experts"][0]
            ev = " ".join(f"[{e['key']}]" for e in top["evidence"][:4])
            others = "; ".join(f"{e['name']} ({e['role']})" for e in r["experts"][1:3])
            owners = sorted({o["name"] for o in r["formal_owners"]})
            return (f"Ask **{top['name']}** ({top['role']}, {top['team']}). They have the strongest hands-on "
                    f"evidence on {r['topic'][0]['name']} {ev}.\n\nAlso knowledgeable: {others}.\n\n"
                    f"Formal owners of related projects: {', '.join(owners)}. Ownership and know-how are not "
                    f"the same person here.")
    if re.search(r"\b(block|blocked|blocking|unblock)", q):
        r = json.loads(T.entity_profile(question))
        if "blocked_by" in r and r["blocked_by"]:
            b = r["blocked_by"][0]
            p = r["profile"][0]
            return (f"{r['entity']['name']} ({p['status']}, led by {p['lead']}) is blocked by **{b['key']}: "
                    f"{b['title']}** ({b['status']}) [{b['key']}] [{b['blocks']}]. "
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
            tk = "; ".join(f"{t['key']} {t['title']} ({t['status']}, {t['assignee']}) [{t['key']}]" for t in r["tickets"])
            return (f"**{r['entity']['name']}** is owned by the {p['owning_team']} team and led by "
                    f"{p['lead']}. Status: {p['status']}. Tickets: {tk or 'none'}.")
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


def answer(question: str, mode: str = "auto") -> dict:
    use_claude = has_credentials() if mode == "auto" else mode == "claude"
    with T.Trace() as tr:
        text = _claude_answer(question) if use_claude else _offline_answer(question)
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
