# file: pfs_move.py
import os, subprocess, sys

REPO = os.environ.get("PFS_REPO", "media")
BRANCH = os.environ.get("PFS_BRANCH", "master")

def run(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"cmd failed: {' '.join(args)}\n{r.stderr}")
    return r.stdout

def move_path(src, dst):
    # Copy (logical, content-addressed) then remove old path—net effect: a move in a new commit.
    run("pachctl", "copy", "file", f"{REPO}@{BRANCH}:{src}", f"{REPO}@{BRANCH}:{dst}")
    run("pachctl", "delete", "file", f"{REPO}@{BRANCH}:{src}")

if __name__ == "__main__":
    # usage: python pfs_move.py /incoming/id/file.mp4 /scanned/id/file.mp4
    move_path(sys.argv[1], sys.argv[2])