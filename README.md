# ContentNotes

ContentNotes takes audio and video content and converts it into structured academic notes. You upload a file, it goes to Gemini, and what comes back are properly formatted notes that reflect the type of content — a programming lecture gets code examples and complexity analysis, a math class gets formal definitions and worked examples, a general talk gets a clean summary. The whole process takes one API call.

The app is deployed on Streamlit Cloud and requires no installation to use.

---

## How it works

When you upload a file, the app runs it through ffmpeg to strip the video track and compress the audio to a lightweight mono MP3. This reduces the file size significantly before anything is sent to the API. The compressed audio goes to Gemini along with a detailed system prompt that describes how to structure the notes depending on the content type. Gemini identifies the category on its own and returns the notes formatted accordingly.

The notes are displayed in the app and can be downloaded as a PDF or Markdown file.

Supported formats: mp3, wav, flac, aac, m4a, ogg, mp4, avi, mov, mkv, webm.

---

## Content categories

The app recognizes the following types of academic content and applies a specific note structure to each:

- Programming and software engineering
- Mathematics
- Statistics
- Theory of computation
- Operating systems and computer architecture
- Machine learning and AI
- Computer networks
- Databases

Anything that does not fit a specific category is handled as general content with a flexible structure.

Both Spanish and English are supported. The language toggle in the top left switches the interface language and the prompts used for note generation.

---

## YouTube support with the local worker

By default the app only shows the file upload tab. YouTube support is intentionally disabled on the cloud deployment because yt-dlp does not work reliably on shared cloud servers.

To enable YouTube, you run a small server called `local_worker.py` on your own machine. This server handles the YouTube download locally and makes the audio available to the cloud app over a tunnel. When the cloud app detects that the worker is reachable, it shows the YouTube tab automatically.

### What the local worker does

`local_worker.py` is a FastAPI application that exposes three endpoints:

- `POST /download-youtube` — receives a YouTube URL, starts the download with yt-dlp in the background, and immediately returns a file ID
- `GET /check/{file_id}` — returns the current status of the download (DOWNLOADING, COMPRESSING, READY, or ERROR)
- `GET /download/{file_id}` — serves the compressed audio file once it is ready
- `GET /health` — used by the cloud app to check if the worker is reachable

The cloud app polls the check endpoint until the file is ready, then downloads it and processes it the same way as a regular file upload.

### Running the local worker

Install the dependencies on your machine:

```bash
pip install fastapi uvicorn yt-dlp
```

ffmpeg must also be installed on your system. The worker uses it to compress the audio after downloading.

Run the server:

```bash
python local_worker.py
```

The server starts on port 8000. To make it reachable from the internet, expose it through a tunnel. Serveo is a simple option that requires no account:

```bash
ssh -R your-chosen-name:80:localhost:8000 serveo.net
```

This gives you a public URL like `https://your-chosen-name.serveo.net`. Add it to your Streamlit secrets:

```toml
GOOGLE_API_KEY = "your_key_here"
LOCAL_WORKER_URL = "https://your-chosen-name.serveo.net"
```

Once the secret is set and the worker is running, reload the app and the YouTube tab will appear. When you stop the worker or close the tunnel, the tab disappears automatically.

### Notes on the tunnel

The connection between the cloud app and your local worker goes through the tunnel. If your internet connection is unstable, downloads may fail or time out. The app retries failed transfers up to three times automatically.

The tunnel only needs to be open while you are actively using the YouTube feature. You can start and stop it as needed without redeploying the app.

---

## Project structure

```
app.py                  main application
optimized_pipeline.py   Gemini integration and note generation
pdf_generator.py        PDF and HTML export
config.json             prompts and translations
local_worker.py         optional local server for YouTube support
requirements.txt        Python dependencies
.streamlit/
    secrets.toml        API key and worker URL (not committed to git)
```

---

## API usage and cost

The app uses a single Gemini API call per file to handle both transcription and note generation. The free tier at https://aistudio.google.com covers personal use comfortably. Audio is billed by duration, and the compression step keeps file sizes small before anything reaches the API.


