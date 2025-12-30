import hashlib
from pathlib import Path
import subprocess
from typing import List

import hmac

from app.config import GITHUB_WEBHOOK_SECRET


def compute_experiment_hash(files: List[Path]) -> str:
    """
    Deterministic hash across file paths + contents
    """
    h = hashlib.sha256()
    for f in sorted(files, key=lambda p: str(p)):
        h.update(str(f.relative_to(f.parents[len(f.parents) - 2])).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def run_git(cmd: List[str], cwd: Path):
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def verify_signature(payload: bytes, signature: str):
    if not signature:
        raise ValueError("Missing signature")

    sha_name, signature = signature.split("=")

    if sha_name != "sha256":
        raise ValueError("Unsupported signature type")

    mac = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        msg=payload,
        digestmod=hashlib.sha256,
    )

    if not hmac.compare_digest(mac.hexdigest(), signature):
        raise ValueError("Invalid signature")
