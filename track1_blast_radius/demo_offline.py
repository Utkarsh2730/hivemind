"""Exercise the graph tools without an LLM - a quick smoke test of the whole data layer.

Run: python demo_offline.py
"""
import json

import tools
from seed import seed

seed()
print("\n--- schema ---")
print(tools.graph_schema())

for vid in ["DEMO-2026-0001", "DEMO-2026-0002", "DEMO-2026-0003"]:
    print(f"\n--- exposure: {vid} ---")
    data = json.loads(tools.exposure_paths(vid))
    for r in data["exposed_routes"]:
        tag = "PUBLIC" if r["public"] else "internal"
        print(f"  [{tag}] {r['route']}: {' -> '.join(r['chain'])}")
    for c in data["direct_callers"]:
        print(f"  caller {c['function']} ({c['module']}) reached by {c['routes_reaching']} route(s)")

print("\n--- owners ---")
print(tools.owners_of(["applyDiscounts", "deepMergeConfig"]))

print("\n--- memory ---")
tools.remember("DEMO-2026-0001 reaches public POST /orders via applyDiscounts; bob owns the fix.",
               ["DEMO-2026-0001", "applyDiscounts"])
print(tools.recall("DEMO-2026-0001"))

print("\n--- write guard ---")
print(tools.run_cypher("MATCH (n) DETACH DELETE n"))
