import requests

from app.github_auth import get_installation_token


def extract_pr_context(payload: dict):
    repo = payload.get("repository")
    installation = payload.get("installation")
    check_run = payload.get("check_run")

    if not repo or not installation or not check_run:
        return None

    return {
        "owner": repo["owner"]["login"],
        "repo": repo["name"],
        "head_sha": check_run["head_sha"],
        "installation_id": installation["id"],
    }


def pr_mergeable(token, owner, repo, pr_number):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    res = requests.get(url, headers=headers)
    res.raise_for_status()

    return res.json()["mergeable"] is True

def merge_pr(token, owner, repo, pr_number):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    payload = {
        "merge_method": "squash"
    }

    res = requests.put(url, headers=headers, json=payload)
    res.raise_for_status()

def resolve_pr_number(token, owner, repo, sha):
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/pulls"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    res = requests.get(url, headers=headers)
    res.raise_for_status()

    prs = res.json()
    if not prs:
        return None

    return prs[0]["number"]

async def try_merge_pr(payload: dict):
    ctx = extract_pr_context(payload)

    if not ctx:
        return

    token = get_installation_token(ctx["installation_id"])

    pr_number = ctx.get("pr_number")

    # Resolve PR from commit SHA if missing
    if not pr_number:
        pr_number = resolve_pr_number(
            token,
            ctx["owner"],
            ctx["repo"],
            ctx["head_sha"],
        )

        if not pr_number:
            print("No PR associated with commit yet")
            return

    # Check mergeability
    if not pr_mergeable(
        token,
        ctx["owner"],
        ctx["repo"],
        pr_number,
    ):
        print("PR not mergeable yet")
        return

    print(f"Merging PR #{pr_number}")

    merge_pr(
        token,
        ctx["owner"],
        ctx["repo"],
        pr_number,
    )
