from datetime import datetime
from typing import Dict, List
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile

from .constants import InvitationStatus

from .onboarding import is_org_member_by_username, load_onboarding, save_onboarding
from .publishing import publish_experiment_backend

from .auth import get_current_user
from .github_utils import create_gitops_repo, initialize_local_repo
from .models import InitRequest, InitResponse, OnboardStatusResponse, PublishResponse
from .config import gh, org
from github import GithubException

app = FastAPI(title="HEDA GitOps Backend")

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
async def publish_experiment(
    experiment_name: str = Form(...),
    files: List[UploadFile] = File(...),
    user: dict = Depends(get_current_user)
):
    github_username = user["nickname"]
    return await publish_experiment_backend(experiment_name, files, github_username)


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
