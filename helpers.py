"""Pomocné funkce, konstanty a UI komponenty pro CPQ aplikaci."""

import re
import unicodedata
import base64
import streamlit as st
import streamlit.components.v1 as components

# =============================================================================
# Konstanty (Texty pro PDF)
# =============================================================================
PREP_A = [
    "",
    "Odstraňte olej a mastnotu vhodným detergentem. Soli a ostatní nečistoty odstraňte omytím vysokotlakou vodou. Po oschnutí otryskejte na Sa 2 1/2 dle ISO 8501-1.",
    "Odstraňte olej a mastnotu vhodným detergentem. Soli a ostatní nečistoty odstraňte omytím vysokotlakou čistou vodou."
]

PREP_B = [
    "",
    "Po oschnutí abrazivně otryskejte na Sa 1 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 3 dle (ČSN) ISO 8501-1. Odstraňte prach."
]

PREP_C = [
    "",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni N 9a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 9a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 10 dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 10a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 11 dle Rugotest No.3. Odstraňte prach.",
    "Příprava povrchu tryskáním na stupeň čistoty Sa 2 1/2 dle ČSN EN ISO 8501-1. Profil drsnosti povrchu střední (G) (ISO 8503-2)"
]

PREP_D = [
    "",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na PSa 2 1/2 dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na PSt 3 dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na PMa dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na St 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na Sa 2 1/2 (není-li to možné, mechanicky očistěte na St3) dle (ČSN) ISO 8501-1. Odstraňte prach."
]

PREP_E = [
    "",
    "Po oschnutí mechanicky očistěte na St 2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí mechanicky očistěte na St 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí proveďte lehké abrazivní ometení za účelem zdrsnění povrchu. Odstraňte prach."
]

PREP_F = [
    "Případná \"bílá rez\" musí být odstraněna obroušením např. smirkovým papírem nebo lehkým abrazivním ometením.",
    "Základní nátěr na žárově stříkané povlaky má být dle platných norem zhotoven v témže dni (pracovní směně) jako metalizace.",
    "Základní nátěr naneste nejdříve naředěný (15-20%) ve slabé vrstvě, nechte uniknout vzduchové bublinky (10-15min.) a poté aplikujte plnou vrstvu.",
    "Všechny nepřilnavé staré nátěry musí být odstraněny a vzniklé ostré přechody se musí zabrousit do ztracena. Pevně přilnavý nátěr je nutné zdrsnit pro zajištění přilnavosti."
]

# =============================================================================
# Helper function: Universal PDF Display
# =============================================================================
def show_pdf(pdf_binary, filename="Kalkulace.pdf", key=None):
    """Zobrazení PDF pomocí viditelnějších minimalistických SVG ikon."""
    try:
        bg_color = st.get_option("theme.backgroundColor") or "#121212"
        primary_color = st.get_option("theme.primaryColor") or "#f39c12"
    except Exception:
        bg_color = "#121212"
        primary_color = "#f39c12"

    b64_pdf = base64.b64encode(pdf_binary).decode('utf-8')

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: {bg_color};
                display: flex;
                justify-content: flex-start;
                align-items: center;
                height: 100vh;
                overflow: hidden;
            }}
            .icon-btn {{
                cursor: pointer;
                text-decoration: none;
                color: #ffffff;
                margin-right: 15px;
                transition: all 0.2s ease-in-out;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 10px;
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.15);
            }}
            .icon-btn svg {{
                width: 28px;
                height: 28px;
                stroke: currentColor;
                stroke-width: 2.5;
                stroke-linecap: round;
                stroke-linejoin: round;
                fill: none;
            }}
            .icon-btn:hover {{
                color: {primary_color};
                background-color: rgba(255, 255, 255, 0.15);
                border-color: {primary_color};
                transform: translateY(-2px);
            }}
        </style>
    </head>
    <body>
        <button class="icon-btn" onclick="openPdf()" title="Otevřít PDF v nové kartě">
            <svg viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
        </button>
        <a class="icon-btn" href="data:application/pdf;base64,{b64_pdf}" download="{filename}" title="Uložit do zařízení">
            <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
        </a>

        <script>
        function openPdf() {{
            const b64 = "{b64_pdf}";
            const byteCharacters = atob(b64);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {{
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }}
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], {{type: 'application/pdf'}});
            const blobUrl = URL.createObjectURL(blob);

            const newWindow = window.open(blobUrl, '_blank');
            if (newWindow) {{
                newWindow.onload = () => {{
                    newWindow.document.title = "{filename}";
                }};
            }}
        }}
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=60)

# =============================================================================
# String/Validation Utilities
# =============================================================================
def sanitize_filename(name):
    """Vytvoří filesystem-safe řetězec bez diakritiky a speciálních znaků."""
    if not name:
        return "Neznamy"
    safe_name = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('utf-8')
    safe_name = re.sub(r'\s+', '_', safe_name)
    safe_name = re.sub(r'[^A-Za-z0-9_.-]', '', safe_name)
    return safe_name.strip('_')