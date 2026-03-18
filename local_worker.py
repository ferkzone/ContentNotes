import os
import time
import logging
import subprocess
import tempfile
from pathlib import Path

import yt_dlp
import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="ContentNotes Worker")

TEMP_DIR = Path(tempfile.gettempdir()) / "contentnotes_worker"
TEMP_DIR.mkdir(exist_ok=True)

# file_id -> status string
# possible values: DOWNLOADING, COMPRESSING, READY, ERROR: <message>
jobs: dict[str, str] = {}


def run_download(url: str, file_id: str, raw_mp3: Path, final_mp3: Path) -> None:
    try:
        jobs[file_id] = "DOWNLOADING"
        logger.info("starting download: %s", url)

        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }],
            "outtmpl": str(raw_mp3).replace(".mp3", ""),
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not raw_mp3.exists():
            raise RuntimeError("yt-dlp finished but output file not found")

        jobs[file_id] = "COMPRESSING"
        logger.info("compressing: %s", file_id)

        result = subprocess.run(
            [
                "ffmpeg", "-i", str(raw_mp3),
                "-acodec", "libmp3lame",
                "-b:a", "32k",
                "-ar", "16000",
                "-ac", "1",
                "-y", str(final_mp3),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {result.returncode}: {result.stderr[:200]}")

        raw_mp3.unlink(missing_ok=True)

        jobs[file_id] = "READY"
        logger.info("done: %s", file_id)

    except Exception as exc:
        logger.error("job %s failed: %s", file_id, exc)
        jobs[file_id] = f"ERROR: {exc}"


@app.post("/download-youtube")
async def download_youtube(data: dict, background_tasks: BackgroundTasks):
    url = data.get("url")
    if not url:
        return JSONResponse(status_code=400, content={"error": "missing url"})

    ts       = int(time.time())
    file_id  = f"yt_{ts}.mp3"
    raw_mp3  = TEMP_DIR / f"raw_{ts}.mp3"
    final_mp3 = TEMP_DIR / file_id

    background_tasks.add_task(run_download, url, file_id, raw_mp3, final_mp3)
    logger.info("accepted job: %s", file_id)

    return {"status": "started", "audio_file": file_id}


@app.get("/check/{file_id}")
async def check_status(file_id: str):
    return {"file_id": file_id, "status": jobs.get(file_id, "NOT_FOUND")}


@app.get("/download/{file_id}")
async def get_file(file_id: str):
    path = TEMP_DIR / file_id
    if path.exists() and jobs.get(file_id) == "READY":
        return FileResponse(path=path, media_type="audio/mpeg", filename=file_id)
    return JSONResponse(
        status_code=404,
        content={"error": "not ready", "status": jobs.get(file_id)},
    )


@app.get("/health")
def health():
    active = sum(1 for s in jobs.values() if s not in ("READY",) and not s.startswith("ERROR"))
    return {"status": "online", "active_jobs": active}


if __name__ == "__main__":
    print("ContentNotes worker running on port 8000")
    print("Open a tunnel with: ssh -R <name>:80:localhost:8000 serveo.net")
    uvicorn.run(app, host="0.0.0.0", port=8000)
