from datetime import datetime
from pathlib import Path
import shutil
import tempfile
from typing import List
from fastapi import UploadFile

from .models import PublishResponse

from .utils import compute_experiment_hash, run_git

from .config import GITHUB_ORG, get_github_client_for_user, get_user_org

from .templates.pr_template import pr_title_template, pr_doc_template


async def publish_experiment_backend(
    experiment_name: str,
    files: List[UploadFile],
    github_username: str,
    user_id: str
):
 
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
        
        gh = get_github_client_for_user(user_id)
        
        org = gh.get_organization(GITHUB_ORG)
        
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
