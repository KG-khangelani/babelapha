# file: docker/clamav/scan.py
import os, json, subprocess, sys, pathlib
from datetime import datetime
from pfs_move import move_path

PACH_TOKEN = os.environ.get("PACH_TOKEN","")
if PACH_TOKEN: os.environ["PACHTOKEN"] = PACH_TOKEN

SRC_PATH   = os.environ["SRC_PATH"]     # e.g. /incoming/1234/file.mp4
ID         = os.environ["OBJ_ID"]       # e.g. 1234
FILENAME   = os.path.basename(SRC_PATH)
TMP        = "/work/in"
pathlib.Path("/work").mkdir(exist_ok=True)

def run(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
    return r

# fetch via S3 gateway
def s3cp(src, dst):
    endpoint = os.environ["PACH_S3_ENDPOINT"]  # http://pach-s3.pachd:30600
    return run("aws","--endpoint-url",endpoint,"s3","cp",src,dst)

# write JSON report back to PFS (reports don’t duplicate the big media file)
def put_report(obj):
    report_path = f"/reports/{ID}/clamav.json"
    tmp = "/work/report.json"
    open(tmp,"w").write(json.dumps(obj, indent=2))
    return run("pachctl","put","file","media@master:"+report_path,"-f",tmp)

# main
s3_url = os.environ["PACH_S3_PREFIX"] + SRC_PATH  # e.g. s3://pach/media/master/incoming/1234/file.mp4
dl = s3cp(s3_url, TMP)
if dl.returncode != 0:
    sys.exit(2)

scan = run("clamscan","--stdout",TMP)
infected = "Infected files: 0" not in scan.stdout

report = {
  "id": ID,
  "file": FILENAME,
  "stage": "virus_scan",
  "status": "infected" if infected else "clean",
  "ts": datetime.now().isoformat()+"Z",
  "raw": scan.stdout[-2000:]  # tail for context
}
put_report(report)

if infected:
    # move to quarantine
    move_path(SRC_PATH, f"/quarantine/{ID}/{FILENAME}")
else:
    # move to scanned
    move_path(SRC_PATH, f"/scanned/{ID}/{FILENAME}")