"""Blast-radius agent: Claude + FalkorDB graph tools.

Run: python agent.py "Which public routes are exposed to DEMO-2026-0001 and who should fix it?"
Needs ANTHROPIC_API_KEY (or another Anthropic credential source).
"""
import json
import sys

import anthropic
from anthropic import beta_tool

import tools

SYSTEM = """You are a security triage agent. The codebase is stored in a FalkorDB graph
(routes, functions, modules, owners, packages, package functions, vulnerabilities, and past findings).
Answer only from what the graph tools return - never guess relationships.
Start by calling recall for the entities in the question to reuse earlier findings.
For exposure questions use exposure_paths, then owners_of for the functions on the path.
When you reach a conclusion, call remember with a one-sentence finding linked to the relevant ids/names.
Finish with: the answer, the exact path(s) through the graph that support it, and who should act."""


@beta_tool
def graph_schema() -> str:
    """Return node labels and relationship patterns in the code graph. Call first if unsure what exists."""
    return tools.graph_schema()


@beta_tool
def run_cypher(query: str) -> str:
    """Run a read-only Cypher query on the code graph and return rows as JSON.

    Args:
        query: A read-only openCypher query (MATCH/RETURN). Writes are rejected.
    """
    return tools.run_cypher(query)


@beta_tool
def exposure_paths(vuln_id: str) -> str:
    """Find every route whose call chain reaches the package function affected by a vulnerability,
    plus all direct callers and how many routes reach them.

    Args:
        vuln_id: Vulnerability id, e.g. DEMO-2026-0001.
    """
    return tools.exposure_paths(vuln_id)


@beta_tool
def owners_of(function_names: list[str]) -> str:
    """Look up the module and owning person for each internal function.

    Args:
        function_names: Internal function names, e.g. ["applyDiscounts"].
    """
    return tools.owners_of(function_names)


@beta_tool
def remember(finding: str, about: list[str]) -> str:
    """Persist a finding in the graph, linked to the nodes it concerns, so later sessions can recall it.

    Args:
        finding: One-sentence conclusion.
        about: Node keys the finding concerns (vulnerability ids, function names, module paths).
    """
    return tools.remember(finding, about)


@beta_tool
def recall(key: str) -> str:
    """Return earlier findings linked to a node (vulnerability id, function name, or module path).

    Args:
        key: The node key to look up.
    """
    return tools.recall(key)


def main(question: str):
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5-5",
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=[graph_schema, run_cypher, exposure_paths, owners_of, remember, recall],
        messages=[{"role": "user", "content": question}],
    )
    final = None
    for message in runner:
        final = message
        for block in message.content:
            if block.type == "tool_use":
                print(f"  -> {block.name}({json.dumps(block.input)})")
    if final is None:
        return
    if final.stop_reason == "refusal":
        print("Request was declined:", final.stop_details)
        return
    print("\n=== ANSWER ===")
    print("".join(b.text for b in final.content if b.type == "text"))
    print("\n=== GRAPH TRACE ===")
    for i, step in enumerate(tools.TRACE, 1):
        print(f"{i}. {step['tool']} {json.dumps(step['args'])}")


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "Which public routes are exposed to DEMO-2026-0001, and who should fix it?")
