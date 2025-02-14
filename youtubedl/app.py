import socket
import dns.resolver

_original_getaddrinfo = socket.getaddrinfo


def custom_getaddrinfo(host, port, family=0, socktype=0, proto=0, flags=0):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["8.8.8.8"]
    try:
        answers = resolver.resolve(host, "A")
        ip = answers[0].to_text()
        return _original_getaddrinfo(ip, port, family, socktype, proto, flags)
    except Exception:
        return _original_getaddrinfo(host, port, family, socktype, proto, flags)


socket.getaddrinfo = custom_getaddrinfo

from flask import (
    Flask,
    jsonify,
    request,
    send_file,
    Response,
    after_this_request,
    render_template,
)
from yt_dlp import YoutubeDL
import threading
import uuid
import re
import tempfile
import zipfile
import shutil
import time
import json
from pathlib import Path

app = Flask(__name__)

jobs = {}


def is_valid_video_id(video_id):
    return re.match(r"^[a-zA-Z0-9_-]{11}$", video_id) is not None


def format_selector(ctx):
    formats = ctx.get("formats")[::-1]
    best_video = next(
        (
            f
            for f in formats
            if f["vcodec"] != "none" and f["acodec"] == "none" and f["ext"] == "mp4"
        ),
        None,
    )
    if not best_video:
        best_video = next(
            f for f in formats if f["vcodec"] != "none" and f["acodec"] == "none"
        )
    audio_ext = "m4a" if best_video["ext"] == "mp4" else "webm"
    best_audio = next(
        f
        for f in formats
        if f["acodec"] != "none" and f["vcodec"] == "none" and f["ext"] == audio_ext
    )
    yield {
        "format_id": f"{best_video['format_id']}+{best_audio['format_id']}",
        "ext": best_video["ext"],
        "requested_formats": [best_video, best_audio],
        "protocol": f"{best_video['protocol']}+{best_audio['protocol']}",
    }


def update_progress(job_id, data):
    job = jobs.get(job_id)
    if not job:
        return
    if data.get("status") == "downloading":
        downloaded = data.get("downloaded_bytes", 0)
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        percent = (downloaded / total * 100) if total > 0 else 0
        speed = data.get("speed", 0)
        eta = data.get("eta", 0)
        job["progress"] = {
            "percent": round(percent, 1),
            "downloaded": downloaded,
            "total": total,
            "speed": speed,
            "eta": eta,
        }
    elif data.get("status") == "finished":
        job["progress"] = {
            "percent": 100,
            "downloaded": data.get("downloaded_bytes", 0),
            "total": data.get("total_bytes", 0),
            "speed": data.get("speed", 0),
            "eta": 0,
        }


def download_job(job_id, video_ids):
    temp_dir = Path(tempfile.mkdtemp())
    downloaded_files = []
    job = jobs[job_id]
    try:
        for video_id in video_ids:
            if not is_valid_video_id(video_id):
                job["error"] = f"Invalid video ID: {video_id}"
                return
            ydl_opts = {
                "format": format_selector,
                "outtmpl": str(temp_dir / "%(title)s.%(ext)s"),
                "merge_output_format": "mp4",
                "quiet": True,
                "progress_hooks": [lambda d, jid=job_id: update_progress(jid, d)],
            }
            url = f"https://www.youtube.com/watch?v={video_id}"
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            for file in temp_dir.glob("*.mp4"):
                if file not in downloaded_files:
                    downloaded_files.append(file)
                    break
        if not downloaded_files:
            job["error"] = "No files downloaded."
            return
        job_dir = Path(tempfile.gettempdir()) / f"job_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        if len(downloaded_files) == 1:
            target = job_dir / downloaded_files[0].name
            shutil.move(str(downloaded_files[0]), str(target))
            job["download_url"] = f"/download_file/{job_id}/{target.name}"
        else:
            zip_path = temp_dir / "videos.zip"
            with zipfile.ZipFile(zip_path, "w") as zipf:
                for file in downloaded_files:
                    zipf.write(file, arcname=file.name)
            target = job_dir / "videos.zip"
            shutil.move(str(zip_path), str(target))
            job["download_url"] = f"/download_file/{job_id}/videos.zip"
        job["completed"] = True
    except Exception as e:
        job["error"] = str(e)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def start_download():
    content = request.get_json()
    if not content or "videoUrls" not in content:
        return jsonify({"error": "Missing videoUrls in request"}), 400
    video_urls = content["videoUrls"]
    urls = [url.strip() for url in video_urls.splitlines() if url.strip()]

    def extract_id(url):
        try:
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(url)
            if "youtu.be" in parsed.netloc:
                return parsed.path.lstrip("/")
            elif "youtube.com" in parsed.netloc:
                qs = parse_qs(parsed.query)
                return qs.get("v", [None])[0]
        except Exception:
            return None

    video_data = []
    for url in urls:
        vid = extract_id(url)
        if vid:
            try:
                with YoutubeDL({"quiet": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    sanitized = ydl.sanitize_info(info)
                    title = sanitized.get("title", vid)
                    uploader = sanitized.get("uploader", "")
            except Exception:
                title = vid
                uploader = ""
            video_data.append({"id": vid, "title": title, "uploader": uploader})
    if not video_data:
        return jsonify({"error": "No valid YouTube URLs found."}), 400
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"progress": {}, "completed": False, "videos": video_data}
    video_ids = [v["id"] for v in video_data]
    thread = threading.Thread(target=download_job, args=(job_id, video_ids))
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def progress(job_id):
    def generate():
        while True:
            job = jobs.get(job_id)
            if not job:
                break
            payload = {
                "progress": job.get("progress", {}),
                "completed": job.get("completed", False),
                "download_url": job.get("download_url", ""),
                "error": job.get("error", ""),
                "videos": job.get("videos", []),
            }
            data = json.dumps(payload)
            yield f"data: {data}\n\n"
            if job.get("completed") or job.get("error"):
                break
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/download_file/<job_id>/<filename>")
def download_file(job_id, filename):
    job_dir = Path(tempfile.gettempdir()) / f"job_{job_id}"
    file_path = job_dir / filename
    if file_path.exists():

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(job_dir)
                jobs.pop(job_id, None)
            except Exception as e:
                app.logger.error(f"Cleanup failed: {str(e)}")
            return response

        return send_file(str(file_path), as_attachment=True)
    return "File not found", 404


if __name__ == "__main__":
    app.run(debug=True)
