"""Seed a sample codebase graph: routes -> functions -> package functions -> vulnerabilities.

All vulnerability IDs are fictional (DEMO-*) test data.
Run: python seed.py
"""
from graph_db import get_graph

PEOPLE = ["alice", "bob", "carol"]

MODULES = [  # (path, owner)
    ("src/api/auth.js", "alice"),
    ("src/api/orders.js", "bob"),
    ("src/api/reports.js", "carol"),
    ("src/lib/tokens.js", "alice"),
    ("src/lib/merge.js", "bob"),
    ("src/lib/render.js", "carol"),
    ("scripts/migrate.js", "bob"),
]

PACKAGES = [("jsonwebtoken", "8.5.1"), ("lodash", "4.17.15"), ("ejs", "3.1.6"), ("axios", "1.6.0")]

PKG_FUNCS = [  # (package, function)
    ("jsonwebtoken", "jwt.verify"),
    ("jsonwebtoken", "jwt.sign"),
    ("lodash", "_.merge"),
    ("lodash", "_.get"),
    ("ejs", "ejs.render"),
    ("axios", "axios.get"),
]

VULNS = [  # (id, severity, summary, affected package function)
    ("DEMO-2026-0001", "critical", "Prototype pollution via deep merge of untrusted objects", "_.merge"),
    ("DEMO-2026-0002", "high", "Signature check bypass when algorithm is not pinned", "jwt.verify"),
    ("DEMO-2026-0003", "high", "Template injection when rendering untrusted options", "ejs.render"),
]

FUNCTIONS = [  # (name, module)
    ("loginHandler", "src/api/auth.js"),
    ("verifySession", "src/lib/tokens.js"),
    ("issueToken", "src/lib/tokens.js"),
    ("createOrder", "src/api/orders.js"),
    ("applyDiscounts", "src/lib/merge.js"),
    ("deepMergeConfig", "src/lib/merge.js"),
    ("exportReport", "src/api/reports.js"),
    ("renderTemplate", "src/lib/render.js"),
    ("runMigration", "scripts/migrate.js"),
]

CALLS = [  # internal function -> function
    ("loginHandler", "issueToken"),
    ("createOrder", "verifySession"),
    ("createOrder", "applyDiscounts"),
    ("exportReport", "verifySession"),
    ("exportReport", "renderTemplate"),
    ("runMigration", "deepMergeConfig"),
]

USES = [  # internal function -> package function
    ("verifySession", "jwt.verify"),
    ("issueToken", "jwt.sign"),
    ("applyDiscounts", "_.merge"),
    ("deepMergeConfig", "_.merge"),
    ("renderTemplate", "ejs.render"),
    ("exportReport", "axios.get"),
]

ROUTES = [  # (method, path, handler, public)
    ("POST", "/login", "loginHandler", True),
    ("POST", "/orders", "createOrder", True),
    ("GET", "/reports/:id", "exportReport", False),
]


def seed():
    g = get_graph()
    try:
        g.delete()
    except Exception:
        pass
    g = get_graph()

    for p in PEOPLE:
        g.query("CREATE (:Person {name: $n})", {"n": p})
    for path, owner in MODULES:
        g.query(
            "MATCH (p:Person {name: $o}) CREATE (m:Module {path: $path}), (p)-[:OWNS]->(m)",
            {"o": owner, "path": path},
        )
    for name, ver in PACKAGES:
        g.query("CREATE (:Package {name: $n, version: $v})", {"n": name, "v": ver})
    for pkg, fn in PKG_FUNCS:
        g.query(
            "MATCH (p:Package {name: $p}) CREATE (f:PackageFunction {name: $f}), (p)-[:EXPORTS]->(f)",
            {"p": pkg, "f": fn},
        )
    for vid, sev, summary, fn in VULNS:
        g.query(
            "MATCH (f:PackageFunction {name: $f})<-[:EXPORTS]-(p:Package) "
            "CREATE (v:Vulnerability {id: $id, severity: $sev, summary: $s}), "
            "(v)-[:AFFECTS]->(f), (p)-[:HAS_VULN]->(v)",
            {"f": fn, "id": vid, "sev": sev, "s": summary},
        )
    for name, mod in FUNCTIONS:
        g.query(
            "MATCH (m:Module {path: $m}) CREATE (f:Function {name: $n}), (f)-[:DEFINED_IN]->(m)",
            {"m": mod, "n": name},
        )
    for a, b in CALLS:
        g.query("MATCH (a:Function {name: $a}), (b:Function {name: $b}) CREATE (a)-[:CALLS]->(b)", {"a": a, "b": b})
    for a, b in USES:
        g.query(
            "MATCH (a:Function {name: $a}), (b:PackageFunction {name: $b}) CREATE (a)-[:CALLS]->(b)",
            {"a": a, "b": b},
        )
    for method, path, handler, public in ROUTES:
        g.query(
            "MATCH (f:Function {name: $h}) "
            "CREATE (r:Route {method: $m, path: $p, public: $pub}), (r)-[:HANDLED_BY]->(f)",
            {"h": handler, "m": method, "p": path, "pub": public},
        )

    counts = g.query("MATCH (n) RETURN labels(n)[0] AS label, count(n) ORDER BY label").result_set
    print("Seeded graph:", {label: c for label, c in counts})


if __name__ == "__main__":
    seed()
