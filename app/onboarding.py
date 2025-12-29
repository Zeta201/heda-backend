
import json
from pathlib import Path
from typing import Dict
from github import GithubException
from .config import org

ONBOARDING_DB = Path("data/onboarding.json")
ONBOARDING_DB.parent.mkdir(exist_ok=True)

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
