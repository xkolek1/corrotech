import time
import streamlit as st
import extra_streamlit_components as stx
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import pandas as pd
import uuid
import datetime
import plotly.graph_objects as go
from functools import lru_cache
import os

DATABASE_URL = st.secrets["postgres"]["DATABASE_URL"]


# -----------------------------------------------------------------------------
# Database Connection & Initialization
# -----------------------------------------------------------------------------
def validate_db_connection(conn):
    """Zkontroluje, jestli server v cloudu náhodou spojení neukončil (např. kvůli nečinnosti)."""
    try:
        if conn.closed != 0:
            return False
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


@st.cache_resource(validate=validate_db_connection)
def get_db_connection():
    """Vytvoří persistentní databázové spojení na PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        conn.autocommit = True
        return conn
    except Exception as e:
        st.error(f"Chyba při připojování k PostgreSQL: {e}")
        st.stop()


# -----------------------------------------------------------------------------
# Cached Data Loading Functions
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_clients():
    conn = get_db_connection()
    return pd.read_sql_query("SELECT ic, name, total_sales, total_profitability, dealer FROM clients", conn)


@st.cache_data(ttl=300)
def load_products():
    conn = get_db_connection()
    return pd.read_sql_query("SELECT id, name, storage_price FROM products", conn)


@st.cache_data(ttl=300)
def load_users():
    conn = get_db_connection()
    return pd.read_sql_query("SELECT id, email, name, role FROM users", conn)


# -----------------------------------------------------------------------------
# Auth Helpers
# -----------------------------------------------------------------------------
def authenticate_user(email, password):
    conn = get_db_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT id, name, role, password_hash FROM users WHERE email = %s", (email,))
        result = cursor.fetchone()

        if result and bcrypt.checkpw(password.encode('utf-8'), result['password_hash'].encode('utf-8')):
            return {"id": result['id'], "name": result['name'], "role": result['role'], "email": email}
    return None


def add_user(email, name, role, password):
    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO users (email, name, role, password_hash) VALUES (%s, %s, %s, %s)",
                           (email, name, role, hashed_pw))
        load_users.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def update_user(user_id, email, name, role, new_password=None):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if new_password:
                salt = bcrypt.gensalt()
                hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')
                cursor.execute("UPDATE users SET email = %s, name = %s, role = %s, password_hash = %s WHERE id = %s",
                               (email, name, role, hashed_pw, user_id))
            else:
                cursor.execute("UPDATE users SET email = %s, name = %s, role = %s WHERE id = %s",
                               (email, name, role, user_id))
        load_users.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def delete_user(user_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    load_users.clear()


# --- Client Helpers ---
def add_client(ic, name, total_sales, total_profitability, dealer):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO clients (ic, name, total_sales, total_profitability, dealer) VALUES (%s, %s, %s, %s, %s)",
                (ic, name, total_sales, total_profitability, dealer))
        load_clients.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def update_client(ic, name, total_sales, total_profitability, dealer):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE clients SET name=%s, total_sales=%s, total_profitability=%s, dealer=%s WHERE ic=%s",
                           (name, total_sales, total_profitability, dealer, ic))
        load_clients.clear()
        return True
    except:
        return False


def delete_client(ic):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM clients WHERE ic=%s", (ic,))
    load_clients.clear()


# --- Product Helpers ---
def add_product(name, storage_price):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO products (name, storage_price) VALUES (%s, %s)",
                           (name, storage_price))
        load_products.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def update_product(product_id, name, storage_price):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE products SET name = %s, storage_price = %s WHERE id = %s",
                (name, storage_price, product_id))
        load_products.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def delete_product(product_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
    load_products.clear()


# --- Token Management Functions ---
def set_session_token(user_id, token):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE users SET session_token = %s WHERE id = %s", (token, user_id))
    load_users.clear()


def clear_session_token(user_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE users SET session_token = NULL WHERE id = %s", (user_id,))
    load_users.clear()


@lru_cache(maxsize=128)
def get_user_by_token(token):
    conn = get_db_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT id, email, name, role FROM users WHERE session_token = %s", (token,))
        result = cursor.fetchone()
        if result:
            return {"id": result['id'], "email": result['email'],
                    "name": result['name'], "role": result['role']}
    return None


# -----------------------------------------------------------------------------
# UI Layout & Flow
# -----------------------------------------------------------------------------

st.set_page_config(page_title="CORROTECH CPQ", page_icon="corro-icon.svg", layout="wide")

if "authenticated" not in st.session_state:
    st.session_state.update({
        "authenticated": False,
        "user_id": None,
        "user_email": None,
        "user_name": None,
        "user_role": None
    })

cookie_manager = stx.CookieManager()

# --- Auto-Login Logic ---
if not st.session_state["authenticated"]:
    stored_token = cookie_manager.get("cpq_session")
    if stored_token:
        user_data = get_user_by_token(stored_token)
        if user_data:
            st.session_state.update({
                "authenticated": True,
                "user_id": user_data["id"],
                "user_email": user_data["email"],
                "user_name": user_data["name"],
                "user_role": user_data["role"]
            })
            st.rerun()


def login_form():
    col_logo1, col_logo2, col_logo3 = st.columns([1, 1, 1])
    with col_logo2:
        if os.path.exists("corr.svg"):
            st.image("corr.svg", use_container_width=True)
        else:
            st.markdown("<h2 style='text-align: center;'>CORROTECH</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("corro.svg")
        with st.form("login_form"):
            email = st.text_input("E-mail")
            password = st.text_input("Heslo", type="password")
            remember_me = st.checkbox("Zůstat přihlášen (7 dní)")
            submit = st.form_submit_button("Přihlásit se", use_container_width=True)

            if submit:
                user_data = authenticate_user(email, password)
                if user_data:
                    st.session_state.update({
                        "authenticated": True,
                        "user_id": user_data["id"],
                        "user_email": user_data["email"],
                        "user_name": user_data["name"],
                        "user_role": user_data["role"]
                    })

                    if remember_me:
                        new_token = str(uuid.uuid4())
                        set_session_token(user_data["id"], new_token)
                        expire_date = datetime.datetime.now() + datetime.timedelta(days=7)
                        cookie_manager.set("cpq_session", new_token, expires_at=expire_date)
                    time.sleep(0.2)
                    st.rerun()
                else:
                    st.error("Špatný e-mail nebo heslo.")


# -----------------------------------------------------------------------------
# Main Application (Protected)
# -----------------------------------------------------------------------------

if not st.session_state["authenticated"]:
    login_form()
    st.stop()

# Sidebar
if os.path.exists("corr.svg"):
    st.sidebar.image("corr.svg", use_container_width=True)
    st.sidebar.markdown("---")

st.sidebar.title(f"Vítej, {st.session_state['user_name']}")
st.sidebar.write(f"Role: {st.session_state['user_role']}")

if st.sidebar.button("Odhlásit se"):
    if st.session_state.get("user_id"):
        clear_session_token(st.session_state["user_id"])
    if cookie_manager.get("cpq_session"):
        cookie_manager.delete("cpq_session")
    st.session_state.clear()
    time.sleep(0.2)
    st.rerun()

st.sidebar.markdown("---")

nav_options = ["Dashboard", "Můj profil"]
if st.session_state["user_role"] == "Admin":
    nav_options.append("Správa systému (Admin)")

page = st.sidebar.radio("Navigace", nav_options)

# --- Pages ---

if page == "Dashboard":
    df_clients = load_clients()
    df_products = load_products()

    st.markdown("<h2 style='text-align: center; margin-bottom: 30px;'>Vyhledávání klienta</h2>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        client_options = [""] + df_clients['name'].tolist()
        selected_client = st.selectbox("Začněte psát název firmy...", client_options, index=0,
                                       label_visibility="collapsed")

    st.markdown("---")

    if selected_client:
        client_row = df_clients[df_clients['name'] == selected_client].iloc[0]
        st.title(f"🏢 {selected_client}")

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
                st.metric("Celková ziskovost bez DPH", f"{profit:,.0f} Kč".replace(",", " "))

        st.markdown(
            f"**Dealer:** {client_row['dealer'] if pd.notna(client_row['dealer']) and str(client_row['dealer']).strip() != '' else '/'}")

        st.markdown("---")

        st.subheader("🔍 Kalkulace cenové nabídky")
        product_options = [""] + df_products['name'].tolist()
        selected_product = st.selectbox("Vyberte produkt k nacenění:", product_options, index=0)

        if selected_product:
            product_row = df_products[df_products['name'] == selected_product].iloc[0]

            p_storage = float(product_row['storage_price'])

            # PLACEHOLDER: Výpočet doporučeného cenového indexu (zatím neřešíme)
            mock_margin_index = 1.5
            p_retail = p_storage * 2

            target_price = p_storage * mock_margin_index
            min_range = max(target_price * 0.85, p_storage)
            max_range = target_price * 1.15

            # PLACEHOLDER: Poslední nákup (zatím nemáme historii v DB)
            last_bought_price = target_price * 0.92
            last_bought_date = "N/A"

            st.write("#### Doporučená cena a rozpětí")

            st.info("Výpočet doporučeného cenového indexu: **XX** (Bude implementováno později)")


            @st.cache_data
            def create_gauge_chart(p_storage, p_retail, target_price, min_range, max_range,
                                   selected_product, last_bought_price):
                fig = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=target_price,
                    number={'suffix': " Kč", 'valueformat': ",.0f"},
                    title={'text': f"Cenová hladina: {selected_product}", 'font': {'size': 20}},
                    delta={'reference': last_bought_price, 'increasing': {'color': "green"},
                           'decreasing': {'color': "red"}},
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
                            'value': target_price
                        }
                    }
                ))
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20))
                return fig


            fig = create_gauge_chart(p_storage, p_retail, target_price, min_range, max_range,
                                     selected_product, last_bought_price)
            st.plotly_chart(fig, use_container_width=True)

            met_col1, met_col2, met_col3 = st.columns(3)
            met_col1.metric("Skladová cena (Náklad)", f"{p_storage:,.0f} Kč".replace(",", " "))
            met_col2.metric(f"Poslední nákup ({last_bought_date})",
                            f"{last_bought_price:,.0f} Kč".replace(",", " "))
            met_col3.metric("Maloobchodní cena (Max)", f"{p_retail:,.0f} Kč".replace(",", " "))

            st.success(
                f"💡 **Tip pro obchod:** Ideální prostor pro vyjednávání (zelená zóna na grafu) "
                f"je mezi **{min_range:,.0f} Kč** a **{max_range:,.0f} Kč**.".replace(",", " ")
            )
    else:
        st.info("👆 Vyberte firmu z vyhledávacího pole výše pro zahájení analýzy.")

elif page == "Můj profil":
    st.title("👤 Můj profil")
    st.write("Zde si můžeš změnit své heslo pro přístup do systému.")

    with st.form("change_my_password_form"):
        st.subheader("Změna hesla")
        old_pwd = st.text_input("Stávající heslo", type="password")
        new_pwd1 = st.text_input("Nové heslo", type="password")
        new_pwd2 = st.text_input("Nové heslo znovu (pro kontrolu)", type="password")

        if st.form_submit_button("Změnit heslo"):
            if not old_pwd or not new_pwd1 or not new_pwd2:
                st.warning("Musíš vyplnit všechna pole.")
            elif new_pwd1 != new_pwd2:
                st.error("Nová hesla se neshodují.")
            elif authenticate_user(st.session_state["user_email"], old_pwd):
                update_user(st.session_state["user_id"], st.session_state["user_email"],
                            st.session_state["user_name"], st.session_state["user_role"], new_pwd1)
                st.success("Heslo bylo úspěšně změněno!")
            else:
                st.error("Stávající heslo není správné.")

elif page == "Správa systému (Admin)":
    st.title("⚙️ Správa systému")

    df_users = load_users()
    df_clients = load_clients()
    df_products = load_products()

    main_tabs = st.tabs(["👥 Uživatelé", "🏢 Firmy", "🎨 Produkty", "📄 Prodeje"])

    # --- USERS TAB ---
    with main_tabs[0]:
        st.dataframe(df_users, use_container_width=True, hide_index=True)
        st.markdown("---")
        utab1, utab2, utab3 = st.tabs(["Přidat uživatele", "Upravit uživatele", "Smazat uživatele"])

        with utab1:
            with st.form("add_user_form", clear_on_submit=True):
                n_name = st.text_input("Jméno a příjmení")
                n_email = st.text_input("E-mail")
                n_role = st.selectbox("Role", ["User", "Admin"])
                n_pass = st.text_input("Heslo", type="password")
                if st.form_submit_button("Vytvořit účet"):
                    if all([n_name, n_email, n_pass]):
                        if add_user(n_email, n_name, n_role, n_pass):
                            st.success("Přidáno!")
                            st.rerun()
                        else:
                            st.error("Uživatel s tímto e-mailem už existuje.")
                    else:
                        st.warning("Vyplňte vše.")

        with utab2:
            u_edit = st.selectbox("Vyber uživatele k úpravě", df_users['email'].tolist(), key="u_edit_sel")
            if u_edit:
                u_row = df_users[df_users['email'] == u_edit].iloc[0]
                with st.form("edit_user_form"):
                    e_name = st.text_input("Jméno", value=u_row['name'])
                    e_email = st.text_input("E-mail", value=u_row['email'])
                    e_role = st.selectbox("Role", ["User", "Admin"], index=0 if u_row['role'] == "User" else 1)
                    e_pass = st.text_input("Nové heslo (nepovinné)", type="password")
                    if st.form_submit_button("Uložit"):
                        if e_name and e_email:
                            if update_user(int(u_row['id']), e_email, e_name, e_role, e_pass if e_pass else None):
                                st.success("Uloženo!")
                                if u_row['email'] == st.session_state['user_email']:
                                    st.session_state.update({'user_name': e_name, 'user_role': e_role})
                                st.rerun()
                            else:
                                st.error("E-mail koliduje.")

        with utab3:
            u_del = st.selectbox("Vyber uživatele ke smazání", df_users['email'].tolist(), key="u_del_sel")
            if u_del:
                if u_del == st.session_state["user_email"]:
                    st.warning("Nemůžeš smazat sám sebe.")
                elif st.button("Smazat účet", type="primary"):
                    delete_user(int(df_users[df_users['email'] == u_del].iloc[0]['id']))
                    st.success("Smazáno.")
                    st.rerun()

    # --- CLIENTS TAB ---
    with main_tabs[1]:
        st.dataframe(df_clients, use_container_width=True, hide_index=True)
        st.markdown("---")
        ctab1, ctab2, ctab3, ctab4 = st.tabs(["Přidat firmu", "Upravit firmu", "Smazat firmu", "📦 Import z Excelu"])

        with ctab1:
            with st.form("add_client_form", clear_on_submit=True):
                c_ic = st.text_input("IČ (Unikátní identifikátor)")
                c_name = st.text_input("Název firmy")
                c_sales = st.number_input("Celkový obrat bez DPH (Kč)", value=0.0)
                c_prof = st.number_input("Ziskovost (Kč)", value=0.0)
                c_dealer = st.text_input("Dealer")

                if st.form_submit_button("Přidat firmu"):
                    if c_ic and c_name:
                        if add_client(c_ic, c_name, c_sales, c_prof, c_dealer):
                            st.success("Firma přidána!")
                            st.rerun()
                        else:
                            st.error("Firma s tímto IČ už existuje.")
                    else:
                        st.warning("IČ a Název nesmí být prázdné.")

        with ctab2:
            c_edit = st.selectbox("Vyber firmu k úpravě", df_clients['name'].tolist(), key="c_edit_sel", index=None,
                                  placeholder="Vyberte firmu...")
            if c_edit:
                c_row = df_clients[df_clients['name'] == c_edit].iloc[0]
                with st.form("edit_client_form"):
                    st.write(f"Úprava firmy s IČ: **{c_row['ic']}**")
                    ce_name = st.text_input("Název firmy", value=c_row['name'])

                    ce_sales_val = 0.0 if pd.isna(c_row['total_sales']) else float(c_row['total_sales'])
                    ce_sales = st.number_input("Celkový obrat bez DPH (Kč)", value=ce_sales_val)

                    ce_prof_val = 0.0 if pd.isna(c_row['total_profitability']) else float(c_row['total_profitability'])
                    ce_prof = st.number_input("Ziskovost (Kč)", value=ce_prof_val)

                    ce_dealer_val = "" if pd.isna(c_row['dealer']) else str(c_row['dealer'])
                    ce_dealer = st.text_input("Dealer", value=ce_dealer_val)

                    if st.form_submit_button("Uložit"):
                        if ce_name:
                            if update_client(str(c_row['ic']), ce_name, ce_sales, ce_prof, ce_dealer):
                                st.success("Uloženo!")
                                st.rerun()
                            else:
                                st.error("Chyba při ukládání do DB.")
                        else:
                            st.warning("Název nesmí být prázdný.")

        with ctab3:
            c_del = st.selectbox("Vyber firmu ke smazání", df_clients['name'].tolist(), key="c_del_sel", index=None,
                                 placeholder="Vyberte firmu...")
            if c_del and st.button("Smazat firmu", type="primary", key="c_del_btn"):
                delete_client(str(df_clients[df_clients['name'] == c_del].iloc[0]['ic']))
                st.success("Smazáno.")
                st.rerun()

        # --- LOGIKA IMPORTU Z EXCELU ---
        with ctab4:
            st.info(
                "Nahrajte soubor s analýzou odběratelů. Lze zpracovat a sečíst více listů (např. prodejních let) najednou.")
            uploaded_file = st.file_uploader("Nahrát Excel s klienty", type=["xlsx", "xls"])

            if uploaded_file:
                try:
                    xls = pd.ExcelFile(uploaded_file)
                    sheet_names = xls.sheet_names

                    st.markdown("### 1. Výběr listů ke zpracování")
                    selected_sheets = st.multiselect(
                        "Vyberte listy (např. jednotlivé roky), které se mají sečíst:",
                        sheet_names,
                        default=sheet_names
                    )

                    if selected_sheets:
                        all_dataframes = []

                        for sheet in selected_sheets:
                            df_raw = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=20)

                            header_idx = 0
                            for idx, row in df_raw.iterrows():
                                row_str = ' '.join([str(val).lower() for val in row.values if pd.notna(val)])
                                if 'ič' in row_str or 'ic' in row_str or 'firma' in row_str or 'název' in row_str or 'odběratel' in row_str:
                                    header_idx = idx
                                    break

                            df_sheet = pd.read_excel(xls, sheet_name=sheet, header=header_idx)
                            df_sheet = df_sheet.dropna(how='all', axis=1)
                            df_sheet.columns = [str(c).replace('\n', ' ').strip() for c in df_sheet.columns]
                            all_dataframes.append(df_sheet)

                        df_import = pd.concat(all_dataframes, ignore_index=True)

                        st.write(
                            f"Náhled sloučených dat (celkem {len(df_import)} řádků ze {len(selected_sheets)} listů):")
                        st.dataframe(df_import.head(3))

                        col_options = df_import.columns.tolist()

                        def_ic = next((c for c in col_options if 'ič' in str(c).lower() or 'ic' in str(c).lower()),
                                      col_options[0])
                        def_name = next((c for c in col_options if
                                         'firma' in str(c).lower() or 'název' in str(c).lower() or 'odběratel' in str(
                                             c).lower()), col_options[0])
                        def_dealer = next(
                            (c for c in col_options if 'dealer' in str(c).lower() or 'zástupce' in str(c).lower()),
                            col_options[0])

                        st.markdown("### 2. Spárování sloupců z Excelu na Databázi")
                        map_ic = st.selectbox("Sloupec s IČ (Povinné):", col_options, index=col_options.index(def_ic))
                        map_name = st.selectbox("Sloupec s Názvem firmy (Povinné):", col_options,
                                                index=col_options.index(def_name))
                        map_dealer = st.selectbox("Sloupec s Dealerem:", col_options,
                                                  index=col_options.index(def_dealer))

                        sum_sales_cols = st.multiselect("Sloupce k sečtení do 'Celkového obratu bez DPH':", col_options,
                                                        default=[c for c in col_options if
                                                                 'obrat' in str(c).lower() and 'bez dph' in str(
                                                                     c).lower()])
                        sum_prof_cols = st.multiselect("Sloupce k sečtení do 'Ziskovosti (hrubý zisk bez DPH)':",
                                                       col_options,
                                                       default=[c for c in col_options if
                                                                'zisk' in str(c).lower() and 'bez dph' in str(
                                                                    c).lower()])

                        if st.button("🚀 Spustit import a sečíst napříč listy", type="primary"):
                            conn = get_db_connection()
                            clients_dict = {}

                            for index, row in df_import.iterrows():
                                c_ic = str(row[map_ic]).strip()
                                c_name = str(row[map_name]).strip()

                                if not c_ic or c_ic.lower() == 'nan' or not c_name or c_name.lower() == 'nan':
                                    continue

                                c_dealer = str(row[map_dealer]).strip() if pd.notna(row[map_dealer]) else ""

                                total_sales = 0.0
                                for sc in sum_sales_cols:
                                    if pd.notna(row[sc]):
                                        try:
                                            total_sales += float(row[sc])
                                        except ValueError:
                                            pass

                                total_prof = 0.0
                                for pc in sum_prof_cols:
                                    if pd.notna(row[pc]):
                                        try:
                                            total_prof += float(row[pc])
                                        except ValueError:
                                            pass

                                if c_ic in clients_dict:
                                    clients_dict[c_ic]['sales'] += total_sales
                                    clients_dict[c_ic]['prof'] += total_prof
                                    if c_dealer and not clients_dict[c_ic]['dealer']:
                                        clients_dict[c_ic]['dealer'] = c_dealer
                                else:
                                    clients_dict[c_ic] = {
                                        'name': c_name,
                                        'dealer': c_dealer,
                                        'sales': total_sales,
                                        'prof': total_prof
                                    }

                            imported_count = 0
                            with conn.cursor() as cursor:
                                for ic_key, data in clients_dict.items():
                                    cursor.execute('''
                                                   INSERT INTO clients (ic, name, total_sales, total_profitability, dealer)
                                                   VALUES (%s, %s, %s, %s, %s)
                                                   ON CONFLICT (ic) DO UPDATE
                                                       SET name                = EXCLUDED.name,
                                                           total_sales         = EXCLUDED.total_sales,
                                                           total_profitability = EXCLUDED.total_profitability,
                                                           dealer              = EXCLUDED.dealer
                                                   ''',
                                                   (ic_key, data['name'], data['sales'], data['prof'], data['dealer']))

                                    imported_count += 1

                            load_clients.clear()
                            st.success(
                                f"🎉 Úspěšně naimportováno / zaktualizováno {imported_count} unikátních firem (sloučeno ze {len(selected_sheets)} listů)!")
                            st.rerun()

                except Exception as e:
                    st.error(f"Při zpracování Excelu došlo k chybě: {e}")

        # --- PRODUCTS TAB ---
        with main_tabs[2]:
            st.dataframe(df_products, use_container_width=True, hide_index=True)
            st.markdown("---")
            ptab1, ptab2, ptab3 = st.tabs(["Přidat produkt", "Upravit produkt", "Smazat produkt"])

            with ptab1:
                with st.form("add_product_form", clear_on_submit=True):
                    p_name = st.text_input("Název produktu")
                    p_price = st.number_input("Jednotková skladová cena (Kč)", min_value=0.0, value=0.0)

                    if st.form_submit_button("Přidat produkt"):
                        if p_name:
                            # Voláme správně jen se 2 argumenty
                            if add_product(p_name, p_price):
                                st.success("Produkt přidán!")
                                st.rerun()
                            else:
                                st.error("Produkt s tímto názvem už existuje.")
                        else:
                            st.warning("Název nesmí být prázdný.")

            with ptab2:
                p_edit = st.selectbox("Vyber produkt k úpravě", df_products['name'].tolist(), key="p_edit_sel")
                if p_edit:
                    p_row = df_products[df_products['name'] == p_edit].iloc[0]
                    with st.form("edit_product_form"):
                        pe_name = st.text_input("Název produktu", value=p_row['name'])
                        pe_price_val = 0.0 if pd.isna(p_row['storage_price']) else float(p_row['storage_price'])

                        pe_price = st.number_input("Jednotková skladová cena (Kč)", min_value=0.0, value=pe_price_val)

                        if st.form_submit_button("Uložit"):
                            if pe_name:
                                # Odstraněno int(), použijeme str() pro jistotu, kdyby tam byla písmena
                                if update_product(str(p_row['id']), pe_name, pe_price):
                                    st.success("Uloženo!")
                                    st.rerun()
                                else:
                                    st.error("Kolize názvu.")
                            else:
                                st.warning("Název nesmí být prázdný.")

            with ptab3:
                p_del = st.selectbox("Vyber produkt ke smazání", df_products['name'].tolist(), key="p_del_sel")
                if p_del and st.button("Smazat produkt", type="primary", key="p_del_btn"):
                    delete_product(str(df_products[df_products['name'] == p_del].iloc[0]['id']))
                    st.success("Smazáno.")
                    st.rerun()
    # --- SALES IMPORT TAB ---
    with main_tabs[3]:
        st.subheader("Import prodejů z Excelu")
        st.info(
            "Nahraj soubor s prodeji (např. ESO9_Online_CO_PřehledProdeje.xlsx). Záznamy, které už v databázi jsou (shoda čísla Dokladu a Kódu zboží), se automaticky přeskočí.")

        uploaded_sales = st.file_uploader("Nahrát Excel s prodeji", type=["xlsx", "xls"], key="sales_uploader")

        if uploaded_sales:
            try:
                df_sales = pd.read_excel(uploaded_sales)

                required_cols = ['Doklad', 'Kód subjektu', 'Jednotková cena', 'Kód zboží', 'Datum', 'Množství']
                missing_cols = [c for c in required_cols if c not in df_sales.columns]

                if missing_cols:
                    st.error(f"V Excelu chybí tyto povinné sloupce: {', '.join(missing_cols)}. Zkontroluj názvy.")
                else:
                    st.write(f"Náhled dat ({len(df_sales)} řádků):")
                    st.dataframe(df_sales.head(3))

                    if st.button("🚀 Spustit import prodejů", type="primary"):
                        conn = get_db_connection()
                        imported_count = 0
                        skipped_count = 0

                        with conn.cursor() as cursor:
                            for index, row in df_sales.iterrows():
                                doklad = str(row['Doklad']).strip()
                                product_id = str(row['Kód zboží']).strip()

                                if not doklad or doklad.lower() == 'nan' or not product_id or product_id.lower() == 'nan':
                                    continue

                                client_ic = str(row['Kód subjektu']).strip() if pd.notna(
                                    row['Kód subjektu']) else ""
                                price = float(row['Jednotková cena']) if pd.notna(row['Jednotková cena']) else 0.0
                                quantity = float(row['Množství']) if pd.notna(row['Množství']) else 0.0

                                try:
                                    purchase_date = pd.to_datetime(row['Datum']).date()
                                except:
                                    purchase_date = None

                                # Obnovené WHERE pro zabránění duplicit - pokud to necháš bez něj, bude se to kopírovat do nekonečna
                                cursor.execute('''
                                               INSERT INTO invoices (id, client_ic, price, product_id, purchase_date, quantity)
                                               SELECT %s, %s, %s, %s, %s, %s
                                               WHERE NOT EXISTS (SELECT 1
                                                                 FROM invoices
                                                                 WHERE id = %s AND product_id = %s)
                                               ''',
                                               (doklad, client_ic, price, product_id, purchase_date, quantity, doklad,
                                                product_id))

                                if cursor.rowcount > 0:
                                    imported_count += 1
                                else:
                                    skipped_count += 1

                        st.success(
                            f"Hotovo! Naimportováno {imported_count} nových záznamů. Přeskočeno {skipped_count} existujících duplikátů.")

            except Exception as e:
                st.error(f"Během zpracování Excelu došlo k chybě: {e}")