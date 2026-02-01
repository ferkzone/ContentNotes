import re
import os
import time
import subprocess
from pathlib import Path
import streamlit as st
import google.generativeai as genai


def extract_video_id(url: str) -> str | None:
    """Extrae ID de video de YouTube"""
    match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None


def download_and_transcribe(source: str, is_youtube: bool = False) -> str | None:
    """Descarga audio y transcribe con Gemini"""
    
    temp_dir = "/tmp/contentnotes"
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        if is_youtube:
            video_id = extract_video_id(source)
            if not video_id:
                st.error(" URL de YouTube inválida")
                return None
            
            try:
                import yt_dlp
            except ImportError:
                st.error("⚠️ Instala: pip install yt-dlp")
                return None
            
            with st.status("Descargando..."):
                audio_path = os.path.join(temp_dir, f"yt_{video_id}.mp3")
                
                ydl_opts = {
                    "format": "bestaudio/best",
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    }],
                    "outtmpl": os.path.join(temp_dir, f"yt_{video_id}"),
                    "quiet": False,
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                }
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
                except Exception as e:
                    st.error(f" Error descargando: {str(e)[:80]}")
                    return None
                
                time.sleep(1)
                if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                    st.error(" No se descargó audio")
                    return None
        else:
            audio_path = source
        
        # Comprimir para optimizar tokens (balance calidad-tamaño)
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        
        with st.status("🔧 Optimizando audio..."):
            compressed = os.path.join(temp_dir, f"{Path(audio_path).stem}_opt.mp3")
            subprocess.run([
                'ffmpeg', '-i', audio_path,
                '-acodec', 'libmp3lame', '-b:a', '48k', '-ar', '16000', '-ac', '1',
                '-y', compressed
            ], capture_output=True, timeout=300)
            
            if os.path.exists(compressed):
                os.unlink(audio_path)
                audio_path = compressed
                file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        
        # Transcribir
        with st.status(f"🎙️ Transcribiendo ({file_size_mb:.1f}MB)..."):
            model = genai.GenerativeModel("gemini-2.5-flash")
            
            try:
                uploaded = genai.upload_file(audio_path)
                
                # Esperar a que esté listo
                for _ in range(40):
                    if genai.get_file(uploaded.name).state.name == "ACTIVE":
                        break
                    time.sleep(2)
                
                response = model.generate_content([
                    "Transcribe completamente este audio. Usa [HABLANTE X] para múltiples voces, [INAUDIBLE] si no se entiende. Solo transcripción.",
                    uploaded
                ])
                
                transcript = response.text.strip() if response.text else None
                genai.delete_file(uploaded.name)
                
                os.unlink(audio_path)
                
                if not transcript or len(transcript) < 50:
                    st.error(" Transcripción muy corta")
                    return None
                
                return transcript
                
            except Exception as e:
                st.error(f" Error Gemini: {str(e)[:80]}")
                return None
    
    except Exception as e:
        st.error(f" Error: {str(e)}")
        return None