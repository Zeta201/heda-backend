from datetime import datetime
import json
from typing import List
from fastapi import FastAPI, File, Form, HTTPException, Header, UploadFile
from pydantic import BaseModel
from auth0_jwks import get_current_user, verify_token
from constants import InvitationStatus
from pathlib import Path
import tempfile
import shutil
import os
from typing import Dict
from templates.pr_verify import pr_verify_template
from templates.pr_finalize import pr_finalize_template
from templates.pr_template import pr_title_template, pr_doc_template

from dotenv import load_dotenv
import requests

from utils import compute_experiment_hash, run_git
load_dotenv()






app = FastAPI(title="HEDA GitOps Backend")

ONBOARDING_DB = Path("data/onboarding.json")
ONBOARDING_DB.parent.mkdir(exist_ok=True)

from fastapi import Depends


def load_onboarding() -> Dict[str, dict]:
    if ONBOARDING_DB.exists():
        return json.loads(ONBOARDING_DB.read_text())
    return {}

def save_onboarding(data: Dict[str, dict]):
    ONBOARDING_DB.write_text(json.dumps(data, indent=2))

def is_org_member_by_username(github_username: str) -> bool:
    for member in org.get_members():
        try:
            if member.login and member.login == github_username:
                return True
        except GithubException:
            pass
    return False


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

# -----------------------------
# API ENDPOINTS
# -----------------------------

@app.post("/init", response_model=InitResponse)
def init_experiment(
    request: InitRequest,
    user: Dict = Depends(get_current_user)
):
    github_username = user["nickname"]

    repo_url = create_gitops_repo(
        github_username,
        request.experiment_name,
    )

    repo_name = f"{github_username}-{request.experiment_name}"
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
    experiment_name: str = Form(...),
    files: List[UploadFile] = File(...),
    user: Dict = Depends(get_current_user)
):
 
    github_username = user["nickname"]
    
    repo_name = f"{github_username}-{experiment_name}"
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
            title=pr_title_template.format(proposal_hash=proposal_hash),
            body=(pr_doc_template.format(proposal_hash=proposal_hash, branch_name=branch_name)),
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

@app.post("/onboard")
def onboard_user(user: Dict = Depends(get_current_user)):

    github_username = user["nickname"]
    
    onboarding = load_onboarding()

    # Idempotent behavior
    if github_username in onboarding:
        return {"message": "Onboarding already initiated"}
    try:
        user = gh.get_user(github_username)
    except GithubException:
        raise HTTPException(
            status_code=400,
            detail=f"GitHub user '{github_username}' does not exist"
        )
        
    try:
        org.invite_user(
            user=user,
            role="direct_member"
        )
    except GithubException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invite user: {e.data}"
        )

    onboarding[github_username] = {
        "github_username": github_username,
        "invited_at": datetime.utcnow().isoformat() + "Z",
        "onboarded": False,
    }
    save_onboarding(onboarding)

    return {"message": "Invitation sent"}

@app.get("/onboard/status", response_model=OnboardStatusResponse)
def onboarding_status(
    user: Dict = Depends(get_current_user)
):
  
    github_username = user["nickname"]

    onboarding = load_onboarding()

    if github_username not in onboarding:
        return OnboardStatusResponse(onboarded=False, invitation=None)

    record = onboarding[github_username]

    # If already marked onboarded
    if record["onboarded"]:
        return OnboardStatusResponse(onboarded=True, invitation="")

    # Check GitHub org membership
    if is_org_member_by_username(record["github_username"]):
        record["onboarded"] = True
        record.update({
            "onboarded": True,
        })
        save_onboarding(onboarding)
        return OnboardStatusResponse(onboarded=True, invitation=InvitationStatus.accepted)

    return OnboardStatusResponse(onboarded=False, invitation=InvitationStatus.pending)
