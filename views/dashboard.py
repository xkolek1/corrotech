import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import datetime
import tempfile
import os
import json
import psycopg2
from uuid import uuid4

from db_manager import (
    load_clients, load_products, load_client_invoices, load_pdf_hmoty,
    generate_doc_number, get_db_connection
)
from helpers import (
    PREP_A, PREP_B, PREP_C, PREP_D, PREP_E, PREP_F,
    sanitize_filename, show_pdf
)


def render_dashboard():
    df_clients = load_clients()
    df_products = load_products()

    st.markdown("<h2 style='text-align: center; margin-bottom: 30px;'>Vyhledávání klienta</h2>", unsafe_allow_html=True)

    layout_col1, layout_col2, layout_col3 = st.columns([1, 2, 1])
    with layout_col2:
        client_options = [""] + df_clients['name'].tolist()

        default_idx = 0
        if "dashboard_selected_client" in st.session_state:
            if st.session_state.dashboard_selected_client in client_options:
                default_idx = client_options.index(st.session_state.dashboard_selected_client)
            st.session_state.pop("dashboard_selected_client", None)

        selected_client = st.selectbox("Začněte psát název firmy...", client_options, index=default_idx,
                                       label_visibility="collapsed")

    st.markdown("---")

    if selected_client:
        client_row = df_clients[df_clients['name'] == selected_client].iloc[0]
        st.title(f"{selected_client}")

        info_col1, info_col2, info_col3 = st.columns(3)
        with info_col1:
            st.metric("IČ", str(client_row['ic']))

        with info_col2:
            sales = client_row['total_sales']
            if pd.isna(sales) or sales == 0:
                st.metric("Celkový obrat bez DPH", "Nezadáno / 0")
            else:
                st.metric("Celkový obrat bez DPH", f"{sales:,.0f} Kč".replace(",", " "))

        with info_col3:
            profit = client_row['total_profitability']
            if pd.isna(profit) or profit == 0:
                st.metric("Celková ziskovost bez DPH", "Nezadáno / 0")
            else:
                st.metric("Celková ziskovost bez DPH", f"{profit:,.0f} Kč - není pravda zatím :)".replace(",", " "))

        raw_dealer = client_row['dealer']
        dealer_str = str(raw_dealer).strip() if pd.notna(raw_dealer) else ""
        st.markdown(f"**Dealer:** {dealer_str if dealer_str else '/'}")

        st.markdown("---")

        df_inv = load_client_invoices(client_row['ic'])

        start_date = '2022-01-01'
        end_date = datetime.date.today()
        all_months = pd.date_range(start=start_date, end=end_date, freq='MS')

        cz_months = {
            1: 'Led', 2: 'Úno', 3: 'Bře', 4: 'Dub', 5: 'Kvě', 6: 'Čvn',
            7: 'Čvc', 8: 'Srp', 9: 'Zář', 10: 'Říj', 11: 'Lis', 12: 'Pro'
        }

        if not df_inv.empty:
            df_inv['purchase_date'] = pd.to_datetime(df_inv['purchase_date'])
            df_inv['turnover'] = df_inv['price'] * df_inv['quantity']
            df_inv['month_start'] = df_inv['purchase_date'].dt.to_period('M').dt.to_timestamp()

            monthly_sales = df_inv.groupby('month_start')['turnover'].sum().reindex(all_months,
                                                                                    fill_value=0).reset_index()
            monthly_sales.columns = ['month', 'turnover']
        else:
            monthly_sales = pd.DataFrame({'month': all_months, 'turnover': 0})

        monthly_sales['cz_month'] = monthly_sales['month'].dt.month.map(cz_months)
        monthly_sales['year'] = monthly_sales['month'].dt.year.astype(str)

        st.subheader("Vývoj měsíčního obratu")

        fig_sales = go.Figure()
        fig_sales.add_trace(go.Bar(
            x=[monthly_sales['year'].tolist(), monthly_sales['cz_month'].tolist()],
            y=monthly_sales['turnover'].tolist(),
            marker_color='#1f77b4',
            text=monthly_sales['turnover'].apply(lambda x: f"{x:,.0f} Kč".replace(",", " ") if x > 0 else ""),
            textposition='auto'
        ))

        fig_sales.update_layout(
            xaxis_title="",
            yaxis_title="Obrat (Kč)",
            margin=dict(l=20, r=20, t=30, b=20),
            height=350,
            xaxis=dict(
                type='multicategory',
                tickangle=-45
            )
        )
        st.plotly_chart(fig_sales, use_container_width=True)

        st.markdown("---")

    st.subheader("Kalkulace cenové nabídky")
    product_options = [""] + df_products['name'].tolist()
    selected_product = st.selectbox("Vyberte produkt k nacenění:", product_options, index=0)

    if selected_product:
        product_row = df_products[df_products['name'] == selected_product].iloc[0]
        p_storage = float(product_row['storage_price'])

        mock_margin_index = 1.5
        p_retail = p_storage * 2
        target_price = p_storage * mock_margin_index
        min_range = max(target_price * 0.85, p_storage)
        max_range = target_price * 1.15

        last_bought_price = target_price * 0.92
        last_bought_date = "N/A"

        st.write("#### Doporučená cena a rozpětí")
        st.info("Výpočet doporučeného cenového indexu: **XX** (Bude implementováno později)")

        @st.cache_data
        def create_gauge_chart(p_st, p_ret, tgt, min_r, max_r, sel_prod, last_bp):
            g_fig = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=tgt,
                number={'suffix': " Kč", 'valueformat': ",.0f"},
                title={'text': f"Cenová hladina: {sel_prod}", 'font': {'size': 20}},
                delta={'reference': last_bp, 'increasing': {'color': "green"},
                       'decreasing': {'color': "red"}},
                gauge={
                    'axis': {'range': [p_st, p_ret], 'tickwidth': 1, 'tickcolor': "darkblue"},
                    'bar': {'color': "rgba(0,0,0,0)"},
                    'bgcolor': "white",
                    'borderwidth': 2,
                    'bordercolor': "gray",
                    'steps': [
                        {'range': [p_st, min_r], 'color': "rgba(255, 99, 132, 0.4)"},
                        {'range': [min_r, max_r], 'color': "rgba(75, 192, 192, 0.5)"},
                        {'range': [max_r, p_ret], 'color': "rgba(54, 162, 235, 0.4)"}
                    ],
                    'threshold': {
                        'line': {'color': "black", 'width': 5},
                        'thickness': 0.75,
                        'value': tgt
                    }
                }
            ))
            g_fig.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20))
            return g_fig

        fig = create_gauge_chart(p_storage, p_retail, target_price, min_range, max_range, selected_product,
                                 last_bought_price)
        st.plotly_chart(fig, use_container_width=True)

        met_col1, met_col2, met_col3 = st.columns(3)
        met_col1.metric("Skladová cena (Náklad)", f"{p_storage:,.0f} Kč".replace(",", " "))
        met_col2.metric(f"Poslední nákup ({last_bought_date})", f"{last_bought_price:,.0f} Kč".replace(",", " "))
        met_col3.metric("Maloobchodní cena (Max)", f"{p_retail:,.0f} Kč".replace(",", " "))

        st.success(
            f"**Tip pro obchod:** Ideální prostor pro vyjednávání (zelená zóna na grafu) "
            f"je mezi **{min_range:,.0f} Kč** a **{max_range:,.0f} Kč**.".replace(",", " ")
        )

    st.markdown("---")
    st.subheader("Generátor PDF Kalkulace")

    template = st.session_state.get("loaded_template", {})

    with st.expander("Nastavení projektu a dokumentu", expanded=True):
        col_doc1, col_doc2 = st.columns(2)
        with col_doc1:
            st.text_input("Dokument č.", value="Vygenerováno automaticky (po kliknutí)", disabled=True)
            pdf_project = st.text_input("Projekt", value=template.get("pdf_project", ""))
            pdf_temp = st.text_input("Provozní teplota", value=template.get("pdf_temp", "Do 120 °C"))
            pdf_corr = st.text_input("Korozní zatížení", value=template.get("pdf_corr", "C4-High"))
            pdf_sys_type = st.text_input("Typ nátěrového systému", value=template.get("pdf_sys_type", "EP/EP/PUR"))

        with col_doc2:
            pdf_substrate = st.text_input("Podkladový materiál", value=template.get("pdf_substrate", "Uhlíková ocel"))
            pdf_client = st.text_area("Poptávající / Aplikační firma (může být více řádků)",
                                      value=template.get("pdf_client", selected_client if selected_client else ""))
            pdf_area = st.number_input("Celková plocha (m²)", min_value=0.1,
                                       value=float(template.get("pdf_area", 100.0)), step=10.0)
            pdf_loss = st.number_input("Hlavní aplikační ztráta pro všechny nátěry (%)", min_value=0, max_value=100,
                                       value=int(template.get("pdf_loss", 50)), step=5)
            pdf_validity = st.text_input("Platnost kalkulace do:", value=template.get("pdf_validity", "30 dní"))

        pdf_pozn = st.text_input("Poznámka (1. řádek tabulky)",
                                 value=template.get("pdf_pozn", "Protipožární ochrana PLATE15*200"))

        st.markdown("#### Příprava povrchu (výběr) - max 3/4 pro 5 nátěrových vrstev")

        def safe_idx(lst, val): return lst.index(val) if val in lst else 0

        prep_a = st.selectbox("A - Základní čištění (vyberte max. 1)", PREP_A,
                              index=safe_idx(PREP_A, template.get("prep_a", "")))
        prep_b = st.selectbox("B - Abrazivní tryskání plošné (vyberte max. 1)", PREP_B,
                              index=safe_idx(PREP_B, template.get("prep_b", "")))
        prep_c = st.selectbox("C - Tryskání se specifikací drsnosti (vyberte max. 1)", PREP_C,
                              index=safe_idx(PREP_C, template.get("prep_c", "")))
        prep_d = st.selectbox("D - Svary a lokální opravy (vyberte max. 1)", PREP_D,
                              index=safe_idx(PREP_D, template.get("prep_d", "")))
        prep_e = st.selectbox("E - Mechanické a speciální plošné (vyberte max. 1)", PREP_E,
                              index=safe_idx(PREP_E, template.get("prep_e", "")))

        default_f = [x for x in template.get("prep_f", []) if x in PREP_F]
        prep_f = st.multiselect("F - Dodatečné pokyny (můžete vybrat více)", PREP_F, default=default_f)

    st.markdown("#### Nátěrové vrstvy")

    df_hmoty = load_pdf_hmoty()

    if 'pdf_rows' not in st.session_state:
        st.session_state.pdf_rows = template.get("pdf_rows", [])

    types_of_coats = ["Penetrační", "Mlhový nástřik", "Napouštěcí", "Základní", "Podkladní", "Vrchní"]
    hmoty_options = df_hmoty['nazev'].tolist() if not df_hmoty.empty else ["Žádná data v DB"]

    for i, row in enumerate(st.session_state.pdf_rows):
        st.markdown(f"**Vrstva {i + 1}**")
        row_c1, row_c2, row_c3, row_c4 = st.columns(4)
        row_c5, row_c6, row_c7 = st.columns([1, 1, 2])

        safe_coat_index = int(types_of_coats.index(row['typ'])) if row['typ'] in types_of_coats else 0
        safe_hmota_index = int(hmoty_options.index(row['hmota'])) if row['hmota'] in hmoty_options else 0

        with row_c1:
            st.session_state.pdf_rows[i]['typ'] = st.selectbox(f"Typ nátěru##{i}", types_of_coats,
                                                               index=safe_coat_index)
        with row_c2:
            st.session_state.pdf_rows[i]['hmota'] = st.selectbox(f"Nátěrová hmota##{i}", hmoty_options,
                                                                 index=safe_hmota_index)
        with row_c3:
            st.session_state.pdf_rows[i]['odstin'] = st.text_input(f"Odstín##{i}", value=row['odstin'])
        with row_c4:
            st.session_state.pdf_rows[i]['dft'] = st.number_input(f"Tloušťka (DFT)##{i}", min_value=0.0,
                                                                  value=float(row['dft']), step=10.0)

        with row_c5:
            st.session_state.pdf_rows[i]['plocha'] = st.number_input(f"% z celk. plochy##{i}", min_value=0.0,
                                                                     max_value=100.0, value=float(row['plocha']))
        with row_c6:
            st.session_state.pdf_rows[i]['c_l'] = st.number_input(f"Cena za litr (Kč)##{i}", min_value=0.0,
                                                                  value=float(row['c_l']))
        with row_c7:
            st.session_state.pdf_rows[i]['redeni'] = st.number_input(f"Ředění (%)##{i}", min_value=0.0, max_value=100.0,
                                                                     value=float(row['redeni']))

        if st.button(f"Odebrat vrstvu {i + 1}", key=f"remove_{i}"):
            st.session_state.pdf_rows.pop(i)
            st.rerun()
        st.markdown("---")

    col_btn_add, col_btn_clear = st.columns([1, 5])
    with col_btn_add:
        if st.button("Přidat vrstvu", icon=":material/add:"):
            st.session_state.pdf_rows.append({
                'typ': 'Základní', 'hmota': hmoty_options[0] if hmoty_options else "",
                'odstin': '', 'dft': 100.0, 'plocha': 100.0, 'c_l': 0.0, 'redeni': 5.0
            })
            st.rerun()
    with col_btn_clear:
        if template and st.button("Vyčistit formulář (Zrušit šablonu)"):
            st.session_state.pop("loaded_template", None)
            st.session_state.pdf_rows = []
            st.rerun()

    if st.button("Vygenerovat PDF", type="primary", icon=":material/picture_as_pdf:"):
        from pdf_generator import KalkulacePDF

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

        pdf = KalkulacePDF(user_info=user_info, validity_date=pdf_validity, signature_id=doc_signature, orientation="L",
                           unit="mm", format="A4")
        pdf.add_page()
        pdf.draw_template_grid(header_info)
        pdf.draw_table(products_data, main_loss=int(pdf_loss), celkova_plocha=pdf_area, sys_type=pdf_sys_type,
                       pozn=pdf_pozn)

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