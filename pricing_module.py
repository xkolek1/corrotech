import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import re
from db_manager import load_products, load_clients, get_db_connection
from helpers import show_pdf
from generate_hempel_pdf import get_hempel_pdfs


# --- CHYTRÝ PARSER HEMPEL KÓDŮ (V4) ---
def parse_hempel_code(pid):
    pid = str(pid).strip()
    if len(pid) < 10 or not pid[0].isdigit():
        return pid, "Jiné/Ostatní", "Bez odstínu", "Jiné/Ostatní balení"

    raw_base = pid[:5]
    if not raw_base.isdigit():
        return pid, "Jiné/Ostatní", "Bez odstínu", "Jiné/Ostatní balení"

    if raw_base.startswith(('08', '95', '97', '98')):
        category = "Tužidlo/Ředidlo"
        clean_base = f"{raw_base} (Tuž/Řed)"
        clean_shade = "Bez odstínu"
    else:
        category = "Barva (Hempel)"
        clean_base = raw_base[:-1] + '0' if raw_base.endswith('9') else raw_base
        raw_shade = pid[5:10]

        if raw_shade == "00000":
            clean_shade = "Tovární základ"
        elif raw_shade.startswith('R'):
            clean_shade = f"RAL {raw_shade[1:]}"
        else:
            clean_shade = f"Tovární standard {raw_shade}"

    suffix = pid[10:]
    clean_suffix = suffix.replace(',', '.')
    match = re.search(r'0*([0-9]+\.?[0-9]*)\.[0-9]{2}$', clean_suffix)
    vol = 0.0
    if match:
        vol = float(match.group(1))
    else:
        parts = clean_suffix.split('.')
        try:
            vol = float('.'.join(parts[:-1])) if len(parts) > 1 else float(parts[0])
        except:
            pass

    if vol > 0:
        if 13.0 <= vol <= 20.0:
            pack = "20 L (Sada/Balení)"
        elif 3.5 <= vol <= 6.0:
            pack = "5 L (Sada/Balení)"
        elif 8.0 <= vol <= 10.0:
            pack = "10 L (Sada/Balení)"
        elif vol < 3.5:
            pack = f"Malé balení ({vol} L)"
        else:
            pack = f"Nestandardní balení ({vol} L)"
    else:
        pack = "Neznámé balení"

    return clean_base, category, clean_shade, pack


@st.cache_data(ttl=300)
def load_and_parse_invoices():
    try:
        db_conn = get_db_connection()
        query = "SELECT client_ic, product_id, purchase_date, quantity, price FROM invoices"
        df = pd.read_sql_query(query, db_conn)
        if not df.empty:
            df['purchase_date'] = pd.to_datetime(df['purchase_date'])
            df[['base_code', 'category', 'shade_name', 'pack_size']] = df.apply(
                lambda row: pd.Series(parse_hempel_code(row['product_id'])), axis=1
            )
        return df
    except Exception as e:
        st.error(f"Nepodařilo se načíst faktury z databáze: {e}")
        return pd.DataFrame()


def render_calculations():
    st.title("Výpočty, Kalkulátor a Ceníky")

    df_products = load_products()
    df_clients = load_clients()
    df_inv = load_and_parse_invoices()

    if not df_inv.empty:
        if 'ic' in df_clients.columns and 'name' in df_clients.columns:
            df_inv = df_inv.merge(df_clients[['ic', 'name']], left_on='client_ic', right_on='ic', how='left')
            df_inv['client_name'] = df_inv['name'].fillna(df_inv['client_ic'].astype(str))
        else:
            df_inv['client_name'] = df_inv['client_ic'].astype(str)
    else:
        df_inv = pd.DataFrame(
            columns=['client_ic', 'product_id', 'purchase_date', 'quantity', 'price', 'base_code', 'category',
                     'shade_name', 'pack_size', 'client_name'])

    st.subheader("B2B Cenový Analytik")

    # =========================================================
    # 1. FILTRY (Výchozí = Všechno)
    # =========================================================
    c1, c2 = st.columns(2)
    with c1:
        client_list = ["Všichni klienti"] + sorted(
            df_inv['client_name'].dropna().unique().tolist()) if not df_inv.empty else ["Všichni klienti"]
        selected_client = st.selectbox("1. Výběr klienta:", client_list)
    with c2:
        prod_list = ["Všechny produkty"] + sorted(df_inv['base_code'].unique().tolist()) if not df_inv.empty else [
            "Všechny produkty"]
        selected_product = st.selectbox("2. Produkt (Základ / Tužidlo):", prod_list)

    df_prod = df_inv.copy()
    if selected_product != "Všechny produkty":
        df_prod = df_inv[df_inv['base_code'] == selected_product].copy()

    product_category = df_prod['category'].iloc[0] if (
                not df_prod.empty and selected_product != "Všechny produkty") else "Smíšené"

    c3, c4, c5 = st.columns(3)

    with c3:
        if not df_prod.empty:
            raw_packs = sorted(df_prod['pack_size'].unique().tolist())
            pack_opts = ["Všechna balení"]

            # Priorita pro 20L a 5L
            for priority_pack in ["20 L (Sada/Balení)", "5 L (Sada/Balení)"]:
                if priority_pack in raw_packs:
                    pack_opts.append(priority_pack)
                    raw_packs.remove(priority_pack)
            pack_opts.extend(raw_packs)
        else:
            pack_opts = ["Všechna balení"]

        selected_pack = st.selectbox("3. Velikost balení:", pack_opts)

    with c4:
        if product_category == "Barva (Hempel)" or selected_product == "Všechny produkty":
            shade_opts = ["Všechny odstíny"] + sorted(df_prod['shade_name'].unique().tolist())
            selected_shade = st.selectbox("4. Odstín:", shade_opts)
        else:
            selected_shade = "Všechny odstíny"
            st.selectbox("4. Odstín:", [selected_shade], disabled=True)

    with c5:
        if product_category == "Barva (Hempel)":
            tinting_cost = st.number_input("5. Cena tónování (Kč/l)", value=0.0, step=5.0,
                                           help="Odpočet z konečné ceny.")
        else:
            tinting_cost = 0.0

    st.markdown("---")

    # =========================================================
    # 2. TEMPOMAT (Zobrazí se POUZE když je vybrán produkt)
    # =========================================================
    if selected_product == "Všechny produkty":
        st.info("ℹ️ Vyberte konkrétní produkt v rolovátku č. 2 pro zobrazení analytického tempomatu a výpočtu cen.")
    else:
        # Pro tempomat aplikujeme plnou kaskádu filtrů (potřebujeme konkrétní agregovanou cenu)
        df_tempomat = df_prod.copy()
        if selected_pack != "Všechna balení":
            df_tempomat = df_tempomat[df_tempomat['pack_size'] == selected_pack]
        if selected_shade != "Všechny odstíny":
            df_tempomat = df_tempomat[df_tempomat['shade_name'] == selected_shade]

        if product_category == "Barva (Hempel)":
            df_tempomat['base_price'] = df_tempomat['price'] - tinting_cost
        else:
            df_tempomat['base_price'] = df_tempomat['price']

        target_col = 'base_price' if selected_shade == "Všechny odstíny" else 'price'

        if df_tempomat.empty:
            st.warning("Pro zadanou kombinaci produktu, odstínu a balení nemáme historická data.")
        else:
            global_min = df_tempomat[target_col].min()
            global_avg = df_tempomat[target_col].mean()
            global_max = df_tempomat[target_col].max()

            p_storage = 0.0
            if not df_products.empty:
                matches = df_products[df_products['name'].str.contains(selected_product.split()[0], na=False)]
                if not matches.empty:
                    p_storage = float(matches.iloc[0]['storage_price'])
            if p_storage == 0:
                p_storage = global_min * 0.75

            client_price = None
            if selected_client != "Všichni klienti":
                df_client_only = df_tempomat[df_tempomat['client_name'] == selected_client].sort_values(
                    by='purchase_date', ascending=False)
                if not df_client_only.empty:
                    client_price = df_client_only.iloc[0][target_col]

            gauge_val = client_price if client_price else global_avg
            p_retail = p_storage * 2.2
            min_range = max(global_min, p_storage * 1.15)
            max_range = max(global_avg * 1.1, min_range * 1.2)

            chart_title = f"{selected_product} {'(Čistý základ)' if selected_shade == 'Všechny odstíny' and product_category == 'Barva (Hempel)' else selected_shade}"
            if selected_pack != "Všechna balení":
                chart_title += f" [{selected_pack}]"

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
                    'threshold': {'line': {'color': "black", 'width': 5}, 'thickness': 0.75, 'value': gauge_val}
                }
            ))
            g_fig.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(g_fig, use_container_width=True)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Odhadovaný Náklad", f"{p_storage:,.0f} Kč".replace(",", " "))
            if selected_client != "Všichni klienti":
                diff = client_price - global_avg if client_price else 0
                m2.metric("Poslední nákup klienta",
                          f"{client_price:,.0f} Kč".replace(",", " ") if client_price else "---",
                          f"{diff:+,.0f} Kč vs Průměr".replace(",", " "), delta_color="inverse")
            else:
                m2.metric("Tržní MAXIMUM", f"{global_max:,.0f} Kč".replace(",", " "))
            m3.metric("Tržní PRŮMĚR", f"{global_avg:,.0f} Kč".replace(",", " "))
            m4.metric("Historické DNO", f"{global_min:,.0f} Kč".replace(",", " "), "Pod toto nedávat!",
                      delta_color="inverse")

    st.markdown("---")

    # =========================================================
    # 3. HISTORICKÉ VÝPISY A GRAFY (Roletky)
    # =========================================================

    # Pomocná funkce pro podbarvení řádků v tabulkách na základě vybrané velikosti/odstínu
    def highlight_rows(row):
        shade_match = (selected_shade != "Všechny odstíny") and (row['Odstín'] == selected_shade)
        pack_match = (selected_pack != "Všechna balení") and (row['Balení'] == selected_pack)

        if shade_match and pack_match:
            return ['background-color: rgba(46, 204, 113, 0.3)'] * len(row)  # Obě shody = tmavší zelená
        elif shade_match or pack_match:
            return ['background-color: rgba(46, 204, 113, 0.1)'] * len(row)  # Jedna shoda = velmi světlá zelená
        return [''] * len(row)

    def prepare_dataframe_for_display(df):
        df_disp = df[
            ['purchase_date', 'client_name', 'base_code', 'shade_name', 'pack_size', 'quantity', 'price']].copy()
        df_disp['purchase_date'] = df_disp['purchase_date'].dt.strftime('%d. %m. %Y')
        df_disp.rename(columns={
            'purchase_date': 'Datum',
            'client_name': 'Klient',
            'base_code': 'Produkt',
            'shade_name': 'Odstín',
            'pack_size': 'Balení',
            'quantity': 'Množ. (l/kg)',
            'price': 'Cena/l'
        }, inplace=True)
        df_disp['Cena/l'] = df_disp['Cena/l'].apply(lambda x: f"{x:,.1f}")
        if selected_product != "Všechny produkty":
            df_disp.drop(columns=['Produkt'], inplace=True, errors='ignore')
        return df_disp

    # A. Historie trhu (Vždy dostupná)
    # Tabulka se filtruje JEN podle produktu, max 100 řádků. Odstín a velikost jen zvýrazňují.
    exp1_title = f"📋 Posledních 100 prodejů ({selected_product if selected_product != 'Všechny produkty' else 'Celý trh'})"
    with st.expander(exp1_title, expanded=False):
        df_market = df_prod.sort_values(by='purchase_date', ascending=False).head(100)
        if df_market.empty:
            st.info("Žádná historická data.")
        else:
            df_market_disp = prepare_dataframe_for_display(df_market)
            st.dataframe(df_market_disp.style.apply(highlight_rows, axis=1), hide_index=True, use_container_width=True)

    # B + C. Klientské moduly (Odemknou se až po výběru klienta)
    if selected_client != "Všichni klienti":

        # B. Historie klienta
        exp2_title = f"📋 Posledních 100 nákupů firmy: {selected_client} ({selected_product if selected_product != 'Všechny produkty' else 'Všechny produkty'})"
        with st.expander(exp2_title, expanded=False):
            df_client_hist = df_prod[df_prod['client_name'] == selected_client].sort_values(by='purchase_date',
                                                                                            ascending=False).head(100)
            if df_client_hist.empty:
                st.info("Klient tento produkt historicky nekoupil.")
            else:
                df_client_disp = prepare_dataframe_for_display(df_client_hist)
                # Zde skryjeme i sloupec Klient, protože se díváme jen na něj
                df_client_disp.drop(columns=['Klient'], inplace=True, errors='ignore')
                st.dataframe(df_client_disp.style.apply(highlight_rows, axis=1), hide_index=True,
                             use_container_width=True)

        # C. Vývoj obratu (Od Října 2021 do současnosti)
        with st.expander(f"📈 Vývoj celkového obratu: {selected_client} (Od Října 2021)", expanded=False):
            # Pro obrat bereme VŽDY všechny produkty klienta, bez ohledu na výběr produktu výše
            df_ts = df_inv[
                (df_inv['client_name'] == selected_client) & (df_inv['purchase_date'] >= '2021-10-01')].copy()
            if df_ts.empty:
                st.info("Pro tohoto klienta nejsou od října 2021 žádná data o obratech.")
            else:
                df_ts['turnover'] = df_ts['price'] * df_ts['quantity']
                df_ts['month_start'] = df_ts['purchase_date'].dt.to_period('M').dt.to_timestamp()

                monthly_sales = df_ts.groupby('month_start')['turnover'].sum().reset_index()

                cz_months = {1: 'Led', 2: 'Úno', 3: 'Bře', 4: 'Dub', 5: 'Kvě', 6: 'Čvn', 7: 'Čvc', 8: 'Srp', 9: 'Zář',
                             10: 'Říj', 11: 'Lis', 12: 'Pro'}
                monthly_sales['cz_month'] = monthly_sales['month_start'].dt.month.map(cz_months)
                monthly_sales['year'] = monthly_sales['month_start'].dt.year.astype(str)

                fig_sales = go.Figure(go.Bar(
                    x=[monthly_sales['year'], monthly_sales['cz_month']],
                    y=monthly_sales['turnover'],
                    text=monthly_sales['turnover'].apply(lambda x: f"{x:,.0f} Kč".replace(",", " ") if x > 0 else ""),
                    textposition='auto',
                    marker_color='#1f77b4'
                ))

                fig_sales.update_layout(
                    title=f"Měsíční obrat klienta: {selected_client}",
                    height=350,
                    margin=dict(l=20, r=20, t=40, b=20),
                    yaxis_title="Obrat (Kč)"
                )
                st.plotly_chart(fig_sales, use_container_width=True)

    st.markdown("---")

    # =========================================================
    # 4. GENERÁTOR PDF CENÍKU
    # =========================================================
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