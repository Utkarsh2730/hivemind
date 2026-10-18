"""Import a public GitHub repository's issues, pull requests and comments into a workspace.

Issues become tickets (GH-<number>), pull requests become docs, comments become messages that reference
their issue. Authors and assignees become people; the repo becomes a project that uses its main language.
Set GITHUB_TOKEN to raise GitHub's rate limit (60 requests/hour without it; one import uses 3-4).
"""
import json
import os
import re
import urllib.error
import urllib.request

import brain_ingest

API = "https://api.github.com"
REPO_RE = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")


def parse_repo(text: str) -> tuple[str, str]:
    m = REPO_RE.match((text or "").strip())
    if not m:
        raise ValueError("Use the form owner/repo or https://github.com/owner/repo")
    return m.group(1), m.group(2)


def _get(path: str):
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "company-brain"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("Repository not found, or it is private.")
        if e.code in (403, 429):
            raise ValueError("GitHub rate limit reached. Try again later, or set GITHUB_TOKEN on the server.")
        raise ValueError(f"GitHub error {e.code}.")
    except urllib.error.URLError:
        raise ValueError("Could not reach GitHub.")


def _clean(body: str, limit: int = 2500) -> str:
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)        # template comments
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)                  # images
    body = re.sub(r"```.*?```", "[code]", body, flags=re.S)          # code blocks
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:limit]


def import_repo(repo_text: str, max_items: int = 150) -> dict:
    owner, name = parse_repo(repo_text)
    repo = _get(f"/repos/{owner}/{name}")
    issues = _get(f"/repos/{owner}/{name}/issues?state=all&per_page=100&sort=updated&direction=desc")
    comments = _get(f"/repos/{owner}/{name}/issues/comments?per_page=100&sort=updated&direction=desc")

    project = repo["name"]
    uses = [repo["language"]] if repo.get("language") else []
    brain_ingest.add_entities(projects=[{"name": project, "lead": repo["owner"]["login"] if repo["owner"]["type"] == "User" else "",
                                         "uses": uses, "aliases": [f"{owner}/{name}"]}])

    is_bot = lambda u: (u or {}).get("type") == "Bot" or (u or {}).get("login", "").endswith("[bot]")
    sources, numbers = [], set()
    for it in issues[:max_items]:
        if is_bot(it.get("user")):
            continue
        n = it["number"]
        numbers.add(n)
        labels = ", ".join(l["name"] for l in it.get("labels", []))
        body = _clean(it.get("body"))
        head = f"{project}: " + ("Labels: " + labels + ". " if labels else "")
        if "pull_request" in it:
            merged = it["pull_request"].get("merged_at")
            state = "merged" if merged else it["state"]
            sources.append({"kind": "doc", "key": f"PR-{n}", "title": f"PR #{n}: {it['title']}",
                            "text": f"{head}Pull request ({state}). {body}", "author": it["user"]["login"],
                            "date": it["created_at"][:10], "detect_decisions": False})
        else:
            status = "done" if it["state"] == "closed" else ("in_progress" if it.get("assignee") else "todo")
            sources.append({"kind": "ticket", "key": f"GH-{n}", "title": it["title"], "text": f"{head}{body}",
                            "author": it["user"]["login"], "date": it["created_at"][:10], "status": status,
                            "assignee": "" if is_bot(it.get("assignee")) else (it.get("assignee") or {}).get("login", "")})
    for c in comments:
        m = re.search(r"/issues/(\d+)$", c.get("issue_url", ""))
        if not m or int(m.group(1)) not in numbers or is_bot(c.get("user")):
            continue
        n = int(m.group(1))
        ref = next((s["key"] for s in sources if s["key"] in (f"GH-{n}", f"PR-{n}")), f"GH-{n}")
        sources.append({"kind": "message", "channel": f"#{project}", "title": "",
                        "text": f"On {ref} in {project}: {_clean(c.get('body'), 1500)}",
                        "author": c["user"]["login"], "date": c["created_at"][:10]})
    sources = [s for s in sources if s["text"].strip()][:200]
    result = brain_ingest.bulk_import(sources)
    result["repo"] = f"{owner}/{name}"
    result["project"] = project
    return result
