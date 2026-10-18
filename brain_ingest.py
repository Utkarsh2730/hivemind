"""Build the company brain graph and ingest new sources live.

Run: python brain_ingest.py   (rebuilds the graph from company_data.py)
"""
import json
import os
import re
from datetime import date

import company_data as cd
from graph_db import get_graph

DECISION_RE = re.compile(
    r"\b(decided|decision:|we will|we're moving|we are moving|go with|going with|approved|agreed|we freeze|switching to)\b",
    re.IGNORECASE,
)


# ---------- entity linking ----------

def _alias_table():
    """(compiled regex, entity key) for every alias, longest first so 'payments gateway' beats 'gateway'."""
    g = get_graph()
    rows = g.query("MATCH (e) WHERE e:Person OR e:Project OR e:System OR e:Team "
                   "RETURN e.key, e.name, e.aliases").result_set
    pairs = []
    for key, name, aliases in rows:
        for a in set([name.lower()] + [x.lstrip("@").lower() for x in (aliases or [])]):
            pairs.append((a, key))
    pairs.sort(key=lambda p: -len(p[0]))
    return [(re.compile(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", re.IGNORECASE), k) for a, k in pairs]


def link_entities(text: str, table=None) -> list[str]:
    table = table or _alias_table()
    found, taken = [], []
    for rx, key in table:
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            if key not in found:
                found.append(key)
    return found


# ---------- build ----------

def build():
    g = get_graph()
    try:
        g.delete()
    except Exception:
        pass
    g = get_graph()
    # Full-text index must exist before data is written.
    g.query("CALL db.idx.fulltext.createNodeIndex('Source', 'text', 'title')")
    g.query("CALL db.idx.fulltext.createNodeIndex('Decision', 'title', 'summary')")
    for label in ["Person", "Team", "Project", "System", "Source", "Decision", "Insight"]:
        g.query(f"CREATE INDEX FOR (n:{label}) ON (n.key)")

    for key, name in cd.TEAMS.items():
        g.query("CREATE (:Team {key: $k, name: $n, aliases: []})", {"k": key, "n": name})
    for key, name, role, team, aliases in cd.PEOPLE:
        g.query("MATCH (t:Team {key: $t}) CREATE (p:Person {key: $k, name: $n, role: $r, aliases: $a})-[:MEMBER_OF]->(t)",
                {"t": team, "k": key, "n": name, "r": role, "a": aliases})
    for key, name, status, team, lead, aliases in cd.PROJECTS:
        g.query("MATCH (t:Team {key: $t}), (l:Person {key: $l}) "
                "CREATE (p:Project {key: $k, name: $n, status: $s, aliases: $a}), (t)-[:OWNS]->(p), (l)-[:LEADS]->(p)",
                {"t": team, "l": lead, "k": key, "n": name, "s": status, "a": aliases})
    for key, name, aliases in cd.SYSTEMS:
        g.query("CREATE (:System {key: $k, name: $n, aliases: $a})", {"k": key, "n": name, "a": aliases})
    for p, s in cd.USES:
        g.query("MATCH (p:Project {key: $p}), (s:System {key: $s}) CREATE (p)-[:USES]->(s)", {"p": p, "s": s})

    table = _alias_table()
    for src in cd.SOURCES:
        _write_source(g, src, table)
    for a, b in cd.BLOCKS:
        g.query("MATCH (a:Source {key: $a}), (b:Source {key: $b}) CREATE (a)-[:BLOCKS]->(b)", {"a": a, "b": b})

    for key, title, summary, d, makers, affects, sources, supersedes in cd.DECISIONS:
        _write_decision(g, key, title, summary, d, makers, affects, sources)
        if supersedes:
            _supersede(g, key, supersedes)

    counts = g.query("MATCH (n) RETURN labels(n)[0], count(n) ORDER BY labels(n)[0]").result_set
    edges = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    print("Company brain built:", {l: c for l, c in counts}, "| edges:", edges)


def _write_source(g, src, table):
    title = src.get("title") or (src["text"][:60] + ("..." if len(src["text"]) > 60 else ""))
    g.query(
        "CREATE (s:Source {key: $k, kind: $kind, title: $title, text: $text, date: $d, channel: $ch, status: $st})",
        {"k": src["key"], "kind": src["kind"], "title": title, "text": src["text"], "d": src["date"],
         "ch": src.get("channel", ""), "st": src.get("status", "")},
    )
    g.query("MATCH (p:Person {key: $a}), (s:Source {key: $k}) CREATE (p)-[:AUTHORED]->(s)",
            {"a": src["author"], "k": src["key"]})
    if src.get("assignee"):
        g.query("MATCH (p:Person {key: $a}), (s:Source {key: $k}) CREATE (s)-[:ASSIGNED_TO]->(p)",
                {"a": src["assignee"], "k": src["key"]})
    mentions = link_entities(src.get("title") or "", table) + link_entities(src["text"], table)
    for m in dict.fromkeys(mentions):
        if m != src["author"]:
            g.query("MATCH (s:Source {key: $k}), (e {key: $m}) MERGE (s)-[:MENTIONS]->(e)", {"k": src["key"], "m": m})
    # Ticket references inside text (e.g. "PAY-52") become REFERENCES edges.
    for ref in set(re.findall(r"\b[A-Z]{2,5}-\d+\b", src["text"])):
        if ref != src["key"]:
            g.query("MATCH (s:Source {key: $k}), (r:Source {key: $r}) MERGE (s)-[:REFERENCES]->(r)",
                    {"k": src["key"], "r": ref})
    return mentions


def _write_decision(g, key, title, summary, d, makers, affects, sources):
    g.query("CREATE (:Decision {key: $k, title: $t, summary: $s, date: $d, status: 'active'})",
            {"k": key, "t": title, "s": summary, "d": d})
    for m in makers:
        g.query("MATCH (p:Person {key: $p}), (d:Decision {key: $k}) MERGE (p)-[:MADE]->(d)", {"p": m, "k": key})
    for a in affects:
        g.query("MATCH (e {key: $a}), (d:Decision {key: $k}) MERGE (d)-[:AFFECTS]->(e)", {"a": a, "k": key})
    for s in sources:
        g.query("MATCH (s:Source {key: $s}), (d:Decision {key: $k}) MERGE (d)-[:DECIDED_IN]->(s)", {"s": s, "k": key})


def _supersede(g, new_key, old_key):
    g.query("MATCH (n:Decision {key: $n}), (o:Decision {key: $o}) "
            "SET o.status = 'superseded' MERGE (n)-[:SUPERSEDES]->(o)", {"n": new_key, "o": old_key})


# ---------- live ingestion (keeping knowledge current) ----------

def _llm_extract(text, author, mentions, candidates):
    """Ask Claude for decision details. Returns dict or None. Falls back silently if no credentials."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
        schema = {
            "type": "object", "additionalProperties": False,
            "required": ["is_decision", "title", "summary", "supersedes"],
            "properties": {
                "is_decision": {"type": "boolean"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "supersedes": {"type": "array", "items": {"type": "string"}},
            },
        }
        prompt = (
            f"New message from {author}:\n{text}\n\nEntities it mentions: {mentions}\n"
            f"Currently active decisions that touch the same entities:\n{json.dumps(candidates, indent=1)}\n\n"
            "Does the message record a decision? If yes give a short title, a one-sentence summary with the reason, "
            "and the keys of any active decisions it replaces (only if it clearly reverses or replaces them)."
        )
        msg = anthropic.Anthropic().messages.create(
            model="claude-opus-5-5", max_tokens=2000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads("".join(b.text for b in msg.content if b.type == "text"))
    except Exception as e:  # never break ingestion on the LLM path
        print("LLM extraction failed, using rule-based extraction:", e)
        return None


def ingest(kind: str, author: str, text: str, channel: str = "", title: str = "") -> dict:
    """Add a new source, link it, detect a decision, and supersede stale decisions. Returns what changed."""
    g = get_graph()
    n = g.query("MATCH (s:Source) WHERE s.key STARTS WITH 'LIVE-' RETURN count(s)").result_set[0][0]
    key = f"LIVE-{n + 1}"
    src = dict(key=key, kind=kind, author=author, text=text, channel=channel, title=title,
               date=date.today().isoformat())
    mentions = list(dict.fromkeys(_write_source(g, src, _alias_table())))
    changed = {"source": key, "mentions": mentions, "decision": None, "superseded": []}

    if not DECISION_RE.search(text):
        return changed

    affects = [m for m in mentions if m.startswith(("project:", "system:"))]
    cand_rows = g.query(
        "MATCH (d:Decision {status: 'active'})-[:AFFECTS]->(e) WHERE e.key IN $a "
        "RETURN d.key, d.title, collect(e.key)", {"a": affects}).result_set
    candidates = [{"key": k, "title": t, "affects": a} for k, t, a in cand_rows]

    llm = _llm_extract(text, author, mentions, candidates)
    if llm is not None and not llm["is_decision"]:
        return changed
    if llm:
        title_, summary, supersedes = llm["title"], llm["summary"], llm["supersedes"]
    else:
        first = re.split(r"(?<=[.!?])\s", text.strip())[0]
        m = re.search(r"(?:decided to|we will|we're moving|we are moving|going with|go with|switching to|agreed to)\s+(.+)",
                      first, re.I)
        clause = (m.group(1) if m else first).rstrip(".")
        if m and re.match(r"(?:we're moving|we are moving)", m.group(0), re.I):
            clause = "move " + clause
        title_, summary = (clause[:1].upper() + clause[1:])[:90], text.strip()
        # Rule: an active decision is stale if it shares a project AND a system with the new one.
        new_proj = {a for a in affects if a.startswith("project:")}
        new_sys = {a for a in affects if a.startswith("system:")}
        supersedes = [c["key"] for c in candidates
                      if new_proj & set(c["affects"]) and new_sys & set(c["affects"])]

    dn = g.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]
    dkey = f"DEC-{dn + 1}"
    _write_decision(g, dkey, title_, summary, src["date"], [author], affects, [key])
    for old in supersedes:
        if old in {c["key"] for c in candidates}:
            _supersede(g, dkey, old)
            changed["superseded"].append(old)
    changed["decision"] = {"key": dkey, "title": title_, "summary": summary,
                           "extraction": "claude" if llm else "rules"}
    return changed


if __name__ == "__main__":
    build()
