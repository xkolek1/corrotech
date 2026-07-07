import streamlit as st
import extra_streamlit_components as stx
import sqlite3
import bcrypt
import pandas as pd
import uuid
import datetime
import plotly.graph_objects as go
from time import sleep

DB_NAME = "corrotech.db"

# -----------------------------------------------------------------------------
# Database Helper Functions (Operating on existing DB)
# -----------------------------------------------------------------------------

def init_db():
    """Initialize the SQLite database, handle migrations (like adding base_retail_price), and seed data."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # --- Clients Table ---
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS clients
                       (
                           id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                           name                TEXT UNIQUE NOT NULL,
                           total_profitability REAL
                       )
                       ''')
        cursor.execute("SELECT COUNT(*) FROM clients")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO clients (name, total_profitability) VALUES (?, ?)",
                           ("Ostravské nátěry a.s.", 150000.0))
            cursor.execute("INSERT INTO clients (name, total_profitability) VALUES (?, ?)",
                           ("Malíři Karviná s.r.o.", -5500.0))

        # --- Products Table ---
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS products
                       (
                           id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                           name               TEXT UNIQUE NOT NULL,
                           unit_storage_price REAL
                       )
                       ''')

        # MIGRATION: Add base_retail_price column if it doesn't exist yet
        cursor.execute("PRAGMA table_info(products)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'base_retail_price' not in columns:
            cursor.execute("ALTER TABLE products ADD COLUMN base_retail_price REAL")
            # Update existing products with dummy retail prices if we are migrating
            cursor.execute(
                "UPDATE products SET base_retail_price = unit_storage_price * 1.5 WHERE base_retail_price IS NULL")

        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO products (name, unit_storage_price, base_retail_price) VALUES (?, ?, ?)",
                           ("Primalex Plus 15kg", 450.50, 750.00))
            cursor.execute("INSERT INTO products (name, unit_storage_price, base_retail_price) VALUES (?, ?, ?)",
                           ("Epoxidový základ 10L", 1250.00, 2100.00))

        conn.commit()


# Ensure tables exist and migrations are applied
init_db()


# --- Auth Helpers ---
def authenticate_user(email, password):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role, password_hash FROM users WHERE email = ?", (email,))
        result = cursor.fetchone()

        if result:
            user_id, name, role, stored_hash = result
            if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                return {"id": user_id, "name": name, "role": role, "email": email}
    return None


def add_user(email, name, role, password):
    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (email, name, role, password_hash) VALUES (?, ?, ?, ?)",
                           (email, name, role, hashed_pw))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_user(user_id, email, name, role, new_password=None):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            if new_password:
                salt = bcrypt.gensalt()
                hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')
                cursor.execute("UPDATE users SET email = ?, name = ?, role = ?, password_hash = ? WHERE id = ?",
                               (email, name, role, hashed_pw, user_id))
            else:
                cursor.execute("UPDATE users SET email = ?, name = ?, role = ? WHERE id = ?",
                               (email, name, role, user_id))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_user(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


# --- Client Helpers ---
def add_client(name, profitability):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.cursor().execute("INSERT INTO clients (name, total_profitability) VALUES (?, ?)",
                                  (name, profitability))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_client(client_id, name, profitability):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.cursor().execute("UPDATE clients SET name = ?, total_profitability = ? WHERE id = ?",
                                  (name, profitability, client_id))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_client(client_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()


# --- Product Helpers ---
def add_product(name, storage_price, retail_price):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.cursor().execute("INSERT INTO products (name, unit_storage_price, base_retail_price) VALUES (?, ?, ?)",
                                  (name, storage_price, retail_price))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_product(product_id, name, storage_price, retail_price):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.cursor().execute(
                "UPDATE products SET name = ?, unit_storage_price = ?, base_retail_price = ? WHERE id = ?",
                (name, storage_price, retail_price, product_id))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_product(product_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()


# --- Token Management Functions ---
def set_session_token(user_id, token):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("UPDATE users SET session_token = ? WHERE id = ?", (token, user_id))
        conn.commit()


def clear_session_token(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("UPDATE users SET session_token = NULL WHERE id = ?", (user_id,))
        conn.commit()


def get_user_by_token(token):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name, role FROM users WHERE session_token = ?", (token,))
        result = cursor.fetchone()
        if result:
            return {"id": result[0], "email": result[1], "name": result[2], "role": result[3]}
    return None


# -----------------------------------------------------------------------------
# UI Layout & Flow
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Corrotech CPQ", page_icon="💧", layout="wide")

cookie_manager = stx.CookieManager()

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# --- Auto-Login Logic (Check for Cookie) ---
if not st.session_state["authenticated"]:
    stored_token = cookie_manager.get("cpq_session")
    if stored_token:
        user_data = get_user_by_token(stored_token)
        if user_data:
            st.session_state["authenticated"] = True
            st.session_state["user_id"] = user_data["id"]
            st.session_state["user_email"] = user_data["email"]
            st.session_state["user_name"] = user_data["name"]
            st.session_state["user_role"] = user_data["role"]
            st.rerun()


def login_form():
    st.markdown("<h1 style='text-align: center;'>Corrotech</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            email = st.text_input("E-mail")
            password = st.text_input("Heslo", type="password")
            remember_me = st.checkbox("Zůstat přihlášen (7 dní)")
            submit = st.form_submit_button("Přihlásit se", use_container_width=True)

            if submit:
                user_data = authenticate_user(email, password)
                if user_data:
                    st.session_state["authenticated"] = True
                    st.session_state["user_id"] = user_data["id"]
                    st.session_state["user_email"] = user_data["email"]
                    st.session_state["user_name"] = user_data["name"]
                    st.session_state["user_role"] = user_data["role"]

                    if remember_me:
                        new_token = str(uuid.uuid4())
                        set_session_token(user_data["id"], new_token)
                        expire_date = datetime.datetime.now() + datetime.timedelta(days=7)
                        cookie_manager.set("cpq_session", new_token, expires_at=expire_date)
                        sleep(0.5)
                    st.rerun()
                else:
                    st.error("Špatný e-mail nebo heslo.")


def logout():
    if "user_id" in st.session_state:
        clear_session_token(st.session_state["user_id"])
    cookie_manager.delete("cpq_session")
    st.session_state.clear()
    sleep(0.5)
    st.rerun()


# -----------------------------------------------------------------------------
# Main Application (Protected)
# -----------------------------------------------------------------------------

if not st.session_state["authenticated"]:
    login_form()
    st.stop()

# Sidebar
st.sidebar.title(f"Vítej, {st.session_state['user_name']}")
st.sidebar.write(f"Role: {st.session_state['user_role']}")
st.sidebar.button("Odhlásit se", on_click=logout)
st.sidebar.markdown("---")

nav_options = ["Dashboard", "Můj profil"]
if st.session_state["user_role"] == "Admin":
    nav_options.append("Správa systému (Admin)")

page = st.sidebar.radio("Navigace", nav_options)

# --- Pages ---

if page == "Dashboard":

    with sqlite3.connect(DB_NAME) as conn:
        df_clients = pd.read_sql_query("SELECT id, name, total_profitability FROM clients", conn)
        df_products = pd.read_sql_query("SELECT id, name, unit_storage_price, base_retail_price FROM products", conn)

    # 1. Hlavní vyhledávání klienta (vždy nahoře)
    st.markdown("<h2 style='text-align: center; margin-bottom: 30px;'>Vyhledávání klienta</h2>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        client_options = [""] + df_clients['name'].tolist()
        selected_client = st.selectbox("Začněte psát název firmy...", client_options, index=0,
                                       label_visibility="collapsed")

    st.markdown("---")

    # 2. Analýza vybraného klienta
    if selected_client:
        client_row = df_clients[df_clients['name'] == selected_client].iloc[0]

        st.title(f"🏢 {selected_client}")

        # --- ZÁKLADNÍ INFO A MARŽE ---
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            profit = client_row['total_profitability']
            if pd.isna(profit):
                st.metric("Celková historická ziskovost", "Nezadáno")
            else:
                st.metric("Celková historická ziskovost", f"{profit:,.0f} Kč")

        with info_col2:
            # TODO: Nahradit reálným modelem. Zatím generujeme mock hodnotu pro ukázku (např. 0.65)
            # 0.00 = skladovka, 1.00 = maloobchodní cena
            mock_margin_index = 0.65
            st.metric(
                "Doporučený index cen",
                f"{mock_margin_index:.2f}",
                "0.0 = Sklad, 1.0 = Maloobchod",
                delta_color="off"
            )

        # --- ČASOVÉ ŘADY A HISTORIE (Placeholdery) ---
        st.subheader("📊 Analýza odběrů")
        tab_time, tab_hist = st.tabs(["Časové řady", "Historie objednávek"])

        with tab_time:
            st.info(
                "Zde bude graf odběrů v čase")
            # Tady pak použijeme st.line_chart nebo st.plotly_chart pro zobrazení reálných dat

        with tab_hist:
            st.info("Zde tabulka historie objednávek s možností filtrování (Kdy, Co, Za kolik).")
            # Tady pak vykreslíme dataframe přes st.dataframe()

        st.markdown("---")

        # --- KALKULACE KONKRÉTNÍHO PRODUKTU PRO TOHOTO KLIENTA ---
        st.subheader("🔍 Kalkulace cenové nabídky")
        product_options = [""] + df_products['name'].tolist()
        selected_product = st.selectbox("Vyberte barvu k nacenění:", product_options, index=0)

        if selected_product:
            product_row = df_products[df_products['name'] == selected_product].iloc[0]

            p_storage = float(product_row['unit_storage_price'])
            p_retail = float(product_row['base_retail_price'])

            # Zamezení dělení nulou nebo špatným datům
            if pd.isna(p_storage) or pd.isna(p_retail) or p_retail <= p_storage:
                st.error("U tohoto produktu chybí správná skladová nebo maloobchodní cena v databázi.")
            else:
                # VÝPOČTY
                # Target price = Skladovka + (Index * (Maloobchod - Skladovka))
                target_price = p_storage + (mock_margin_index * (p_retail - p_storage))

                # Rozmezí +- 15% z target price
                min_range = target_price * 0.85
                max_range = target_price * 1.15

                # Ujistíme se, že min_range neklesne pod skladovku
                min_range = max(min_range, p_storage)

                # MOCK historické ceny (jakože už to někdy koupili levněji)
                last_bought_price = target_price * 0.92
                last_bought_date = "15. 5. 2026"

                st.write("#### Doporučená cena a rozpětí")

                # --- PLOTLY TACHOMETR (Gauge Chart) ---
                fig = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=target_price,
                    number={'suffix': " Kč", 'valueformat': ",.0f"},
                    title={'text': f"Cenová hladina: {selected_product}", 'font': {'size': 20}},
                    delta={'reference': last_bought_price, 'increasing': {'color': "green"},
                           'decreasing': {'color': "red"}},
                    gauge={
                        'axis': {'range': [p_storage, p_retail], 'tickwidth': 1, 'tickcolor': "darkblue"},
                        'bar': {'color': "rgba(0,0,0,0)"},  # Skryjeme výchozí progress bar, chceme jen ručičku
                        'bgcolor': "white",
                        'borderwidth': 2,
                        'bordercolor': "gray",
                        'steps': [
                            {'range': [p_storage, min_range], 'color': "rgba(255, 99, 132, 0.4)"},
                            # Červená - pod marží
                            {'range': [min_range, max_range], 'color': "rgba(75, 192, 192, 0.5)"},
                            # Zelená - ideální zóna
                            {'range': [max_range, p_retail], 'color': "rgba(54, 162, 235, 0.4)"}  # Modrá - vysoká marže
                        ],
                        'threshold': {
                            'line': {'color': "black", 'width': 5},
                            'thickness': 0.75,
                            'value': target_price  # Ručička ukazující na cílovou cenu
                        }
                    }
                ))

                # Úprava layoutu pro lepší zobrazení ve Streamlitu
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig, use_container_width=True)

                # Detailní výpis pod grafem
                met_col1, met_col2, met_col3 = st.columns(3)
                met_col1.metric("Skladová cena (Náklad)", f"{p_storage:,.0f} Kč")

                if last_bought_price:
                    met_col2.metric(f"Poslední nákup ({last_bought_date})", f"{last_bought_price:,.0f} Kč")
                else:
                    met_col2.metric("Poslední nákup", "NaN")

                met_col3.metric("Maloobchodní cena (Max)", f"{p_retail:,.0f} Kč")

                st.info(
                    f"💡 **Tip pro obchod:** Ideální prostor pro vyjednávání (zelená zóna na grafu) je mezi **{min_range:,.0f} Kč** a **{max_range:,.0f} Kč**.")

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
            else:
                if authenticate_user(st.session_state["user_email"], old_pwd):
                    update_user(st.session_state["user_id"], st.session_state["user_email"],
                                st.session_state["user_name"], st.session_state["user_role"], new_pwd1)
                    st.success("Heslo bylo úspěšně změněno!")
                else:
                    st.error("Stávající heslo není správné.")

elif page == "Správa systému (Admin)":
    st.title("⚙️ Správa systému")

    with sqlite3.connect(DB_NAME) as conn:
        df_users = pd.read_sql_query("SELECT id, email, name, role FROM users", conn)
        df_clients = pd.read_sql_query("SELECT id, name, total_profitability FROM clients", conn)
        df_products = pd.read_sql_query("SELECT id, name, unit_storage_price, base_retail_price FROM products", conn)

    main_tabs = st.tabs(["👥 Uživatelé", "🏢 Firmy", "🎨 Produkty"])

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
                    if n_name and n_email and n_pass:
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
                                    st.session_state['user_name'], st.session_state['user_role'] = e_name, e_role
                                st.rerun()
                            else:
                                st.error("E-mail koliduje.")

        with utab3:
            u_del = st.selectbox("Vyber uživatele ke smazání", df_users['email'].tolist(), key="u_del_sel")
            if u_del:
                if u_del == st.session_state["user_email"]:
                    st.warning("Nemůžeš smazat sám sebe.")
                else:
                    if st.button("Smazat účet", type="primary"):
                        delete_user(int(df_users[df_users['email'] == u_del].iloc[0]['id']))
                        st.success("Smazáno.")
                        st.rerun()

    # --- CLIENTS TAB ---
    with main_tabs[1]:
        st.dataframe(df_clients, use_container_width=True, hide_index=True)
        st.markdown("---")
        ctab1, ctab2, ctab3 = st.tabs(["Přidat firmu", "Upravit firmu", "Smazat firmu"])

        with ctab1:
            with st.form("add_client_form", clear_on_submit=True):
                c_name = st.text_input("Název firmy")
                c_prof = st.number_input("Celková ziskovost (Kč)", value=0.0)
                if st.form_submit_button("Přidat firmu"):
                    if c_name:
                        if add_client(c_name, c_prof):
                            st.success("Firma přidána!")
                            st.rerun()
                        else:
                            st.error("Firma s tímto názvem už existuje.")
                    else:
                        st.warning("Název nesmí být prázdný.")

        with ctab2:
            c_edit = st.selectbox("Vyber firmu k úpravě", df_clients['name'].tolist(), key="c_edit_sel")
            if c_edit:
                c_row = df_clients[df_clients['name'] == c_edit].iloc[0]
                with st.form("edit_client_form"):
                    ce_name = st.text_input("Název firmy", value=c_row['name'])
                    ce_prof_val = 0.0 if pd.isna(c_row['total_profitability']) else float(c_row['total_profitability'])
                    ce_prof = st.number_input("Celková ziskovost (Kč)", value=ce_prof_val)
                    if st.form_submit_button("Uložit"):
                        if ce_name:
                            if update_client(int(c_row['id']), ce_name, ce_prof):
                                st.success("Uloženo!")
                                st.rerun()
                            else:
                                st.error("Kolize názvu.")
                        else:
                            st.warning("Název nesmí být prázdný.")

        with ctab3:
            c_del = st.selectbox("Vyber firmu ke smazání", df_clients['name'].tolist(), key="c_del_sel")
            if c_del:
                if st.button("Smazat firmu", type="primary", key="c_del_btn"):
                    delete_client(int(df_clients[df_clients['name'] == c_del].iloc[0]['id']))
                    st.success("Smazáno.")
                    st.rerun()

    # --- PRODUCTS TAB ---
    with main_tabs[2]:
        st.dataframe(df_products, use_container_width=True, hide_index=True)
        st.markdown("---")
        ptab1, ptab2, ptab3 = st.tabs(["Přidat produkt", "Upravit produkt", "Smazat produkt"])

        with ptab1:
            with st.form("add_product_form", clear_on_submit=True):
                p_name = st.text_input("Název produktu")
                p_price = st.number_input("Jednotková skladová cena (Kč)", min_value=0.0, value=0.0)
                p_retail = st.number_input("Základní prodejní cena (Kč)", min_value=0.0, value=0.0)
                if st.form_submit_button("Přidat produkt"):
                    if p_name:
                        if add_product(p_name, p_price, p_retail):
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
                    pe_price_val = 0.0 if pd.isna(p_row['unit_storage_price']) else float(p_row['unit_storage_price'])
                    pe_retail_val = 0.0 if pd.isna(p_row['base_retail_price']) else float(p_row['base_retail_price'])

                    pe_price = st.number_input("Jednotková skladová cena (Kč)", min_value=0.0, value=pe_price_val)
                    pe_retail = st.number_input("Základní prodejní cena (Kč)", min_value=0.0, value=pe_retail_val)

                    if st.form_submit_button("Uložit"):
                        if pe_name:
                            if update_product(int(p_row['id']), pe_name, pe_price, pe_retail):
                                st.success("Uloženo!")
                                st.rerun()
                            else:
                                st.error("Kolize názvu.")
                        else:
                            st.warning("Název nesmí být prázdný.")

        with ptab3:
            p_del = st.selectbox("Vyber produkt ke smazání", df_products['name'].tolist(), key="p_del_sel")
            if p_del:
                if st.button("Smazat produkt", type="primary", key="p_del_btn"):
                    delete_product(int(df_products[df_products['name'] == p_del].iloc[0]['id']))
                    st.success("Smazáno.")
                    st.rerun()