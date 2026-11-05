import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import re
import datetime
from db_manager import load_products, load_clients, get_db_connection
from helpers import show_pdf
from generate_hempel_pdf import get_hempel_pdfs


# --- CHYTRÝ PARSER HEMPEL KÓDŮ (V4) ---
def parse_hempel_code(pid):
    """Rozdělí produkty na Barvy, Tužidla a Ostatní, a přiřadí správné balení."""
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

    # --- FILTRY ---
    c1, c2 = st.columns(2)
    with c1:
        client_list = ["Všichni klienti"] + sorted(
            df_inv['client_name'].dropna().unique().tolist()) if not df_inv.empty else ["Všichni klienti"]
        selected_client = st.selectbox("1. Výběr klienta:", client_list)
    with c2:
        prod_list = ["Všechny produkty"] + sorted(df_inv['base_code'].unique().tolist()) if not df_inv.empty else [
            "Všechny produkty"]
        selected_product = st.selectbox("2. Produkt (Základ / Tužidlo / Ostatní):", prod_list)

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

            # 20L a 5L prioritně nahoře
            if "20 L (Sada/Balení)" in raw_packs:
                pack_opts.append("20 L (Sada/Balení)")
                raw_packs.remove("20 L (Sada/Balení)")
            if "5 L (Sada/Balení)" in raw_packs:
                pack_opts.append("5 L (Sada/Balení)")
                raw_packs.remove("5 L (Sada/Balení)")

            pack_opts.extend(raw_packs)
        else:
            pack_opts = ["Všechna balení"]

        selected_pack = st.selectbox("3. Velikost balení:", pack_opts)

    with c4:
        if product_category == "Barva (Hempel)" or selected_product == "Všechny produkty":
            shade_opts = ["Všechny odstíny (Čistý základ)"] + sorted(df_prod['shade_name'].unique().tolist())
            selected_shade = st.selectbox("4. Odstín:", shade_opts)
        else:
            selected_shade = "Všechny odstíny (Čistý základ)"
            st.selectbox("4. Odstín:", [selected_shade], disabled=True)

    with c5:
        if product_category == "Barva (Hempel)":
            tinting_cost = st.number_input("5. Cena tónování (Kč/l)", value=0.0, step=5.0,
                                           help="Odpočet z konečné ceny.")
        else:
            tinting_cost = 0.0

    st.markdown("---")

    # Aplikace filtrů pro analýzu
    df_filtered = df_prod.copy()
    if selected_client != "Všichni klienti":
        df_filtered = df_filtered[df_filtered['client_name'] == selected_client]
    if selected_pack != "Všechna balení":
        df_filtered = df_filtered[df_filtered['pack_size'] == selected_pack]

    is_base_view = (selected_shade == "Všechny odstíny (Čistý základ)")
    if not is_base_view:
        df_filtered = df_filtered[df_filtered['shade_name'] == selected_shade]

    if product_category == "Barva (Hempel)":
        df_filtered['base_price'] = df_filtered['price'] - tinting_cost
    else:
        df_filtered['base_price'] = df_filtered['price']

    target_col = 'base_price' if is_base_view else 'price'

    # 1. EXPANDER: Měsíční odběry (Timeseries)
    with st.expander("📈 Měsíční odběry klienta (Obrat v Kč)", expanded=False):
        if df_filtered.empty:
            st.info("Pro tento výběr nejsou k dispozici žádná data o obratech.")
        else:
            df_ts = df_filtered.copy()
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

            title_text = f"Vývoj odběrů: {selected_client}" if selected_client != "Všichni klienti" else "Celofiremní obrat (filtrovaný)"
            fig_sales.update_layout(
                title=title_text,
                height=350,
                margin=dict(l=20, r=20, t=40, b=20),
                yaxis_title="Obrat (Kč)"
            )
            st.plotly_chart(fig_sales, use_container_width=True)

    # 2. EXPANDER: Tempomat (pouze pro konkrétní produkt)
    with st.expander("🎯 Vývoj ceny a Tempomat", expanded=False):
        if selected_product == "Všechny produkty":
            st.warning("⚠️ Vyberte konkrétní produkt v kroku 2 pro zobrazení cenového tempomatu a doporučených marží.")
        elif df_filtered.empty:
            st.info("Pro tento výběr nemáme k dispozici cenová data.")
        else:
            global_min = df_filtered[target_col].min()
            global_avg = df_filtered[target_col].mean()
            global_max = df_filtered[target_col].max()

            # Nákladová cena z DB
            p_storage = 0.0
            if not df_products.empty:
                matches = df_products[df_products['name'].str.contains(selected_product.split()[0], na=False)]
                if not matches.empty:
                    p_storage = float(matches.iloc[0]['storage_price'])
            if p_storage == 0:
                p_storage = global_min * 0.75

            client_price = None
            if selected_client != "Všichni klienti":
                df_client_only = df_filtered[df_filtered['client_name'] == selected_client].sort_values(
                    by='purchase_date', ascending=False)
                if not df_client_only.empty:
                    client_price = df_client_only.iloc[0][target_col]

            gauge_val = client_price if client_price else global_avg
            p_retail = p_storage * 2.2
            min_range = max(global_min, p_storage * 1.15)
            max_range = max(global_avg * 1.1, min_range * 1.2)

            chart_title = f"{selected_product} {'(Čistý základ)' if is_base_view and product_category == 'Barva (Hempel)' else selected_shade}"

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

    # 3. EXPANDER: Historická tabulka
    with st.expander("📋 Historický výpis prodejů pro daný výběr", expanded=False):
        if df_filtered.empty:
            st.info("Pro zadané filtry nebyly nalezeny žádné faktury.")
        else:
            df_disp = df_filtered[
                ['purchase_date', 'client_name', 'base_code', 'shade_name', 'pack_size', 'quantity', 'price',
                 'base_price']].copy()
            df_disp['purchase_date'] = df_disp['purchase_date'].dt.strftime('%d. %m. %Y')

            price_col_name = 'Očištěný základ / Kč' if product_category == "Barva (Hempel)" else 'Konečná cena / Kč'

            df_disp.rename(columns={
                'purchase_date': 'Datum',
                'client_name': 'Klient',
                'base_code': 'Produkt',
                'shade_name': 'Odstín',
                'pack_size': 'Balení',
                'quantity': 'Množství (l/kg)',
                'price': 'Fakturová cena / Kč',
                'base_price': price_col_name
            }, inplace=True)

            df_disp['Fakturová cena / Kč'] = df_disp['Fakturová cena / Kč'].apply(lambda x: f"{x:,.1f}")
            df_disp[price_col_name] = df_disp[price_col_name].apply(lambda x: f"{x:,.1f}")

            # Pokud máme vybrán konkrétní produkt, skryjeme jeho sloupec v tabulce pro čistší zobrazení
            if selected_product != "Všechny produkty":
                df_disp.drop(columns=['Produkt'], inplace=True)

            st.dataframe(df_disp.sort_values(by='Datum', ascending=False), hide_index=True, use_container_width=True)

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