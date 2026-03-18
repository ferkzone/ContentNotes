# [ContentNotes](https://tuapp.streamlit.app)

A local application that takes any audio or video file and turns it into structured academic notes using Google's Gemini AI. It runs entirely on your machine, works offline for everything except the AI calls, and supports YouTube videos directly through yt-dlp.

---

## What it does

You give it an audio file, a video file, or a YouTube URL. It compresses the audio, sends it to Gemini, and returns detailed notes formatted by content type. If it detects a programming lecture, it structures the notes differently than if it detects a math class or a general talk. The notes come out in Markdown and can be exported as PDF.

---

## Requirements

Before installing the Python dependencies, make sure you have the following installed on your system:

**Python 3.11 or higher**
Download from https://www.python.org/downloads/

**ffmpeg**
Required for audio compression. Without it the app cannot process any file.
- Windows: `winget install ffmpeg` or download from https://ffmpeg.org/download.html
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`

After installing ffmpeg on Windows, restart your terminal so the PATH is updated.

**A Google Gemini API key**
Get one for free at https://aistudio.google.com/app/apikey. The free tier is enough for personal use.

---

## Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/yourusername/contentnotes-local.git
cd contentnotes-local
pip install -r requirements.txt
```

Create a `.streamlit` folder in the root of the project and inside it a file called `secrets.toml`:

```
.streamlit/
    secrets.toml
```

Add your API key to that file:

```toml
GOOGLE_API_KEY = "your_api_key_here"
```

Do not commit this file to git. Add `.streamlit/secrets.toml` to your `.gitignore`.

---

## Running the app

```bash
python -m streamlit run app.py
```

Then open http://localhost:8501 in your browser. The app does not need an internet connection except to reach the Gemini API.

---

## Using YouTube

YouTube support works out of the box through yt-dlp, which is included in the dependencies. Paste any YouTube URL into the YouTube tab and the app handles the download, compression, and note generation automatically.

If a video fails to download, updating yt-dlp usually fixes it since YouTube changes its internals frequently:

```bash
pip install --upgrade yt-dlp
```

---

## File formats supported

Audio: mp3, wav, flac, aac, m4a, ogg
Video: mp4, avi, mov, mkv, webm

Video files are fine to upload. The app strips the video track automatically before sending anything to the API, so you are only billed for audio tokens.

---

## PDF export

The app generates PDFs using xhtml2pdf, which works on Windows without any additional system libraries. The PDF includes syntax-highlighted code blocks and basic LaTeX symbol rendering for math content.

WeasyPrint is also included as a higher-quality alternative for Linux and macOS. The app will use it automatically if it is available on your system.

---

## File size and cost

Gemini charges based on audio duration, not file size. A one-hour lecture at 32kbps mono (how the app compresses it) is about 14MB. The free tier covers a reasonable amount of usage for personal note-taking.

---

## Project structure

```
app.py                  main application
optimized_pipeline.py   Gemini integration and note generation
pdf_generator.py        PDF and HTML export
config.json             prompts and translations
requirements.txt        Python dependencies
.env                    your API key (not committed to git)
```

---

## Notes

The app stores no data. Everything is processed in memory and temporary files are deleted after each run. Your API key never leaves your machine except in the requests to Google's API.

The language toggle in the top left switches the interface and the note generation prompts between Spanish and English.
