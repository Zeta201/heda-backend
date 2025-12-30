from dotenv import load_dotenv
import os
from app.auth import get_github_token_for_user
from github import Github
from github.Auth import AppAuth

load_dotenv()


GITHUB_ORG = os.environ.get("GITHUB_ORG") 
ADMIN_GITHUB_TOKEN = os.environ.get("GITHUB_ADMIN_TOKEN")  
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")  
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")


if not ADMIN_GITHUB_TOKEN:
    raise RuntimeError("Missing environment variables: GITHUB_ADMIN_TOKEN")

gh = Github(ADMIN_GITHUB_TOKEN)
org = gh.get_organization(GITHUB_ORG)

def get_user_gh(user_token: str):
    return Github(user_token)

def get_user_org(user_token: str):
    gh = get_user_gh(user_token)
    return gh.get_organization(GITHUB_ORG)


def get_github_client_for_user(user_id: str) -> Github:
    github_token = get_github_token_for_user(user_id)
    return Github(github_token)


