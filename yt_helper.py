import re
import os
import time
import subprocess
import requests  # <--- IMPORTANTE: Necesario para hablar con Cobalt
from pathlib import Path
import streamlit as st
import google.generativeai as genai

# --- CONFIGURACIÓN DE COBALT ---
# Puedes cambiar esta URL si la oficial está saturada.
# Lista de instancias: https://instances.cobalt.tools/
COBALT_API_URL = "https://api.cobalt.tools/api/json"

def extract_video_id(url: str) -> str | None:
    """Extrae ID de video de YouTube (útil para nombres de archivo)"""
    match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else "video_temp"

def download_with_cobalt(url: str, output_path: str):
    """
    Actualizado para la API v10 de Cobalt.
    """
    # La URL de la API v10 suele ser la misma, pero el cuerpo del JSON cambió
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Payload actualizado para v10
    payload = {
        "url": url,
        "videoQuality": "720",     # Requerido en algunas instancias
        "audioFormat": "mp3",      # Formato de audio
        "filenameStyle": "basic",
        "downloadMode": "audio"    # IMPORTANTE: Solo audio
    }
    
    try:
        # Intentamos con la instancia oficial o una alternativa si falla
        response = requests.post(COBALT_API_URL, json=payload, headers=headers, timeout=20)
        
        if response.status_code != 200:
            # Si la instancia oficial falla, podrías intentar con otra de la lista
            # ej: https://cobalt.api.unblockers.it/api/json
            st.error(f"Error en Cobalt API ({response.status_code}): {response.text}")
            return False
            
        data = response.json()
        
        # En v10, el estado suele ser 'tunnel', 'redirect' o 'success'
        status = data.get("status")
        download_url = data.get("url")

        if status == "error":
            st.error(f"Cobalt dice: {data.get('text')}")
            return False

        if not download_url:
            st.error("No se encontró el enlace de descarga en la respuesta.")
            return False

        # 2. Descargar el archivo
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024): # Chunks de 1MB
                    f.write(chunk)
        
        return True

    except Exception as e:
        st.error(f"Error de conexión: {str(e)}")
        return False
        
def download_and_transcribe(source: str, is_youtube: bool = False) -> str | None:
    """Descarga audio vía Cobalt y transcribe con Gemini"""
    
    temp_dir = "/tmp/contentnotes"
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        if is_youtube:
            video_id = extract_video_id(source)
            audio_path = os.path.join(temp_dir, f"yt_{video_id}.mp3")
            
            with st.status("🚀 Procesando con Cobalt API..."):
                # Llamamos a la función de Cobalt en lugar de usar yt-dlp
                success = download_with_cobalt(source, audio_path)
                
                if not success:
                    return None
                
                time.sleep(1) # Un respiro para asegurar escritura en disco
                
                if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                    st.error("❌ El archivo de audio parece estar vacío.")
                    return None
        else:
            audio_path = source
        
        # --- A PARTIR DE AQUÍ ES TU LÓGICA ORIGINAL DE FFMPEG Y GEMINI ---
        
        # Comprimir para optimizar tokens (balance calidad-tamaño)
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        
        with st.status("🔧 Optimizando audio con FFmpeg..."):
            compressed = os.path.join(temp_dir, f"{Path(audio_path).stem}_opt.mp3")
            
            # Usamos ffmpeg para asegurar que el formato sea digerible por Gemini
            subprocess.run([
                'ffmpeg', '-i', audio_path,
                '-acodec', 'libmp3lame', '-b:a', '48k', '-ar', '16000', '-ac', '1',
                '-y', compressed
            ], capture_output=True, timeout=300)
            
            if os.path.exists(compressed):
                # Borramos el original pesado
                if is_youtube and os.path.exists(audio_path):
                    os.unlink(audio_path)
                audio_path = compressed
                file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        
        # Transcribir con Gemini
        with st.status(f"🎙️ Transcribiendo ({file_size_mb:.1f}MB)..."):
            model = genai.GenerativeModel("gemini-2.0-flash") # Actualizado a 2.0 (más rápido) o usa 1.5
            
            try:
                uploaded = genai.upload_file(audio_path)
                
                # Esperar a que esté listo
                for _ in range(40):
                    if genai.get_file(uploaded.name).state.name == "ACTIVE":
                        break
                    time.sleep(2)
                
                response = model.generate_content([
                    "Transcribe completamente este audio. Usa [HABLANTE X] para múltiples voces. Solo el texto.",
                    uploaded
                ])
                
                transcript = response.text.strip() if response.text else None
                
                # Limpieza en la nube
                genai.delete_file(uploaded.name)
                
                # Limpieza local
                if os.path.exists(audio_path):
                    os.unlink(audio_path)
                
                if not transcript or len(transcript) < 50:
                    st.error("⚠️ La transcripción fue muy corta o falló.")
                    return None
                
                return transcript
                
            except Exception as e:
                st.error(f"⚠️ Error Gemini: {str(e)[:100]}")
                return None
    
    except Exception as e:
        st.error(f"❌ Error General: {str(e)}")
        return None

