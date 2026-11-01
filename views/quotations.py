import streamlit as st
import datetime
import json
import psycopg2
from uuid import uuid4
import os
import tempfile

from db_manager import load_clients, load_pdf_hmoty, generate_doc_number, get_db_connection
from helpers import sanitize_filename, show_pdf
from pdf_generator import KalkulacePDF

# --- ROZŠÍŘENÉ SEZNAMY PŘÍPRAVY POVRCHU ---
PREP_A = [
    "",
    "Odstraňte olej a mastnotu vhodným detergentem. Soli a ostatní nečistoty odstraňte omytím vysokotlakou vodou. Po oschnutí otryskejte na Sa 2 1/2 dle ISO 8501-1.",
    "Odstraňte olej a mastnotu vhodným detergentem. Soli a ostatní nečistoty odstraňte omytím vysokotlakou čistou vodou.",
    "Vlastní zadání"
]

PREP_B = [
    "",
    "Po oschnutí abrazivně otryskejte na Sa 1 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Otryskání vysokotlakým vodním paprskem na Wa 1 dle ISO 8501-4 (blesková koroze max. L).",
    "Otryskání vysokotlakým vodním paprskem na Wa 2 dle ISO 8501-4 (blesková koroze max. M).",
    "Otryskání vysokotlakým vodním paprskem na Wa 2 1/2 dle ISO 8501-4 (blesková koroze max. M).",
    "Vlastní zadání"
]

PREP_C = [
    "",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni N 9a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 9a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 10 dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 10a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 11 dle Rugotest No.3. Odstraňte prach.",
    "Příprava povrchu tryskáním na stupeň čistoty Sa 2 1/2 dle ČSN EN ISO 8501-1. Profil drsnosti povrchu střední (G) (ISO 8503-2)",
    "Vlastní zadání"
]

PREP_D = [
    "",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na PSa 2 1/2 dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na PSt 3 dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na PMa dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na St 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na Sa 2 1/2 (není-li to možné, mechanicky očistěte na St3) dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Vlastní zadání"
]

PREP_E = [
    "",
    "Po oschnutí mechanicky očistěte na St 2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí mechanicky očistěte na St 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí proveďte lehké abrazivní ometení za účelem zdrsnění povrchu. Odstraňte prach.",
    "Vlastní zadání"
]

PREP_F = [
    "Případná \"bílá rez\" musí být odstraněna obroušením např. smirkovým papírem nebo lehkým abrazivním ometením.",
    "Základní nátěr na žárově stříkané povlaky má být dle platných norem zhotoven v témže dni (pracovní směně) jako metalizace.",
    "Základní nátěr naneste nejdříve naředěný (15-20%) ve slabé vrstvě, nechte uniknout vzduchové bublinky (10-15min.) a poté aplikujte plnou vrstvu.",
    "Všechny nepřilnavé staré nátěry musí být odstraněny a vzniklé ostré přechody se musí zabrousit do ztracena. Pevně přilnavý nátěr je nutné zdrsnit pro zajištění přilnavosti."
]


# ---------------------------------------------

# --- POMOCNÉ FUNKCE PRO CHYTRÝ FILTR BAREV ---
def assign_chem_base(nazev):
    """Z existujícího názvu barvy odvodí chemickou bázi."""
    n = str(nazev).upper()
    if "AVANTGUARD" in n or "ZINC" in n or "ZINK" in n: return "Zinkepoxid"
    if "GALVOSIL" in n: return "Zinksilikát"
    if "HEMPAREA" in n: return "Polyurea"
    if "HEMPAXANE" in n: return "Polysiloxan"
    if "HEMPATHANE" in n or "PUR " in n: return "Polyuretan"
    if "HEMPADUR" in n or "HEMPAPRIME" in n or "EPOX" in n: return "Epoxid"
    if "HEMUCRYL" in n or "HEMPATEX" in n or "PRO ACRYLIC" in n or "HEMPAFIRE" in n: return "Akrylát"
    if "ALKYD" in n or "HEMPALIN" in n: return "Alkyd"
    return "Jiné"


def get_expected_base(sys_type, layer_index, total_layers):
    """Určí, jakou chemickou bázi by měla mít aktuální vrstva podle Hempel ISO systémů."""
    if "Vlastní" in sys_type: return None
    prefix = sys_type.split(" (")[0].strip()

    bases = []
    if prefix == "EP":
        bases = ["Epoxid"]
    elif prefix == "EP/EP":
        bases = ["Epoxid", "Epoxid"]
    elif prefix == "EP/PUR":
        bases = ["Epoxid", "Polyuretan"]
    elif prefix == "EP/EP/PUR":
        bases = ["Epoxid", "Epoxid", "Polyuretan"]
    elif prefix == "Zn(R)/EP/PUR":
        bases = ["Zinkepoxid", "Epoxid", "Polyuretan"]
    elif prefix == "Zn(R)/EP/Polysiloxan":
        bases = ["Zinkepoxid", "Epoxid", "Polysiloxan"]
    elif prefix == "Zn(R)/Polyurea":
        bases = ["Zinkepoxid", "Polyurea"]
    elif prefix == "PUR DTM":
        bases = ["Polyuretan"]
    elif prefix == "AK":
        bases = ["Alkyd"]
    elif prefix == "AY":
        bases = ["Akrylát"]
    elif prefix == "ESI/EP/PUR":
        bases = ["Zinksilikát", "Epoxid", "Polyuretan"]
    else:
        return None

    if total_layers == 1: return bases[0]

    if layer_index == 0:
        return bases[0]
    elif layer_index == total_layers - 1:
        return bases[-1]
    else:
        return bases[1] if len(bases) >= 3 else bases[0]


# ---------------------------------------------

def render_quotations():
    st.title("Tvorba cenové nabídky")

    df_clients = load_clients()
    client_options = [""] + df_clients['name'].tolist()

    default_idx = 0
    if "dashboard_selected_client" in st.session_state and st.session_state.dashboard_selected_client in client_options:
        default_idx = client_options.index(st.session_state.dashboard_selected_client)
        st.session_state.pop("dashboard_selected_client", None)

    selected_client = st.selectbox("Vyberte klienta:", client_options, index=default_idx)

    st.markdown("---")
    st.subheader("Generátor PDF Kalkulace")

    template = st.session_state.get("loaded_template", {})
    is_template_loaded = bool(template)

    with st.expander("Nastavení projektu a dokumentu", expanded=True):
        col_doc1, col_doc2 = st.columns(2)

        corr_options = [
            "C1 - Velmi nízká", "C2 - Nízká", "C3 - Střední", "C4 - Vysoká",
            "C5 - Velmi vysoká", "CX - Extrémní", "Im1 - Sladká voda",
            "Im2 - Mořská/poloslaná voda", "Im3 - Půda", "Im4 - Mořská s katodickou ochranou",
            "Vlastní zadání"
        ]

        sys_options = [
            "EP (Epoxid)",
            "EP/EP (Epoxid/Epoxid)",
            "EP/PUR (Epoxid/Polyuretan)",
            "EP/EP/PUR (Epoxid/Epoxid/Polyuretan)",
            "Zn(R)/EP/PUR (Zinkepoxid/Epoxid/Polyuretan)",
            "Zn(R)/EP/Polysiloxan (Zinkepoxid/Epoxid/Polysiloxan)",
            "Zn(R)/Polyurea (Zinkepoxid/Polyurea)",
            "PUR DTM (Jednovrstvý polyuretan)",
            "AK (Alkyd)",
            "AY (Akrylát)",
            "ESI/EP/PUR (Zinksilikát/Epoxid/Polyuretan)",
            "PUR (Polyuretan)",
            "Vlastní zadání"
        ]

        substrate_options = [
            "Uhlíková ocel",
            "Žárově pozinkovaná ocel",
            "Hliník",
            "Nerezová ocel",
            "Žárově stříkaná ocel (metalizace)",
            "Vlastní zadání"
        ]

        def safe_idx_select(lst, val, fallback_idx=0):
            if val in lst:
                return lst.index(val)
            elif val:
                return len(lst) - 1
            return fallback_idx

        with col_doc1:
            st.text_input("Dokument č.", value="Vygenerováno automaticky (po kliknutí)", disabled=True)
            pdf_project = st.text_input("Projekt", value=template.get("pdf_project", ""))
            pdf_temp = st.text_input("Provozní teplota", value=template.get("pdf_temp", "Do 120 °C"))

            corr_val = template.get("pdf_corr", "C4 - Vysoká")
            corr_idx = safe_idx_select(corr_options, corr_val)
            sel_corr = st.selectbox("Korozní zatížení (ISO 12944)", corr_options, index=corr_idx)
            if sel_corr == "Vlastní zadání":
                pdf_corr = st.text_input("Zadejte vlastní korozní zatížení",
                                         value=corr_val if corr_val not in corr_options else "")
            else:
                pdf_corr = sel_corr

            sys_val = template.get("pdf_sys_type", "EP/EP/PUR (Epoxid/Epoxid/Polyuretan)")
            sys_idx = safe_idx_select(sys_options, sys_val)
            sel_sys = st.selectbox("Typ nátěrového systému", sys_options, index=sys_idx)
            if sel_sys == "Vlastní zadání":
                pdf_sys_type = st.text_input("Zadejte vlastní typ systému",
                                             value=sys_val if sys_val not in sys_options else "")
            else:
                pdf_sys_type = sel_sys

        with col_doc2:
            sub_val = template.get("pdf_substrate", "Uhlíková ocel")
            sub_idx = safe_idx_select(substrate_options, sub_val)
            sel_sub = st.selectbox("Podkladový materiál", substrate_options, index=sub_idx)
            if sel_sub == "Vlastní zadání":
                pdf_substrate = st.text_input("Zadejte vlastní podklad",
                                              value=sub_val if sub_val not in substrate_options else "")
            else:
                pdf_substrate = sel_sub

            pdf_client = st.text_area("Poptávající / Aplikační firma",
                                      value=template.get("pdf_client", selected_client if selected_client else ""))
            pdf_area = st.number_input("Celková plocha (m²)", min_value=0.1,
                                       value=float(template.get("pdf_area", 100.0)), step=10.0)
            pdf_loss = st.number_input("Hlavní aplikační ztráta (%)", min_value=0, max_value=100,
                                       value=int(template.get("pdf_loss", 50)), step=5)
            pdf_validity = st.text_input("Platnost kalkulace do:", value=template.get("pdf_validity", "30 dní"))

        pdf_pozn = st.text_input("Poznámka (1. řádek tabulky)", value=template.get("pdf_pozn", ""))
        st.markdown("---")

        # Striktní validace
        corr_upper = pdf_corr.upper()
        sys_upper = pdf_sys_type.upper()
        sub_lower = pdf_substrate.lower()

        is_c1_c2 = "C1" in corr_upper or "C2" in corr_upper
        is_c5 = "C5" in corr_upper
        is_cx = "CX" in corr_upper
        is_im = "IM" in corr_upper
        is_c3_plus = any(x in corr_upper for x in ["C3", "C4", "C5", "CX"]) or is_im

        is_galvanized = "pozinkovaná" in sub_lower or "pozink" in sub_lower
        is_alu_inox = "hliník" in sub_lower or "nerez" in sub_lower

        has_zink = "ZN" in sys_upper or "ESI" in sys_upper
        is_ak_ay = "AK" in sys_upper or "AY" in sys_upper or "ALKYD" in sys_upper or "AKRYLÁT" in sys_upper
        is_pure_ep = sys_upper.strip() in ["EP (EPOXID)", "EP/EP (EPOXID/EPOXID)"]
        is_custom = "VLASTNÍ ZADÁNÍ" in sys_upper

        is_valid = True
        warning_msg = ""
        info_msg = ""

        if not is_custom:
            if is_im:
                if not is_pure_ep:
                    is_valid = False
                    warning_msg = "Pro prostředí ponoru (Im1-Im4) brožura Hempel uvádí pouze čistě epoxidové systémy (EP nebo EP/EP)."
            elif is_cx:
                if not has_zink:
                    is_valid = False
                    warning_msg = "Pro extrémní prostředí (CX) materiály Hempel vyžadují zinkem bohatý základ (Zn(R) nebo ESI)."
            elif is_c5:
                if is_ak_ay:
                    is_valid = False
                    warning_msg = "Pro prostředí C5 normy neuvádí alkydové (AK) ani akrylátové (AY) systémy jako vhodné."
            elif is_c1_c2:
                if has_zink:
                    warning_msg = "Zinkové základy jsou pro C1/C2 v pořádku, ale zbytečně silné (naddimenzované)."

        if is_custom:
            st.info("Vlastní zadání – nelze provést plnou automatickou kontrolu vůči ISO 12944.")
        elif not is_valid:
            st.error(f"⚠️ **Není doporučeno (ISO 12944):** {warning_msg}")
        elif warning_msg:
            st.warning(f"ℹ️ **Upozornění:** {warning_msg}")
        else:
            st.success(
                "✅ Kombinace korozního prostředí a typu systému přesně odpovídá specifikacím Hempel (ISO 12944).")

        if has_zink and not is_galvanized and not is_alu_inox:
            info_msg = "💡 **Nutná příprava povrchu:** Zinkové základy (zinkepoxid/zinksilikát) pro správnou funkci vyžadují abrazivní otryskání (Sa 2.5 nebo Sa 3)."
        elif is_c3_plus and not is_galvanized and not is_alu_inox:
            info_msg = "💡 **Doporučená příprava povrchu:** Tabulky nátěrových systémů od C3 výše standardně předpokládají aplikaci na otryskaný podklad (Sa 2.5)."
        elif is_galvanized:
            info_msg = "💡 **Pozinkovaný podklad:** Hempel doporučuje alkalické omytí, odstranění bílé rzi a lehké abrazivní ometení minerálním abrazivem."
        elif is_alu_inox:
            info_msg = "💡 **Hliník/Nerez:** Doporučuje se čistá voda, odmaštění a ideálně lehké odrhnutí speciálním brusivem."

        if info_msg:
            st.info(info_msg)

        st.markdown("#### Příprava povrchu (výběr)")

        def find_idx(lst, partial_string, default_idx=0):
            for idx, item in enumerate(lst):
                if partial_string in item:
                    return idx
            return default_idx

        if not is_template_loaded:
            default_a_idx = find_idx(PREP_A, "vysokotlakou čistou vodou", 0)

            if has_zink or is_c3_plus:
                default_b_idx = find_idx(PREP_B, "Sa 2 1/2", 0)
            else:
                default_b_idx = 0

            default_c_idx = 0
            default_d_idx = find_idx(PREP_D, "mechanicky očistěte na St3", 0)
            default_e_idx = find_idx(PREP_E, "lehké abrazivní ometení", 0) if (is_galvanized or is_alu_inox) else 0

            base_f = []
            if is_galvanized:
                for item in PREP_F:
                    if "bílá rez" in item:
                        base_f.append(item)
            default_f_vals = base_f
            custom_f_val = ""
        else:
            default_a_idx = safe_idx_select(PREP_A, template.get("prep_a", ""))
            default_b_idx = safe_idx_select(PREP_B, template.get("prep_b", ""))
            default_c_idx = safe_idx_select(PREP_C, template.get("prep_c", ""))
            default_d_idx = safe_idx_select(PREP_D, template.get("prep_d", ""))
            default_e_idx = safe_idx_select(PREP_E, template.get("prep_e", ""))
            default_f_vals = [x for x in template.get("prep_f", []) if x in PREP_F]
            custom_f_val = template.get("prep_f_custom", "")

        def custom_prep_select(label, options, default_idx, template_val, key_prefix):
            if is_template_loaded and template_val and template_val not in options:
                idx = len(options) - 1
            else:
                idx = default_idx

            sel = st.selectbox(label, options, index=idx, key=f"{key_prefix}_sel")
            if sel == "Vlastní zadání":
                return st.text_input(f"Vlastní text: {label.split('(')[0].strip()}",
                                     value=template_val if template_val not in options else "",
                                     key=f"{key_prefix}_txt")
            return sel

        prep_a = custom_prep_select("A - Základní čištění (vyberte max. 1)", PREP_A, default_a_idx,
                                    template.get("prep_a", ""), "a")
        prep_b = custom_prep_select("B - Abrazivní / Vodní tryskání (vyberte max. 1)", PREP_B, default_b_idx,
                                    template.get("prep_b", ""), "b")
        prep_c = custom_prep_select("C - Tryskání se specifikací drsnosti (vyberte max. 1)", PREP_C, default_c_idx,
                                    template.get("prep_c", ""), "c")
        prep_d = custom_prep_select("D - Svary a lokální opravy (vyberte max. 1)", PREP_D, default_d_idx,
                                    template.get("prep_d", ""), "d")
        prep_e = custom_prep_select("E - Mechanické a speciální plošné (vyberte max. 1)", PREP_E, default_e_idx,
                                    template.get("prep_e", ""), "e")

        prep_f_selected = st.multiselect("F - Dodatečné pokyny (můžete vybrat více)", PREP_F, default=default_f_vals)
        prep_f_custom = st.text_area("Vlastní dodatečné pokyny (nepovinné)", value=custom_f_val)

        prep_f = prep_f_selected.copy()
        if prep_f_custom.strip():
            prep_f.append(prep_f_custom.strip())

    st.markdown("#### Příplatky")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        fuel_surcharge_active = st.checkbox("Aktivovat palivový příplatek",
                                            value=template.get("fuel_surcharge_active", True))
    with col_s2:
        fuel_surcharge_pct = st.number_input("Výše palivového příplatku (%)", min_value=0.0, max_value=100.0,
                                             value=float(template.get("fuel_surcharge_pct", 5.0)), step=1.0,
                                             disabled=not fuel_surcharge_active)

    st.markdown("#### Nátěrové vrstvy")

    # Chytrý filtr vrstev
    smart_filter = st.checkbox("Filtrovat dostupné barvy podle specifikací Hempel (Doporučeno)", value=True)

    df_hmoty = load_pdf_hmoty()
    all_hmoty = df_hmoty['nazev'].tolist() if not df_hmoty.empty else ["Žádná data v DB"]

    if 'pdf_rows' not in st.session_state:
        st.session_state.pdf_rows = template.get("pdf_rows", [])

    types_of_coats = [
        "Základní (Primer)", "Mezinátěr (Intermediate)", "Vrchní (Topcoat)",
        "Jednovrstvý (DTM)", "Kotevní (Sealer)", "Protipožární",
        "Penetrační / Mlhový", "Antifouling", "Jiné"
    ]

    for i, row in enumerate(st.session_state.pdf_rows):
        st.markdown(f"**Vrstva {i + 1}**")

        total_layers = len(st.session_state.pdf_rows)
        expected_base = get_expected_base(pdf_sys_type, i, total_layers)

        # Aplikace filtru na barvy
        if smart_filter and expected_base:
            hmoty_options = [h for h in all_hmoty if assign_chem_base(h) == expected_base]
            if not hmoty_options:  # Fallback pokud by filtr vyřadil úplně všechno
                hmoty_options = all_hmoty
        else:
            hmoty_options = all_hmoty

        row_c1, row_c2, row_c3 = st.columns(3)
        row_c4, row_c5, row_c6, row_c7 = st.columns(4)

        # Odhad typu nátěru podle pořadí vrstvy
        if total_layers == 1:
            auto_coat = "Jednovrstvý (DTM)" if expected_base == "Polyuretan" else "Základní (Primer)"
        elif i == 0:
            auto_coat = "Základní (Primer)"
        elif i == total_layers - 1:
            auto_coat = "Vrchní (Topcoat)"
        else:
            auto_coat = "Mezinátěr (Intermediate)"

        current_coat = row['typ'] if row['typ'] in types_of_coats else auto_coat
        safe_coat_index = types_of_coats.index(current_coat)

        # Bezpečný výběr hmoty
        safe_hmota_index = hmoty_options.index(row['hmota']) if row['hmota'] in hmoty_options else 0

        with row_c1:
            st.session_state.pdf_rows[i]['typ'] = st.selectbox(
                "Typ nátěru", options=types_of_coats, index=safe_coat_index, key=f"coat_typ_{i}"
            )
        with row_c2:
            st.session_state.pdf_rows[i]['hmota'] = st.selectbox(
                "Nátěrová hmota", options=hmoty_options, index=safe_hmota_index, key=f"hmota_{i}"
            )
        with row_c3:
            st.session_state.pdf_rows[i]['odstin'] = st.text_input(
                "Odstín", value=row['odstin'], key=f"odstin_{i}"
            )

        with row_c4:
            st.session_state.pdf_rows[i]['dft'] = st.number_input(
                "Tloušťka (DFT) [µm]", min_value=0.0, value=float(row['dft']), step=10.0, key=f"dft_{i}"
            )
        with row_c5:
            st.session_state.pdf_rows[i]['plocha'] = st.number_input(
                "% z celk. plochy", min_value=0.0, max_value=100.0, value=float(row['plocha']), step=5.0,
                key=f"plocha_{i}"
            )
        with row_c6:
            st.session_state.pdf_rows[i]['c_l'] = st.number_input(
                "Cena za litr (Kč)", min_value=0.0, value=float(row['c_l']), step=10.0, key=f"c_l_{i}"
            )
        with row_c7:
            st.session_state.pdf_rows[i]['redeni'] = st.number_input(
                "Ředění (%)", min_value=0.0, max_value=100.0, value=float(row['redeni']), step=1.0, key=f"redeni_{i}"
            )

        if st.button(f"Odebrat vrstvu {i + 1}", key=f"remove_{i}"):
            st.session_state.pdf_rows.pop(i)
            st.rerun()

        st.divider()

    col_btn_add, col_btn_clear = st.columns([1, 5])
    with col_btn_add:
        if st.button("Přidat vrstvu", icon=":material/add:"):
            st.session_state.pdf_rows.append({
                'typ': 'Základní (Primer)', 'hmota': all_hmoty[0] if all_hmoty else "",
                'odstin': '', 'dft': 100.0, 'plocha': 100.0, 'c_l': 0.0, 'redeni': 5.0
            })
            st.rerun()
    with col_btn_clear:
        if template and st.button("Vyčistit formulář (Zrušit šablonu)"):
            st.session_state.pop("loaded_template", None)
            st.session_state.pdf_rows = []
            st.rerun()

    if st.button("Vygenerovat PDF", type="primary", icon=":material/picture_as_pdf:"):
        doc_signature = str(uuid4()).upper()
        doc_no = generate_doc_number(st.session_state.get("user_id", "XX"))

        final_prep_texts = [p for p in [prep_a, prep_b, prep_c, prep_d, prep_e] if p.strip()] + prep_f

        form_data_payload = {
            "pdf_project": pdf_project,
            "pdf_temp": pdf_temp,
            "pdf_corr": pdf_corr,
            "pdf_sys_type": pdf_sys_type,
            "pdf_substrate": pdf_substrate,
            "pdf_client": pdf_client,
            "pdf_area": pdf_area,
            "pdf_loss": pdf_loss,
            "pdf_validity": pdf_validity,
            "pdf_pozn": pdf_pozn,
            "prep_a": prep_a,
            "prep_b": prep_b,
            "prep_c": prep_c,
            "prep_d": prep_d,
            "prep_e": prep_e,
            "prep_f": prep_f_selected,
            "prep_f_custom": prep_f_custom,
            "fuel_surcharge_active": fuel_surcharge_active,
            "fuel_surcharge_pct": fuel_surcharge_pct,
            "pdf_rows": st.session_state.pdf_rows
        }
        form_data_json = json.dumps(form_data_payload)

        header_info = {
            "doc_no": doc_no,
            "project": pdf_project,
            "temp": pdf_temp,
            "corrosion": pdf_corr,
            "substrate": pdf_substrate,
            "client_company": pdf_client,
            "prep_texts": final_prep_texts
        }

        user_info = {
            "name": st.session_state.get("user_name", "Neznámý"),
            "phone": st.session_state.get("user_phone", ""),
            "email": st.session_state.get("user_email", "")
        }

        products_data = []
        for row in st.session_state.pdf_rows:
            matched = df_hmoty[df_hmoty['nazev'] == row['hmota']]
            if not matched.empty:
                db_susina = matched.iloc[0]['susina']
                db_redidlo = matched.iloc[0]['redidlo']
                db_cislo = matched.iloc[0]['cislo_odstinu']
            else:
                db_susina, db_redidlo, db_cislo = "", "", ""

            products_data.append({
                "typ": row['typ'], "hmota": row['hmota'], "cislo": db_cislo, "odstin": row['odstin'],
                "dft": row['dft'], "susina": db_susina, "plocha": row['plocha'], "c_l": row['c_l']
            })
            products_data.append({"hmota": db_redidlo, "redeni": row['redeni']})

        final_fuel_pct = fuel_surcharge_pct if fuel_surcharge_active else 0.0

        pdf = KalkulacePDF(user_info=user_info, validity_date=pdf_validity, signature_id=doc_signature, orientation="L",
                           unit="mm", format="A4")
        pdf.add_page()
        pdf.draw_template_grid(header_info)

        pdf.draw_table(products_data, main_loss=int(pdf_loss), celkova_plocha=pdf_area, sys_type=pdf_sys_type,
                       pozn=pdf_pozn, fuel_pct=final_fuel_pct)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_name = tmp.name
        tmp.close()

        pdf.output(tmp_name)
        with open(tmp_name, "rb") as f:
            pdf_bytes = f.read()
        os.remove(tmp_name)

        try:
            db_conn = get_db_connection()
            with db_conn.cursor() as db_cursor:
                db_cursor.execute(
                    "INSERT INTO pdf_archive (signature_id, author_email, client_name, pdf_file, doc_no, form_data) VALUES (%s, %s, %s, %s, %s, %s)",
                    (doc_signature, st.session_state.get("user_email", "Neznámý"), pdf_client,
                     psycopg2.Binary(pdf_bytes), doc_no, form_data_json)
                )
        except Exception as e:
            st.warning(f"Kalkulace vygenerována, ale nepodařilo se ji uložit do archivu: {e}")

        st.session_state.pop("loaded_template", None)

        date_str = datetime.date.today().strftime('%y%m%d')
        client_first_line = pdf_client.split('\n')[0].strip() if pdf_client else "Neznamy"
        comp_name = sanitize_filename(client_first_line)

        st.session_state["ready_pdf_bytes"] = pdf_bytes
        st.session_state["ready_pdf_name"] = f"{date_str}_{comp_name}_{doc_no}.pdf"

    if "ready_pdf_bytes" in st.session_state:
        st.success("✅ Kalkulace byla úspěšně vygenerována!")

        show_pdf(
            pdf_binary=st.session_state["ready_pdf_bytes"],
            filename=st.session_state["ready_pdf_name"]
        )