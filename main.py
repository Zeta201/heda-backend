from datetime import datetime
from typing import List
from fastapi import FastAPI, File, Form, HTTPException, Header, UploadFile
from pydantic import BaseModel
from github import Github, GithubException
from pathlib import Path
import tempfile
import shutil
import subprocess
import os

from dotenv import load_dotenv
import requests

from utils import compute_experiment_hash, run_git
load_dotenv()

# -----------------------------
# CONFIGURATION
# -----------------------------

GITHUB_ORG = "heda-gitops"  # Your GitOps org
ADMIN_GITHUB_TOKEN = os.environ.get("GITHUB_ADMIN_TOKEN")  # Admin token
BACKEND_AUTH_TOKEN = os.environ.get("HEDA_BACKEND_TOKEN")   # Simple auth token

if not ADMIN_GITHUB_TOKEN or not BACKEND_AUTH_TOKEN:
    raise RuntimeError("Missing environment variables: GITHUB_ADMIN_TOKEN or HEDA_BACKEND_TOKEN")

gh = Github(ADMIN_GITHUB_TOKEN)
org = gh.get_organization(GITHUB_ORG)

# -----------------------------
# Pydantic models
# -----------------------------

class InitRequest(BaseModel):
    username: str
    experiment_name: str

class InitResponse(BaseModel):
    repo_url: str
    message: str

class PublishResponse(BaseModel):
    experiment_id: str
    pr_url: str
    message: str


app = FastAPI(title="HEDA GitOps Backend")


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

def create_gitops_repo(username: str, experiment_name: str) -> str:
    """
    Create an empty GitOps repository for experiment proposals.
    """
    repo_name = f"{username}-{experiment_name}"

    try:
        repo = org.create_repo(
            name=repo_name,
            private=False,
            description=f"HEDA GitOps repo for {username}/{experiment_name}",
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

        pr_verify_path.write_text(
            """\
name: PR Verify

on:
  pull_request:
    branches: [ main ]
    
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install HEDA
        run: |
          pip install --upgrade pip
          pip install git+https://github.com/Zeta201/heda.git
      - name: Finalize experiment
        run: |
          heda finalize
      - name: Verify experiment
        run: |
          heda verify
""" )
        
        pr_finalize_path = tmp_dir / ".github/workflows/main-finalize.yml"
        pr_finalize_path.parent.mkdir(parents=True, exist_ok=True)
        pr_finalize_path.write_text(
            """\
                            
name: Main Finalize

on:
  push:
    branches: [ main ]

jobs:
  finalize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # Needed to push tags

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install HEDA
        run: |
          pip install --upgrade pip
          pip install git+https://github.com/Zeta201/heda.git

      - name: Finalize experiment
        run: |
          heda finalize

      - name: Verify experiment
        run: |
          heda verify

      - name: Upload verification artifacts
        uses: actions/upload-artifact@v4
        with:
          name: verification
          path: verification.json
"""
        )

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

# -----------------------------
# API ENDPOINTS
# -----------------------------

@app.post("/init", response_model=InitResponse)
def init_experiment(request: InitRequest, x_auth_token: str = Header(...)):
    if x_auth_token != BACKEND_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    repo_url = create_gitops_repo(
        request.username,
        request.experiment_name,
    )

    repo_name = f"{request.username}-{request.experiment_name}"
    try:
        initialize_local_repo(repo_url, repo_name)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize GitOps repository: {e}",
        )

    return InitResponse(
        repo_url=repo_url,
        message=(
            "GitOps repository initialized.\n"
            "Submit experiments via pull requests."
        ),
    )


@app.post("/publish", response_model=PublishResponse)
async def publish_experiment_backend(
    username: str = Form(...),
    experiment_name: str = Form(...),
    files: List[UploadFile] = File(...),
    x_auth_token: str = Header(...),
):
    if x_auth_token != BACKEND_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    repo_name = f"{username}-{experiment_name}"
    repo_url = f"https://github.com/{GITHUB_ORG}/{repo_name}.git"

    tmp_dir = Path(tempfile.mkdtemp(prefix="heda-publish-"))

    try:
        # 1. Clone repo
        run_git(["git", "clone", repo_url, str(tmp_dir)], cwd=Path("/"))

        # 2. Write uploaded files
        for file in files:
            dest = tmp_dir / file.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await file.read())

        # 3. Compute proposal hash (NOT final)
        tracked_files = [
            p for p in tmp_dir.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]
        proposal_hash = compute_experiment_hash(tracked_files)[:8]

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        branch_name = f"publish/{timestamp}-{proposal_hash}"

        # 4. Create branch
        run_git(["git", "checkout", "-b", branch_name], cwd=tmp_dir)

        # 5. Commit
        run_git(["git", "add", "."], cwd=tmp_dir)
        run_git(
            ["git", "commit", "-m", f"Propose experiment ({proposal_hash})"],
            cwd=tmp_dir
        )

        # 6. Push branch
        run_git(["git", "push", "-u", "origin", branch_name], cwd=tmp_dir)

        # 7. Open PR
        repo = org.get_repo(repo_name)

        pr = repo.create_pull(
            title=f"Propose experiment {proposal_hash}",
            body=(
                "### Experiment Proposal\n\n"
                f"- Proposal hash: `{proposal_hash}`\n"
                f"- Branch: `{branch_name}`\n\n"
                "This PR triggers reproducibility verification.\n"
                "If merged, the experiment will be versioned automatically."
            ),
            head=branch_name,
            base="main",
        )

        return PublishResponse(
            experiment_id=proposal_hash,
            pr_url=pr.html_url,
            message="Pull request created",
        )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
