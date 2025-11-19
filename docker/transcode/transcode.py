import os, subprocess, json, sys, pathlib
from datetime import datetime

ID       = os.environ["OBJ_ID"]
SRC_PATH = os.environ["SRC_PATH"]       # /validated/<id>/<file>
FILENAME = os.path.basename(SRC_PATH)
BASENAME = os.path.splitext(FILENAME)[0]
TMPDIR   = "/work"
pathlib.Path(TMPDIR).mkdir(exist_ok=True)

def run(*args):
    """Run command and log errors."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Command failed: {' '.join(args)}", file=sys.stderr)
        print(f"STDERR: {result.stderr}", file=sys.stderr)
    return result

print(f"[transcode] Processing {SRC_PATH}")

endpoint = os.environ.get("PACH_S3_ENDPOINT", "http://pachd-proxy-backend.pachyderm:1600")
s3pref   = os.environ.get("PACH_S3_PREFIX", "s3://pach/media/master")

# fetch
print(f"[transcode] Downloading from S3: {s3pref}{SRC_PATH}")
if run("aws", "--endpoint-url", endpoint, "s3", "cp", s3pref + SRC_PATH, f"{TMPDIR}/in").returncode != 0:
    print(f"[ERROR] Failed to download source file", file=sys.stderr)
    sys.exit(2)

# make HLS (simple 720p)
print(f"[transcode] Encoding to HLS...")
hlsdir = f"{TMPDIR}/hls"
os.makedirs(hlsdir, exist_ok=True)
ff = run("ffmpeg", "-y", "-i", f"{TMPDIR}/in", "-vf", "scale=-2:720", "-c:v", "h264", "-c:a", "aac",
         "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod", f"{hlsdir}/{BASENAME}.m3u8")
status = "success" if ff.returncode == 0 else "failed"

print(f"[transcode] Encoding status: {status}")
# upload rendition folder
if status == "success":
    print(f"[transcode] Uploading HLS output to S3")
    run("aws", "--endpoint-url", endpoint, "s3", "cp", "--recursive", hlsdir, f"{s3pref}/transcoded/{ID}/hls")

# report
report = {
    "id": ID,
    "file": FILENAME,
    "stage": "transcode",
    "status": status,
    "ts": datetime.utcnow().isoformat() + "Z"
}
print(f"[transcode] Report: {json.dumps(report, indent=2)}")
with open(f"{TMPDIR}/report.json", "w") as f:
    json.dump(report, f, indent=2)

print(f"[transcode] Uploading report to Pachyderm")
run("pachctl", "put", "file", f"media@master:/reports/{ID}/transcode.json", "-f", f"{TMPDIR}/report.json")
print(f"[transcode] Task complete (status={status})")