import streamlit as st
import pandas as pd
from db_manager import get_db_connection

# --- CHYTRÝ PARSER HEMPEL KÓDŮ ---
def parse_hempel_code(product_id):
    """
    Rozseká Hempel kód (např. 55619R5010017.5.40) na základ (produkt) a odstín (RAL/Standard).
    """
    pid = str(product_id).strip()
    
    # 1. Kontrola délky - Hempel kódy mají minimálně 10 znaků pro bázi a odstín
    if len(pid) < 10:
        return "Neznámý produkt", "Neznámý odstín"
        
    raw_base = pid[:5]
    raw_shade = pid[5:10]
    
    # 2. Čištění základu: Pokud končí 9 (tónovací báze), převedeme na 0 (čistý produkt)
    if raw_base.endswith('9'):
        clean_base = raw_base[:-1] + '0'
    else:
        clean_base = raw_base
        
    # Označení ředidel a tužidel
    if clean_base.startswith('08'):
        base_name = f"Ředidlo {clean_base}"
    elif clean_base.startswith('95') or clean_base.startswith('97') or clean_base.startswith('98'):
        base_name = f"Tužidlo {clean_base}"
    else:
        base_name = f"Produkt {clean_base}"
        
    # 3. Čištění odstínu
    if raw_shade == "00000":
        clean_shade = "Bez odstínu (Tužidla/Ředidla)"
    elif raw_shade.startswith('R'):
        clean_shade = f"RAL {raw_shade[1:]}"
    else:
        clean_shade = f"Standard {raw_shade}"
        
    return clean_base, clean_shade


# --- NAČTENÍ DAT ---
@st.cache_data(ttl=300)
def load_and_parse_invoices():
    """Načte data faktur z DB a rovnou je rozparsuje."""
    try:
        db_conn = get_db_connection()
        query = "SELECT client_ic, product_id, purchase_date, quantity, price FROM invoices"
        df = pd.read_sql_query(query, db_conn)
        
        if not df.empty:
            df['purchase_date'] = pd.to_datetime(df['purchase_date'])
            # Aplikace parseru
            df[['base_code', 'shade_name']] = df.apply(
                lambda row: pd.Series(parse_hempel_code(row['product_id'])), axis=1
            )
        return df
    except Exception as e:
        st.error(f"Chyba při načítání faktur z databáze: {e}")
        return pd.DataFrame()


# --- HLAVNÍ FUNKCE PRO ZOBRAZENÍ V APLIKACI ---
def render_pricing_analytics(df_clients):
    st.subheader("B2B Cenový analyzátor pro Hempel produkty")
    st.markdown("Zadejte klienta, produkt a konkrétní odstín (např. RAL 3000) pro zobrazení historických cen. Systém automaticky slučuje tónované báze (končící na 9) pod hlavní produkt (končící na 0).")
    
    df_inv = load_and_parse_invoices()
    
    if df_inv.empty:
        st.warning("Žádná data z faktur nejsou k dispozici. Zkontrolujte připojení k databázi.")
        return
        
    # Spárování IČO s názvy klientů
    if 'ic' in df_clients.columns and 'name' in df_clients.columns:
        # Použijeme merge pro efektivní spojení
        df_inv = df_inv.merge(df_clients[['ic', 'name']], left_on='client_ic', right_on='ic', how='left')
        df_inv['client_name'] = df_inv['name'].fillna(df_inv['client_ic'].astype(str))
    else:
        df_inv['client_name'] = df_inv['client_ic'].astype(str)
        
    # --- FILTR ---
    col1, col2, col3 = st.columns(3)
    
    with col1:
        client_list = ["Všichni klienti"] + sorted(df_inv['client_name'].dropna().unique().tolist())
        selected_client = st.selectbox("Vyberte klienta:", client_list)
        
    with col2:
        # Zobrazujeme pouze "Produkty" (vyřazujeme tužidla a ředidla podle prefixu)
        product_list = sorted(df_inv[~df_inv['base_code'].str.startswith(('08', '95', '97', '98'))]['base_code'].unique().tolist())
        selected_product = st.selectbox("Hempel Produkt (např. 55610 pro Hempathane):", product_list)
        
    with col3:
        # Vyfiltrujeme odstíny dostupné pro tento produkt (aby nešlo vybrat RAL, který se pro danou barvu nikdy neprodal)
        shade_list = sorted(df_inv[df_inv['base_code'] == selected_product]['shade_name'].unique().tolist())
        if not shade_list:
            shade_list = ["Žádná data pro tento produkt"]
        selected_shade = st.selectbox("Odstín (RAL/Standardní):", shade_list)
        
    st.divider()
    
    # --- ANALÝZA A VÝPOČET ---
    # 1. Globální statistiky pro produkt a odstín napříč trhem
    df_global = df_inv[(df_inv['base_code'] == selected_product) & (df_inv['shade_name'] == selected_shade)]
    
    if df_global.empty:
        st.info(f"Kombinaci produktu {selected_product} v odstínu {selected_shade} jste historicky ještě nikomu neprodali.")
        return
        
    global_min = df_global['price'].min()
    global_avg = df_global['price'].mean()
    global_max = df_global['price'].max()
    
    # 2. Specifické statistiky pro vybraného klienta
    client_price = None
    client_date = None
    
    if selected_client != "Všichni klienti":
        # Vyfiltrujeme nákupy pouze pro tohoto klienta a seřadíme od nejnovějšího
        df_client = df_global[df_global['client_name'] == selected_client].sort_values(by='purchase_date', ascending=False)
        if not df_client.empty:
            client_price = df_client.iloc[0]['price'] 
            client_date = df_client.iloc[0]['purchase_date'].strftime('%d. %m. %Y')
            
    # --- ZOBRAZENÍ VÝSLEDKŮ ---
    st.markdown(f"### Přehled cen: Produkt `{selected_product}` | Odstín `{selected_shade}`")
    
    metric_cols = st.columns(3)
    
    with metric_cols[0]:
        if selected_client == "Všichni klienti":
            st.metric("Nejvyšší prodejní cena", f"{global_max:,.0f} Kč/l".replace(",", " "), "Historické maximum", delta_color="off")
        elif client_price is not None:
            # Rozdíl oproti celofiremnímu průměru (ukazuje, zda mu prodáváme draze nebo levně)
            diff_to_avg = client_price - global_avg
            st.metric(
                label=f"Poslední cena ({selected_client[:15]}...)", 
                value=f"{client_price:,.0f} Kč/l".replace(",", " "),
                delta=f"{diff_to_avg:+,.0f} Kč vs tržní průměr".replace(",", " "),
                delta_color="inverse" # Zelená = je pod průměrem (pro klienta dobré), Červená = je nad průměrem
            )
            st.caption(f"Naposledy nakoupeno: {client_date}")
        else:
            st.metric(label=f"Poslední cena", value="Nenalezeno")
            st.caption("Tento klient daný odstín ještě nikdy nekoupil.")
            
    with metric_cols[1]:
        st.metric("Průměrná tržní cena", f"{global_avg:,.0f} Kč/l".replace(",", " "), "Průměr ze všech firem", delta_color="off")
        
    with metric_cols[2]:
        st.metric("Historické DNO (Minimum)", f"{global_min:,.0f} Kč/l".replace(",", " "), "Pod tuto cenu již nechodit", delta_color="inverse")

    # --- TABULKA VŠECH PRODEJŮ ---
    with st.expander("Zobrazit všechny historické prodeje pro tuto kombinaci (od nejnovějšího)"):
        display_cols = ['purchase_date', 'client_name', 'quantity', 'price']
        
        # Přejmenování sloupců pro hezčí zobrazení
        df_display = df_global[display_cols].sort_values(by='purchase_date', ascending=False).rename(
            columns={
                'purchase_date': 'Datum', 
                'client_name': 'Klient', 
                'quantity': 'Prodané Množství (L/kg)', 
                'price': 'Cena (Kč)'
            }
        )
        
        # Formátování datumu aby v tabulce vypadalo čistě
        df_display['Datum'] = df_display['Datum'].dt.strftime('%d.%m.%Y')
        
        st.dataframe(df_display, use_container_width=True, hide_index=True)