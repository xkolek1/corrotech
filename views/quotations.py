import streamlit as st
import datetime
import json
import psycopg2
from uuid import uuid4
import os
import tempfile

from db_manager import load_clients, load_pdf_hmoty, generate_doc_number, get_db_connection
from helpers import PREP_A, PREP_B, PREP_C, PREP_D, PREP_E, PREP_F, sanitize_filename, show_pdf
from pdf_generator import KalkulacePDF


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

        # Možnosti dle ISO 12944 a Hempel
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
            "AK (Alkyd)",
            "AY (Akrylát)",
            "ESI/EP/PUR (Zinksilikát/Epoxid/Polyuretan)",
            "PUR (Polyuretan)",
            "Vlastní zadání"
        ]

        def safe_idx_select(lst, val, fallback_idx=0):
            return lst.index(val) if val in lst else fallback_idx

        with col_doc1:
            st.text_input("Dokument č.", value="Vygenerováno automaticky (po kliknutí)", disabled=True)
            pdf_project = st.text_input("Projekt", value=template.get("pdf_project", ""))
            pdf_temp = st.text_input("Provozní teplota", value=template.get("pdf_temp", "Do 120 °C"))

            # Korozní zatížení
            corr_val = template.get("pdf_corr", "C4 - Vysoká")
            corr_idx = safe_idx_select(corr_options, corr_val,
                                       len(corr_options) - 1 if corr_val not in corr_options else 0)
            sel_corr = st.selectbox("Korozní zatížení (ISO 12944)", corr_options, index=corr_idx)
            if sel_corr == "Vlastní zadání":
                pdf_corr = st.text_input("Zadejte vlastní korozní zatížení",
                                         value=corr_val if corr_val not in corr_options else "")
            else:
                pdf_corr = sel_corr

            # Typ systému
            sys_val = template.get("pdf_sys_type", "EP/EP/PUR (Epoxid/Epoxid/Polyuretan)")
            sys_idx = safe_idx_select(sys_options, sys_val, len(sys_options) - 1 if sys_val not in sys_options else 0)
            sel_sys = st.selectbox("Typ nátěrového systému", sys_options, index=sys_idx)
            if sel_sys == "Vlastní zadání":
                pdf_sys_type = st.text_input("Zadejte vlastní typ systému",
                                             value=sys_val if sys_val not in sys_options else "")
            else:
                pdf_sys_type = sel_sys

        with col_doc2:
            pdf_substrate = st.text_input("Podkladový materiál", value=template.get("pdf_substrate", "Uhlíková ocel"))
            pdf_client = st.text_area("Poptávající / Aplikační firma",
                                      value=template.get("pdf_client", selected_client if selected_client else ""))
            pdf_area = st.number_input("Celková plocha (m²)", min_value=0.1,
                                       value=float(template.get("pdf_area", 100.0)), step=10.0)
            pdf_loss = st.number_input("Hlavní aplikační ztráta (%)", min_value=0, max_value=100,
                                       value=int(template.get("pdf_loss", 50)), step=5)
            pdf_validity = st.text_input("Platnost kalkulace do:", value=template.get("pdf_validity", "30 dní"))

        pdf_pozn = st.text_input("Poznámka (1. řádek tabulky)",
                                 value=template.get("pdf_pozn", ""))

        st.markdown("---")

        # Validace nátěrového systému vs koroze
        is_c5_cx = any(x in pdf_corr for x in ["C5", "CX"])
        is_im = "Im" in pdf_corr
        is_ak_ay = any(x in pdf_sys_type for x in ["AK", "AY", "Alkyd", "Akrylát"])
        has_zink = "Zn" in pdf_sys_type or "Zink" in pdf_sys_type
        is_c3_plus = any(x in pdf_corr for x in ["C3", "C4", "C5", "CX"]) or is_im


        st.info("zatím nic moc nehlídá (zatím chybí notičky 🤓)")
        if (is_c5_cx or is_im) and is_ak_ay:
            st.error(
                f"⚠️ **Nedoporučeno:** {pdf_sys_type} není podle normy ISO 12944 standardně vhodný pro {pdf_corr}.")
        elif has_zink and "C1" in pdf_corr:
            st.warning(
                f"ℹ️ **Naddimenzováno:** Zinkové základy jsou pro {pdf_corr} technologicky v pořádku, ale zbytečně silné.")
        else:
            st.success(f"✅ Kombinace prostředí a systému dává technologicky smysl.")

        if has_zink:
            st.info(
                "💡 **Nutná příprava povrchu:** Zinkové základy (zinkepoxid/zinksilikát) vyžadují abrazivní otryskání (Sa 2.5 nebo Sa 3).")
        elif is_c3_plus:
            st.info(
                "💡 **Doporučená příprava povrchu:** Pro C3 a vyšší (či ponor) norma standardně počítá s abrazivním otryskáním (Sa 2.5).")

        st.markdown("#### Příprava povrchu (výběr)")

        # Pokus o vyhledání Sa 2.5 v dostupných seznamech
        def find_sa25_idx(options_list):
            for idx, item in enumerate(options_list):
                if "Sa 2" in item or "Sa2" in item:
                    return idx
            return 0

        # Pokud není načtená šablona a systém si to žádá, přednastavíme Sa 2.5 v plošném tryskání (PREP_B)
        default_b_idx = find_sa25_idx(PREP_B) if (not is_template_loaded and (has_zink or is_c3_plus)) else 0

        def safe_idx(lst, val, fallback=0):
            return lst.index(val) if val in lst else fallback

        prep_a = st.selectbox("A - Základní čištění (vyberte max. 1)", PREP_A,
                              index=safe_idx(PREP_A, template.get("prep_a", "")))

        prep_b = st.selectbox("B - Abrazivní tryskání plošné (vyberte max. 1)", PREP_B,
                              index=safe_idx(PREP_B, template.get("prep_b", ""), fallback=default_b_idx))

        prep_c = st.selectbox("C - Tryskání se specifikací drsnosti (vyberte max. 1)", PREP_C,
                              index=safe_idx(PREP_C, template.get("prep_c", "")))

        prep_d = st.selectbox("D - Svary a lokální opravy (vyberte max. 1)", PREP_D,
                              index=safe_idx(PREP_D, template.get("prep_d", "")))

        prep_e = st.selectbox("E - Mechanické a speciální plošné (vyberte max. 1)", PREP_E,
                              index=safe_idx(PREP_E, template.get("prep_e", "")))

        default_f = [x for x in template.get("prep_f", []) if x in PREP_F]
        prep_f = st.multiselect("F - Dodatečné pokyny (můžete vybrat více)", PREP_F, default=default_f)

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

    df_hmoty = load_pdf_hmoty()

    if 'pdf_rows' not in st.session_state:
        st.session_state.pdf_rows = template.get("pdf_rows", [])

    types_of_coats = [
        "Základní (Primer)", "Mezinátěr (Intermediate)", "Vrchní (Topcoat)",
        "Jednovrstvý (DTM)", "Kotevní (Sealer)", "Protipožární",
        "Penetrační / Mlhový", "Antifouling", "Jiné"
    ]
    hmoty_options = df_hmoty['nazev'].tolist() if not df_hmoty.empty else ["Žádná data v DB"]

    for i, row in enumerate(st.session_state.pdf_rows):
        st.markdown(f"**Vrstva {i + 1}**")

        row_c1, row_c2, row_c3 = st.columns(3)
        row_c4, row_c5, row_c6, row_c7 = st.columns(4)

        safe_coat_index = types_of_coats.index(row['typ']) if row['typ'] in types_of_coats else 0
        safe_hmota_index = hmoty_options.index(row['hmota']) if row['hmota'] in hmoty_options else 0

        with row_c1:
            st.session_state.pdf_rows[i]['typ'] = st.selectbox(
                "Typ nátěru",
                options=types_of_coats,
                index=safe_coat_index,
                key=f"coat_typ_{i}"
            )
        with row_c2:
            st.session_state.pdf_rows[i]['hmota'] = st.selectbox(
                "Nátěrová hmota",
                options=hmoty_options,
                index=safe_hmota_index,
                key=f"hmota_{i}"
            )
        with row_c3:
            st.session_state.pdf_rows[i]['odstin'] = st.text_input(
                "Odstín",
                value=row['odstin'],
                key=f"odstin_{i}"
            )

        with row_c4:
            st.session_state.pdf_rows[i]['dft'] = st.number_input(
                "Tloušťka (DFT) [µm]",
                min_value=0.0,
                value=float(row['dft']),
                step=10.0,
                key=f"dft_{i}"
            )
        with row_c5:
            st.session_state.pdf_rows[i]['plocha'] = st.number_input(
                "% z celk. plochy",
                min_value=0.0,
                max_value=100.0,
                value=float(row['plocha']),
                step=5.0,
                key=f"plocha_{i}"
            )
        with row_c6:
            st.session_state.pdf_rows[i]['c_l'] = st.number_input(
                "Cena za litr (Kč)",
                min_value=0.0,
                value=float(row['c_l']),
                step=10.0,
                key=f"c_l_{i}"
            )
        with row_c7:
            st.session_state.pdf_rows[i]['redeni'] = st.number_input(
                "Ředění (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(row['redeni']),
                step=1.0,
                key=f"redeni_{i}"
            )

        if st.button(f"Odebrat vrstvu {i + 1}", key=f"remove_{i}"):
            st.session_state.pdf_rows.pop(i)
            st.rerun()

        st.divider()

    col_btn_add, col_btn_clear = st.columns([1, 5])
    with col_btn_add:
        if st.button("Přidat vrstvu", icon=":material/add:"):
            st.session_state.pdf_rows.append({
                'typ': 'Základní (Primer)', 'hmota': hmoty_options[0] if hmoty_options else "",
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
            "prep_f": prep_f,
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