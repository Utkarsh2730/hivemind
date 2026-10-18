"""Company-wide insights computed with FalkorDB's built-in graph algorithms.

- Key connectors: betweenness centrality over people, sources, projects and systems. People who sit on the
  most paths between knowledge; if they leave, information stops flowing.
- Central topics: PageRank. The projects and systems everything else points at.
- Single-expert risks: systems where only one person has hands-on evidence.
- Unconnected knowledge: weakly connected components. Items linked to nobody and nothing.
- Stalled work: tickets in progress or blocked for a long time, or blocking other work.
"""
import json
from datetime import date, timedelta

import brain_tools as T
from graph_db import get_graph


def _q(query, params=None):
    res = get_graph().ro_query(query, params or {})
    cols = [h[1] for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


def insights() -> dict:
    out = {}
    try:
        rows = _q("CALL algo.betweenness({nodeLabels: ['Person', 'Source', 'Project', 'System', 'Decision'], "
                  "relationshipTypes: ['AUTHORED', 'MENTIONS', 'LEADS', 'USES', 'MADE', 'AFFECTS', 'DECIDED_IN', 'ASSIGNED_TO']}) "
                  "YIELD node, score WHERE node:Person RETURN node.key AS key, node.name AS name, node.role AS role, score "
                  "ORDER BY score DESC LIMIT 5")
        top = rows[0]["score"] if rows and rows[0]["score"] else 1
        out["key_connectors"] = [{**r, "score": round(100 * r["score"] / top)} for r in rows if r["score"] > 0]
    except Exception:
        out["key_connectors"] = []
    try:
        out["central_topics"] = _q(
            "CALL algo.pageRank(null, null) YIELD node, score WHERE node:Project OR node:System "
            "RETURN node.key AS key, node.name AS name, labels(node)[0] AS type, score ORDER BY score DESC LIMIT 5")
    except Exception:
        out["central_topics"] = []

    single = []
    for s in _q("MATCH (s:System) OPTIONAL MATCH (src:Source)-[:MENTIONS]->(s) "
                "WITH s, count(src) AS n WHERE n >= 2 RETURN s.key AS key, s.name AS name ORDER BY n DESC LIMIT 25"):
        with T.quiet():
            experts = json.loads(T.who_knows(s["name"])).get("experts", [])
        if len(experts) == 1 or (len(experts) >= 2 and experts[0]["score"] >= 3 * experts[1]["score"]):
            e = experts[0]
            single.append({"key": s["key"], "system": s["name"], "person": e["name"], "person_key": e.get("key"),
                           "evidence": [x["key"] for x in e["evidence"][:3]]})
    out["single_expert"] = single[:6]

    try:
        comps = _q("CALL algo.WCC({nodeLabels: ['Person', 'Team', 'Project', 'System', 'Source', 'Decision']}) "
                   "YIELD node, componentId RETURN componentId AS c, collect(node.key) AS keys, count(node) AS n ORDER BY n DESC")
        out["unconnected"] = [k for c in comps[1:] for k in c["keys"] if ":" not in str(k)][:10]  # sources/decisions only
    except Exception:
        out["unconnected"] = []

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    out["stalled"] = _q(
        "MATCH (t:Source {kind: 'ticket'}) WHERE t.status IN ['in_progress', 'blocked'] "
        "OPTIONAL MATCH (t)-[:BLOCKS]->(x) OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(a) "
        "WITH t, a, collect(x.key) AS blocks WHERE t.date < $c OR size(blocks) > 0 "
        "RETURN t.key AS key, t.title AS title, t.status AS status, t.date AS date, a.name AS assignee, blocks "
        "ORDER BY size(blocks) DESC, date LIMIT 6", {"c": cutoff})
    return out


def insights_text() -> tuple[str, list[str]]:
    """Plain-language summary with citations, plus the node keys to highlight on the map."""
    i = insights()
    lines, keys = [], []
    if i["key_connectors"]:
        names = ", ".join(f"**{p['name']}**" + (f" ({p['role']})" if p.get("role") else "") for p in i["key_connectors"][:3])
        lines.append(f"- **Key connectors:** {names} link the most people, projects and decisions together "
                     f"(betweenness centrality). If one of them is away, information stops flowing.")
        keys += [p["key"] for p in i["key_connectors"][:3]]
    for s in i["single_expert"][:4]:
        lines.append(f"- **Single expert:** only {s['person']} has real hands-on evidence on {s['system']}. "
                     + " ".join(f"[{k}]" for k in s["evidence"]))
        keys += [s["key"]] + s["evidence"] + ([s["person_key"]] if s.get("person_key") else [])
    for t in i["stalled"][:3]:
        why = f"blocks {', '.join(t['blocks'])}" if t["blocks"] else f"{t['status'].replace('_', ' ')} since {t['date']}"
        lines.append(f"- **Stalled:** {t['title']} ({t['assignee'] or 'unassigned'}), {why}. [{t['key']}]")
        keys.append(t["key"])
    if i["central_topics"]:
        lines.append("- **Most central topics** (PageRank): " + ", ".join(t["name"] for t in i["central_topics"][:4]) +
                     ". Changes here affect the most work.")
        keys += [t["key"] for t in i["central_topics"][:4]]
    if i["unconnected"]:
        lines.append(f"- **Unconnected knowledge:** {len(i['unconnected'])} item(s) aren't linked to any person or project, "
                     f"so nobody will find them: " + " ".join(f"[{k}]" for k in i["unconnected"][:5]))
        keys += i["unconnected"]
    if not lines:
        return "Not enough connected data yet. Add more people, projects and knowledge.", []
    return "Here are the knowledge risks the graph shows:\n" + "\n".join(lines), keys
