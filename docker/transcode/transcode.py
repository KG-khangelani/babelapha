import os, subprocess, json, sys, pathlib
from datetime import datetime
ID       = os.environ["OBJ_ID"]
SRC_PATH = os.environ["SRC_PATH"]       # /validated/<id>/<file>
FILENAME = os.path.basename(SRC_PATH)
BASENAME = os.path.splitext(FILENAME)[0]
TMPDIR   = "/work"
pathlib.Path(TMPDIR).mkdir(exist_ok=True)

def run(*args): return subprocess.run(args, capture_output=True, text=True)

endpoint = os.environ["PACH_S3_ENDPOINT"]
s3pref   = os.environ["PACH_S3_PREFIX"]

# fetch
if run("aws","--endpoint-url",endpoint,"s3","cp",s3pref+SRC_PATH, f"{TMPDIR}/in").returncode != 0:
    sys.exit(2)

# make HLS (simple 720p)
hlsdir = f"{TMPDIR}/hls"
os.makedirs(hlsdir, exist_ok=True)
ff = run("ffmpeg","-y","-i",f"{TMPDIR}/in","-vf","scale=-2:720","-c:v","h264","-c:a","aac",
         "-f","hls","-hls_time","4","-hls_playlist_type","vod",f"{hlsdir}/{BASENAME}.m3u8")
status = "success" if ff.returncode==0 else "failed"

# upload rendition folder
if status=="success":
    run("aws","--endpoint-url",endpoint,"s3","cp","--recursive",hlsdir, f"{s3pref}/transcoded/{ID}/hls")

# report
report = {"id": ID, "file": FILENAME, "stage": "transcode", "status": status, "ts": datetime.utcnow().isoformat()+"Z"}
open(f"{TMPDIR}/report.json","w").write(json.dumps(report, indent=2))
run("pachctl","put","file","media@master:/reports/{}/transcode.json".format(ID),"-f",f"{TMPDIR}/report.json")

# finally: leave the source at /validated; you may optionally "archive" it:
# from pfs_move import move_path
# move_path(SRC_PATH, f"/validated/{ID}/{FILENAME}")  # no-op example