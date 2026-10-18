"""Graph tools for the company brain agent. Plain functions; each call is recorded in the active Trace
so the UI can show the reasoning path and highlight the subgraph behind an answer."""
import contextvars
import json
import re

from brain_ingest import link_entities
from graph_db import get_graph

_trace = contextvars.ContextVar("trace", default=None)
_WRITE_RE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s+db\.idx\.fulltext\.(create|drop))\b", re.I)


class Trace:
    def __init__(self):
        self.steps, self.keys = [], []

    def __enter__(self):
        self._tok = _trace.set(self)
        return self

    def __exit__(self, *a):
        _trace.reset(self._tok)


def _record(tool, args, result: dict):
    keys = list(dict.fromkeys(_collect_keys(result)))
    t = _trace.get()
    if t is not None:
        t.steps.append({"tool": tool, "args": args, "found": len(keys)})
        t.keys.extend(k for k in keys if k not in t.keys)
    return json.dumps(result, default=str)


def _collect_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "key" and isinstance(v, str):
                yield v
            else:
                yield from _collect_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _collect_keys(v)


def _q(query, params=None):
    res = get_graph().ro_query(query, params or {})
    cols = [h[1] for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


def resolve(text: str) -> list[dict]:
    """Map free text to graph entities (people, teams, projects, systems)."""
    keys = link_entities(text)
    if not keys:
        keys = [r["key"] for r in _q(
            "MATCH (e) WHERE (e:Person OR e:Project OR e:System OR e:Team) AND toLower(e.name) CONTAINS toLower($t) "
            "RETURN e.key AS key", {"t": text.strip()})]
    if not keys:
        return []
    return _q("MATCH (e) WHERE e.key IN $k RETURN e.key AS key, e.name AS name, labels(e)[0] AS type", {"k": keys})


def _sources(keys):
    rows = _q(
        "MATCH (s:Source) WHERE s.key IN $k "
        "OPTIONAL MATCH (a:Person)-[:AUTHORED]->(s) "
        "RETURN s.key AS key, s.kind AS kind, s.title AS title, s.date AS date, s.channel AS channel, "
        "s.status AS status, a.name AS author, s.text AS text ORDER BY s.date", {"k": keys})
    return rows


# ---------------- tools ----------------

def search_knowledge(query: str, limit: int = 8) -> str:
    words = re.findall(r"[A-Za-z0-9]{3,}", query)
    stop = {"the", "and", "who", "why", "what", "did", "does", "for", "how", "our", "are", "was", "with", "about", "that", "this"}
    terms = "|".join(w for w in words if w.lower() not in stop) or query
    hits = _q("CALL db.idx.fulltext.queryNodes('Source', $t) YIELD node, score "
              "RETURN node.key AS key, score ORDER BY score DESC LIMIT $l", {"t": terms, "l": limit})
    entities = resolve(query)
    if entities:  # boost sources that mention the resolved entities
        extra = _q("MATCH (s:Source)-[:MENTIONS]->(e) WHERE e.key IN $k "
                   "RETURN s.key AS key, count(e) AS c, s.date AS d ORDER BY c DESC, d DESC LIMIT $l",
                   {"k": [e["key"] for e in entities], "l": limit})
        keys = list(dict.fromkeys([h["key"] for h in hits] + [x["key"] for x in extra]))[:limit + 4]
    else:
        keys = [h["key"] for h in hits]
    decisions = _q("CALL db.idx.fulltext.queryNodes('Decision', $t) YIELD node "
                   "RETURN node.key AS key, node.title AS title, node.status AS status, node.date AS date LIMIT 5",
                   {"t": terms})
    return _record("search_knowledge", {"query": query},
                   {"entities": entities, "sources": _sources(keys), "decisions": decisions})


def entity_profile(name: str) -> str:
    ents = resolve(name)
    if not ents:
        return _record("entity_profile", {"name": name}, {"error": f"no entity matches '{name}'"})
    e = ents[0]
    k, t = e["key"], e["type"]
    out = {"entity": e}
    if t == "Person":
        out["profile"] = _q("MATCH (p:Person {key: $k})-[:MEMBER_OF]->(t) RETURN p.role AS role, t.name AS team, t.key AS team_key", {"k": k})
        out["leads"] = _q("MATCH (:Person {key: $k})-[:LEADS]->(p) RETURN p.key AS key, p.name AS name, p.status AS status", {"k": k})
        out["open_tickets"] = _q("MATCH (s:Source {kind: 'ticket'})-[:ASSIGNED_TO]->(:Person {key: $k}) WHERE s.status <> 'done' "
                                 "RETURN s.key AS key, s.title AS title, s.status AS status", {"k": k})
        out["decisions_made"] = _q("MATCH (:Person {key: $k})-[:MADE]->(d) RETURN d.key AS key, d.title AS title, d.status AS status, d.date AS date", {"k": k})
        out["writes_about"] = _q("MATCH (:Person {key: $k})-[:AUTHORED]->(s)-[:MENTIONS]->(x:System) "
                                 "RETURN x.name AS topic, count(s) AS sources ORDER BY sources DESC LIMIT 6", {"k": k})
    elif t == "Project":
        out["profile"] = _q("MATCH (p:Project {key: $k}) OPTIONAL MATCH (t:Team)-[:OWNS]->(p) OPTIONAL MATCH (l:Person)-[:LEADS]->(p) "
                            "RETURN p.status AS status, t.name AS owning_team, t.key AS team_key, l.name AS lead, l.key AS lead_key", {"k": k})
        out["uses"] = _q("MATCH (:Project {key: $k})-[:USES]->(s) RETURN s.key AS key, s.name AS name", {"k": k})
        out["tickets"] = _q("MATCH (s:Source {kind: 'ticket'})-[:MENTIONS]->(:Project {key: $k}) OPTIONAL MATCH (s)-[:ASSIGNED_TO]->(a) "
                            "OPTIONAL MATCH (b:Source)-[:BLOCKS]->(s) "
                            "RETURN s.key AS key, s.title AS title, s.status AS status, a.name AS assignee, collect(b.key) AS blocked_by", {"k": k})
        out["blocked_by"] = _q("MATCH (b:Source)-[:BLOCKS]->(s:Source)-[:MENTIONS]->(:Project {key: $k}) "
                               "OPTIONAL MATCH (b)-[:ASSIGNED_TO]->(a) RETURN b.key AS key, b.title AS title, b.status AS status, "
                               "a.name AS assignee, a.key AS assignee_key, s.key AS blocks", {"k": k})
        out["decisions"] = _q("MATCH (d:Decision)-[:AFFECTS]->(:Project {key: $k}) RETURN d.key AS key, d.title AS title, d.status AS status, d.date AS date ORDER BY d.date", {"k": k})
    elif t == "System":
        out["used_by"] = _q("MATCH (p:Project)-[:USES]->(:System {key: $k}) OPTIONAL MATCH (l:Person)-[:LEADS]->(p) "
                            "RETURN p.key AS key, p.name AS name, l.name AS lead", {"k": k})
        out["decisions"] = _q("MATCH (d:Decision)-[:AFFECTS]->(:System {key: $k}) RETURN d.key AS key, d.title AS title, d.status AS status, d.date AS date ORDER BY d.date", {"k": k})
    elif t == "Team":
        out["members"] = _q("MATCH (p:Person)-[:MEMBER_OF]->(:Team {key: $k}) RETURN p.key AS key, p.name AS name, p.role AS role", {"k": k})
        out["owns"] = _q("MATCH (:Team {key: $k})-[:OWNS]->(p) RETURN p.key AS key, p.name AS name, p.status AS status", {"k": k})
    out["recent_sources"] = _q("MATCH (s:Source)-[:MENTIONS]->({key: $k}) RETURN s.key AS key, s.title AS title, s.date AS date "
                               "ORDER BY s.date DESC LIMIT 5", {"k": k})
    return _record("entity_profile", {"name": name}, out)


def who_knows(topic: str) -> str:
    """Rank people by evidence of hands-on knowledge, separate from formal ownership."""
    ents = [e for e in resolve(topic) if e["type"] in ("System", "Project")]
    if not ents:
        return _record("who_knows", {"topic": topic}, {"error": f"no system or project matches '{topic}'"})
    keys = [e["key"] for e in ents]
    signals = [
        (3, "authored", "MATCH (p:Person)-[:AUTHORED]->(s:Source)-[:MENTIONS]->(e) WHERE e.key IN $k RETURN p.key AS person, s.key AS ev"),
        (2, "assigned", "MATCH (s:Source)-[:ASSIGNED_TO]->(p:Person) MATCH (s)-[:MENTIONS]->(e) WHERE e.key IN $k RETURN p.key AS person, s.key AS ev"),
        (2, "thanked_or_named_by_others", "MATCH (a:Person)-[:AUTHORED]->(s:Source)-[:MENTIONS]->(p:Person), (s)-[:MENTIONS]->(e) "
                                          "WHERE e.key IN $k AND a <> p RETURN p.key AS person, s.key AS ev"),
        (2, "made_decision", "MATCH (p:Person)-[:MADE]->(d:Decision)-[:AFFECTS]->(e) WHERE e.key IN $k RETURN p.key AS person, d.key AS ev"),
    ]
    scores = {}
    for w, kind, q in signals:
        for r in _q(q, {"k": keys}):
            s = scores.setdefault(r["person"], {"score": 0, "evidence": {}})
            if r["ev"] not in s["evidence"]:
                s["evidence"][r["ev"]] = kind
                s["score"] += w
    owners = _q("MATCH (l:Person)-[:LEADS]->(p:Project) WHERE p.key IN $k OR (p)-[:USES]->(:System {key: $k[0]}) "
                "RETURN l.key AS key, l.name AS name, p.name AS project", {"k": keys})
    people = {r["key"]: r for r in _q("MATCH (p:Person)-[:MEMBER_OF]->(t) WHERE p.key IN $k "
                                       "RETURN p.key AS key, p.name AS name, p.role AS role, t.name AS team", {"k": list(scores)})}
    ranked = sorted(scores.items(), key=lambda x: -x[1]["score"])[:5]
    result = {"topic": ents, "experts": [{**people[p], "score": s["score"],
                                          "evidence": [{"key": k, "signal": v} for k, v in s["evidence"].items()]}
                                         for p, s in ranked],
              "formal_owners": owners}
    return _record("who_knows", {"topic": topic}, result)


def decision_trail(topic: str) -> str:
    """Decisions about a topic, oldest first, with who made them, where, and what replaced what."""
    ents = resolve(topic)
    keys = [e["key"] for e in ents]
    if keys:
        dkeys = [r["key"] for r in _q("MATCH (d:Decision)-[:AFFECTS]->(e) WHERE e.key IN $k RETURN DISTINCT d.key AS key", {"k": keys})]
    else:
        terms = "|".join(re.findall(r"[A-Za-z0-9]{3,}", topic)) or topic
        dkeys = [r["key"] for r in _q("CALL db.idx.fulltext.queryNodes('Decision', $t) YIELD node RETURN node.key AS key", {"t": terms})]
    decisions = []
    for d in _q("MATCH (d:Decision) WHERE d.key IN $k RETURN d.key AS key, d.title AS title, d.summary AS summary, "
                "d.date AS date, d.status AS status ORDER BY d.date", {"k": dkeys}):
        k = d["key"]
        d["made_by"] = _q("MATCH (p:Person)-[:MADE]->(:Decision {key: $k}) RETURN p.key AS key, p.name AS name, p.role AS role", {"k": k})
        d["sources"] = _q("MATCH (:Decision {key: $k})-[:DECIDED_IN]->(s) OPTIONAL MATCH (a)-[:AUTHORED]->(s) "
                          "RETURN s.key AS key, s.kind AS kind, s.title AS title, s.date AS date, a.name AS author, s.text AS text", {"k": k})
        d["supersedes"] = _q("MATCH (:Decision {key: $k})-[:SUPERSEDES]->(o) RETURN o.key AS key, o.title AS title", {"k": k})
        d["superseded_by"] = _q("MATCH (n)-[:SUPERSEDES]->(:Decision {key: $k}) RETURN n.key AS key, n.title AS title", {"k": k})
        d["affects"] = _q("MATCH (:Decision {key: $k})-[:AFFECTS]->(e) RETURN e.key AS key, e.name AS name", {"k": k})
        decisions.append(d)
    return _record("decision_trail", {"topic": topic}, {"topic": ents, "decisions": decisions})


def run_cypher(query: str) -> str:
    if _WRITE_RE.search(query):
        return _record("run_cypher", {"query": query}, {"error": "only read-only queries are allowed"})
    try:
        return _record("run_cypher", {"query": query}, {"rows": _q(query)})
    except Exception as e:
        return _record("run_cypher", {"query": query}, {"error": str(e)})


SCHEMA = """Nodes: Person{key,name,role}, Team{key,name}, Project{key,name,status}, System{key,name},
Source{key,kind(doc|ticket|message|meeting),title,text,date,channel,status}, Decision{key,title,summary,date,status(active|superseded)}
Edges: (Person)-[:MEMBER_OF]->(Team), (Team)-[:OWNS]->(Project), (Person)-[:LEADS]->(Project), (Project)-[:USES]->(System),
(Person)-[:AUTHORED]->(Source), (Source)-[:MENTIONS]->(Person|Project|System|Team), (Source)-[:ASSIGNED_TO]->(Person),
(Source)-[:REFERENCES]->(Source), (Source)-[:BLOCKS]->(Source), (Person)-[:MADE]->(Decision),
(Decision)-[:AFFECTS]->(Project|System), (Decision)-[:DECIDED_IN]->(Source), (Decision)-[:SUPERSEDES]->(Decision)"""
