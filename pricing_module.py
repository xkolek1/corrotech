import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import re
from db_manager import load_products, load_clients, get_db_connection
from helpers import show_pdf
from generate_hempel_pdf import get_hempel_pdfs


# --- CHYTRÝ PARSER HEMPEL KÓDŮ (V4 - Striktní filtrace kategorií) ---
def parse_hempel_code(pid):
    """Rozdělí produkty na Barvy, Tužidla a Ostatní, a přiřadí správné balení."""
    pid = str(pid).strip()

    # 1. Non-Hempel nebo zmetky (Spreje, Sigma, PM položky atd.)
    if len(pid) < 10 or not pid[0].isdigit():
        return pid, "Jiné/Ostatní", "Bez odstínu", "Jiné/Ostatní balení"

    raw_base = pid[:5]

    if not raw_base.isdigit():
        return pid, "Jiné/Ostatní", "Bez odstínu", "Jiné/Ostatní balení"

    # 2. Tužidla a Ředidla (Zde nás tónování vůbec nezajímá)
    if raw_base.startswith(('08', '95', '97', '98')):
        category = "Tužidlo/Ředidlo"
        clean_base = f"{raw_base} (Tuž/Řed)"
        clean_shade = "Bez odstínu"
    # 3. Standardní Hempel Barvy
    else:
        category = "Barva (Hempel)"
        # Sloučení tónovaných bází (9) s čistými (0)
        clean_base = raw_base[:-1] + '0' if raw_base.endswith('9') else raw_base
        raw_shade = pid[5:10]

        if raw_shade == "00000":
            clean_shade = "Tovární základ"
        elif raw_shade.startswith('R'):
            clean_shade = f"RAL {raw_shade[1:]}"
        else:
            clean_shade = f"Tovární standard {raw_shade}"

    # 4. Seskupování do logických SETŮ
    suffix = pid[10:]
    clean_suffix = suffix.replace(',', '.')
    # Hledáme objem před posledním číslem revize (např. 17.5 z 017.5.40)
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

    # Přidělení do obchodního setu
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
    """Rychlé načtení z DB."""
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

    st.subheader("Cenový analytik")

    # --- FILTRY ---
    c1, c2 = st.columns(2)
    with c1:
        client_list = ["Všichni klienti"] + sorted(
            df_inv['client_name'].dropna().unique().tolist()) if not df_inv.empty else ["Všichni klienti"]
        selected_client = st.selectbox("1. Výběr klienta:", client_list)
    with c2:
        prod_list = sorted(df_inv['base_code'].unique().tolist()) if not df_inv.empty else ["Žádná data"]
        selected_product = st.selectbox("2. Produkt (Základ / Tužidlo / Ostatní):", prod_list)

    st.markdown("---")

    # Zjistíme kategorii vybraného produktu
    df_prod = df_inv[df_inv['base_code'] == selected_product].copy() if not df_inv.empty else pd.DataFrame()
    product_category = df_prod['category'].iloc[0] if not df_prod.empty else "Jiné/Ostatní"

    # Vykreslíme dynamické filtry podle kategorie
    c3, c4, c5 = st.columns(3)

    with c3:
        # Nabídka balení je VŽDY vázaná čistě na tento konkrétní produkt
        if not df_prod.empty:
            pack_opts = ["Všechna balení"] + sorted(df_prod['pack_size'].unique().tolist(), reverse=True)
        else:
            pack_opts = ["Všechna balení"]
        selected_pack = st.selectbox("3. Velikost balení:", pack_opts)

    with c4:
        if product_category == "Barva (Hempel)":
            shade_opts = ["Všechny odstíny (Čistý základ)"] + sorted(df_prod['shade_name'].unique().tolist())
            selected_shade = st.selectbox("4. Odstín:", shade_opts)
        else:
            st.info("Odstín se u tohoto typu produktu neřeší.")
            selected_shade = "Všechny odstíny (Čistý základ)"

    with c5:
        if product_category == "Barva (Hempel)":
            tinting_cost = st.number_input("5. Cena tónování (Kč/l)", value=0.0, step=5.0,
                                           help="Odpočet z konečné ceny.")
        else:
            tinting_cost = 0.0

    st.markdown("---")

    # --- ANALÝZA A VÝPOČET ---
    p_storage = 0.0
    if not df_products.empty and selected_product != "Žádná data":
        matches = df_products[df_products['name'].str.contains(selected_product.split()[0], na=False)]
        if not matches.empty:
            p_storage = float(matches.iloc[0]['storage_price'])

    if df_prod.empty:
        st.warning("Pro tento produkt nemáme historická data.")
    else:
        if selected_pack != "Všechna balení":
            df_prod = df_prod[df_prod['pack_size'] == selected_pack]

        if df_prod.empty:
            st.warning(f"V balení '{selected_pack}' se tento produkt historicky neprodal.")
        else:
            # Uplatníme tónování pouze pokud je to Hempel barva a díváme se na agregovaný základ
            if product_category == "Barva (Hempel)":
                df_prod['base_price'] = df_prod['price'] - tinting_cost
            else:
                df_prod['base_price'] = df_prod['price']  # U tužidel nic neodečítáme

            is_base_view = (selected_shade == "Všechny odstíny (Čistý základ)")

            if is_base_view:
                df_view = df_prod
                target_col = 'base_price'
                title_suffix = "(Čistý základ)" if product_category == "Barva (Hempel)" else "(Konečná cena)"
                chart_title = f"{selected_product} {title_suffix} - {selected_pack}"
            else:
                df_view = df_prod[df_prod['shade_name'] == selected_shade]
                target_col = 'price'
                chart_title = f"{selected_product} {selected_shade} - {selected_pack}"

            if df_view.empty:
                st.info(f"Kombinaci {selected_shade} v balení {selected_pack} jsme ještě neprodali.")
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

                # --- GRAF ---
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
                        f"Nákup klienta ({client_date})",
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

                    price_col_name = 'Očištěný základ' if product_category == "Barva (Hempel)" else 'Konečná cena'

                    df_disp.rename(columns={
                        'purchase_date': 'Datum',
                        'client_name': 'Klient',
                        'shade_name': 'Odstín',
                        'pack_size': 'Set',
                        'quantity': 'Množství (l/kg)',
                        'price': 'Fakturovaná cena',
                        'base_price': price_col_name
                    }, inplace=True)

                    df_disp['Fakturovaná cena'] = df_disp['Fakturovaná cena'].apply(lambda x: f"{x:,.1f} Kč")
                    df_disp[price_col_name] = df_disp[price_col_name].apply(lambda x: f"{x:,.1f} Kč")

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