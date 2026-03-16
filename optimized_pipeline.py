"""
optimized_pipeline.py
=====================
Pipeline optimizado: audio → notas exhaustivas en UNA sola llamada a Gemini.
Recibe el config dict desde app.py — no carga config.json por su cuenta.
"""

import logging
import time
from typing import Callable, Dict, Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

PRIMARY_MODEL     = "gemini-2.5-flash"
FALLBACK_MODEL    = "gemini-2.0-flash"
MAX_POLL_ATTEMPTS = 40  # 40 × 2 s = ~80 s máximo


class OptimizedPipelineProcessor:
    """
    Procesa un archivo de audio directamente a notas académicas.

    Uso desde app.py:
        processor = OptimizedPipelineProcessor(config=config, language="es")
        result    = processor.process_audio(audio_path, log_fn=st.write)
        notes     = result['analysis']
        context   = result['context']
    """

    def __init__(self, config: Dict, language: str = "es"):
        self.language      = language
        self.config        = config
        self._cached_model = None
        self._cache_name: Optional[str] = None

    # ── System Instruction ───────────────────────────────────────────────────

    def _build_system_instruction(self) -> str:
        prompts = self.config["prompts"].get(self.language, {})
        categories_text = []

        for category_key, template in prompts.items():
            category_name = category_key.replace("academic_stem_", "").replace("_", " ").title()
            inst_list     = "\n".join(f"  • {i}" for i in template.get("instructions", []))
            categories_text.append(f"""
══════════════════════════════════════════
CATEGORÍA: {category_key}  |  {category_name}
ROL: {template.get('system_role', '')}
OBJETIVO: {template.get('intro', '')}
INSTRUCCIONES:
{inst_list}
══════════════════════════════════════════""")

        exhaustiveness_es = """
══════════════════════════════════════════
REGLAS DE EXHAUSTIVIDAD (OBLIGATORIAS)
══════════════════════════════════════════
• NUNCA uses frases vagas como "entre otros", "y más", "etc.", "se menciona brevemente".
• Cada concepto mencionado en el audio debe aparecer en las notas.
• Audio  5 min → mínimo  300 palabras.
• Audio 10 min → mínimo  600 palabras.
• Audio 20+ min → mínimo 1200 palabras.
• Usa SIEMPRE estructura jerárquica: títulos, subtítulos, listas, ejemplos.
• Si el profesor da un ejemplo, escríbelo completo.
• Si se menciona una fórmula, código o definición, transcríbela textualmente.
• Está PROHIBIDO resumir en exceso. Prioriza profundidad sobre brevedad.
══════════════════════════════════════════"""

        exhaustiveness_en = """
══════════════════════════════════════════
EXHAUSTIVENESS RULES (MANDATORY)
══════════════════════════════════════════
• NEVER use vague phrases like "among others", "and more", "etc.", "briefly mentioned".
• Every concept in the audio must appear in the notes.
• Audio  5 min → minimum  300 words.
• Audio 10 min → minimum  600 words.
• Audio 20+ min → minimum 1200 words.
• ALWAYS use hierarchical structure: titles, subtitles, lists, examples.
• If the speaker gives an example, write it fully.
• If a formula, code, or definition is mentioned, transcribe it verbatim.
• Over-summarizing is FORBIDDEN. Prioritize depth over brevity.
══════════════════════════════════════════"""

        joined = "\n".join(categories_text)

        if self.language == "es":
            return f"""Eres un asistente académico experto que genera notas EXHAUSTIVAS a partir de audio/video.

PROCESO:
1. Escucha el audio completo
2. Identifica la categoría más apropiada
3. Genera notas siguiendo sus instrucciones
4. Primera línea obligatoria: [CATEGORÍA: nombre_categoria]

{exhaustiveness_es}

CATÁLOGO:
{joined}

Si no encaja en ninguna categoría específica usa 'general_content'.

FORMATO:
[CATEGORÍA: nombre_categoria]
[notas exhaustivas]"""

        return f"""You are an expert academic assistant generating EXHAUSTIVE notes from audio/video.

PROCESS:
1. Listen to the complete audio
2. Identify the most appropriate category
3. Generate notes following its instructions
4. First line required: [CATEGORY: category_name]

{exhaustiveness_en}

CATALOG:
{joined}

If nothing fits, use 'general_content'.

FORMAT:
[CATEGORY: category_name]
[exhaustive notes]"""

    # ── Model ────────────────────────────────────────────────────────────────

    def _get_model(self, log_fn: Optional[Callable] = None):
        if self._cached_model is not None:
            return self._cached_model

        def log(msg: str) -> None:
            if log_fn:
                log_fn(msg)

        system_instruction = self._build_system_instruction()

        try:
            if len(system_instruction) > 32_000:
                cache = genai.caching.CachedContent.create(
                    model=PRIMARY_MODEL,
                    display_name=f"contentnotes_{self.language}",
                    system_instruction=system_instruction,
                    ttl="3600s",
                )
                self._cache_name   = cache.name
                self._cached_model = genai.GenerativeModel.from_cached_content(cache)
                log("✅ Context cache creado")
            else:
                self._cached_model = genai.GenerativeModel(
                    model_name=PRIMARY_MODEL,
                    system_instruction=system_instruction,
                )
        except Exception as e:
            logger.warning("Cache falló, usando modelo de respaldo: %s", e)
            log(f"⚠️ Usando {FALLBACK_MODEL}")
            self._cached_model = genai.GenerativeModel(
                model_name=FALLBACK_MODEL,
                system_instruction=system_instruction,
            )

        return self._cached_model

    # ── Parsing ──────────────────────────────────────────────────────────────

    def _parse_response(self, raw_text: str) -> Dict:
        lines    = raw_text.split("\n")
        category = "general_content"
        start    = 0

        if lines and (lines[0].startswith("[CATEGORÍA:") or lines[0].startswith("[CATEGORY:")):
            try:
                category = lines[0].split(":", 1)[1].strip().rstrip("]")
                start    = 1
            except (IndexError, ValueError) as e:
                logger.warning("No se pudo parsear categoría: %s", e)

        labels = {
            "academic_stem_programming": "💻 Programación",
            "academic_stem_math":        "📐 Matemáticas",
            "academic_stem_statistics":  "📊 Estadística",
            "academic_stem_theory":      "🧠 Teoría",
            "academic_stem_systems":     "⚙️ Sistemas",
            "academic_stem_ai":          "🤖 IA",
            "academic_stem_networking":  "🌐 Redes",
            "academic_stem_database":    "🗄️ BD",
            "general_content":           "📄 General",
        }

        confidence = 0.9 if category != "general_content" else 0.6

        return {
            "analysis": "\n".join(lines[start:]).strip(),
            "context": {
                "context":          category.replace("academic_stem_", ""),
                "confidence":       confidence,
                "content_type":     "academic" if "academic" in category else "general",
                "prompt_key":       category,
                "subject":          category.replace("academic_stem_", "").replace("_", " ").title(),
                "category":         category,
                "detection_method": "optimized_pipeline_v3",
                "content_label":    labels.get(category, "📄 General"),
                "keyword_score":    confidence * 100,
            },
        }

    # ── Entrada principal ────────────────────────────────────────────────────

    def process_audio(self, audio_path: str, log_fn: Optional[Callable] = None) -> Dict:
        """
        Procesa audio → notas en una sola llamada a Gemini.

        Args:
            audio_path: Ruta al MP3 ya comprimido.
            log_fn:     Callable para progreso (p.ej. st.write).

        Raises:
            RuntimeError: Si Gemini falla al procesar el archivo.
            TimeoutError: Si el archivo no se activa en tiempo límite.
        """
        def log(msg: str) -> None:
            if log_fn:
                log_fn(msg)

        log("📤 Subiendo audio a Gemini...")
        uploaded = genai.upload_file(audio_path, mime_type="audio/mp3")

        log("⏳ Esperando procesamiento...")
        for _ in range(MAX_POLL_ATTEMPTS):
            info = genai.get_file(uploaded.name)
            if info.state.name == "ACTIVE":
                log("✅ Listo")
                break
            if info.state.name == "FAILED":
                raise RuntimeError("Gemini falló al procesar el audio.")
            time.sleep(2)
        else:
            raise TimeoutError(
                f"Gemini no activó el archivo tras {MAX_POLL_ATTEMPTS * 2} s."
            )

        log("🧠 Generando notas...")
        model    = self._get_model(log_fn=log_fn)
        response = model.generate_content(
            [uploaded],
            generation_config={
                "temperature":       0.1,
                "top_p":             0.95,
                "top_k":             40,
                "max_output_tokens": 16_384,
            },
        )

        try:
            genai.delete_file(uploaded.name)
        except Exception as e:
            logger.warning("No se pudo eliminar archivo de Gemini: %s", e)

        return self._parse_response(response.text.strip())
