"""Accuracy check: questions about the demo company with the facts a correct answer must contain.

Each case passes when the answer names every expected fact and cites every expected source.
Run: python eval_qa.py            (uses Claude if ANTHROPIC_API_KEY is set, otherwise the graph-only planner)
     python eval_qa.py --graph    (force graph-only)
"""
import sys
import time

import brain_agent
import brain_ingest
from graph_db import workspace

CASES = [
    ("Why did we choose Postgres for the ledger, and who made that call?",
     ["Postgres", "Arjun", "Maya"], ["DEC-1"]),
    ("Who should I ask about Kafka consumer lag?", ["Tomas"], ["DOC-3"]),
    ("What changed about customer login, and why?", ["Auth0", "Keycloak"], ["DEC-3", "DEC-4"]),
    ("Why is the checkout redesign blocked and who can unblock it?", ["Zara"], ["PAY-52"]),
    ("Who owns the Payments Gateway and what are they working on?", ["Lena"], ["PAY-52"]),
    ("Who should I ask about Redis?", ["Zara"], ["PAY-31"]),
    ("Why did we move warehouse transforms to dbt?", ["dbt"], ["DEC-7"]),
    ("Who should I ask about Keycloak?", ["Noor"], []),
    ("Where are our biggest knowledge risks?", ["Noor"], ["PAY-52"]),
    ("What do we know about the Stripe retry storm incident?", ["retry"], ["PAY-52"]),
]


def run(mode="auto"):
    brain_ingest.build_demo()
    passed, rows = 0, []
    with workspace("demo"):
        for q, facts, cites in CASES:
            t = time.time()
            r = brain_agent.answer(q, mode=mode, company="Lumen Pay")
            text = r["answer"]
            missing = [f for f in facts if f.lower() not in text.lower()] + [c for c in cites if c not in r["cited"]]
            ok = not missing
            passed += ok
            rows.append((ok, q, missing, time.time() - t, r["mode"]))
    for ok, q, missing, secs, m in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {secs:5.1f}s  {q}" + (f"   missing: {missing}" if missing else ""))
    print(f"\n{passed}/{len(CASES)} correct ({100 * passed // len(CASES)}%) in {rows[0][4]} mode")
    return passed, len(CASES)


if __name__ == "__main__":
    p, n = run("graph" if "--graph" in sys.argv else "auto")
    sys.exit(0 if p == n else 1)
