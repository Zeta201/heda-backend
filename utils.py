import hashlib
from pathlib import Path
import subprocess
from typing import List


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

