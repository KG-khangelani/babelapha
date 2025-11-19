# file: docker/clamav/scan.py
import os, json, subprocess, sys, pathlib
from datetime import datetime
from utils.pfs_move import move_path

PACH_TOKEN = os.environ.get("PACH_TOKEN", "")
if PACH_TOKEN:
    os.environ["PACHTOKEN"] = PACH_TOKEN

SRC_PATH   = os.environ["SRC_PATH"]     # e.g. /incoming/1234/file.mp4
ID         = os.environ["OBJ_ID"]       # e.g. 1234
FILENAME   = os.path.basename(SRC_PATH)
TMP        = "/work/in"
pathlib.Path("/work").mkdir(exist_ok=True)

def run(*args):
    """Run command and return result; log errors."""
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[ERROR] Command failed: {' '.join(args)}", file=sys.stderr)
        print(f"STDERR: {r.stderr}", file=sys.stderr)
    return r

# Fetch via S3 gateway
def s3cp(src, dst):
    endpoint = os.environ.get("PACH_S3_ENDPOINT", "http://pachd-proxy-backend.pachyderm:1600")
    return run("aws", "--endpoint-url", endpoint, "s3", "cp", src, dst)

# Write JSON report back to PFS (reports don't duplicate the big media file)
def put_report(obj):
    report_path = f"/reports/{ID}/clamav.json"
    tmp = "/work/report.json"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    return run("pachctl", "put", "file", "media@master:" + report_path, "-f", tmp)

# Main
print(f"[clamav] Scanning {SRC_PATH}")
s3_url = os.environ.get("PACH_S3_PREFIX", "s3://pach/media/master") + SRC_PATH
print(f"[clamav] Downloading from S3: {s3_url}")
dl = s3cp(s3_url, TMP)
if dl.returncode != 0:
    print(f"[ERROR] Failed to download from S3", file=sys.stderr)
    sys.exit(2)

print(f"[clamav] Running clamscan")
scan = run("clamscan", "--stdout", TMP)
infected = "Infected files: 0" not in scan.stdout

report = {
  "id": ID,
  "file": FILENAME,
  "stage": "virus_scan",
  "status": "infected" if infected else "clean",
  "ts": datetime.now().isoformat() + "Z",
  "raw": scan.stdout[-2000:]  # tail for context
}
print(f"[clamav] Report: {json.dumps(report, indent=2)}")
print(f"[clamav] Uploading report")
report_result = put_report(report)
if report_result.returncode != 0:
    print(f"[WARN] Failed to upload report, continuing", file=sys.stderr)

print(f"[clamav] Moving file (status={report['status']})")
try:
    if infected:
        # move to quarantine
        move_path(SRC_PATH, f"/quarantine/{ID}/{FILENAME}")
    else:
        # move to clean
        move_path(SRC_PATH, f"/clean/{ID}/{FILENAME}")
    print(f"[clamav] Task complete")
except SystemExit as e:
    print(f"[ERROR] Failed to move file: {e}", file=sys.stderr)
    sys.exit(3)
