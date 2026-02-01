import streamlit as st
import os
import re
import time
from io import BytesIO
from dotenv import load_dotenv
import google.generativeai as genai
from yt_helper import download_and_transcribe
from config_loader import init_config, get_context_detector, get_prompt_builder
import tempfile
import markdown
import markdown
from io import BytesIO
import re
import markdown
from xhtml2pdf import pisa
from io import BytesIO

# CONFIGURACIÓN STREAMLIT
st.set_page_config(
    page_title="ContentNotes",
    page_icon="📓",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CARGA DE ENTORNO Y ESTADO

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

if 'config_loader' not in st.session_state:
    st.session_state.config_loader = init_config(language="es")

if 'current_language' not in st.session_state:
    st.session_state.current_language = "es"

config_loader = st.session_state.config_loader

def toggle_language():
    if st.session_state.current_language == "es":
        st.session_state.current_language = "en"
    else:
        st.session_state.current_language = "es"
    st.session_state.config_loader.set_language(st.session_state.current_language)

config_loader.set_language(st.session_state.current_language)
i18n = config_loader.get_all_translations()
context_detector = get_context_detector(config_loader)
prompt_builder = get_prompt_builder(config_loader)


# LÓGICA DE PDF

def generate_pdf(text, title="Notas"):
    """
    Genera un PDF convirtiendo Markdown -> HTML -> PDF directamente.
    Soporta CSS para estilos avanzados.
    """
    try:
        # 1. Convertir Markdown a HTML
        # Agregamos extensiones útiles para tablas y bloques de código
        html_content = markdown.markdown(text, extensions=['tables', 'fenced_code', 'sane_lists'])
        
        # 2. Definir estilos CSS (Aquí controlas el diseño visual del PDF)
        css_style = """
        <style>
            @page {
                size: A4;
                margin: 2cm;
                @frame footer_frame {           /* Static Frame */
                    -pdf-frame-content: footerContent;
                    bottom: 1cm;
                    margin-left: 2cm;
                    margin-right: 2cm;
                    height: 1cm;
                }
            }
            body { font-family: Helvetica, sans-serif; font-size: 11pt; color: #2a2a2a; line-height: 1.5; }
            h1 { font-size: 24pt; color: #1a1a1a; text-align: center; border-bottom: 2px solid #ddd; padding-bottom: 10px; margin-bottom: 20px; }
            h2 { font-size: 16pt; color: #2a2a2a; margin-top: 20px; margin-bottom: 10px; }
            h3 { font-size: 13pt; color: #3a3a3a; font-weight: bold; }
            p { margin-bottom: 10px; text-align: justify; }
            ul, ol { margin-bottom: 10px; margin-left: 15px; }
            li { margin-bottom: 5px; }
            code { background-color: #f0f0f0; font-family: Courier; padding: 2px; }
            pre { background-color: #f0f0f0; border: 1px solid #ccc; padding: 10px; font-family: Courier; font-size: 9pt; white-space: pre-wrap; }
            blockquote { border-left: 4px solid #ccc; padding-left: 10px; color: #666; font-style: italic; margin: 15px 0; }
            table { border-collapse: collapse; width: 100%; margin-bottom: 15px; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; font-weight: bold; }
        </style>
        """

        # 3. Construir el HTML completo
        full_html = f"""
        <html>
        <head>{css_style}</head>
        <body>
            <h1>{title}</h1>
            {html_content}
            
            <div id="footerContent" style="text-align:center; color:#888; font-size:9pt;">
                Generado con ContentNotes.
            </div>
        </body>
        </html>
        """

        # 4. Generar el PDF en memoria
        buffer = BytesIO()
        # pisa.CreatePDF convierte el string HTML/CSS directamente a bytes PDF
        pisa_status = pisa.CreatePDF(full_html, dest=buffer)

        # Verificar errores
        if pisa_status.err:
            print(f"Error generando PDF: {pisa_status.err}")
            return None
            
        return buffer.getvalue()

    except Exception as e:
        print(f"Error crítico en PDF: {e}")
        return None

# CSS Y SCRIPTS

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

/* Estilo para que el botón de idioma sea minimalista */
.stButton button[kind="secondary"] {
    border: 1px solid var(--eink-border) !important;
    background: transparent !important;
    color: var(--eink-fg) !important;
    font-size: 0.8rem !important;
    min-height: 30px !important;
    height: 35px !important;
}

#eink-flash-overlay {
    position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 99999;
    pointer-events: none; opacity: 0; background: #f5f5f3;
}
body::before {
    content: ''; position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 9998; opacity: 0.04;
    background-image: repeating-linear-gradient(0deg, #000 0px, #000 1px, transparent 1px, transparent 3px), repeating-linear-gradient(90deg, #000 0px, #000 1px, transparent 1px, transparent 3px);
    background-size: 100% 3px, 3px 100%;
}
body::after {
    content: ''; position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 9997;
    background: radial-gradient(ellipse at center, transparent 0%, transparent 60%, rgba(0,0,0,0.02) 85%, rgba(0,0,0,0.08) 100%);
}
.eink-title { text-align: center; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 2px solid var(--eink-border); }
.eink-title h1 { font-family: 'Lora', serif; font-size: 2.4rem; color: var(--eink-fg); margin: 0; font-weight: 400; letter-spacing: 1px; }
.eink-title p { color: var(--eink-text-light); font-size: 0.95rem; font-weight: 300; letter-spacing: 0.5px; margin: 0.5rem 0 0 0; }
.eink-card { background: white !important; border: 2px solid var(--eink-border) !important; padding: 2rem !important; margin-bottom: 1.5rem !important; box-shadow: 6px 6px 0px var(--eink-shadow) !important; }
.eink-card-title { color: var(--eink-fg) !important; font-size: 1.1rem !important; font-weight: 600 !important; margin-bottom: 1.5rem !important; font-family: 'Lora', serif !important; letter-spacing: 0.6px !important; }
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
.stButton button[kind="primary"] { background: var(--eink-fg) !important; color: #f5f5f3 !important; border: 2px solid var(--eink-fg) !important; font-family: 'Merriweather', serif !important; border-radius: 0 !important; font-weight: 500 !important; min-height: 48px !important; }
.stButton button:hover { box-shadow: 3px 3px 0px var(--eink-shadow) !important; }
[data-testid="stFileUploadDropzone"] { background: #fafaf8 !important; border: 2px dashed var(--eink-border) !important; }
.eink-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
.eink-meta-item { padding: 1rem; background: #fafaf8; border: 1px solid var(--eink-border); }
.eink-meta-label { color: var(--eink-text-light); font-size: 0.85rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.6rem; }
.eink-meta-value { color: var(--eink-fg); font-size: 1.1rem; font-weight: 600; font-family: 'Lora', serif; }
.eink-card-compact { background: white !important; border: 2px solid var(--eink-border) !important; padding: 0.3rem 1rem !important; margin-bottom: 0.2rem !important; box-shadow: 6px 6px 0px var(--eink-shadow) !important; }
.eink-card-compact .eink-card-title { color: var(--eink-fg) !important; font-size: 0.9rem !important; font-weight: 600 !important; margin-bottom: 0.2rem !important; font-family: 'Lora', serif !important; letter-spacing: 0.6px !important; }
.eink-footer { text-align: center; padding: 1.5rem 1.5rem 1rem; border-top: 1px solid var(--eink-border); color: var(--eink-text-light); font-size: 0.85rem; margin-top: 2rem; }
@media (max-width: 768px) { [data-testid="stMainBlockContainer"] { padding: 1.5rem 1rem !important; } .eink-title h1 { font-size: 2rem; } }
</style>

<div id="eink-flash-overlay"></div>

<script>
function triggerEinkFlash() {
    const overlay = document.getElementById('eink-flash-overlay');
    if(!overlay) return;
    overlay.style.transition = 'none';
    overlay.style.opacity = '1';
    overlay.style.background = '#000000';
    setTimeout(() => {
        overlay.style.transition = 'background 0.2s ease, opacity 0.4s ease';
        overlay.style.background = '#f5f5f3';
        overlay.style.opacity = '0';
    }, 100);
}
window.triggerEinkFlash = triggerEinkFlash;
</script>
""", unsafe_allow_html=True)

for key in ['transcript', 'analysis', 'context', 'source_name']:
    if key not in st.session_state:
        st.session_state[key] = ""

# UI PRINCIPAL

# FILA SUPERIOR: Botón de Idioma a la izquierda
col_l, col_r = st.columns([0.1, 0.9])
with col_l:
    btn_label = "EN" if st.session_state.current_language == "es" else "ES"
    if st.button(btn_label, key="lang_toggle"):
        toggle_language()
        st.rerun()

# FILA TÍTULO: Centrado debajo del botón
st.markdown(f"""
<div class="eink-title">
    <h1>{i18n['app_title']}</h1>
    <p>{i18n['app_subtitle']}</p>
</div>
""", unsafe_allow_html=True)

# TABS
tab1, tab2 = st.tabs([i18n['tab_youtube'], i18n['tab_file']])

with tab1:
    st.markdown(f'<div class="eink-card-compact"><div class="eink-card-title">{i18n["youtube_title"]}</div>', unsafe_allow_html=True)
    yt_url = st.text_input(i18n["youtube_title"], placeholder=i18n["youtube_placeholder"], label_visibility="collapsed", key="yt_input")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button(i18n["btn_process"], key="btn_process_yt", use_container_width=True, type="primary"):
            if yt_url:
                st.session_state.transcript = ""
                st.session_state.analysis = ""
                with st.spinner(i18n["downloading"]):
                    transcript = download_and_transcribe(yt_url, is_youtube=True)
                    if transcript:
                        st.session_state.transcript = transcript
                        st.session_state.source_name = "YouTube"
                        
                        # Detectar contexto con nueva lógica
                        context = context_detector.detect(transcript)
                        full_prompt = prompt_builder.build_prompt(
                            transcript=transcript,
                            prompt_key=context.get('prompt_key', 'general'),
                            subject=context.get('context', 'General'),
                            category=context.get('context', 'general')
                        )
                        
                        # Generar análisis
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        response = model.generate_content(full_prompt)
                        
                        if response.text:
                            st.session_state.analysis = response.text
                            st.session_state.context = context
                        
                        st.rerun()
            else:
                st.error(i18n["error_invalid_url"])
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.markdown(f'<div class="eink-card-compact"><div class="eink-card-title">{i18n["file_title"]}</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader(i18n["file_types"], type=['mp4', 'avi', 'mov', 'mp3', 'wav', 'flac', 'aac', 'm4a'], label_visibility="collapsed", key="file_input")
    if uploaded:
        st.markdown(f"**📄 {uploaded.name}** ({round(uploaded.size/1024/1024, 2)}MB)")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button(i18n["btn_process"], key="btn_process_file", use_container_width=True, type="primary"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{uploaded.name.split(".")[-1]}') as tmp:
                    tmp.write(uploaded.getbuffer())
                    tmp_path = tmp.name
                st.session_state.transcript = ""
                st.session_state.analysis = ""
                
                with st.spinner(i18n["processing"]):
                    transcript = download_and_transcribe(tmp_path, is_youtube=False)
                    if transcript:
                        st.session_state.transcript = transcript
                        st.session_state.source_name = uploaded.name
                        
                        # Detectar contexto con nueva lógica
                        context = context_detector.detect(transcript)
                        full_prompt = prompt_builder.build_prompt(
                            transcript=transcript,
                            prompt_key=context.get('prompt_key', 'general'),
                            subject=context.get('context', 'General'),
                            category=context.get('context', 'general')
                        )
                        
                        # Generar análisis
                        model = genai.GenerativeModel("gemini-2.5-flash")
                        response = model.generate_content(full_prompt)
                        
                        if response.text:
                            st.session_state.analysis = response.text
                            st.session_state.context = context
                
                try: os.unlink(tmp_path)
                except: pass
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# SECCIÓN: MOSTRAR NOTAS GENERADAS

if st.session_state.analysis:
    st.markdown('<div class="eink-divider"></div>', unsafe_allow_html=True)
    context = st.session_state.context
    st.subheader(i18n["notes_generated"])
    
    # Mostrar metadatos con confianza visible
    col1, col2, col3 = st.columns(3)
    with col1: 
        st.markdown(f"""<div class='eink-meta-item'>
            <div class='eink-meta-label'>{i18n['meta_type']}</div>
            <div class='eink-meta-value'>{context.get('content_label', 'Contenido General')}</div>
            <div style='font-size: 0.75rem; color: #808080; margin-top: 0.5rem;'>Confianza: {context.get('confidence', 0):.1%}</div>
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
    
    # Mostrar las notas
    st.markdown(f'<div class="eink-result">{st.session_state.analysis}</div>', unsafe_allow_html=True)
    
    # Sección de descargas
    filename = st.text_input(i18n["filename_label"], value="notas", key="filename_input", label_visibility="collapsed")
    col1, col2, col3 = st.columns(3)
    with col1:
        pdf_bytes = generate_pdf(st.session_state.analysis)
        if pdf_bytes: 
            st.download_button(
                i18n["btn_download_pdf"], 
                pdf_bytes, 
                f"{filename}.pdf", 
                "application/pdf", 
                use_container_width=True
            )
    with col2: 
        st.download_button(
            i18n["btn_download_md"], 
            st.session_state.analysis.encode(), 
            f"{filename}.md", 
            "text/markdown", 
            use_container_width=True
        )
    with col3:
        if st.button(i18n["btn_new"], key="btn_new", use_container_width=True):
            st.session_state.analysis = ""
            st.session_state.transcript = ""
            st.rerun()

# FOOTER
st.markdown(f"""<div class="eink-footer"><p>{i18n['footer_copyright']}</p></div>""", unsafe_allow_html=True)

# EJECUTAR FLASH AL FINAL DE CADA CARGA
st.markdown('<script>window.triggerEinkFlash();</script>', unsafe_allow_html=True)