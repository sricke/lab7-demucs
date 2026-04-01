#!/usr/bin/env python3

import base64
import hashlib
import io
import json
import os
from datetime import datetime, timezone

import redis
from flask import Flask, jsonify, request, send_file
from minio import Minio
from minio.error import S3Error


app = Flask(__name__)


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
QUEUE_KEY = os.getenv("REDIS_QUEUE_KEY", "toWorker")
LOG_KEY = os.getenv("REDIS_LOG_KEY", "logging")

MINIO_HOST = os.getenv("MINIO_HOST", "localhost:9000")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "rootuser")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "rootpass123")
MINIO_INPUT_BUCKET = os.getenv("MINIO_INPUT_BUCKET", "queue")
MINIO_OUTPUT_BUCKET = os.getenv("MINIO_OUTPUT_BUCKET", "output")

TRACK_NAMES = {"bass.mp3", "base.mp3", "drums.mp3", "vocals.mp3", "other.mp3"}

redis_client = redis.StrictRedis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
)
minio_client = Minio(
    MINIO_HOST,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)


def log_info(message: str) -> None:
    payload = f"[{datetime.now(timezone.utc).isoformat()}] {message}"
    try:
        redis_client.lpush(LOG_KEY, payload)
    except Exception:
        pass


def ensure_bucket(bucket_name: str) -> None:
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)


def normalize_track_name(track: str) -> str:
    if track == "base.mp3":
        return "bass.mp3"
    return track


@app.route("/", methods=["GET"])
def root():
    return "<h1> Music Separation Server</h1><p> Use a valid endpoint </p>", 200


@app.route("/apiv1/separate", methods=["POST"])
def separate():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"reason": "Request must contain JSON body"}), 400

    mp3_b64 = data.get("mp3")
    if not mp3_b64:
        return jsonify({"reason": "Missing required field 'mp3'"}), 400

    try:
        mp3_bytes = base64.b64decode(mp3_b64)
    except Exception:
        return jsonify({"reason": "Field 'mp3' must be valid base64 data"}), 400

    songhash = hashlib.sha224(mp3_bytes).hexdigest()
    callback = data.get("callback")

    object_name = f"{songhash}.mp3"
    try:
        ensure_bucket(MINIO_INPUT_BUCKET)
        ensure_bucket(MINIO_OUTPUT_BUCKET)
        minio_client.put_object(
            MINIO_INPUT_BUCKET,
            object_name,
            io.BytesIO(mp3_bytes),
            length=len(mp3_bytes),
            content_type="audio/mpeg",
        )
    except S3Error as exc:
        log_info(f"minio write failed for {songhash}: {exc}")
        return jsonify({"reason": "Unable to persist MP3 in object storage"}), 500

    work_item = {
        "songhash": songhash,
        "callback": callback,
        "input_bucket": MINIO_INPUT_BUCKET,
        "input_object": object_name,
        "output_bucket": MINIO_OUTPUT_BUCKET,
    }

    try:
        redis_client.rpush(QUEUE_KEY, json.dumps(work_item))
    except Exception as exc:
        log_info(f"redis queue write failed for {songhash}: {exc}")
        return jsonify({"reason": "Unable to enqueue work item"}), 500

    log_info(f"queued separation request for {songhash}")
    return jsonify({"hash": songhash, "reason": "Song enqueued for separation"}), 200


@app.route("/apiv1/queue", methods=["GET"])
def queue_dump():
    try:
        queue = redis_client.lrange(QUEUE_KEY, 0, -1)
    except Exception as exc:
        log_info(f"redis queue read failed: {exc}")
        return jsonify({"reason": "Unable to read queue"}), 500
    return jsonify({"queue": queue}), 200


@app.route("/apiv1/track/<songhash>/<track>", methods=["GET"])
def get_track(songhash, track):
    if track not in TRACK_NAMES:
        return jsonify({"reason": "Track must be one of bass/base/vocals/drums/other.mp3"}), 400

    normalized_track = normalize_track_name(track)
    object_name = f"{songhash}-{normalized_track}"
    try:
        response = minio_client.get_object(MINIO_OUTPUT_BUCKET, object_name)
        data = response.read()
        response.close()
        response.release_conn()
    except S3Error:
        return jsonify({"reason": "Track not found"}), 404

    return send_file(
        io.BytesIO(data),
        mimetype="audio/mpeg",
        as_attachment=True,
        download_name=normalized_track,
    )


@app.route("/apiv1/remove/<songhash>/<track>", methods=["GET", "DELETE"])
def remove_track(songhash, track):
    if track not in TRACK_NAMES:
        return jsonify({"reason": "Track must be one of bass/base/vocals/drums/other.mp3"}), 400

    normalized_track = normalize_track_name(track)
    object_name = f"{songhash}-{normalized_track}"
    try:
        minio_client.remove_object(MINIO_OUTPUT_BUCKET, object_name)
    except S3Error:
        return jsonify({"reason": "Track not found"}), 404

    log_info(f"removed track object {object_name}")
    return jsonify({"reason": "Track removed", "hash": songhash, "track": normalized_track}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
