import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import minio
import redis
import requests

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
QUEUE_KEY = os.getenv("REDIS_QUEUE_KEY", "toWorker")
LOG_KEY = os.getenv("REDIS_LOG_KEY", "logging")

MINIO_HOST = os.getenv("MINIO_HOST", "localhost:9000")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "rootuser")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "rootpass123")

# Must match rest/rest-server.py defaults
MINIO_INPUT_BUCKET = os.getenv("MINIO_INPUT_BUCKET", "queue")
MINIO_OUTPUT_BUCKET = os.getenv("MINIO_OUTPUT_BUCKET", "output")


DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "mdx_extra_q")
DEMUCS_TIMEOUT_SEC = int(os.getenv("DEMUCS_TIMEOUT_SEC", "1200"))

redis_client = redis.StrictRedis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
)
minio_client = minio.Minio(
    MINIO_HOST,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)


def log_info(message: str) -> None:
    payload = f"[{datetime.now(timezone.utc).isoformat()}] {message}"
    print(payload, flush=True)
    try:
        redis_client.lpush(LOG_KEY, payload)
    except Exception:
        pass


def fire_callback(callback):
    if not callback or not isinstance(callback, dict):
        return
    url = callback.get("url")
    payload = callback.get("data")
    if not url:
        return
    try:
        requests.post(url, json=payload if payload is not None else {}, timeout=30)
    except Exception as e:
        log_info(f"Error firing callback: {url} with payload {payload}: {e}")


def process_work_item(work_item: dict) -> None:
    songhash = work_item["songhash"]
    input_bucket = work_item.get("input_bucket", MINIO_INPUT_BUCKET)
    input_object = work_item["input_object"]
    output_bucket = work_item.get("output_bucket", MINIO_OUTPUT_BUCKET)
    callback = work_item.get("callback")

    local_mp3 = os.path.join("/tmp", input_object)
    os.makedirs("/tmp", exist_ok=True)

    try:
        resp = minio_client.get_object(input_bucket, input_object)
        data = resp.read()
        resp.close()
        resp.release_conn()
    except Exception as exc:
        log_info(f"minio get failed {input_bucket}/{input_object}: {exc}")
        return

    with open(local_mp3, "wb") as f:
        f.write(data)

    out_root = "/tmp/output"
    os.makedirs(out_root, exist_ok=True)

    # run using subprocess so we can see logs
    argv = [
        "python3",
        "-u",
        "-m",
        "demucs.separate",
        "-n",
        DEMUCS_MODEL,
        "--out",
        out_root,
        local_mp3,
        "--mp3",
    ]
    log_info(
        f"demucs starting model={DEMUCS_MODEL} songhash={songhash} "
    )
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        run_kw = {
            "args": argv,
            "env": env,
            "check": False,
        }
        if DEMUCS_TIMEOUT_SEC > 0:
            run_kw["timeout"] = DEMUCS_TIMEOUT_SEC
        completed = subprocess.run(**run_kw)
        rc = completed.returncode
    except subprocess.TimeoutExpired:
        log_info(
            f"demucs TIMEOUT after {DEMUCS_TIMEOUT_SEC}s for {songhash}; "
            f"increase DEMUCS_TIMEOUT_SEC or set 0 to disable"
        )
        return
    log_info(f"demucs finished for {songhash} rc={rc}")
    if rc != 0:
        log_info(f"demucs failed rc={rc} for {songhash}")
        return

    stem = os.path.splitext(input_object)[0]
    separated_dir = os.path.join(out_root, DEMUCS_MODEL, stem)
    if not os.path.isdir(separated_dir):
        for sub in sorted(os.listdir(out_root)):
            cand = os.path.join(out_root, sub, stem)
            if os.path.isdir(cand):
                separated_dir = cand
                log_info(f"found demucs output under {separated_dir}")
                break
    if not os.path.isdir(separated_dir):
        log_info(f"missing demucs output dir under {out_root} for stem={stem}")
        return

    for fname in os.listdir(separated_dir):
        if not fname.endswith(".mp3"):
            continue
        local_path = os.path.join(separated_dir, fname)
        object_name = f"{songhash}-{fname}"
        try:
            minio_client.fput_object(output_bucket, object_name, local_path)
        except Exception as exc:
            log_info(f"minio put failed {output_bucket}/{object_name}: {exc}")
            return

    log_info(f"completed separation for {songhash}")
    fire_callback(callback)


def main():
    log_info("worker started")
    while True:
        try:
            popped = redis_client.blpop(QUEUE_KEY, timeout=0)
            if not popped:
                continue
            _, raw = popped
            work_item = json.loads(raw)
            log_info(f"got work: {work_item.get('songhash', '?')}")
            process_work_item(work_item)
        except json.JSONDecodeError as exc:
            log_info(f"bad queue JSON: {exc}")
        except Exception as exc:
            log_info(f"worker loop error: {exc}")
        sys.stdout.flush()
        sys.stderr.flush()


if __name__ == "__main__":
    main()
