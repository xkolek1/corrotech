import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import re
from db_manager import load_products, load_clients, get_db_connection
from helpers import show_pdf
from generate_hempel_pdf import get_hempel_pdfs


# --- CHYTRÝ PARSER HEMPEL KÓDŮ (UPRAVENO PRO SETY) ---
def parse_hempel_code(product_id):
    """Rozseká Hempel kód na základ (produkt), odstín a přeloží balení do ucelených SETů (5L, 20L)."""
    pid = str(product_id).strip()

    # 1. Filtrace ne-Hempel produktů (Spreje, Sigma, PM položky)
    if len(pid) < 10 or pid.startswith(('Sprej', 'PM', 'Sigma', 'CTPG', 'r7')):
        return "Jiný produkt", "Neznámý odstín", "Jiné/Neznámé"

    raw_base = pid[:5]
    raw_shade = pid[5:10]

    # Čištění báze (tónované s 9 na konci jdou na čisté 0)
    if raw_base.endswith('9'):
        clean_base = raw_base[:-1] + '0'
    else:
        clean_base = raw_base

    # Čištění odstínu
    if raw_shade == "00000":
        clean_shade = "Bez odstínu (Báze/Tuž/Řed)"
    elif raw_shade.startswith('R'):
        clean_shade = f"RAL {raw_shade[1:]}"
    else:
        clean_shade = f"Standard {raw_shade}"

    # --- LOGIKA PRO VELIKOSTI (KOMPLETNÍ SETY) ---
    suffix = pid[10:]
    clean_suffix = suffix.replace(',', '.')

    # Extrakce číselné hodnoty před posledním bodem (např. z 017.5.40 vyndá 17.5)
    match = re.search(r'0*([0-9]+\.?[0-9]*)\.[0-9]{2}$', clean_suffix)
    if match:
        vol = float(match.group(1))
    else:
        # Pokud se regex nechytne, zkusíme to rozsekat ručně
        parts = clean_suffix.split('.')
        try:
            vol = float('.'.join(parts[:-1])) if len(parts) > 1 else float(parts[0])
        except:
            vol = 0.0

    # PŘEVOD NA STANDARDNÍ OBCHODNÍ SETY (Báze + Tužidlo)
    if vol > 0:
        # Velké sety (okolo 20L)
        if 13.0 <= vol <= 20.0:
            clean_pack = "20 L (Set/Plechovka)"
        # Malé sety (okolo 5L)
        elif 3.5 <= vol <= 6.0:
            clean_pack = "5 L (Set/Plechovka)"
        # Speciální nebo jednosložkové obaly
        elif 8.0 <= vol <= 10.0:
            clean_pack = "10 L (Set/Plechovka)"
        elif vol < 3.5:
            # Většinou jde čistě o plechovky tužidel prodávané zvlášť
            clean_pack = "Tužidlo/Samostatné balení"
        else:
            clean_pack = f"{vol} L (Netypické balení)"
    else:
        clean_pack = "Jiné/Neznámé"

    return clean_base, clean_shade, clean_pack


@st.cache_data(ttl=300)
def load_and_parse_invoices():
    """Načte data z DB a rozparsuje kódy pouze JEDNOU za 5 minut."""
    try:
        db_conn = get_db_connection()
        query = "SELECT client_ic, product_id, purchase_date, quantity, price FROM invoices"
        df = pd.read_sql_query(query, db_conn)
        if not df.empty:
            df['purchase_date'] = pd.to_datetime(df['purchase_date'])
            # Aplikace parseru na celou tabulku (proběhne rychle v RAM)
            df[['base_code', 'shade_name', 'pack_size']] = df.apply(
                lambda row: pd.Series(parse_hempel_code(row['product_id'])), axis=1
            )
            # Vyhodíme věci, které náš parser označil jako "Jiný produkt" (Spreje apod.)
            df = df[df['base_code'] != "Jiný produkt"]
        return df
    except Exception as e:
        st.error(f"Nepodařilo se načíst faktury z databáze: {e}")
        return pd.DataFrame()


def render_calculations():
    st.title("Výpočty, Kalkulátor a Ceníky")

    # Načtení dat
    df_products = load_products()
    df_clients = load_clients()
    df_inv = load_and_parse_invoices()

    # Spojení faktur s klienty
    if not df_inv.empty:
        if 'ic' in df_clients.columns and 'name' in df_clients.columns:
            df_inv = df_inv.merge(df_clients[['ic', 'name']], left_on='client_ic', right_on='ic', how='left')
            df_inv['client_name'] = df_inv['name'].fillna(df_inv['client_ic'].astype(str))
        else:
            df_inv['client_name'] = df_inv['client_ic'].astype(str)
    else:
        df_inv = pd.DataFrame(
            columns=['client_ic', 'product_id', 'purchase_date', 'quantity', 'price', 'base_code', 'shade_name',
                     'pack_size', 'client_name'])

    st.subheader("Cenový analytik")
    st.markdown("Historické ceny z faktur očištěné o náklady na tónování.")

    # --- FILTRY ---
    c1, c2, c3 = st.columns(3)
    with c1:
        client_list = ["Všichni klienti"] + sorted(
            df_inv['client_name'].dropna().unique().tolist()) if not df_inv.empty else ["Všichni klienti"]
        selected_client = st.selectbox("1. Výběr klienta:", client_list)
    with c2:
        if not df_inv.empty:
            # Odstraníme tužidla a ředidla ze seznamu produktů
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

    c4, c5, c6 = st.columns([1, 1, 1])
    with c4:
        if not df_inv.empty and selected_product != "Žádná data":
            # Filtrujeme dostupné sety (většinou 20 L nebo 5 L) a zbavíme se podivností
            df_for_pack = df_inv[
                (df_inv['base_code'] == selected_product) & (~df_inv['pack_size'].str.contains('Tužidlo|Neznámé'))]
            pack_opts = sorted(df_for_pack['pack_size'].unique().tolist(), reverse=True)  # 20 L bude nahoře
            pack_opts = ["Všechna balení"] + pack_opts
        else:
            pack_opts = ["Všechna balení"]
        selected_pack = st.selectbox("4. Velikost balení:", pack_opts)

    with c5:
        tinting_cost = st.number_input("5. Cena tónování (Kč/l)", value=0.0, step=5.0,
                                       help="Odečítá se od celkové ceny pro výpočet ceny čisté báze.")

    st.markdown("---")

    # --- ANALÝZA A VÝPOČET ---
    df_prod = df_inv[df_inv['base_code'] == selected_product].copy() if not df_inv.empty else pd.DataFrame()

    p_storage = 0.0
    if not df_products.empty and selected_product != "Žádná data":
        matches = df_products[df_products['name'].str.contains(selected_product, na=False)]
        if not matches.empty:
            p_storage = float(matches.iloc[0]['storage_price'])

    if df_prod.empty:
        st.warning("Pro tento produkt nemáme historická data.")
    else:
        # Zohlednění filtru na balení
        if selected_pack != "Všechna balení":
            df_prod = df_prod[df_prod['pack_size'] == selected_pack]

        if df_prod.empty:
            st.warning(f"V balení '{selected_pack}' tento produkt v historii není.")
        else:
            df_prod['base_price'] = df_prod['price'] - tinting_cost
            is_base_view = (selected_shade == "Všechny odstíny (Čistý základ)")

            if is_base_view:
                df_view = df_prod
                target_col = 'base_price'
                chart_title = f"{selected_product} (Čistý základ) - {selected_pack}"
            else:
                df_view = df_prod[df_prod['shade_name'] == selected_shade]
                target_col = 'price'
                chart_title = f"{selected_product} {selected_shade} - {selected_pack}"

            if df_view.empty:
                st.info(f"Odstín {selected_shade} jsme v tomto balení ještě neprodali.")
            else:
                global_min = df_view[target_col].min()
                global_avg = df_view[target_col].mean()
                global_max = df_view[target_col].max()

                client_price = None
                client_date = "N/A"
                if selected_client != "Všichni klienti":
                    df_client = df_view[df_view['client_name'] == selected_client].sort_values(by='purchase_date',
                                                                                               ascending=False)
                    if not df_client.empty:
                        client_price = df_client.iloc[0][target_col]
                        client_date = df_client.iloc[0]['purchase_date'].strftime('%d. %m. %Y')

                if p_storage == 0:
                    p_storage = global_min * 0.75

                p_retail = p_storage * 2.2
                gauge_val = client_price if client_price else global_avg

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
                m1.metric("Odhadovaný Náklad", f"{p_storage:,.0f} Kč".replace(",", " "))

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
                m4.metric("Historické DNO", f"{global_min:,.0f} Kč".replace(",", " "), "Pod toto nedávat!",
                          delta_color="inverse")

                # --- DETAILNÍ TABULKA ---
                with st.expander(f"Zobrazit kompletní historii prodejů ({len(df_view)} záznamů)"):
                    df_disp = df_view[['purchase_date', 'client_name', 'shade_name', 'pack_size', 'quantity', 'price',
                                       'base_price']].copy()
                    df_disp['purchase_date'] = df_disp['purchase_date'].dt.strftime('%d. %m. %Y')
                    df_disp.rename(columns={
                        'purchase_date': 'Datum',
                        'client_name': 'Klient',
                        'shade_name': 'Odstín',
                        'pack_size': 'Set',
                        'quantity': 'Množství (l/kg)',
                        'price': 'Cena faktury',
                        'base_price': 'Očištěný základ'
                    }, inplace=True)

                    df_disp['Cena faktury'] = df_disp['Cena faktury'].apply(lambda x: f"{x:,.1f} Kč")
                    df_disp['Očištěný základ'] = df_disp['Očištěný základ'].apply(lambda x: f"{x:,.1f} Kč")

                    st.dataframe(df_disp.sort_values(by='Datum', ascending=False), hide_index=True,
                                 use_container_width=True)

    st.markdown("---")

    # --- GENERÁTOR PDF CENÍKU ---
    st.subheader("Hempel – Barevný ceník RAL")
    pdf_type = st.radio("Formát ceníku:", ["Digital (dlouhá obrazovka pro e-mail)", "Print (A4 na šířku pro tisk)"])

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