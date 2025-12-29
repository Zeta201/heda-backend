from dotenv import load_dotenv
import os
from github import Github, GithubException

load_dotenv()

# -----------------------------
# CONFIGURATION
# -----------------------------

GITHUB_ORG = os.environ.get("GITHUB_ORG") 
ADMIN_GITHUB_TOKEN = os.environ.get("GITHUB_ADMIN_TOKEN")  # Admin token

if not ADMIN_GITHUB_TOKEN:
    raise RuntimeError("Missing environment variables: GITHUB_ADMIN_TOKEN")

gh = Github(ADMIN_GITHUB_TOKEN)
org = gh.get_organization(GITHUB_ORG)