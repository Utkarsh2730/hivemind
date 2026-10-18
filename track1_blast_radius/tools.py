"""Graph tools the agent can call. Plain functions so they can be tested without an LLM.

Every call is appended to TRACE so the agent can show how it reached its answer.
"""
import json
import re
import time

from graph_db import get_graph

TRACE: list[dict] = []
_WRITE_RE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP)\b", re.IGNORECASE)


def _log(tool: str, args: dict, result):
    TRACE.append({"tool": tool, "args": args, "result_preview": str(result)[:300]})
    return result


def _rows(res):
    return [dict(zip(res.header and [h[1] for h in res.header], row)) for row in res.result_set]


def graph_schema() -> str:
    g = get_graph()
    labels = [r[0] for r in g.query("CALL db.labels()").result_set]
    rels = g.query(
        "MATCH (a)-[r]->(b) RETURN DISTINCT labels(a)[0], type(r), labels(b)[0]"
    ).result_set
    out = {"node_labels": labels, "relationships": [f"({a})-[:{t}]->({b})" for a, t, b in rels]}
    return _log("graph_schema", {}, json.dumps(out, indent=2))


def run_cypher(query: str) -> str:
    if _WRITE_RE.search(query):
        return _log("run_cypher", {"query": query}, "ERROR: only read-only queries are allowed")
    try:
        res = get_graph().ro_query(query)
        return _log("run_cypher", {"query": query}, json.dumps(_rows(res), default=str))
    except Exception as e:
        return _log("run_cypher", {"query": query}, f"ERROR: {e}")


def exposure_paths(vuln_id: str) -> str:
    """Multi-hop: route -> handler -> ...calls... -> vulnerable package function."""
    q = (
        "MATCH (v:Vulnerability {id: $id})-[:AFFECTS]->(pf:PackageFunction) "
        "MATCH path = (r:Route)-[:HANDLED_BY]->(:Function)-[:CALLS*0..6]->(:Function)-[:CALLS]->(pf) "
        "RETURN r.method + ' ' + r.path AS route, r.public AS public, "
        "[n IN nodes(path) | coalesce(n.name, n.path)] AS chain"
    )
    rows = _rows(get_graph().ro_query(q, {"id": vuln_id}))
    # Also find code that calls the vulnerable function but isn't reachable from any route
    q2 = (
        "MATCH (v:Vulnerability {id: $id})-[:AFFECTS]->(pf)<-[:CALLS]-(f:Function)-[:DEFINED_IN]->(m) "
        "OPTIONAL MATCH (r:Route)-[:HANDLED_BY]->(:Function)-[:CALLS*0..6]->(f) "
        "RETURN f.name AS function, m.path AS module, count(r) AS routes_reaching"
    )
    callers = _rows(get_graph().ro_query(q2, {"id": vuln_id}))
    out = {"vuln": vuln_id, "exposed_routes": rows, "direct_callers": callers}
    return _log("exposure_paths", {"vuln_id": vuln_id}, json.dumps(out, default=str))


def owners_of(function_names: list[str]) -> str:
    q = (
        "MATCH (f:Function)-[:DEFINED_IN]->(m:Module)<-[:OWNS]-(p:Person) "
        "WHERE f.name IN $names RETURN f.name AS function, m.path AS module, p.name AS owner"
    )
    rows = _rows(get_graph().ro_query(q, {"names": function_names}))
    return _log("owners_of", {"function_names": function_names}, json.dumps(rows))


def remember(finding: str, about: list[str]) -> str:
    """Store a finding in the graph and link it to the nodes it is about (memory across sessions)."""
    g = get_graph()
    g.query("CREATE (:Finding {text: $t, ts: $ts})", {"t": finding, "ts": time.time()})
    for key in about:
        g.query(
            "MATCH (f:Finding {text: $t}) MATCH (n) "
            "WHERE n.name = $k OR n.id = $k OR n.path = $k "
            "MERGE (f)-[:ABOUT]->(n)",
            {"t": finding, "k": key},
        )
    return _log("remember", {"finding": finding, "about": about}, "stored")


def recall(key: str) -> str:
    q = (
        "MATCH (f:Finding)-[:ABOUT]->(n) WHERE n.name = $k OR n.id = $k OR n.path = $k "
        "RETURN f.text AS finding, f.ts AS ts ORDER BY f.ts DESC LIMIT 10"
    )
    rows = _rows(get_graph().ro_query(q, {"k": key}))
    return _log("recall", {"key": key}, json.dumps(rows))
