import os
import json
import time
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

from optimized_pipeline import OptimizedPipelineProcessor
from pdf_generator import PDFGenerator

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN STREAMLIT
# ============================================================================

st.set_page_config(
    page_title="ContentNotes",
    page_icon="📓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================================
# ENTORNO
# ============================================================================

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# ============================================================================
# CONFIG
# ============================================================================

def load_config() -> dict:
    """Busca config.json junto al script o en la raíz del proyecto."""
    for candidate in [
        Path("config.json"),
        Path(__file__).parent / "config.json",
        Path(__file__).parent.parent / "config.json",
    ]:
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("config.json no encontrado")


def get_translations(config: dict, language: str) -> dict:
    try:
        return config["translations"][language]
    except KeyError:
        logger.warning("Traducciones no encontradas para: %s", language)
        return {}

# ============================================================================
# SESSION STATE
# ============================================================================

if "config" not in st.session_state:
    st.session_state.config = load_config()

if "current_language" not in st.session_state:
    st.session_state.current_language = "es"

for key in ("analysis", "source_name"):
    if key not in st.session_state:
        st.session_state[key] = ""

if "context" not in st.session_state:
    st.session_state.context = {}

# ============================================================================
# PROCESSOR
# ============================================================================

def _get_processor() -> OptimizedPipelineProcessor:
    lang = st.session_state.current_language
    if (
        "processor" not in st.session_state
        or st.session_state.processor.language != lang
    ):
        st.session_state.processor = OptimizedPipelineProcessor(
            config=st.session_state.config,
            language=lang,
        )
    return st.session_state.processor

# ============================================================================
# IDIOMA
# ============================================================================

def toggle_language() -> None:
    st.session_state.current_language = (
        "en" if st.session_state.current_language == "es" else "es"
    )
    if "processor" in st.session_state:
        del st.session_state.processor


config = st.session_state.config
i18n   = get_translations(config, st.session_state.current_language)

# ============================================================================
# WORKER LOCAL
# ============================================================================

MAX_POLL_ATTEMPTS    = 60
MAX_DOWNLOAD_RETRIES = 3


@st.cache_data(ttl=30)
def check_worker_available() -> bool:
    try:
        worker_url = st.secrets.get("LOCAL_WORKER_URL")
        if not worker_url:
            return False
        r = requests.get(f"{worker_url.strip().rstrip('/')}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def download_youtube_audio(url: str, log_fn=None) -> Optional[str]:
    """Descarga audio de YouTube a través del worker local."""
    TEMP_DIR = "/tmp/contentnotes"
    os.makedirs(TEMP_DIR, exist_ok=True)

    def log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    worker_url = st.secrets.get("LOCAL_WORKER_URL")
    if not worker_url:
        st.error("❌ LOCAL_WORKER_URL no configurado en Secrets.")
        return None
    worker_url = worker_url.strip().rstrip("/")

    # Paso 1: Solicitar descarga
    log("🎬 Enviando orden al PC...")
    try:
        res = requests.post(f"{worker_url}/download-youtube", json={"url": url}, timeout=15)
        res.raise_for_status()
        file_id = res.json().get("audio_file")
        if not file_id:
            st.error("❌ El worker no devolvió un file_id.")
            return None
    except requests.RequestException as e:
        st.error(f"❌ Error al contactar el worker: {e}")
        return None

    # Paso 2: Polling con timeout
    log("⏳ El PC está procesando...")
    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            check  = requests.get(f"{worker_url}/check/{file_id}", timeout=10)
            status = check.json().get("status", "")
            if status == "READY":
                log("✅ Audio listo")
                break
            if "ERROR" in status:
                st.error(f"❌ Error en el worker: {status}")
                return None
            log(f"🔄 {status}... ({attempt + 1}/{MAX_POLL_ATTEMPTS})")
        except requests.RequestException:
            log("⚠️ Micro-corte, reintentando...")
        time.sleep(5)
    else:
        st.error(f"❌ Timeout tras {MAX_POLL_ATTEMPTS * 5 // 60} minutos.")
        return None

    # Paso 3: Descargar archivo
    safe_name  = Path(file_id).name  # evita path traversal
    local_path = os.path.join(TEMP_DIR, safe_name)
    log(f"📥 Transfiriendo {safe_name}...")

    for attempt in range(MAX_DOWNLOAD_RETRIES):
        try:
            with requests.get(f"{worker_url}/download/{file_id}", stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16_384):
                        if chunk:
                            f.write(chunk)
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                return local_path
        except requests.RequestException as e:
            if attempt < MAX_DOWNLOAD_RETRIES - 1:
                log(f"⚠️ Reintento {attempt + 1}/{MAX_DOWNLOAD_RETRIES}...")
                time.sleep(3)
            else:
                st.error(f"❌ Descarga fallida: {e}")
                return None
    return None

# ============================================================================
# AUDIO — compresión local con ffmpeg
# ============================================================================

def compress_audio_local(file_path: str) -> Optional[str]:
    """Elimina video y convierte a MP3 32k/16kHz/mono para reducir tokens."""
    try:
        output_path = Path(file_path).parent / f"{Path(file_path).stem}_opt.mp3"
        result = subprocess.run(
            ["ffmpeg", "-i", file_path, "-vn", "-c:a", "libmp3lame",
             "-b:a", "32k", "-ar", "16000", "-ac", "1", "-y", str(output_path)],
            capture_output=True, timeout=600, text=True,
        )
        if result.returncode == 0 and output_path.exists():
            orig_mb = os.path.getsize(file_path) / 1_048_576
            comp_mb = output_path.stat().st_size / 1_048_576
            st.success(f"✅ {orig_mb:.1f} MB → {comp_mb:.1f} MB ({(1 - comp_mb/orig_mb)*100:.0f}% reducción)")
            return str(output_path)
        st.error(f"❌ ffmpeg: {result.stderr[:300]}")
        return None
    except subprocess.TimeoutExpired:
        st.error("❌ Timeout en ffmpeg.")
        return None
    except Exception as e:
        st.error(f"❌ Error comprimiendo: {e}")
        return None

# ============================================================================
# PDF
# ============================================================================

def generate_document(analysis_text: str, title: str = "Notas",
                       source: str = "", context: str = "", confidence: float = 0):
    try:
        pdf_gen = PDFGenerator(title=title)
        pdf_gen.add_title(title)
        pdf_gen.add_metadata(source=source, context=context, confidence=confidence)
        pdf_gen.add_content_from_markdown(analysis_text)
        return pdf_gen.generate_pdf()
    except Exception as e:
        st.error(f"❌ Error generando documento: {e}")
        return None

# ============================================================================
# CSS + SCRIPTS
# ============================================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Merriweather:wght@300;400;700&family=Lora:wght@400;500;600&display=swap');

:root {
    --eink-bg: #f5f5f3;
    --eink-fg: #1a1a1a;
    --eink-border: #c8c8c0;
    --eink-text-light: #505050;
    --eink-shadow: rgba(0, 0, 0, 0.04);
}

* { margin: 0; padding: 0; box-sizing: border-box; -webkit-font-smoothing: antialiased; }

html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--eink-bg) !important;
    font-family: 'Merriweather', serif !important;
    color: var(--eink-fg) !important;
}
[data-testid="stMainBlockContainer"] {
    background-color: var(--eink-bg) !important;
    max-width: 1000px !important;
    padding: 1.5rem 1.5rem !important;
}
footer, #MainMenu, header { display: none !important; }

.stButton button[kind="primary"] { background: var(--eink-fg) !important; color: #f5f5f3 !important; border: 2px solid var(--eink-fg) !important; font-family: 'Merriweather', serif !important; border-radius: 0 !important; font-weight: 500 !important; min-height: 48px !important; }
.stButton button[kind="secondary"] { border: 1px solid var(--eink-border) !important; background: transparent !important; color: var(--eink-fg) !important; font-size: 0.8rem !important; height: 35px !important; }
.stButton button:hover { box-shadow: 3px 3px 0px var(--eink-shadow) !important; }

#eink-flash-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 99999; pointer-events: none; opacity: 0; background: #f5f5f3; }

body::before { content: ''; position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 9998; opacity: 0.04;
    background-image: repeating-linear-gradient(0deg, #000 0px, #000 1px, transparent 1px, transparent 3px), repeating-linear-gradient(90deg, #000 0px, #000 1px, transparent 1px, transparent 3px);
    background-size: 100% 3px, 3px 100%; }
body::after { content: ''; position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 9997;
    background: radial-gradient(ellipse at center, transparent 0%, transparent 60%, rgba(0,0,0,0.02) 85%, rgba(0,0,0,0.08) 100%); }

.eink-title { text-align: center; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 2px solid var(--eink-border); }
.eink-title h1 { font-family: 'Lora', serif; font-size: 2.4rem; color: var(--eink-fg); margin: 0; font-weight: 400; letter-spacing: 1px; }
.eink-title p { color: var(--eink-text-light); font-size: 0.95rem; font-weight: 300; letter-spacing: 0.5px; margin: 0.5rem 0 0 0; }

.eink-card-compact { background: white !important; border: 2px solid var(--eink-border) !important; padding: 0.3rem 1rem !important; margin-bottom: 0.2rem !important; box-shadow: 6px 6px 0px var(--eink-shadow) !important; }
.eink-card-compact .eink-card-title { color: var(--eink-fg) !important; font-size: 0.9rem !important; font-weight: 600 !important; margin-bottom: 0.2rem !important; font-family: 'Lora', serif !important; }

.eink-divider { height: 2px; background: var(--eink-border); margin: 2rem 0 !important; }

.eink-result { background: white !important; border: 2px solid var(--eink-border) !important; padding: 2rem !important; margin: 2rem 0 !important; box-shadow: 6px 6px 0px var(--eink-shadow) !important; }
.eink-result h1, .eink-result h2, .eink-result h3 { color: var(--eink-fg) !important; font-family: 'Lora', serif !important; font-weight: 400 !important; margin-top: 1.5rem !important; margin-bottom: 1rem !important; }
.eink-result p, .eink-result li { color: #2a2a2a !important; line-height: 1.8 !important; margin-bottom: 1rem !important; font-size: 0.95rem !important; }
.eink-result blockquote { border-left: 4px solid var(--eink-border) !important; padding-left: 1rem !important; margin: 1.5rem 0 !important; color: #505050 !important; font-style: italic !important; }

[data-baseweb="tab-list"] { border-bottom: 2px solid var(--eink-border) !important; }
[data-baseweb="tab"] { color: var(--eink-text-light) !important; font-family: 'Merriweather', serif !important; }
[aria-selected="true"] { color: var(--eink-fg) !important; border-bottom: 2px solid var(--eink-fg) !important; }

.stTextInput input { border: 2px solid var(--eink-border) !important; background: #fefefe !important; color: var(--eink-fg) !important; border-radius: 0 !important; font-family: 'Merriweather', serif !important; }
.stTextInput input:focus { border-color: var(--eink-fg) !important; box-shadow: inset 0 0 0 1px var(--eink-fg) !important; }
[data-testid="stFileUploadDropzone"] { background: #fafaf8 !important; border: 2px dashed var(--eink-border) !important; }

.eink-meta-item { padding: 1rem; background: #fafaf8; border: 1px solid var(--eink-border); }
.eink-meta-label { color: var(--eink-text-light); font-size: 0.85rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.6rem; }
.eink-meta-value { color: var(--eink-fg); font-size: 1.1rem; font-weight: 600; font-family: 'Lora', serif; }

.eink-footer { text-align: center; padding: 1.5rem 1.5rem 1rem; border-top: 1px solid var(--eink-border); color: var(--eink-text-light); font-size: 0.85rem; margin-top: 2rem; }

@media (max-width: 768px) {
    [data-testid="stMainBlockContainer"] { padding: 1.5rem 1rem !important; }
    .eink-title h1 { font-size: 2rem; }
}
</style>

<div id="eink-flash-overlay"></div>
<script>
function triggerEinkFlash() {
    const o = document.getElementById('eink-flash-overlay');
    if (!o) return;
    o.style.transition = 'none'; o.style.opacity = '1'; o.style.background = '#000';
    setTimeout(() => {
        o.style.transition = 'background 0.2s ease, opacity 0.4s ease';
        o.style.background = '#f5f5f3'; o.style.opacity = '0';
    }, 100);
}
window.triggerEinkFlash = triggerEinkFlash;
</script>
""", unsafe_allow_html=True)

# ============================================================================
# UI — BARRA SUPERIOR
# ============================================================================

col_l, _ = st.columns([0.1, 0.9])
with col_l:
    if st.button("EN" if st.session_state.current_language == "es" else "ES", key="lang_toggle"):
        toggle_language()
        st.rerun()

st.markdown(f"""
<div class="eink-title">
    <h1>{i18n['app_title']}</h1>
    <p>{i18n['app_subtitle']}</p>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# TABS
# ============================================================================

worker_available = check_worker_available()
tabs_map: dict   = {}

if worker_available:
    tabs = st.tabs([i18n["tab_youtube"], i18n["tab_file"]])
    tabs_map["youtube"] = tabs[0]
    tabs_map["file"]    = tabs[1]
else:
    tabs = st.tabs([i18n["tab_file"]])
    tabs_map["file"] = tabs[0]

# ============================================================================
# TAB YOUTUBE
# ============================================================================

if "youtube" in tabs_map:
    with tabs_map["youtube"]:
        st.markdown(
            f'<div class="eink-card-compact"><div class="eink-card-title">{i18n["youtube_title"]}</div>',
            unsafe_allow_html=True,
        )
        yt_url = st.text_input(
            i18n["youtube_title"], placeholder=i18n["youtube_placeholder"],
            label_visibility="collapsed", key="yt_input",
        )
        _, col_btn, _ = st.columns([1, 1, 1])
        with col_btn:
            process_yt = st.button(i18n["btn_process"], key="btn_yt", use_container_width=True, type="primary")

        if process_yt:
            if not yt_url or not yt_url.startswith("http"):
                st.error(i18n["error_invalid_url"])
            else:
                st.session_state.analysis = ""
                with st.status("📡 Conectando con el PC local...", expanded=True):
                    audio_path = download_youtube_audio(yt_url, log_fn=st.write)

                if not audio_path:
                    st.stop()

                try:
                    with st.status("🚀 Generando notas...", expanded=True):
                        result = _get_processor().process_audio(audio_path, log_fn=st.write)
                except (RuntimeError, TimeoutError) as e:
                    st.error(f"❌ {e}")
                    st.stop()
                finally:
                    try:
                        if audio_path and os.path.exists(audio_path):
                            os.unlink(audio_path)
                    except OSError:
                        pass

                st.session_state.analysis    = result["analysis"]
                st.session_state.context     = result["context"]
                st.session_state.source_name = "YouTube"
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# TAB ARCHIVO
# ============================================================================

with tabs_map["file"]:
    st.markdown(
        f'<div class="eink-card-compact"><div class="eink-card-title">{i18n["file_title"]}</div>',
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        i18n["file_types"],
        type=["mp4", "avi", "mov", "mp3", "wav", "flac", "aac", "m4a", "mkv", "webm", "ogg"],
        label_visibility="collapsed", key="file_input",
    )

    if uploaded:
        st.markdown(f"**📄 {uploaded.name}** ({round(uploaded.size / 1_048_576, 2)} MB)")
        _, col_btn, _ = st.columns([1, 1, 1])
        with col_btn:
            process_file = st.button(i18n["btn_process"], key="btn_file", use_container_width=True, type="primary")

        if process_file:
            suffix = f'.{uploaded.name.rsplit(".", 1)[-1]}'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded.getbuffer())
                tmp_path = tmp.name

            st.session_state.analysis = ""
            st.write("🔧 Optimizando audio...")
            compressed_path = compress_audio_local(tmp_path)

            if not compressed_path:
                os.unlink(tmp_path)
                st.stop()

            try:
                with st.status("🚀 Procesando...", expanded=True):
                    result = _get_processor().process_audio(compressed_path, log_fn=st.write)
            except (RuntimeError, TimeoutError) as e:
                st.error(f"❌ {e}")
                st.stop()
            finally:
                for p in (tmp_path, compressed_path):
                    try:
                        if p and os.path.exists(p):
                            os.unlink(p)
                    except OSError:
                        pass

            st.session_state.analysis    = result["analysis"]
            st.session_state.context     = result["context"]
            st.session_state.source_name = uploaded.name
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# RESULTADOS
# ============================================================================

if st.session_state.analysis:
    st.markdown('<div class="eink-divider"></div>', unsafe_allow_html=True)
    context = st.session_state.context
    st.subheader(i18n["notes_generated"])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""<div class='eink-meta-item'>
            <div class='eink-meta-label'>{i18n['meta_type']}</div>
            <div class='eink-meta-value'>{context.get('content_label', 'General')}</div>
            <div style='font-size:0.75rem;color:#808080;margin-top:0.5rem;'>
                Confianza: {context.get('confidence', 0):.1%}
            </div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div class='eink-meta-item'>
            <div class='eink-meta-label'>{i18n['meta_source']}</div>
            <div class='eink-meta-value'>{st.session_state.source_name}</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""<div class='eink-meta-item'>
            <div class='eink-meta-label'>{i18n['meta_subject']}</div>
            <div class='eink-meta-value'>{context.get('context', 'General').title()}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown(f'<div class="eink-result">{st.session_state.analysis}</div>', unsafe_allow_html=True)

    filename = st.text_input(
        i18n["filename_label"], value="notas",
        key="filename_input", label_visibility="collapsed",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        doc = generate_document(
            st.session_state.analysis, title=filename.title(),
            source=st.session_state.source_name,
            context=context.get("context", "General"),
            confidence=context.get("confidence", 0),
        )
        if doc:
            if not doc.is_pdf:
                st.warning("⚠️ WeasyPrint no instalado. Descargando como HTML.")
            st.download_button(
                label=i18n["btn_download_pdf"] if doc.is_pdf else "📄 HTML",
                data=doc.data, file_name=f"{filename}.{doc.ext}",
                mime=doc.mimetype, use_container_width=True,
            )
    with col2:
        st.download_button(
            i18n["btn_download_md"], st.session_state.analysis.encode(),
            f"{filename}.md", "text/markdown", use_container_width=True,
        )
    with col3:
        if st.button(i18n["btn_new"], key="btn_new", use_container_width=True):
            st.session_state.analysis = ""
            st.rerun()

# ============================================================================
# FOOTER
# ============================================================================

st.markdown(f'<div class="eink-footer"><p>{i18n["footer_copyright"]}</p></div>', unsafe_allow_html=True)
st.markdown("<script>window.triggerEinkFlash();</script>", unsafe_allow_html=True)
