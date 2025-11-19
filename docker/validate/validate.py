import os, json, subprocess, sys, pathlib, re
from datetime import datetime
from utils.pfs_move import move_path

SRC_PATH = os.environ["SRC_PATH"]       # /clean/<id>/<file>
ID       = os.environ["OBJ_ID"]
FILENAME = os.path.basename(SRC_PATH)
TMP      = "/work/in"
pathlib.Path("/work").mkdir(exist_ok=True)

def run(*args):
    """Run a command and return result; exit on failure."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: Command failed: {' '.join(args)}", file=sys.stderr)
        print(f"STDERR: {result.stderr}", file=sys.stderr)
        print(f"STDOUT: {result.stdout}", file=sys.stderr)
    return result

# Get Pachyderm endpoint and S3 configuration
endpoint = os.environ.get("PACH_S3_ENDPOINT", "http://pachd-proxy-backend.pachyderm:1600")
s3_url   = os.environ.get("PACH_S3_PREFIX", "s3://pach/media/master") + SRC_PATH

print(f"[validate] Downloading from S3: {s3_url}")
dl = run("aws", "s3", "cp", s3_url, TMP, "--endpoint-url", endpoint)
if dl.returncode != 0:
    print(f"[ERROR] Failed to download media file from Pachyderm S3", file=sys.stderr)
    sys.exit(2)

print(f"[validate] Running ffprobe on {TMP}")
ff = run("ffprobe", "-v", "error", "-hide_banner", "-show_streams", "-show_format", TMP)

print(f"[validate] Running mediainfo on {TMP}")
mi = run("mediainfo", TMP)

valid = ff.returncode == 0 and "codec_name" in ff.stdout
reason = None
if not valid:
    reason = mi.stdout[-400:] if mi.stdout else "No mediainfo output"

report = {
  "id": ID, 
  "file": FILENAME, 
  "stage": "validation",
  "status": "valid" if valid else "invalid",
  "ts": datetime.utcnow().isoformat()+"Z",
  "ffprobe_ok": ff.returncode == 0,
  "ffprobe_stderr": ff.stderr[-500:] if ff.stderr else "",
  "mediainfo_tail": mi.stdout[-1200:] if mi.stdout else ""
}

print(f"[validate] Report: {json.dumps(report, indent=2)}")
open("/work/report.json", "w").write(json.dumps(report, indent=2))

print(f"[validate] Uploading validation report to Pachyderm")
report_cmd = run("pachctl", "put", "file", f"media@master:/reports/{ID}/validation.json", "-f", "/work/report.json")
if report_cmd.returncode != 0:
    print(f"[WARN] Failed to upload report, but continuing with move operation", file=sys.stderr)

print(f"[validate] Moving media file (valid={valid})")
try:
    if valid:
        move_path(SRC_PATH, f"/validated/{ID}/{FILENAME}")
    else:
        move_path(SRC_PATH, f"/quarantine/{ID}/{FILENAME}")
    print(f"[validate] File moved successfully")
except SystemExit as e:
    print(f"[ERROR] Failed to move file: {e}", file=sys.stderr)
    sys.exit(3)

print(f"[validate] Task complete (status={report['status']})")