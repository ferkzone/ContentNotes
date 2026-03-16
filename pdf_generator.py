"""
pdf_generator.py
================
Convierte Markdown (con LaTeX y bloques de código) a PDF usando WeasyPrint.

Si WeasyPrint no está disponible, devuelve HTML con extensión .html en lugar
de un .pdf silenciosamente roto — y avisa al caller con un flag explícito.
"""

import re
import logging
from datetime import datetime

import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

logger = logging.getLogger(__name__)

# WeasyPrint — funciona en Linux/Cloud (requiere GTK)
try:
    from weasyprint import HTML as WeasyHTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    logger.warning("WeasyPrint no disponible, se usará xhtml2pdf como fallback.")

# xhtml2pdf — puro Python, funciona en Windows sin dependencias del sistema
try:
    from io import BytesIO
    from xhtml2pdf import pisa
    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False
    logger.warning("xhtml2pdf no disponible.")


# ============================================================================
# LATEX → UNICODE / HTML
# ============================================================================

LATEX_SYMBOLS = {
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\varepsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η',
    r'\theta': 'θ', r'\vartheta': 'ϑ', r'\iota': 'ι', r'\kappa': 'κ',
    r'\lambda': 'λ', r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ',
    r'\pi': 'π', r'\varpi': 'ϖ', r'\rho': 'ρ', r'\varrho': 'ϱ',
    r'\sigma': 'σ', r'\varsigma': 'ς', r'\tau': 'τ', r'\upsilon': 'υ',
    r'\phi': 'φ', r'\varphi': 'φ', r'\chi': 'χ', r'\psi': 'ψ', r'\omega': 'ω',
    r'\Gamma': 'Γ', r'\Delta': 'Δ', r'\Theta': 'Θ', r'\Lambda': 'Λ',
    r'\Xi': 'Ξ', r'\Pi': 'Π', r'\Sigma': 'Σ', r'\Upsilon': 'Υ',
    r'\Phi': 'Φ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
    r'\infty': '∞', r'\partial': '∂', r'\nabla': '∇',
    r'\pm': '±', r'\mp': '∓', r'\times': '×', r'\div': '÷',
    r'\cdot': '·', r'\circ': '∘', r'\bullet': '•',
    r'\leq': '≤', r'\geq': '≥', r'\neq': '≠', r'\approx': '≈',
    r'\equiv': '≡', r'\sim': '∼', r'\propto': '∝',
    r'\in': '∈', r'\notin': '∉', r'\subset': '⊂', r'\supset': '⊃',
    r'\cup': '∪', r'\cap': '∩', r'\emptyset': '∅',
    r'\forall': '∀', r'\exists': '∃', r'\nexists': '∄',
    r'\neg': '¬', r'\wedge': '∧', r'\vee': '∨',
    r'\oplus': '⊕', r'\otimes': '⊗',
    r'\to': '→', r'\leftarrow': '←', r'\Rightarrow': '⇒',
    r'\Leftarrow': '⡐', r'\Leftrightarrow': '⇔', r'\leftrightarrow': '↔',
    r'\uparrow': '↑', r'\downarrow': '↓',
    r'\ldots': '…', r'\cdots': '⋯', r'\vdots': '⋮', r'\ddots': '⋱',
    r'\sum': '∑', r'\prod': '∏', r'\int': '∫', r'\oint': '∮',
    r'\sqrt': '√',
    r'\langle': '⟨', r'\rangle': '⟩',
    r'\|': '‖', r'\{': '{', r'\}': '}',
    r'\hbar': 'ℏ', r'\ell': 'ℓ',
    r'\mathbb{R}': 'ℝ', r'\mathbb{N}': 'ℕ', r'\mathbb{Z}': 'ℤ',
    r'\mathbb{Q}': 'ℚ', r'\mathbb{C}': 'ℂ',
    r'\text{sin}': 'sin', r'\sin': 'sin', r'\cos': 'cos',
    r'\tan': 'tan', r'\log': 'log', r'\ln': 'ln', r'\lim': 'lim',
    r'\max': 'max', r'\min': 'min', r'\sup': 'sup', r'\inf': 'inf',
    r'\det': 'det', r'\exp': 'exp',
}


def _latex_symbols(expr: str) -> str:
    expr = re.sub(r'\\mathbb\{([A-Z])\}',
                  lambda m: {'R': 'ℝ', 'N': 'ℕ', 'Z': 'ℤ', 'Q': 'ℚ', 'C': 'ℂ'}.get(m.group(1), m.group(1)), expr)
    expr = re.sub(r'\\text\{([^}]+)\}', r'\1', expr)
    expr = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', expr)
    expr = re.sub(r'\\mathbf\{([^}]+)\}', r'<b>\1</b>', expr)
    expr = re.sub(r'\\mathit\{([^}]+)\}', r'<i>\1</i>', expr)
    for cmd, sym in sorted(LATEX_SYMBOLS.items(), key=lambda x: -len(x[0])):
        expr = expr.replace(cmd, sym)
    return expr


def _process_scripts(expr: str) -> str:
    expr = re.sub(r'\^\{([^}]+)\}', lambda m: f'<sup>{m.group(1)}</sup>', expr)
    expr = re.sub(r'\^([A-Za-z0-9])', r'<sup>\1</sup>', expr)
    expr = re.sub(r'_\{([^}]+)\}', lambda m: f'<sub>{m.group(1)}</sub>', expr)
    expr = re.sub(r'_([A-Za-z0-9])', r'<sub>\1</sub>', expr)
    return expr


def _process_frac(expr: str) -> str:
    def frac_replace(m):
        return (f'<span class="math-frac">'
                f'<span class="math-num">{m.group(1)}</span>'
                f'<span class="math-den">{m.group(2)}</span></span>')
    return re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', frac_replace, expr)


def _render_latex(expr: str, block: bool = False) -> str:
    expr = _process_frac(expr)
    expr = _latex_symbols(expr)
    expr = _process_scripts(expr)
    if block:
        return f'<div class="math-block">{expr}</div>'
    return f'<span class="math-inline">{expr}</span>'


def process_latex_in_html(html: str) -> str:
    html = re.sub(
        r'\$\$(.+?)\$\$',
        lambda m: _render_latex(m.group(1).strip(), block=True),
        html, flags=re.DOTALL
    )
    html = re.sub(
        r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)',
        lambda m: _render_latex(m.group(1).strip(), block=False),
        html
    )
    return html


# ============================================================================
# SYNTAX HIGHLIGHTING
# ============================================================================

def highlight_code(code: str, lang: str = '') -> str:
    try:
        lexer = get_lexer_by_name(lang.strip(), stripall=True) if lang.strip() else guess_lexer(code)
    except ClassNotFound:
        lexer = TextLexer()
    formatter = HtmlFormatter(style='one-dark', noclasses=True, wrapcode=False)
    return highlight(code, lexer, formatter)


def apply_syntax_highlighting(html: str) -> str:
    def replace_block(m):
        lang = (m.group(1) or '').strip()
        code_raw = (m.group(2)
                    .replace('&amp;', '&').replace('&lt;', '<')
                    .replace('&gt;', '>').replace('&quot;', '"')
                    .replace('&#39;', "'"))
        lang_label = f'<div class="code-lang">{lang.upper()}</div>' if lang else ''
        highlighted = highlight_code(code_raw, lang)
        return f'<div class="code-wrapper">{lang_label}{highlighted}</div>'

    return re.sub(
        r'<pre><code(?:\s+class="language-([^"]*)")?>(.*?)</code></pre>',
        replace_block,
        html,
        flags=re.DOTALL
    )


def _preprocess_markdown(md: str) -> str:
    lines = md.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith('```'):
            indent = len(line) - len(stripped)
            fence_open = stripped
            block_lines = []
            i += 1
            while i < len(lines):
                curr = lines[i]
                curr_stripped = curr.lstrip()
                if curr_stripped.startswith('```') and curr_stripped.strip() == '```':
                    break
                if curr.startswith(' ' * indent):
                    block_lines.append(curr[indent:])
                else:
                    block_lines.append(curr.lstrip() if curr.strip() else '')
                i += 1
            if result and result[-1].strip():
                result.append('')
            result.append(fence_open)
            result.extend(block_lines)
            result.append('```')
            result.append('')
        else:
            result.append(line)
        i += 1
    return '\n'.join(result)


# ============================================================================
# CSS DEL PDF
# ============================================================================

def _build_css() -> str:
    # Nota: sin variables CSS (var()) — xhtml2pdf no las soporta.
    # Valores literales: fg=#1a1a1a, border=#c8c8c0, muted=#505050, light=#808080, accent=#2d5d7b
    return """
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

@page { size: A4; margin: 2cm 2.2cm 2.5cm 2.2cm; }

html, body { background: white; }

body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 10.5pt;
    line-height: 1.75;
    color: #1a1a1a;
}

.pdf-header { text-align: center; margin-bottom: 20pt; }
.pdf-header h1 {
    font-family: Georgia, serif;
    font-size: 22pt;
    font-weight: 400;
    color: #1a1a1a;
    margin: 0;
}

h1, h2, h3, h4, h5, h6 {
    font-family: Georgia, serif;
    font-weight: 400;
    color: #1a1a1a;
}
h1 { font-size: 16pt; margin-top: 18pt; margin-bottom: 10pt; }
h2 { font-size: 13pt; margin-top: 16pt; margin-bottom: 8pt; color: #2d5d7b; border-bottom: 1px solid #e0e0e0; padding-bottom: 4pt; }
h3 { font-size: 11.5pt; margin-top: 14pt; margin-bottom: 6pt; }
h4 { font-size: 10.5pt; margin-top: 10pt; margin-bottom: 4pt; }

p { margin-bottom: 8pt; text-align: justify; }

ul, ol { margin: 6pt 0 10pt 18pt; }
li { margin-bottom: 4pt; line-height: 1.65; }

strong { font-weight: 700; }
em     { font-style: italic; }

blockquote {
    border-left: 4px solid #c8c8c0;
    margin: 12pt 0;
    padding: 8pt 12pt;
    background: white;
    color: #505050;
    font-style: italic;
    font-size: 10pt;
}

a { color: #2d5d7b; text-decoration: none; }
hr { border-top: 1px solid #c8c8c0; margin: 14pt 0; }

table { width: 100%; border-collapse: collapse; margin: 12pt 0; font-size: 9.5pt; }
thead { background: #1a1a1a; color: #ffffff; }
th { padding: 6pt 8pt; text-align: left; font-weight: 600; font-size: 8.5pt; border: 1px solid #c8c8c0; }
td { padding: 5pt 8pt; border: 1px solid #c8c8c0; vertical-align: top; }

code {
    font-family: 'Courier New', Courier, monospace;
    font-size: 9pt;
    background: #f0f0ee;
    color: #c0392b;
    padding: 1pt 4pt;
    border: 1px solid #dddddd;
}

pre {
    background: #282C34;
    color: #ABB2BF;
    padding: 10pt 12pt;
    font-family: 'Courier New', Courier, monospace;
    font-size: 8.5pt;
    line-height: 1.5;
    margin: 12pt 0;
    border: 2px solid #3a3a3a;
}

pre code {
    background: transparent;
    color: inherit;
    border: none;
    padding: 0;
    font-size: inherit;
}

.math-inline { font-style: italic; font-family: Georgia, serif; color: #2d5d7b; font-size: 10.5pt; }
.math-block { text-align: center; font-style: italic; font-family: Georgia, serif; color: #1a1a1a; font-size: 12pt; margin: 12pt auto; padding: 10pt; border-left: 3px solid #2d5d7b; border-right: 3px solid #2d5d7b; }

.pdf-footer { margin-top: 20pt; padding-top: 10pt; border-top: 1px solid #c8c8c0; text-align: center; font-size: 8pt; color: #808080; }
"""


# ============================================================================
# CLASE PRINCIPAL
# ============================================================================

# Tipo de retorno explícito para que app.py sepa si recibió PDF o HTML
class GenerationResult:
    """Encapsula el resultado de generate_pdf con metadatos sobre el tipo de archivo."""
    def __init__(self, data: bytes, is_pdf: bool):
        self.data    = data
        self.is_pdf  = is_pdf
        # Extensión y MIME type listos para usar en st.download_button
        self.ext      = "pdf"  if is_pdf else "html"
        self.mimetype = "application/pdf" if is_pdf else "text/html"


class SimplePDFGenerator:
    """Generador PDF e-ink: Markdown → HTML enriquecido → PDF (o HTML si WeasyPrint falta)."""

    def __init__(self, title: str = "Notas Generadas"):
        self.title = title
        self._sections: list[str] = []
        self.metadata: dict = {}

    def add_title(self, title: str) -> None:
        self.title = title

    def add_metadata(self, source: str = '', context: str = '', confidence: float = 0) -> None:
        self.metadata = {
            'source':     (source or 'Archivo')[:50],
            'context':    (context or 'General').title(),
            'confidence': f'{confidence:.1%}',
        }

    def add_content_from_markdown(self, md_text: str) -> None:
        md_text = _preprocess_markdown(md_text)
        html = markdown.markdown(md_text, extensions=['fenced_code', 'tables', 'attr_list'])
        html = apply_syntax_highlighting(html)
        html = process_latex_in_html(html)
        html = re.sub(r'<code class="inline-code">([^<]+)</code>', r'<code>\1</code>', html)
        html = re.sub(r'<p>\s*</p>', '', html)
        self._sections.append(html)

    def add_footer(self) -> None:
        pass  # Compatibilidad con código antiguo

    def generate_pdf(self) -> "GenerationResult":
        """
        Genera el documento y retorna un GenerationResult.

        Orden de prioridad:
        1. WeasyPrint  → PDF de alta calidad (Linux/Cloud, requiere GTK)
        2. xhtml2pdf   → PDF funcional (Windows, puro Python)
        3. HTML        → fallback último recurso

        El caller usa result.ext y result.mimetype para el download_button.
        """
        full_html = self._build_full_html()

        # 1. WeasyPrint (cloud / Linux)
        if WEASYPRINT_AVAILABLE:
            try:
                pdf_bytes = WeasyHTML(string=full_html).write_pdf()
                return GenerationResult(data=pdf_bytes, is_pdf=True)
            except Exception as e:
                logger.error("WeasyPrint falló: %s — intentando xhtml2pdf", e)

        # 2. xhtml2pdf (Windows / cualquier plataforma)
        if XHTML2PDF_AVAILABLE:
            try:
                buffer = BytesIO()
                status = pisa.CreatePDF(full_html, dest=buffer)
                if not status.err:
                    return GenerationResult(data=buffer.getvalue(), is_pdf=True)
                logger.error("xhtml2pdf reportó errores: %s", status.err)
            except Exception as e:
                logger.error("xhtml2pdf falló: %s", e)

        # 3. Fallback HTML
        logger.warning("Ningún motor PDF disponible — devolviendo HTML.")
        return GenerationResult(data=full_html.encode("utf-8"), is_pdf=False)

    def _build_full_html(self) -> str:
        now     = datetime.now().strftime('%d/%m/%Y %H:%M')
        css     = _build_css()
        content = '\n'.join(self._sections)
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self.title}</title>
<style>{css}</style>
</head>
<body>
<div class="pdf-header"><h1>{self.title}</h1></div>
{content}
<div class="pdf-footer"><p>Generado con ContentNotes &bull; {now}</p></div>
</body>
</html>"""


# Alias de compatibilidad
PDFGenerator = SimplePDFGenerator