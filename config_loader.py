import json
import re
from pathlib import Path
from typing import Dict, Optional
import google.generativeai as genai


class ConfigLoader:
    """Carga y gestiona configuración desde JSON"""
    
    def __init__(self, config_path: str = "config.json", language: str = "es"):
        # LÓGICA DE BÚSQUEDA INTELIGENTE
        # 1. Mira si la ruta tal cual existe
        path_obj = Path(config_path)
        
        # 2. Si no existe, intenta buscarlo en la misma carpeta que este script (src/)
        if not path_obj.exists():
            path_obj = Path(__file__).parent / "config.json"
        
        # 3. Si aún no existe, intenta en la carpeta superior (raíz)
        if not path_obj.exists():
            path_obj = Path(__file__).parent.parent / "config.json"

        self.config_path = path_obj
        self.language = language
        self.config = self._load_config()
        
        if self.language not in self.config['app_settings']['supported_languages']:
            self.language = self.config['app_settings']['default_language']
    
    def _load_config(self) -> Dict:
        # Ahora usamos self.config_path que ya fue validado arriba
        if not self.config_path.exists():
            # Esto imprimirá la ruta real que falló para que sepas dónde lo buscó
            raise FileNotFoundError(f"No se encontró el archivo en: {self.config_path.absolute()}")
            
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def set_language(self, language: str) -> bool:
        if language in self.config['app_settings']['supported_languages']:
            self.language = language
            return True
        return False
    
    def get_all_translations(self) -> dict:
        try:
            return self.config['translations'][self.language]
        except:
            return {}
    
    def get_prompt_template(self, prompt_key: str) -> Dict:
        try:
            templates = self.config['prompts'].get(self.language, {})
            if prompt_key not in templates:
                return templates.get('general_content', {})
            return templates.get(prompt_key, {})
        except:
            return {}


class DeepAnalyzer:
    """
    Análisis PROFUNDO del contenido
    Detecta Categoría Y Sub-categoría para seleccionar el prompt exacto.
    """
    
    def __init__(self, api_key: str, language: str = "es"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        self.language = language
    
    def analyze_deep(self, transcript: str) -> Dict:
        """
        ANÁLISIS DEEP V2:
        Ahora detecta el sub-tema específico (Math, Code, AI, etc.)
        """
        
        words = transcript.split()[:1500]
        sample = " ".join(words)
        
        # Prompt mejorado para detectar sub-temas específicos
        if self.language == "es":
            analysis_prompt = """Analiza este contenido y clasifícalo con precisión técnica:

1. CATEGORÍA PRINCIPAL: (ACADEMIC, ENTERTAINMENT, GENERAL)
2. SUB-TEMA ESPECÍFICO: 
   - Si es ACADEMIC, elige el que mejor encaje: [Programming, Math, Statistics, Theory, Systems, AI, Networking, Database, Other]
   - Si es otro, usa una palabra descriptiva.

3. CONTEXTO: ¿Qué es esto? (Clase, Tutorial, Gameplay, Noticia)

Responde en JSON estrictamente:
{{
    "category": "ACADEMIC|ENTERTAINMENT|GENERAL",
    "sub_topic": "Programming|Math|Statistics|Theory|Systems|AI|Networking|Database|Other",
    "confidence": 0.0-1.0,
    "purpose": "Propósito en una frase",
    "has_formal_teaching": true/false,
    "reasoning": "Por qué elegiste esta categoría y sub-tema"
}}

CONTENIDO:
{content}"""
        else:
            analysis_prompt = """Analyze this content and categorize with technical precision:

1. MAIN CATEGORY: (ACADEMIC, ENTERTAINMENT, GENERAL)
2. SPECIFIC SUB-TOPIC: 
   - If ACADEMIC, choose best fit: [Programming, Math, Statistics, Theory, Systems, AI, Networking, Database, Other]
   - If other, use a descriptive word.

Respond in JSON strictly:
{{
    "category": "ACADEMIC|ENTERTAINMENT|GENERAL",
    "sub_topic": "Programming|Math|Statistics|Theory|Systems|AI|Networking|Database|Other",
    "confidence": 0.0-1.0,
    "purpose": "Purpose in one sentence",
    "has_formal_teaching": true/false,
    "reasoning": "Reasoning for category and sub-topic"
}}

CONTENT:
{content}"""
        
        analysis_prompt = analysis_prompt.format(content=sample)
        
        try:
            response = self.model.generate_content(
                analysis_prompt,
                generation_config={"temperature": 0.1} # Bajamos temperatura para ser más precisos
            )
            
            response_text = response.text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            result = json.loads(response_text)
            return result
        
        except Exception as e:
            print(f" Error en análisis profundo: {e}")
            return {
                "category": "GENERAL", 
                "sub_topic": "Other",
                "confidence": 0.0,
                "has_formal_teaching": False
            }


class ContextDetector:
    
    def __init__(self, config_loader: ConfigLoader, api_key: str):
        self.config_loader = config_loader
        self.language = config_loader.language
        if not api_key:
            raise ValueError("API key de Gemini es REQUERIDA")
        self.analyzer = DeepAnalyzer(api_key, config_loader.language)
    
    def _map_topic_to_key(self, category: str, sub_topic: str) -> str:
        """
        EL CEREBRO DEL SISTEMA:
        Mapea lo que Gemini detectó a las llaves de tu config.json
        """
        category = category.lower()
        sub_topic = sub_topic.lower()

        # 1. Si no es académico, usa general
        if category != 'academic':
            return 'general_content'

        # 2. Mapa de palabras clave a llaves de config.json
        # Estas claves deben coincidir con lo que detecta DeepAnalyzer
        mapping = {
            'programming': 'academic_stem_programming',
            'code': 'academic_stem_programming',
            'development': 'academic_stem_programming',
            
            'math': 'academic_stem_math',
            'algebra': 'academic_stem_math',
            'calculus': 'academic_stem_math',
            
            'statistics': 'academic_stem_statistics',
            'data analysis': 'academic_stem_statistics',
            
            'theory': 'academic_stem_theory',
            'computer science': 'academic_stem_theory',
            
            'systems': 'academic_stem_systems',
            'os': 'academic_stem_systems',
            'hardware': 'academic_stem_systems',
            
            'ai': 'academic_stem_ai',
            'machine learning': 'academic_stem_ai',
            
            'networking': 'academic_stem_networking',
            'network': 'academic_stem_networking',
            
            'database': 'academic_stem_database',
            'sql': 'academic_stem_database'
        }

        # Buscamos coincidencias
        for key, config_key in mapping.items():
            if key in sub_topic:
                return config_key

        # 3. Fallback inteligente
        return 'general_content'

    def detect(self, transcript: str) -> dict:
        if not transcript or len(transcript.strip()) < 50:
            return self._unknown_result()
        
        # 1. Análisis Profundo
        analysis = self.analyzer.analyze_deep(transcript)
        
        # 2. Extracción de datos
        category = analysis.get('category', 'GENERAL').lower()
        sub_topic = analysis.get('sub_topic', 'Other')
        confidence = analysis.get('confidence', 0.5)
        has_formal_teaching = analysis.get('has_formal_teaching', False)
        
        # 3. Refinamiento de Categoría
        if confidence < 0.6:
            category = 'general'
        elif has_formal_teaching and category == 'academic':
            category = 'academic'
        
        # 4. Seleccion de prompt
        prompt_key = self._map_topic_to_key(category, sub_topic)
        
        # 5. Generación de etiquetas para la UI
        labels = {
            "es": {"academic": "📚 Académico", "entertainment": "🎬 Entretenimiento", "general": "📄 General"},
            "en": {"academic": "📚 Academic", "entertainment": "🎬 Entertainment", "general": "📄 General"}
        }
        lang_labels = labels.get(self.language, labels["es"])
        content_label = f"{lang_labels.get(category, '📄 General')} ({sub_topic})"

        return {
            "context": category,
            "confidence": confidence,
            "content_type": category,
            "prompt_key": prompt_key,
            "subject": sub_topic,
            "category": category,
            "detection_method": "deep_analysis_gemini_v8",
            "content_label": content_label,
            "keyword_score": confidence * 100,
            "reasoning": analysis.get('reasoning', ''),
            "creator": analysis.get('creator', ''),
            "purpose": analysis.get('purpose', ''),
            "has_formal_teaching": has_formal_teaching
        }

    def _unknown_result(self) -> dict:
        return {
            "context": "general",
            "confidence": 0.0,
            "content_type": "general",
            "prompt_key": "general_content",
            "subject": "general",
            "category": "general",
            "detection_method": "unknown",
            "content_label": "📄 Contenido General",
            "keyword_score": 0,
            "reasoning": "Contenido muy corto",
            "creator": "unknown",
            "purpose": "unknown",
            "has_formal_teaching": False
        }


class PromptBuilder:
    """Constructor de prompts - Sin cambios"""
    
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
    
    def build_prompt(self, transcript: str, prompt_key: str, 
                     subject: str = "General", category: str = "general") -> str:
        """Construye prompt final"""
        
        prompt_template = self.config_loader.get_prompt_template(prompt_key)
        
        if not prompt_template:
            prompt_template = self.config_loader.get_prompt_template('general_content')
        
        system_role = prompt_template.get('system_role', '')
        intro = prompt_template.get('intro', '')
        instructions = prompt_template.get('instructions', [])
        
        instructions_text = "\n".join(f"• {inst}" for inst in instructions)
        
        prompt = f"""{system_role}

{intro}

INSTRUCCIONES:
{instructions_text}

CONTENIDO A PROCESAR:
{transcript}

Por favor, genera las notas siguiendo las instrucciones indicadas."""
        
        return prompt



# FUNCIONES DE INICIALIZACIÓN

def init_config(language: str = "es") -> ConfigLoader:
    """Inicializa el loader de configuración"""
    return ConfigLoader("config.json", language)


def get_context_detector(config_loader: ConfigLoader, api_key: str = None) -> ContextDetector:
    """
    Obtiene el detector de contexto v7
    API key se obtiene automáticamente de variables de entorno
    """
    if not api_key:
        # Intenta obtener de variables de entorno
        import os
        api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        # Intenta obtener de st.secrets
        try:
            import streamlit as st
            api_key = st.secrets.get("GOOGLE_API_KEY")
        except:
            pass
    
    if not api_key:
        raise ValueError(
            "API key de Gemini no encontrada.\n"
            "Configura GOOGLE_API_KEY en:\n"
            "1. .env file (GOOGLE_API_KEY=...)\n"
            "2. O en Streamlit secrets (.streamlit/secrets.toml)"
        )
    
    return ContextDetector(config_loader, api_key)


def get_prompt_builder(config_loader: ConfigLoader) -> PromptBuilder:
    """Obtiene el constructor de prompts"""
    return PromptBuilder(config_loader)