import re
import logging
from datetime import datetime

import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

logger = logging.getLogger(__name__)

try:
    from weasyprint import HTML as WeasyHTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    logger.warning(
        "WeasyPrint no está instalado. Los PDFs se generarán como HTML. "
        "Instala weasyprint para habilitar la exportación real a PDF."
    )


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
    return """
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --eink-fg:     #1a1a1a;
    --eink-border: #c8c8c0;
    --eink-muted:  #505050;
    --eink-light:  #808080;
    --accent:      #2d5d7b;
}

@page { size: A4; margin: 2cm 2.2cm 2.5cm 2.2cm; background: white; }

html, body { background: white !important; }

body {
    font-family: 'Merriweather', 'Georgia', 'Times New Roman', serif;
    font-size: 10.5pt;
    line-height: 1.75;
    color: #1a1a1a;
}

.pdf-header { text-align: center; margin-bottom: 1.6rem; }
.pdf-header h1 {
    font-family: 'Lora', 'Georgia', serif;
    font-size: 22pt;
    font-weight: 400;
    letter-spacing: 0.5px;
    color: var(--eink-fg);
    margin: 0;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Lora', 'Georgia', serif;
    font-weight: 400;
    color: var(--eink-fg);
    page-break-after: avoid;
}
h1 { font-size: 16pt; margin: 1.4rem 0 0.8rem; }
h2 { font-size: 13pt; margin: 1.2rem 0 0.6rem; color: var(--accent); border-bottom: 1px solid #e0e0e0; padding-bottom: 0.3rem; }
h3 { font-size: 11.5pt; margin: 1rem 0 0.5rem; }
h4 { font-size: 10.5pt; margin: 0.8rem 0 0.4rem; }

p { margin-bottom: 0.8rem; text-align: justify; orphans: 3; widows: 3; }

ul, ol { margin: 0.5rem 0 0.8rem 1.4rem; }
li { margin-bottom: 0.35rem; line-height: 1.65; }

strong { font-weight: 700; }
em     { font-style: italic; }

blockquote {
    border-left: 4px solid var(--eink-border);
    margin: 1rem 0;
    padding: 0.7rem 1rem;
    background: white;
    color: var(--eink-muted);
    font-style: italic;
    font-size: 10pt;
}

a { color: var(--accent); text-decoration: none; }
hr { border: none; border-top: 1px solid var(--eink-border); margin: 1.2rem 0; }

table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 9.5pt; page-break-inside: avoid; }
thead { background: var(--eink-fg); color: #ffffff; }
th { padding: 6pt 8pt; text-align: left; font-weight: 600; font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.3px; border: 1px solid var(--eink-border); }
td { padding: 5pt 8pt; border: 1px solid var(--eink-border); vertical-align: top; }

code {
    font-family: 'Courier New', 'Consolas', monospace;
    font-size: 9pt;
    background: #f0f0ee;
    color: #c0392b;
    padding: 1pt 4pt;
    border-radius: 2px;
    border: 1px solid #ddd;
}

.code-wrapper { margin: 1rem 0; overflow: hidden; page-break-inside: avoid; border: 2px solid #3a3a3a; }
.code-lang { background: #1a1a1a; color: #6a737d; font-family: 'Courier New', monospace; font-size: 7pt; padding: 3pt 12pt; text-transform: uppercase; letter-spacing: 1.2px; }
.code-wrapper > div { background: #282C34; margin: 0; padding: 0; }
.code-wrapper pre { background: #282C34 !important; color: #ABB2BF !important; margin: 0 !important; padding: 12pt 14pt !important; font-family: 'Courier New', 'Consolas', monospace !important; font-size: 8.5pt !important; line-height: 1.6 !important; white-space: pre-wrap !important; word-break: break-word !important; border: none !important; }
.code-wrapper pre code, .code-wrapper pre span { background: transparent !important; color: inherit !important; border: none !important; padding: 0 !important; border-radius: 0 !important; font-size: inherit !important; font-family: inherit !important; }

.math-inline { font-style: italic; font-family: 'Georgia', serif; color: var(--accent); font-size: 10.5pt; }
.math-block { display: block; text-align: center; font-style: italic; font-family: 'Georgia', serif; color: var(--eink-fg); font-size: 12pt; margin: 1rem auto; padding: 0.8rem 1rem; border-left: 3px solid var(--accent); border-right: 3px solid var(--accent); page-break-inside: avoid; }
.math-frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 2pt; }
.math-num { border-bottom: 1px solid currentColor; padding: 0 2pt; font-size: 0.85em; }
.math-den { padding: 0 2pt; font-size: 0.85em; }

.pdf-footer { margin-top: 1.5rem; padding-top: 0.8rem; border-top: 1px solid var(--eink-border); text-align: center; font-size: 8pt; color: var(--eink-light); }
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

        - Si WeasyPrint está disponible → PDF real (is_pdf=True)
        - Si no está disponible          → HTML de alta calidad (is_pdf=False)

        El caller (app.py) usa result.ext y result.mimetype para el
        download_button, por lo que el usuario siempre sabe qué tipo recibe.
        """
        full_html = self._build_full_html()

        if WEASYPRINT_AVAILABLE:
            try:
                pdf_bytes = WeasyHTML(string=full_html).write_pdf()
                return GenerationResult(data=pdf_bytes, is_pdf=True)
            except Exception as e:
                logger.error("WeasyPrint falló al generar el PDF: %s", e)
                # Caída controlada: devuelve HTML con is_pdf=False
                return GenerationResult(data=full_html.encode("utf-8"), is_pdf=False)

        # WeasyPrint no instalado: devuelve HTML
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
