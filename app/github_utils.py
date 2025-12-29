from pathlib import Path
import shutil
import tempfile

import requests
from .utils import run_git
from github import GithubException
from .config import org, ADMIN_GITHUB_TOKEN, GITHUB_ORG

from .templates.pr_verify import pr_verify_template
from .templates.pr_finalize import pr_finalize_template

def protect_main_branch(repo_name: str):
    """
    Enforce PR-only merges and block direct pushes to main.
    """
    url = f"https://api.github.com/repos/{GITHUB_ORG}/{repo_name}/branches/main/protection"

    headers = {
        "Authorization": f"token {ADMIN_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    payload = {
        "required_pull_request_reviews": None,

        "required_status_checks": {
            "strict": True,
            "contexts": ["verify"]
        },

        "enforce_admins": True,

        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,

        "restrictions": None
    }

    response = requests.put(url, headers=headers, json=payload)

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to protect main branch: {response.status_code} {response.text}"
        )

def create_gitops_repo(github_username: str, experiment_name: str) -> str:
    """
    Create an empty GitOps repository for experiment proposals.
    """
    repo_name = f"{github_username}-{experiment_name}"

    try:
        repo = org.create_repo(
            name=repo_name,
            private=False,
            description=f"HEDA GitOps repo for {github_username}/{experiment_name}",
            auto_init=False,
            allow_squash_merge=True,
            allow_merge_commit=True,
            allow_rebase_merge=True,
        )
    except GithubException as e:
        raise RuntimeError(f"Failed to create repo: {e.data}")


    return repo.clone_url


def initialize_local_repo(repo_url: str, repo_name: str) -> None:
    """
    Initialize an empty GitOps repository with CI policy.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="heda-init-"))

    try:
        run_git(["git", "init"], cwd=tmp_dir)
        run_git(["git", "remote", "add", "origin", repo_url], cwd=tmp_dir)

        # -----------------------------
        # GitHub Actions workflow
        # -----------------------------
        pr_verify_path = tmp_dir / ".github/workflows/pr-verify.yml"
        pr_verify_path.parent.mkdir(parents=True, exist_ok=True)

        pr_verify_path.write_text(pr_verify_template)
        
        pr_finalize_path = tmp_dir / ".github/workflows/main-finalize.yml"
        pr_finalize_path.parent.mkdir(parents=True, exist_ok=True)
        pr_finalize_path.write_text(pr_finalize_template)

        # -----------------------------
        # Initial policy commit
        # -----------------------------
        run_git(["git", "add", "."], cwd=tmp_dir)
        run_git(
            ["git", "commit", "-m", "chore: initialize GitOps policy"],
            cwd=tmp_dir,
        )
        run_git(["git", "branch", "-M", "main"], cwd=tmp_dir)
        run_git(["git", "push", "-u", "origin", "main"], cwd=tmp_dir)
        # Protect main branch programmatically
        protect_main_branch(repo_name)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
