import os, json, subprocess, sys, pathlib, re
from datetime import datetime
from utils.pfs_move import move_path

SRC_PATH = os.environ["SRC_PATH"]       # /scanned/<id>/<file>
ID       = os.environ["OBJ_ID"]
FILENAME = os.path.basename(SRC_PATH)
TMP      = "/work/in"
pathlib.Path("/work").mkdir(exist_ok=True)

def run(*args):
    return subprocess.run(args, capture_output=True, text=True)

endpoint = os.environ["PACH_S3_ENDPOINT"]
s3_url   = os.environ["PACH_S3_PREFIX"] + SRC_PATH
dl = run("aws","--endpoint-url",endpoint,"s3","cp",s3_url,TMP)
if dl.returncode != 0: sys.exit(2)

ff = run("ffprobe","-v","error","-hide_banner","-show_streams","-show_format",TMP)
mi = run("mediainfo",TMP)

valid = ff.returncode == 0 and "codec_name" in ff.stdout
reason = None
if not valid:
    reason = mi.stdout[-400:]

report = {
  "id": ID, "file": FILENAME, "stage": "validation",
  "status": "valid" if valid else "invalid",
  "ts": datetime.utcnow().isoformat()+"Z",
  "ffprobe_ok": ff.returncode == 0,
  "mediainfo_tail": mi.stdout[-1200:]
}
open("/work/report.json","w").write(json.dumps(report, indent=2))
run("pachctl","put","file","media@master:/reports/{}/validation.json".format(ID),"-f","/work/report.json")

if valid:
    move_path(SRC_PATH, f"/validated/{ID}/{FILENAME}")
else:
    move_path(SRC_PATH, f"/quarantine/{ID}/{FILENAME}")