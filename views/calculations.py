import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db_manager import load_products, load_clients, get_db_connection
from helpers import show_pdf
from generate_hempel_pdf import get_hempel_pdfs


# --- CHYTRÝ PARSER HEMPEL KÓDŮ ---
def parse_hempel_code(product_id):
    """Rozseká Hempel kód na základ (produkt) a odstín."""
    pid = str(product_id).strip()
    if len(pid) < 10:
        return "Neznámý produkt", "Neznámý odstín"

    raw_base = pid[:5]
    raw_shade = pid[5:10]

    if raw_base.endswith('9'):
        clean_base = raw_base[:-1] + '0'
    else:
        clean_base = raw_base

    if raw_shade == "00000":
        clean_shade = "Bez odstínu (Báze/Tuž/Řed)"
    elif raw_shade.startswith('R'):
        clean_shade = f"RAL {raw_shade[1:]}"
    else:
        clean_shade = f"Standard {raw_shade}"

    return clean_base, clean_shade


@st.cache_data(ttl=300)
def load_invoices_data():
    """Načte data faktur z DB."""
    try:
        db_conn = get_db_connection()
        query = "SELECT client_ic, product_id, purchase_date, quantity, price FROM invoices"
        df = pd.read_sql_query(query, db_conn)
        if not df.empty:
            df['purchase_date'] = pd.to_datetime(df['purchase_date'])
        return df
    except Exception as e:
        st.error(f"Nepodařilo se načíst faktury z databáze: {e}")
        return pd.DataFrame()


def render_calculations():
    st.title("Výpočty, Kalkulátor a Ceníky")

    # Načtení dat
    df_products = load_products()
    df_clients = load_clients()
    df_inv = load_invoices_data()

    # Předzpracování faktur s pojistkou proti prázdné databázi
    if not df_inv.empty:
        df_inv[['base_code', 'shade_name']] = df_inv.apply(
            lambda row: pd.Series(parse_hempel_code(row['product_id'])), axis=1
        )
        if 'ic' in df_clients.columns and 'name' in df_clients.columns:
            df_inv = df_inv.merge(df_clients[['ic', 'name']], left_on='client_ic', right_on='ic', how='left')
            df_inv['client_name'] = df_inv['name'].fillna(df_inv['client_ic'].astype(str))
        else:
            df_inv['client_name'] = df_inv['client_ic'].astype(str)
    else:
        # Vytvoření prázdné struktury, aby UI nespadlo na KeyError
        df_inv = pd.DataFrame(
            columns=['client_ic', 'product_id', 'purchase_date', 'quantity', 'price', 'base_code', 'shade_name',
                     'client_name'])

    st.subheader("Cenový analytik")
    st.markdown("Historické ceny z faktur očištěné o náklady na tónování.")

    # --- FILTRY ---
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    with c1:
        client_list = ["Všichni klienti"] + sorted(
            df_inv['client_name'].dropna().unique().tolist()) if not df_inv.empty else ["Všichni klienti"]
        selected_client = st.selectbox("1. Výběr klienta:", client_list)
    with c2:
        if not df_inv.empty:
            prod_list = sorted(
                df_inv[~df_inv['base_code'].str.startswith(('08', '95', '97', '98'))]['base_code'].unique().tolist())
        else:
            prod_list = ["Žádná data"]
        selected_product = st.selectbox("2. Produkt (Základ):", prod_list)
    with c3:
        if not df_inv.empty and selected_product != "Žádná data":
            shade_opts = ["Všechny odstíny (Čistý základ)"] + sorted(
                df_inv[df_inv['base_code'] == selected_product]['shade_name'].unique().tolist())
        else:
            shade_opts = ["Všechny odstíny (Čistý základ)"]
        selected_shade = st.selectbox("3. Odstín (volitelně):", shade_opts)
    with c4:
        tinting_cost = st.number_input("Cena tónování (Kč)", value=0.0, step=5.0,
                                       help="Odečítá se od celkové ceny pro výpočet ceny čisté báze.")

    st.markdown("---")

    # --- ANALÝZA A VÝPOČET ---
    df_prod = df_inv[df_inv['base_code'] == selected_product].copy() if not df_inv.empty else pd.DataFrame()

    # Získání storage price (Nákladu) z databáze produktů (odhad přes shodu v názvu)
    p_storage = 0.0
    if not df_products.empty and selected_product != "Žádná data":
        matches = df_products[df_products['name'].str.contains(selected_product, na=False)]
        if not matches.empty:
            p_storage = float(matches.iloc[0]['storage_price'])

    if df_prod.empty:
        st.warning("Pro tento produkt nemáme historická data.")
    else:
        # Výpočet čisté základní ceny odpočtem tónování
        df_prod['base_price'] = df_prod['price'] - tinting_cost

        is_base_view = (selected_shade == "Všechny odstíny (Čistý základ)")

        if is_base_view:
            df_view = df_prod
            target_col = 'base_price'
            chart_title = f"{selected_product} (Čistý základ očištěný o tónování)"
        else:
            df_view = df_prod[df_prod['shade_name'] == selected_shade]
            target_col = 'price'  # U konkrétního odstínu analyzujeme konečnou cenu vč. tónování
            chart_title = f"{selected_product} v odstínu {selected_shade} (Konečná cena)"

        if df_view.empty:
            st.info(f"Odstín {selected_shade} jsme v historii ještě neprodali.")
        else:
            global_min = df_view[target_col].min()
            global_avg = df_view[target_col].mean()
            global_max = df_view[target_col].max()

            # Klientské statistiky
            client_price = None
            client_date = "N/A"
            if selected_client != "Všichni klienti":
                df_client = df_view[df_view['client_name'] == selected_client].sort_values(by='purchase_date',
                                                                                           ascending=False)
                if not df_client.empty:
                    client_price = df_client.iloc[0][target_col]
                    client_date = df_client.iloc[0]['purchase_date'].strftime('%d. %m. %Y')

            # Nastavení limitů pro budíky (pokud nemáme storage price v db, odhadneme ho)
            if p_storage == 0:
                p_storage = global_min * 0.75

            p_retail = p_storage * 2
            gauge_val = client_price if client_price else global_avg

            # Zelená (bezpečná) vyjednávací zóna
            min_range = max(global_min, p_storage * 1.15)
            max_range = max(global_avg * 1.1, min_range * 1.2)

            # --- VYKRESLENÍ GRAFU ---
            g_fig = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=gauge_val,
                number={'suffix': " Kč", 'valueformat': ",.0f"},
                title={'text': chart_title, 'font': {'size': 20}},
                delta={'reference': global_avg, 'increasing': {'color': "green"}, 'decreasing': {'color': "red"}},
                gauge={
                    'axis': {'range': [p_storage, p_retail], 'tickwidth': 1, 'tickcolor': "darkblue"},
                    'bar': {'color': "rgba(0,0,0,0)"},
                    'bgcolor': "white",
                    'borderwidth': 2,
                    'bordercolor': "gray",
                    'steps': [
                        {'range': [p_storage, min_range], 'color': "rgba(255, 99, 132, 0.4)"},
                        {'range': [min_range, max_range], 'color': "rgba(75, 192, 192, 0.5)"},
                        {'range': [max_range, p_retail], 'color': "rgba(54, 162, 235, 0.4)"}
                    ],
                    'threshold': {
                        'line': {'color': "black", 'width': 5},
                        'thickness': 0.75,
                        'value': gauge_val
                    }
                }
            ))
            g_fig.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(g_fig, use_container_width=True)

            # --- METRIKY ---
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Nákladová cena (Storage)", f"{p_storage:,.0f} Kč".replace(",", " "))

            if selected_client != "Všichni klienti":
                diff = client_price - global_avg if client_price else 0
                m2.metric(
                    f"Poslední nákup: {selected_client[:12]}...",
                    f"{client_price:,.0f} Kč".replace(",", " ") if client_price else "---",
                    f"{diff:+,.0f} Kč vs Průměr".replace(",", " "),
                    delta_color="inverse"
                )
            else:
                m2.metric("Tržní MAXIMUM", f"{global_max:,.0f} Kč".replace(",", " "))

            m3.metric("Tržní PRŮMĚR", f"{global_avg:,.0f} Kč".replace(",", " "))
            m4.metric("Historické DNO", f"{global_min:,.0f} Kč".replace(",", " "), "Pod toto již nechodit!",
                      delta_color="inverse")

            # --- DETAILNÍ HISTORICKÁ TABULKA ---
            with st.expander(f"Zobrazit kompletní historii prodejů ({len(df_view)} záznamů)"):
                df_disp = df_view[
                    ['purchase_date', 'client_name', 'shade_name', 'quantity', 'price', 'base_price']].copy()
                df_disp['purchase_date'] = df_disp['purchase_date'].dt.strftime('%d. %m. %Y')
                df_disp.rename(columns={
                    'purchase_date': 'Datum',
                    'client_name': 'Klient',
                    'shade_name': 'Odstín',
                    'quantity': 'Množství (l)',
                    'price': 'Konečná cena faktury (Kč)',
                    'base_price': 'Očištěná cena základu (Kč)'
                }, inplace=True)
                st.dataframe(df_disp.sort_values(by='Datum', ascending=False), hide_index=True,
                             use_container_width=True)

    st.markdown("---")

    # --- GENERÁTOR PDF CENÍKU ---
    st.subheader("Hempel – Barevný ceník RAL (PDF Generátor)")
    st.write("Vygeneruje se PDF s vypočtenými cenami pro jednotlivé odstíny RAL podle aktuálních matic.")

    pdf_type = st.radio("Formát ceníku:",
                        ["Digital (dlouhá obrazovka pro zaslání e-mailem)", "Print (A4 na šířku pro klasický tisk)"])

    if st.button("Vygenerovat ceník Hempel", type="primary", icon=":material/palette:"):
        with st.spinner("Generuji PDF soubory..."):
            try:
                pdfs = get_hempel_pdfs("hempel_export/hempel_colors.csv")

                if "Digital" in pdf_type:
                    st.session_state["hempel_pdf_bytes"] = pdfs["digital"]
                    st.session_state["hempel_pdf_name"] = "hempel_cenik_digital.pdf"
                else:
                    st.session_state["hempel_pdf_bytes"] = pdfs["print"]
                    st.session_state["hempel_pdf_name"] = "hempel_cenik_tisk.pdf"

            except Exception as e:
                st.error(f"Chyba při generování Hempel ceníku: {e}")

    if "hempel_pdf_bytes" in st.session_state:
        st.success("✅ Ceník Hempel byl úspěšně vygenerován!")
        show_pdf(
            pdf_binary=st.session_state["hempel_pdf_bytes"],
            filename=st.session_state["hempel_pdf_name"]
        )