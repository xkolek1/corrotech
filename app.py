"""Streamlit aplikace pro CPQ a správu dat CORROTECH."""

# Imports and application configuration
import time
import os
import datetime
import tempfile
import streamlit as st
import extra_streamlit_components as stx
import streamlit.components.v1 as components
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import pandas as pd
import plotly.graph_objects as go
import base64
import calendar
from functools import lru_cache
from uuid import uuid4

from pdf_generator import KalkulacePDF

DATABASE_URL = st.secrets["postgres"]["DATABASE_URL"]

def validate_db_connection(db_conn):
    """Ověří, že uložené databázové spojení je stále použitelné."""
    try:
        if db_conn.closed != 0:
            return False
        with db_conn.cursor() as db_cursor:
            db_cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


@st.cache_resource(validate=validate_db_connection)
def get_db_connection():
    """Vytvoří nebo vrátí sdílené připojení k PostgreSQL."""
    try:
        db_conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        db_conn.autocommit = True
        return db_conn
    except Exception as db_err:
        st.error(f"Chyba při připojování k PostgreSQL: {db_err}")
        st.stop()


# =============================================================================
# Cached Data Loading Functions
# =============================================================================
@st.cache_data(ttl=300)
def load_monthly_sales():
    db_conn = get_db_connection()
    query = """
            SELECT c.ic, \
                   c.name                                                   AS client_name, \
                   c.dealer, \
                   TO_CHAR(DATE_TRUNC('month', i.purchase_date), 'YYYY-MM') AS month, \
                   SUM(i.price * i.quantity)                                AS monthly_turnover
            FROM clients c
                     JOIN invoices i ON c.ic = i.client_ic
            GROUP BY c.ic, c.name, c.dealer, month
            ORDER BY month DESC \
            """
    return pd.read_sql_query(query, db_conn)

@st.cache_data(ttl=300)
def load_dealers_comparison():
    db_conn = get_db_connection()
    query = """
        SELECT 
            COALESCE(NULLIF(TRIM(c.dealer), ''), 'Bez dealera') AS dealer,
            TO_CHAR(DATE_TRUNC('month', i.purchase_date), 'YYYY-MM') AS month,
            SUM(i.price * i.quantity) AS turnover,
            SUM(i.price * i.quantity) * 0.20 AS profit
        FROM invoices i
        JOIN clients c ON i.client_ic = c.ic
        GROUP BY COALESCE(NULLIF(TRIM(c.dealer), ''), 'Bez dealera'), month
        ORDER BY month
    """
    return pd.read_sql_query(query, db_conn)


@st.cache_data(ttl=300)
def load_client_items_by_months(client_ic, selected_months_tuple):
    db_conn = get_db_connection()
    if not selected_months_tuple:
        return pd.DataFrame()

    format_strings = ','.join(['%s'] * len(selected_months_tuple))
    query = f"""
        SELECT 
            p.id AS product_id,
            p.name AS product_name,
            SUM(i.quantity) AS total_qty,
            AVG(i.price) AS avg_price
        FROM invoices i
        JOIN products p ON i.product_id = p.id
        WHERE i.client_ic = %s
          AND TO_CHAR(DATE_TRUNC('month', i.purchase_date), 'YYYY-MM') IN ({format_strings})
        GROUP BY p.id, p.name
    """
    params = [str(client_ic)] + list(selected_months_tuple)
    return pd.read_sql_query(query, db_conn, params=tuple(params))

@st.cache_data(ttl=300)
def load_clients():
    db_conn = get_db_connection()
    query = """
        SELECT 
            c.ic, 
            c.name, 
            COALESCE(SUM(i.price * i.quantity), 0) AS total_sales,
            c.total_profitability, 
            c.dealer 
        FROM clients c
        LEFT JOIN invoices i ON c.ic = i.client_ic
        GROUP BY c.ic, c.name, c.total_profitability, c.dealer
    """
    return pd.read_sql_query(query, db_conn)


@st.cache_data(ttl=300)
def load_products():
    db_conn = get_db_connection()
    return pd.read_sql_query("SELECT id, name, storage_price FROM products", db_conn)


@st.cache_data(ttl=300)
def load_users():
    db_conn = get_db_connection()
    return pd.read_sql_query("SELECT id, email, name, role, phone_number FROM users", db_conn)


@st.cache_data(ttl=300)
def load_pdf_hmoty():
    db_conn = get_db_connection()
    return pd.read_sql_query("SELECT id, cislo_odstinu, nazev, redidlo, susina FROM pdf_hmoty", db_conn)

@st.cache_data(ttl=300)
def load_client_invoices(client_ic):
    db_conn = get_db_connection()
    query = """
        SELECT purchase_date, price, quantity 
        FROM invoices 
        WHERE client_ic = %s
    """
    return pd.read_sql_query(query, db_conn, params=(str(client_ic),))


# =============================================================================
# Auth & User Management Helpers
# =============================================================================
def authenticate_user(email, password):
    db_conn = get_db_connection()
    with db_conn.cursor(cursor_factory=RealDictCursor) as db_cursor:
        db_cursor.execute("SELECT id, name, role, password_hash, phone_number FROM users WHERE email = %s", (email,))
        result = db_cursor.fetchone()

        if result:
            pwd_hash = result['password_hash']
            if isinstance(pwd_hash, str):
                pwd_hash = pwd_hash.encode('utf-8')

            if bcrypt.checkpw(password.encode('utf-8'), pwd_hash):
                return {
                    "id": result['id'],
                    "name": result['name'],
                    "role": result['role'],
                    "email": email,
                    "phone": result['phone_number']
                }
    return None


def add_user(user_id, email, name, role, phone_number, password):
    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            db_cursor.execute(
                "INSERT INTO users (id, email, name, role, phone_number, password_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, email, name, role, phone_number, hashed_pw))
        load_users.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def update_user(current_id, new_id, email, name, role, phone_number, new_password=None):
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            if new_password:
                salt = bcrypt.gensalt()
                hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')
                db_cursor.execute(
                    "UPDATE users SET id = %s, email = %s, name = %s, role = %s, phone_number = %s, password_hash = %s WHERE id = %s",
                    (new_id, email, name, role, phone_number, hashed_pw, current_id))
            else:
                db_cursor.execute(
                    "UPDATE users SET id = %s, email = %s, name = %s, role = %s, phone_number = %s WHERE id = %s",
                    (new_id, email, name, role, phone_number, current_id))
        load_users.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def delete_user(user_id):
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    load_users.clear()


# =============================================================================
# CRUD pro klienty a produkty
# =============================================================================
def add_client(ic, name, total_sales, total_profitability, dealer):
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            db_cursor.execute(
                "INSERT INTO clients (ic, name, total_sales, total_profitability, dealer) VALUES (%s, %s, %s, %s, %s)",
                (ic, name, total_sales, total_profitability, dealer))
        load_clients.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def update_client(ic, name, total_sales, total_profitability, dealer):
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            db_cursor.execute(
                "UPDATE clients SET name=%s, total_sales=%s, total_profitability=%s, dealer=%s WHERE ic=%s",
                (name, total_sales, total_profitability, dealer, ic))
        load_clients.clear()
        return True
    except Exception:
        return False


def delete_client(ic):
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("DELETE FROM clients WHERE ic=%s", (ic,))
    load_clients.clear()


def add_product(name, storage_price):
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            db_cursor.execute("INSERT INTO products (name, storage_price) VALUES (%s, %s)",
                              (name, storage_price))
        load_products.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def update_product(prod_id, name, storage_price):
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            db_cursor.execute(
                "UPDATE products SET name = %s, storage_price = %s WHERE id = %s",
                (name, storage_price, prod_id))
        load_products.clear()
        return True
    except psycopg2.IntegrityError:
        return False


def delete_product(prod_id):
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("DELETE FROM products WHERE id = %s", (prod_id,))
    load_products.clear()


# =============================================================================
# Session Token Helpers
# =============================================================================
def set_session_token(user_id, token):
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("UPDATE users SET session_token = %s WHERE id = %s", (token, user_id))
    load_users.clear()


def clear_session_token(user_id):
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("UPDATE users SET session_token = NULL WHERE id = %s", (user_id,))
    load_users.clear()


@lru_cache(maxsize=128)
def get_user_by_token(token):
    db_conn = get_db_connection()
    with db_conn.cursor(cursor_factory=RealDictCursor) as db_cursor:
        db_cursor.execute("SELECT id, email, name, role, phone_number FROM users WHERE session_token = %s", (token,))
        result = db_cursor.fetchone()
        if result:
            return {
                "id": result['id'], "email": result['email'],
                "name": result['name'], "role": result['role'],
                "phone": result['phone_number']
            }
    return None


# =============================================================================
# Konstanty (Texty pro PDF)
# =============================================================================
PREP_A = [
    "",
    "Odstraňte olej a mastnotu vhodným detergentem. Soli a ostatní nečistoty odstraňte omytím vysokotlakou vodou. Po oschnutí otryskejte na Sa 2 1/2 dle ISO 8501-1.",
    "Odstraňte olej a mastnotu vhodným detergentem. Soli a ostatní nečistoty odstraňte omytím vysokotlakou čistou vodou."
]
PREP_B = [
    "",
    "Po oschnutí abrazivně otryskejte na Sa 1 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 3 dle (ČSN) ISO 8501-1. Odstraňte prach."
]
PREP_C = [
    "",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni N 9a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 9a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 10 dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 10a dle Rugotest No.3. Odstraňte prach.",
    "Po oschnutí abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1 s drsností povrchu odpovídající stupni BN 11 dle Rugotest No.3. Odstraňte prach.",
    "Příprava povrchu tryskáním na stupeň čistoty Sa 2 1/2 dle ČSN EN ISO 8501-1. Profil drsnosti povrchu střední (G) (ISO 8503-2)"
]
PREP_D = [
    "",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na PSa 2 1/2 dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na PSt 3 dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na PMa dle (ČSN) ISO 8501-2. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na Sa 2 1/2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa mechanicky očistěte na St 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí svary a poškozená místa abrazivně otryskejte na Sa 2 1/2 (není-li to možné, mechanicky očistěte na St3) dle (ČSN) ISO 8501-1. Odstraňte prach."
]
PREP_E = [
    "",
    "Po oschnutí mechanicky očistěte na St 2 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí mechanicky očistěte na St 3 dle (ČSN) ISO 8501-1. Odstraňte prach.",
    "Po oschnutí proveďte lehké abrazivní ometení za účelem zdrsnění povrchu. Odstraňte prach."
]
PREP_F = [
    "Případná \"bílá rez\" musí být odstraněna obroušením např. smirkovým papírem nebo lehkým abrazivním ometením.",
    "Základní nátěr na žárově stříkané povlaky má být dle platných norem zhotoven v témže dni (pracovní směně) jako metalizace.",
    "Základní nátěr naneste nejdříve naředěný (15-20%) ve slabé vrstvě, nechte uniknout vzduchové bublinky (10-15min.) a poté aplikujte plnou vrstvu.",
    "Všechny nepřilnavé staré nátěry musí být odstraněny a vzniklé ostré přechody se musí zabrousit do ztracena. Pevně přilnavý nátěr je nutné zdrsnit pro zajištění přilnavosti."
]

# =============================================================================
# App initialization and state management
# =============================================================================
st.set_page_config(page_title="CORROTECH CPQ", page_icon="img/corro-icon.svg", layout="wide")

if "authenticated" not in st.session_state:
    st.session_state.update({
        "authenticated": False,
        "user_id": None,
        "user_email": None,
        "user_name": None,
        "user_role": None,
        "user_phone": None
    })

cookie_manager = stx.CookieManager()

if not st.session_state["authenticated"]:
    stored_token = cookie_manager.get("cpq_session")
    if stored_token:
        fetched_user_data = get_user_by_token(stored_token)
        if fetched_user_data:
            st.session_state.update({
                "authenticated": True,
                "user_id": fetched_user_data["id"],
                "user_email": fetched_user_data["email"],
                "user_name": fetched_user_data["name"],
                "user_role": fetched_user_data["role"],
                "user_phone": fetched_user_data["phone"]
            })
            st.rerun()

# =============================================================================
# Helper function: Universal PDF Display
# =============================================================================
def show_pdf(pdf_binary, filename="Kalkulace.pdf", key=None):
    """Reliable PDF display for Streamlit Cloud across browsers."""
    st.subheader("Náhled PDF")

    shown = False

    # Native Streamlit PDF renderer (works best when available)
    try:
        if hasattr(st, "pdf"):
            st.pdf(pdf_binary)  # Streamlit >= version with st.pdf
            shown = True
    except Exception:
        shown = False

    # If native preview is unavailable/fails, show clear fallback message
    if not shown:
        st.warning(
            "Náhled PDF nelze v tomto prostředí zobrazit. "
            "Použijte stažení souboru níže."
        )

    # Always provide download
    st.download_button(
        label="Stáhnout PDF do zařízení",
        data=pdf_binary,
        file_name=filename,
        mime="application/pdf",
        icon=":material/download:",
        key=key
    )

# =============================================================================
# Login & Public Pages
# =============================================================================
def login_form():
    _logo1, _logo2, _logo3 = st.columns([1, 1, 1])
    with _logo2:
        st.image("img/corro.svg", use_container_width=True)

    _col1, _col2, _col3 = st.columns([1, 2, 1])
    with _col2:
        with st.form("login_form"):
            email = st.text_input("E-mail")
            password = st.text_input("Heslo", type="password")
            remember_me = st.checkbox("Zůstat přihlášen (7 dní)")
            submit = st.form_submit_button("Přihlásit se", use_container_width=True)

            if submit:
                logged_in_data = authenticate_user(email, password)
                if logged_in_data:
                    st.session_state.update({
                        "authenticated": True,
                        "user_id": logged_in_data["id"],
                        "user_email": logged_in_data["email"],
                        "user_name": logged_in_data["name"],
                        "user_role": logged_in_data["role"],
                        "user_phone": logged_in_data["phone"]
                    })

                    if remember_me:
                        new_token = str(uuid4())
                        set_session_token(logged_in_data["id"], new_token)
                        expire_date = datetime.datetime.now() + datetime.timedelta(days=7)
                        cookie_manager.set("cpq_session", new_token, expires_at=expire_date)

                    time.sleep(0.2)
                    st.rerun()
                else:
                    st.error("Špatný e-mail nebo heslo.")


def render_verify_page():
    st.title("Ověření pravosti kalkulace (PDF)")
    st.write(
        "Zadejte kód (Elektronickou stopu dokumentu / ID) z patičky PDF. Systém ověří pravost a otevře originální dokument.")

    verify_code = st.text_input("Kód dokumentu (ID):", placeholder="např. 4F8A3B2E-...")

    if st.button("Vyhledat a zobrazit", type="primary", icon=":material/visibility:"):
        if verify_code.strip():
            try:
                db_conn = get_db_connection()
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    v_cursor.execute(
                        "SELECT created_at, author_email, client_name, pdf_file FROM pdf_archive WHERE signature_id = %s",
                        (verify_code.strip(),)
                    )
                    result = v_cursor.fetchone()

                    if result:
                        st.success("✅ Dokument byl nalezen a ověřen!")

                        pdf_bytes = bytes(result['pdf_file'])
                        show_pdf(pdf_bytes, filename=f"Original_{result['client_name']}.pdf", key=f"dl_pub_{verify_code}")

                        with st.expander("Detaily dokumentu"):
                            st.write(f"**Datum vygenerování:** {result['created_at']}")
                            st.write(f"**Generoval:** {result['author_email']}")
                            st.write(f"**Poptávající firma:** {result['client_name']}")

                    else:
                        st.error("❌ Dokument s tímto kódem neexistuje.")
            except Exception as e:
                st.error(f"Chyba při prohledávání databáze: {e}")
        else:
            st.warning("Musíš zadat nějaký kód.")


if not st.session_state["authenticated"]:
    unauth_tabs = st.tabs(["🔒 Přihlášení do systému", "📄 Ověření pravosti PDF"])
    with unauth_tabs[0]:
        login_form()
    with unauth_tabs[1]:
        render_verify_page()
    st.stop()

# =============================================================================
# Sidebar navigation and layout
# =============================================================================
st.markdown("""
    <style>
    [data-testid="stSidebar"] {
        min-width: 220px !important;
        max-width: 220px !important;
    }

    [data-testid="stSidebar"] div.stButton > button p {
        display: block !important;
    }
    [data-testid="stSidebar"] div.stButton > button > div {
        justify-content: flex-start !important;
        padding-left: 10px;
    }
    </style>
""", unsafe_allow_html=True)

st.sidebar.image("img/corro.svg", use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.markdown(f"**{st.session_state['user_name']}** ({st.session_state['user_role']})")

if "current_page" not in st.session_state:
    st.session_state.current_page = "Dashboard"

page = st.session_state.current_page

if st.sidebar.button("Dashboard", icon=":material/dashboard:", use_container_width=True, type="primary" if page == "Dashboard" else "secondary"):
    st.session_state.current_page = "Dashboard"
    st.rerun()

if st.sidebar.button("Odběratelé", icon=":material/groups:", use_container_width=True, type="primary" if page == "Odběratelé" else "secondary"):
    st.session_state.current_page = "Odběratelé"
    st.rerun()

if st.sidebar.button("Analýza a Predikce", icon=":material/timeline:", use_container_width=True, type="primary" if page == "Analýza a Predikce" else "secondary"):
    st.session_state.current_page = "Analýza a Predikce"
    st.rerun()

if st.sidebar.button("Porovnání dealerů", icon=":material/bar_chart:", use_container_width=True, type="primary" if page == "Porovnání dealerů" else "secondary"):
    st.session_state.current_page = "Porovnání dealerů"
    st.rerun()

if st.sidebar.button("Archiv nabídek", icon=":material/folder_shared:", use_container_width=True, type="primary" if page == "Archiv nabídek" else "secondary"):
    st.session_state.current_page = "Archiv nabídek"
    st.rerun()

if st.sidebar.button("Můj profil", icon=":material/person:", use_container_width=True, type="primary" if page == "Můj profil" else "secondary"):
    st.session_state.current_page = "Můj profil"
    st.rerun()

if st.session_state["user_role"] == "Admin":
    if st.sidebar.button("Správa systému", icon=":material/settings:", use_container_width=True, type="primary" if page == "Správa systému (Admin)" else "secondary"):
        st.session_state.current_page = "Správa systému (Admin)"
        st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("Odhlásit se", icon=":material/logout:", use_container_width=True, type="secondary"):
    if st.session_state.get("user_id"):
        clear_session_token(st.session_state["user_id"])
    if cookie_manager.get("cpq_session"):
        cookie_manager.delete("cpq_session")
    st.session_state.clear()
    time.sleep(0.2)
    st.rerun()

st.sidebar.markdown("---")
page = st.session_state.current_page


# =============================================================================
# Main app routing
# =============================================================================

if page == "Dashboard":
    df_clients = load_clients()
    df_products = load_products()
    df_hmoty = load_pdf_hmoty()

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
                st.metric("Celková ziskovost bez DPH", f"{profit:,.0f} Kč".replace(",", " "))

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

    with st.expander("Nastavení projektu a dokumentu", expanded=True):
        col_doc1, col_doc2 = st.columns(2)
        with col_doc1:
            pdf_doc_no = st.text_input("Dokument č.", value=f"{datetime.date.today().year}DF01...")
            pdf_project = st.text_input("Projekt")
            pdf_temp = st.text_input("Provozní teplota", value="Do 120 °C")
            pdf_corr = st.text_input("Korozní zatížení", value="C4-High")
            pdf_sys_type = st.text_input("Typ nátěrového systému", value="EP/EP/PUR")

        with col_doc2:
            pdf_substrate = st.text_input("Podkladový materiál", value="Uhlíková ocel")
            pdf_client = st.text_area("Poptávající / Aplikační firma (může být více řádků)",
                                      value=selected_client if selected_client else "")
            pdf_area = st.number_input("Celková plocha (m²)", min_value=0.1, value=100.0, step=10.0)
            pdf_loss = st.number_input("Hlavní aplikační ztráta pro všechny nátěry (%)", min_value=0, max_value=100,
                                       value=50, step=5)
            pdf_validity = st.text_input("Platnost kalkulace do:", value="30 dní")

        pdf_pozn = st.text_input("Poznámka (1. řádek tabulky)", value="Protipožární ochrana PLATE15*200")

        st.markdown("#### Příprava povrchu (výběr) - max 3/4 pro 5 nátěrových vrstev")
        prep_a = st.selectbox("A - Základní čištění (vyberte max. 1)", PREP_A)
        prep_b = st.selectbox("B - Abrazivní tryskání plošné (vyberte max. 1)", PREP_B)
        prep_c = st.selectbox("C - Tryskání se specifikací drsnosti (vyberte max. 1)", PREP_C)
        prep_d = st.selectbox("D - Svary a lokální opravy (vyberte max. 1)", PREP_D)
        prep_e = st.selectbox("E - Mechanické a speciální plošné (vyberte max. 1)", PREP_E)
        prep_f = st.multiselect("F - Dodatečné pokyny (můžete vybrat více)", PREP_F)

    st.markdown("#### Nátěrové vrstvy")

    if 'pdf_rows' not in st.session_state:
        st.session_state.pdf_rows = []

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

    if st.button("Přidat vrstvu", icon=":material/add:"):
        st.session_state.pdf_rows.append({
            'typ': 'Základní', 'hmota': hmoty_options[0] if hmoty_options else "",
            'odstin': '', 'dft': 100.0, 'plocha': 100.0, 'c_l': 0.0, 'redeni': 5.0
        })
        st.rerun()

    if st.button("Vygenerovat PDF", type="primary", icon=":material/picture_as_pdf:"):
        doc_signature = str(uuid4()).upper()

        final_prep_texts = [p for p in [prep_a, prep_b, prep_c, prep_d, prep_e] if p.strip()] + prep_f

        header_info = {
            "doc_no": pdf_doc_no,
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

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.output(tmp.name)
            with open(tmp.name, "rb") as f:
                pdf_bytes = f.read()
        os.remove(tmp.name)

        try:
            db_conn = get_db_connection()
            with db_conn.cursor() as db_cursor:
                db_cursor.execute(
                    "INSERT INTO pdf_archive (signature_id, author_email, client_name, pdf_file) VALUES (%s, %s, %s, %s)",
                    (doc_signature, st.session_state.get("user_email", "Neznámý"), pdf_client,
                     psycopg2.Binary(pdf_bytes))
                )
        except Exception as e:
            st.warning(f"Kalkulace vygenerována, ale nepodařilo se ji uložit do archivu: {e}")

        st.download_button(
            label="Stáhnout PDF Kalkulaci",
            data=pdf_bytes,
            file_name=f"Kalkulace_{selected_client if selected_client else 'Neznamy'}.pdf",
            mime="application/pdf",
            icon=":material/download:",
            key=f"dl_new_{doc_signature}"
        )


elif page == "Můj profil":
    st.title("Můj profil")
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
                update_user(st.session_state["user_id"], st.session_state["user_id"], st.session_state["user_email"],
                            st.session_state["user_name"], st.session_state["user_role"],
                            st.session_state.get("user_phone", ""), new_pwd1)
                st.success("Heslo bylo úspěšně změněno!")
            else:
                st.error("Stávající heslo není správné.")


elif page == "Odběratelé":
    st.title("Odběratelé (Přehled a filtrace)")

    @st.dialog("Detail odběratele", width="large")
    def show_company_dialog(client_name, months, trend_values):
        st.write(f"## {client_name}")

        if st.button(
            "Přejít do Dashboardu",
            type="primary",
            use_container_width=True,
            icon=":material/dashboard:"
        ):
            st.session_state.current_page = "Dashboard"
            st.session_state.dashboard_selected_client = client_name
            st.rerun()

        st.markdown("---")
        st.markdown("##### Zvětšený graf vývoje obratu")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=months, y=trend_values, mode="lines+markers", line=dict(width=3, color="#1f77b4")))
        fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20), xaxis_title="", yaxis_title="Obrat (Kč)")
        st.plotly_chart(fig, use_container_width=True)

    df_monthly = load_monthly_sales()

    if df_monthly.empty:
        st.info("Zatím žádná data o prodejích.")
    else:
        df_monthly["dealer"] = df_monthly["dealer"].fillna("").astype(str)
        all_months = sorted(df_monthly["month"].unique().tolist(), reverse=True)
        all_dealers = sorted([d for d in df_monthly["dealer"].unique() if d.strip() != ""])
        all_clients = sorted(df_monthly["client_name"].unique().tolist())
        default_months = all_months[:12] if len(all_months) >= 12 else all_months

        st.markdown("### Filtrace dat")
        f_col1, f_col2, f_col3, f_col4 = st.columns([2, 2, 2, 1])

        with f_col1:
            sel_months = st.multiselect("Měsíce", all_months, default=default_months)
        with f_col2:
            sel_dealers = st.multiselect("Dealeři", all_dealers, default=[])
        with f_col3:
            sel_clients = st.multiselect("Firmy (konkrétní výběr)", all_clients, default=[])
        with f_col4:
            top_n = st.number_input("Limit top firem", min_value=1, value=20, step=10)

        filtered_df = df_monthly.copy()
        if sel_months:
            filtered_df = filtered_df[filtered_df["month"].isin(sel_months)]
        else:
            filtered_df = filtered_df.iloc[0:0]

        if sel_dealers:
            filtered_df = filtered_df[filtered_df["dealer"].isin(sel_dealers)]
        if sel_clients:
            filtered_df = filtered_df[filtered_df["client_name"].isin(sel_clients)]

        if filtered_df.empty:
            st.warning("Zadaným filtrům neodpovídají žádná data (nebo nejsou vybrány měsíce).")
        else:
            pivot_df = filtered_df.pivot_table(index=["client_name", "ic", "dealer"], columns="month", values="monthly_turnover", aggfunc="sum", fill_value=0)
            pivot_df["Celkem (vybrané období)"] = pivot_df.sum(axis=1)
            pivot_df = pivot_df.sort_values(by="Celkem (vybrané období)", ascending=False).reset_index()

            if not sel_clients:
                pivot_df = pivot_df.head(top_n)

            st.markdown(f"*Zobrazuji záznamy pro {len(pivot_df)} firem. **Kliknutím na řádek zobrazíš detaily.***")

            formatted_pivot = pivot_df.drop(columns=["ic"]).rename(columns={"client_name": "Firma", "dealer": "Dealer"})
            month_cols = sorted([c for c in formatted_pivot.columns if c not in ["Firma", "Dealer", "Celkem (vybrané období)"]])
            formatted_pivot["Trend"] = formatted_pivot[month_cols].values.tolist()

            for col in month_cols:
                formatted_pivot[col] = formatted_pivot[col].map(lambda x: f"{x:,.0f} Kč".replace(",", " ") if x > 0 else "-")

            max_sales = float(formatted_pivot["Celkem (vybrané období)"].max()) if not formatted_pivot.empty else 1000000
            cols_order = ["Firma", "Dealer", "Celkem (vybrané období)"] + month_cols + ["Trend"]
            formatted_pivot = formatted_pivot[cols_order]

            event = st.dataframe(
                formatted_pivot,
                hide_index=True,
                use_container_width=True,
                height=700,
                row_height=40,
                selection_mode="single-row",
                on_select="rerun",
                column_config={
                    "Firma": st.column_config.TextColumn("Firma", width="large"),
                    "Dealer": st.column_config.TextColumn("Dealer", width="medium"),
                    "Celkem (vybrané období)": st.column_config.ProgressColumn("Celkem", format="%d Kč", min_value=0, max_value=max_sales, width="medium"),
                    "Trend": st.column_config.LineChartColumn("Trend", y_min=0, width="medium")
                }
            )

            if len(event.selection.rows) > 0:
                selected_index = event.selection.rows[0]
                selected_row = formatted_pivot.iloc[selected_index]
                trend_data = selected_row["Trend"]
                show_company_dialog(selected_row["Firma"], month_cols, trend_data)


elif page == "Analýza a Predikce":
    import calendar

    st.title("Časové řady, Anomálie a Predikce")

    df_monthly = load_monthly_sales()

    if df_monthly.empty:
        st.info("Zatím nejsou k dispozici žádná data.")
    else:
        df_monthly['month_dt'] = pd.to_datetime(df_monthly['month'])

        # --- 1. Zjištění posledního data v databázi pro extrapolaci ---
        db_conn = get_db_connection()
        with db_conn.cursor() as cur:
            cur.execute("SELECT MAX(purchase_date) FROM invoices")
            max_date_val = cur.fetchone()[0]

        if not max_date_val:
            max_date_val = datetime.date.today()

        days_in_month = calendar.monthrange(max_date_val.year, max_date_val.month)[1]
        passed_days = max_date_val.day
        proration_factor = days_in_month / passed_days if passed_days > 0 else 1.0
        current_month_str = max_date_val.strftime('%Y-%m')

        # --- 2. Filtrování a Režim zobrazení ---
        main_view = st.radio("Základní pohled:", ["Celkový trh (Včetně anomálií)", "Výběr konkrétních firem"],
                             horizontal=True)

        # =====================================================================
        # VĚTEV A: CELKOVÝ TRH
        # =====================================================================
        if main_view == "Celkový trh (Včetně anomálií)":
            # Čisté záložky jen pro celkový trh
            tab1, tab2, tab3, tab4, tab5 = st.tabs(
                ["Vývoj a Šoky", "Sezónnost", "Podíl firem na trhu", "Predikce (Nástřel)", "Hlídač výpadků"])

            # Výpočty pro celkový trh
            ts_overall = df_monthly.groupby('month_dt')['monthly_turnover'].sum().reset_index()
            ts_overall = ts_overall.sort_values('month_dt')
            ts_overall['month_num'] = ts_overall['month_dt'].dt.month

            ts_completed = ts_overall[ts_overall['month_dt'] < pd.to_datetime(current_month_str)]

            if not ts_completed.empty:
                monthly_avg = ts_completed.groupby('month_num')['monthly_turnover'].mean()
                overall_avg = ts_completed['monthly_turnover'].mean()
                season_index = (monthly_avg / overall_avg).to_dict()
            else:
                season_index = {i: 1.0 for i in range(1, 13)}

            ts_overall['season_index'] = ts_overall['month_num'].map(season_index).fillna(1.0)
            ts_overall['adj_turnover'] = ts_overall['monthly_turnover'] / ts_overall['season_index']

            ts_overall.loc[ts_overall['month_dt'] == pd.to_datetime(current_month_str), 'prorated_turnover'] = \
            ts_overall['monthly_turnover'] * proration_factor
            ts_overall['prorated_turnover'] = ts_overall['prorated_turnover'].fillna(ts_overall['monthly_turnover'])

            window_size = 6
            ts_overall['trend'] = ts_overall['adj_turnover'].rolling(window=window_size, min_periods=1).mean()
            ts_overall['std'] = ts_overall['adj_turnover'].rolling(window=window_size, min_periods=3).std().fillna(0)
            ts_overall['upper_bound'] = ts_overall['trend'] + (1.96 * ts_overall['std'])
            ts_overall['lower_bound'] = ts_overall['trend'] - (1.96 * ts_overall['std'])

            anomalies_high = ts_overall[ts_overall['adj_turnover'] > ts_overall['upper_bound']]
            anomalies_low = ts_overall[
                (ts_overall['adj_turnover'] < ts_overall['lower_bound']) & (ts_overall['adj_turnover'] > 0)]

            # Vykreslení: Vývoj a Šoky
            with tab1:
                st.markdown("### Historický vývoj obratu")
                st.write(
                    "Graf zobrazuje **reálný obrat** a **sezónně očištěný obrat**. Očištěná křivka vyrovnává běžné výkyvy (např. očekávané slabé zimní měsíce). Šoky a anomálie systém detekuje výhradně z očištěných dat.")
                fig_ts = go.Figure()
                fig_ts.add_trace(go.Scatter(x=ts_overall['month_dt'], y=ts_overall['monthly_turnover'], mode='lines',
                                            name='Reálný obrat', line=dict(color='rgba(31, 119, 180, 0.7)', width=2)))
                fig_ts.add_trace(go.Scatter(x=ts_overall['month_dt'], y=ts_overall['adj_turnover'], mode='lines',
                                            name='Sezónně očištěný obrat', line=dict(color='#f39c12', width=3)))
                fig_ts.add_trace(go.Scatter(x=ts_overall['month_dt'], y=ts_overall['trend'], mode='lines',
                                            name='Trend (6M očištěný)',
                                            line=dict(color='#e74c3c', width=2, dash='dot')))
                fig_ts.add_trace(
                    go.Scatter(x=anomalies_high['month_dt'], y=anomalies_high['adj_turnover'], mode='markers',
                               name='Pozitivní šok',
                               marker=dict(color='green', size=10, symbol='circle-open', line=dict(width=2))))
                fig_ts.add_trace(
                    go.Scatter(x=anomalies_low['month_dt'], y=anomalies_low['adj_turnover'], mode='markers',
                               name='Negativní šok', marker=dict(color='red', size=10, symbol='x', line=dict(width=2))))

                fig_ts.update_layout(height=450, hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_ts, use_container_width=True)

            # Vykreslení: Sezónnost
            with tab2:
                st.markdown("### Sezónnost (Průměrný výkon v měsících)")
                st.write(
                    "Průměrný celkový obrat napříč všemi roky (pouze z uzavřených měsíců). Ukazuje silná a slabá období trhu.")
                cz_months = {1: 'Leden', 2: 'Únor', 3: 'Březen', 4: 'Duben', 5: 'Květen', 6: 'Červen', 7: 'Červenec',
                             8: 'Srpen', 9: 'Září', 10: 'Říjen', 11: 'Listopad', 12: 'Prosinec'}
                seasonality = ts_completed.groupby('month_num')['monthly_turnover'].mean().reindex(range(1, 13)).fillna(
                    0).reset_index()
                seasonality['month_name'] = seasonality['month_num'].map(cz_months)

                fig_season = go.Figure(go.Bar(
                    x=seasonality['month_name'],
                    y=seasonality['monthly_turnover'],
                    marker_color='#2ecc71',
                    text=seasonality['monthly_turnover'].apply(
                        lambda x: f"{x:,.0f} Kč".replace(",", " ") if x > 0 else ""),
                    textposition='auto'
                ))
                fig_season.update_layout(height=400, xaxis_title="", yaxis_title="Průměrný obrat (Kč)")
                st.plotly_chart(fig_season, use_container_width=True)

            # Vykreslení: Podíl firem (Pareto)
            with tab3:
                st.markdown("### Zásluha firem na celkovém obratu")
                st.write("Rozpad celkového obratu pro vybrané časové období.")

                sp_col1, sp_col2, sp_col3 = st.columns([1, 1, 2])
                with sp_col1:
                    share_period_type = st.radio("Časový úsek:", ["Celý rok", "Konkrétní měsíc"])
                with sp_col2:
                    if share_period_type == "Celý rok":
                        available_years = sorted(df_monthly['month_dt'].dt.year.unique().tolist(), reverse=True)
                        selected_period = st.selectbox("Vyber rok:", available_years)
                        df_share = df_monthly[df_monthly['month_dt'].dt.year == selected_period]
                    else:
                        available_months = sorted(df_monthly['month'].unique().tolist(), reverse=True)
                        selected_period = st.selectbox("Vyber měsíc:", available_months)
                        df_share = df_monthly[df_monthly['month'] == selected_period]
                with sp_col3:
                    top_share_n = st.slider("Oddělit do grafu Top X firem:", 1, 20, 5)

                if df_share.empty:
                    st.info("Pro vybrané období nejsou data.")
                else:
                    firm_totals = df_share.groupby('client_name')['monthly_turnover'].sum().sort_values(ascending=False)
                    total_turnover = firm_totals.sum()

                    top_firms_share = firm_totals.head(top_share_n)
                    others_share = firm_totals.iloc[top_share_n:].sum()

                    labels = top_firms_share.index.tolist()
                    values = top_firms_share.values.tolist()

                    if others_share > 0:
                        labels.append(f"Ostatní firmy ({len(firm_totals) - top_share_n})")
                        values.append(others_share)

                    fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.4, textinfo='percent+label',
                                                     hovertemplate="<b>%{label}</b><br>Obrat: %{value:,.0f} Kč<br>Podíl: %{percent}<extra></extra>")])

                    # Zvýšena výška a přidán velký spodní okraj (b=120), aby dlouhé názvy firem v legendě nepřetékaly mimo prvek
                    fig_pie.update_layout(height=550, margin=dict(l=0, r=0, t=20, b=120), showlegend=True)
                    st.plotly_chart(fig_pie, use_container_width=True)

                    st.metric(f"Celkový obrat trhu ({selected_period})", f"{total_turnover:,.0f} Kč".replace(",", " "))
                    top_pct = (top_firms_share.sum() / total_turnover) * 100 if total_turnover > 0 else 0
                    st.info(
                        f"💡 **Top {top_share_n} firem** z grafu generuje **{top_pct:.1f} %** celkového obratu v tomto období.")

            # Vykreslení: Predikce
            with tab4:
                st.markdown("### Krátkodobá predikce s extrapolací")
                st.info(
                    f"💡 **Info k datům:** Poslední faktura v systému je z **{max_date_val.strftime('%d.%m.%Y')}** (odjeto {passed_days} z {days_in_month} dnů). Aktuální měsíc je extrapolován koeficientem **{proration_factor:.2f}x**.")

                if len(ts_overall) >= 18:
                    last_date = ts_overall['month_dt'].max()
                    recent_3m = ts_overall.tail(3)['prorated_turnover'].sum()
                    last_year_3m = ts_overall[(ts_overall['month_dt'] >= last_date - pd.DateOffset(months=14)) & (
                                ts_overall['month_dt'] <= last_date - pd.DateOffset(months=12))][
                        'monthly_turnover'].sum()

                    growth_factor = (recent_3m / last_year_3m) if last_year_3m > 0 else 1.0
                    growth_factor = max(0.5, min(growth_factor, 1.5))

                    future_dates = [last_date + pd.DateOffset(months=i) for i in range(1, 4)]
                    future_vals = []

                    for d in future_dates:
                        hist_val = ts_overall[ts_overall['month_dt'] == (d - pd.DateOffset(years=1))][
                            'monthly_turnover'].sum()
                        future_vals.append(hist_val * growth_factor)

                    fig_pred = go.Figure()
                    closed_hist = ts_overall.iloc[:-1].tail(12)
                    current_m = ts_overall.tail(2)

                    fig_pred.add_trace(
                        go.Scatter(x=closed_hist['month_dt'], y=closed_hist['monthly_turnover'], mode='lines+markers',
                                   name='Uzavřené měsíce', line=dict(color='#1f77b4', width=2)))
                    fig_pred.add_trace(
                        go.Scatter(x=current_m['month_dt'], y=current_m['prorated_turnover'], mode='lines+markers',
                                   name='Aktuální měsíc (Dopočet)', line=dict(color='#1f77b4', width=2, dash='dot')))

                    conn_x = [ts_overall['month_dt'].iloc[-1], future_dates[0]]
                    conn_y = [ts_overall['prorated_turnover'].iloc[-1], future_vals[0]]
                    fig_pred.add_trace(go.Scatter(x=conn_x, y=conn_y, mode='lines', showlegend=False,
                                                  line=dict(color='#9b59b6', width=2, dash='dash')))
                    fig_pred.add_trace(
                        go.Scatter(x=future_dates, y=future_vals, mode='lines+markers', name='Výhled (Další 3 měsíce)',
                                   line=dict(color='#9b59b6', width=2, dash='dash')))

                    fig_pred.update_layout(height=400, hovermode="x unified")
                    st.plotly_chart(fig_pred, use_container_width=True)
                else:
                    st.warning("Pro smysluplnou predikci potřebuje systém data za více než 18 měsíců.")

            # Vykreslení: Hlídač výpadků
            with tab5:
                st.markdown("### Hlídač výpadků (Riziko ztráty klienta)")
                st.write(
                    "Hlídač analyzuje VŠECHNY firmy a hledá ty, které historicky odebíraly, ale poslední 2 **uzavřené** měsíce nemají tržbu.")

                df_completed_churn = df_monthly[df_monthly['month_dt'] < pd.to_datetime(current_month_str)]

                if not df_completed_churn.empty:
                    pivot_churn = df_completed_churn.pivot_table(index='client_name', columns='month_dt',
                                                                 values='monthly_turnover', aggfunc='sum').fillna(0)
                    churn_alerts = []
                    for client, row in pivot_churn.iterrows():
                        recent_6m = row.tail(6)
                        if len(recent_6m) == 6:
                            last_2m = recent_6m.tail(2).sum()
                            prev_4m = recent_6m.head(4).sum()
                            if prev_4m > 50000 and last_2m == 0:
                                churn_alerts.append({
                                    'Firma': client,
                                    'Obrat (4 měsíce před výpadkem)': prev_4m,
                                    'Obrat (poslední 2 uzavřené měsíce)': last_2m,
                                    'Status': '🔴 Kritický výpadek'
                                })
                    if churn_alerts:
                        df_churn = pd.DataFrame(churn_alerts).sort_values('Obrat (4 měsíce před výpadkem)',
                                                                          ascending=False)
                        df_churn['Obrat (4 měsíce před výpadkem)'] = df_churn['Obrat (4 měsíce před výpadkem)'].apply(
                            lambda x: f"{x:,.0f} Kč".replace(",", " "))
                        df_churn['Obrat (poslední 2 uzavřené měsíce)'] = "0 Kč"
                        st.dataframe(df_churn, use_container_width=True, hide_index=True)
                    else:
                        st.success(
                            "Vypadá to skvěle! Žádný z významných klientů nemá v posledních plných měsících kritický výpadek nákupů.")
                else:
                    st.info("Zatím není dostatek uzavřených měsíců pro výpočet výpadků.")


        # =====================================================================
        # VĚTEV B: VÝBĚR KONKRÉTNÍCH FIREM
        # =====================================================================
        elif main_view == "Výběr konkrétních firem":
            st.markdown("---")
            col_sel1, col_sel2 = st.columns([1, 1])

            selected_firms = []

            with col_sel1:
                selection_method = st.radio("Jak vybrat firmy:", ["Zadat ručně", "Top X firem automaticky"],
                                            horizontal=True)

                if selection_method == "Top X firem automaticky":
                    top_x_num = st.slider("Počet firem (Top X):", 1, 30, 5)
                    selected_firms = df_monthly.groupby('client_name')['monthly_turnover'].sum().nlargest(
                        top_x_num).index.tolist()
                    st.info(f"**Vybráno:** {', '.join(selected_firms)}")
                else:
                    all_clients = sorted(df_monthly["client_name"].unique().tolist())
                    selected_firms = st.multiselect("Vyber firmy ke srovnání:", all_clients)

            with col_sel2:
                display_type = st.radio("Způsob výpisu v grafu:",
                                        ["Jednotlivé čáry (max 10 firem)", "Souhrnný graf (Průměr vybraných)"],
                                        horizontal=True)
                plot_individual = display_type == "Jednotlivé čáry (max 10 firem)"
                show_average = not plot_individual

                if plot_individual and len(selected_firms) > 10:
                    st.warning("Při výběru více než 10 firem by byl graf nepřehledný. Bude zobrazeno pouze prvních 10.")
                    selected_firms = selected_firms[:10]

                # Zobrazí checkbox pro normalizaci jen pro jednotlivé firmy
                if plot_individual:
                    normalize_trend = st.checkbox("Porovnat pouze trend (Normalizace do stejného měřítka 0-100 %)",
                                                  help="Eliminuje rozdíly v objemech peněz. Historicky nejlepší měsíc každé firmy = 100 %. Zohlední se ve vývoji i sezónnosti.")
                else:
                    normalize_trend = False

            df_plot = df_monthly[df_monthly['client_name'].isin(selected_firms)].copy()

            # Čisté záložky jen pro výběr firem
            tab_v1, tab_v2 = st.tabs(["Porovnání vývoje", "Porovnání sezónnosti"])

            # Vykreslení: Vývoj firem
            with tab_v1:
                if df_plot.empty or not selected_firms:
                    st.info("Vyber alespoň jednu firmu pro zobrazení dat.")
                else:
                    fig_ts = go.Figure()
                    y_axis_title = "Obrat (% z historického maxima)" if normalize_trend else "Obrat (Kč)"

                    if plot_individual:
                        for firm in selected_firms:
                            f_data = df_plot[df_plot['client_name'] == firm].groupby('month_dt')[
                                'monthly_turnover'].sum().reset_index()
                            if normalize_trend and f_data['monthly_turnover'].max() > 0:
                                f_data['plot_val'] = (f_data['monthly_turnover'] / f_data[
                                    'monthly_turnover'].max()) * 100
                            else:
                                f_data['plot_val'] = f_data['monthly_turnover']
                            fig_ts.add_trace(
                                go.Scatter(x=f_data['month_dt'], y=f_data['plot_val'], mode='lines+markers', name=firm,
                                           line=dict(width=2)))

                    elif show_average:
                        agg_data = df_plot.groupby(['month_dt', 'client_name'])['monthly_turnover'].sum().reset_index()
                        avg_data = agg_data.groupby('month_dt')['monthly_turnover'].mean().reset_index()

                        # Normalizace u průměru se už neaplikuje, je vynucena na False
                        avg_data['plot_val'] = avg_data['monthly_turnover']

                        fig_ts.add_trace(
                            go.Scatter(x=avg_data['month_dt'], y=avg_data['plot_val'], mode='lines+markers',
                                       name='Průměr vybraných firem', line=dict(width=3, color='#9b59b6')))

                    fig_ts.update_layout(height=450, hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0),
                                         yaxis_title=y_axis_title)
                    st.plotly_chart(fig_ts, use_container_width=True)

            # Vykreslení: Sezónnost firem
            with tab_v2:
                cz_months = {1: 'Leden', 2: 'Únor', 3: 'Březen', 4: 'Duben', 5: 'Květen', 6: 'Červen', 7: 'Červenec',
                             8: 'Srpen', 9: 'Září', 10: 'Říjen', 11: 'Listopad', 12: 'Prosinec'}
                df_completed = df_plot[df_plot['month_dt'] < pd.to_datetime(current_month_str)].copy()

                if not df_completed.empty:
                    df_completed['month_num'] = df_completed['month_dt'].dt.month
                    fig_season = go.Figure()
                    y_axis_title_season = "Průměrný obrat (% z nejsilnějšího měsíce)" if normalize_trend else "Průměrný obrat (Kč)"

                    if plot_individual:
                        for firm in selected_firms:
                            f_season = df_completed[df_completed['client_name'] == firm].groupby('month_num')[
                                'monthly_turnover'].mean().reindex(range(1, 13)).fillna(0).reset_index()
                            f_season['month_name'] = f_season['month_num'].map(cz_months)

                            if normalize_trend and f_season['monthly_turnover'].max() > 0:
                                f_season['plot_val'] = (f_season['monthly_turnover'] / f_season[
                                    'monthly_turnover'].max()) * 100
                            else:
                                f_season['plot_val'] = f_season['monthly_turnover']

                            fig_season.add_trace(go.Bar(x=f_season['month_name'], y=f_season['plot_val'], name=firm))

                    elif show_average:
                        agg_season = df_completed.groupby(['month_num', 'client_name'])[
                            'monthly_turnover'].sum().reset_index()
                        avg_season = agg_season.groupby('month_num')['monthly_turnover'].mean().reindex(
                            range(1, 13)).fillna(0).reset_index()
                        avg_season['month_name'] = avg_season['month_num'].map(cz_months)

                        avg_season['plot_val'] = avg_season['monthly_turnover']

                        fig_season.add_trace(go.Bar(x=avg_season['month_name'], y=avg_season['plot_val'], name='Průměr',
                                                    marker_color='#9b59b6'))

                    fig_season.update_layout(height=400, barmode='group', xaxis_title="",
                                             yaxis_title=y_axis_title_season)
                    st.plotly_chart(fig_season, use_container_width=True)
                else:
                    st.info("Nedostatek uzavřených měsíců pro výpočet sezónnosti u těchto firem.")


elif page == "Porovnání dealerů":
    st.title("Porovnání výkonnosti dealerů")
    df_dealers = load_dealers_comparison()

    if df_dealers.empty:
        st.info("Zatím nejsou k dispozici žádná data z prodejů.")
    else:
        all_dealers = sorted(df_dealers['dealer'].unique().tolist())
        f_col1, f_col2 = st.columns([3, 1])
        with f_col1:
            top_3 = df_dealers.groupby('dealer')['turnover'].sum().sort_values(ascending=False).head(3).index.tolist()
            selected_dealers = st.multiselect("Vyber dealery k porovnání:", all_dealers, default=top_3)
        with f_col2:
            metric_to_show = st.selectbox("Zobrazovaná metrika:", ["Obrat", "Zisk (příprava)"])

        if not selected_dealers:
            st.warning("Vyber alespoň jednoho dealera.")
        else:
            val_col = 'turnover' if metric_to_show == "Obrat" else 'profit'
            df_plot = df_dealers[df_dealers['dealer'].isin(selected_dealers)].copy()
            st.markdown("### Meziroční porovnání (Aktuální měsíc vs. Loni)")
            max_month = df_plot['month'].max()

            try:
                yr, mo = max_month.split('-')
                last_year_month = f"{int(yr) - 1}-{mo}"
                kpi_cols = st.columns(len(selected_dealers))
                for idx, dealer in enumerate(selected_dealers):
                    dealer_data = df_plot[df_plot['dealer'] == dealer]
                    val_now = dealer_data[dealer_data['month'] == max_month][val_col].sum()
                    val_last_year = dealer_data[dealer_data['month'] == last_year_month][val_col].sum()
                    delta = val_now - val_last_year
                    delta_pct = (delta / val_last_year * 100) if val_last_year > 0 else 0.0

                    with kpi_cols[idx]:
                        st.metric(
                            label=f"{dealer} ({mo}/{yr})",
                            value=f"{val_now:,.0f} Kč".replace(",", " "),
                            delta=f"{delta:,.0f} Kč ({delta_pct:+.1f} %)".replace(",", " ") if val_last_year > 0 else "Žádná data z loňska",
                            delta_color="normal"
                        )
            except Exception:
                st.info("Nemám dostatek dat pro meziroční srovnání (YoY).")

            st.markdown("---")
            st.subheader(f"Měsíční vývoj ({metric_to_show})")
            pivot_time = df_plot.pivot(index='month', columns='dealer', values=val_col).fillna(0)

            fig_time = go.Figure()
            for col in pivot_time.columns:
                fig_time.add_trace(go.Scatter(x=pivot_time.index, y=pivot_time[col], mode='lines+markers', name=col, line=dict(width=3)))

            fig_time.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Měsíc", yaxis_title=f"{metric_to_show} (Kč)", hovermode="x unified")
            st.plotly_chart(fig_time, use_container_width=True)

            st.subheader(f"Kumulativní růst v aktuálním roce ({metric_to_show})")
            current_year = max_month.split('-')[0]
            df_ytd = df_plot[df_plot['month'].str.startswith(current_year)].copy()

            if not df_ytd.empty:
                df_ytd = df_ytd.sort_values(by=['dealer', 'month'])
                df_ytd['cumulative'] = df_ytd.groupby('dealer')[val_col].cumsum()
                pivot_ytd = df_ytd.pivot(index='month', columns='dealer', values='cumulative').ffill().fillna(0)

                fig_ytd = go.Figure()
                for col in pivot_ytd.columns:
                    fig_ytd.add_trace(go.Scatter(x=pivot_ytd.index, y=pivot_ytd[col], mode='lines', name=col, fill='tozeroy', line=dict(width=2)))

                fig_ytd.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Měsíc", yaxis_title=f"Kumulativní {metric_to_show} (Kč)", hovermode="x unified")
                st.plotly_chart(fig_ytd, use_container_width=True)
            else:
                st.info(f"Pro rok {current_year} nejsou zatím žádná data k zobrazení.")


elif page == "Archiv nabídek":
    st.title("Archiv cenových nabídek")

    @st.dialog("Potvrzení smazání")
    def confirm_delete_dialog(sig_id):
        st.warning("Opravdu chceš nenávratně smazat tuto kalkulaci z archivu? Tuto akci nelze vzít zpět.")
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("Ano, smazat", type="primary", use_container_width=True):
                try:
                    conn = get_db_connection()
                    with conn.cursor() as c:
                        c.execute("DELETE FROM pdf_archive WHERE signature_id = %s", (sig_id,))
                    st.success("Smazáno!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Chyba při mazání: {e}")
        with dc2:
            if st.button("Zrušit", use_container_width=True):
                st.rerun()

    tab1, tab2, tab3 = st.tabs(["Moje nabídky", "Sdílené (Finální)", "Vyhledat podle kódu (Ověření)"])
    db_conn = get_db_connection()

    with tab1:
        with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
            v_cursor.execute(
                "SELECT signature_id, created_at, client_name, is_final FROM pdf_archive WHERE author_email = %s ORDER BY created_at DESC",
                (st.session_state["user_email"],)
            )
            my_docs = v_cursor.fetchall()

        if my_docs:
            options = {doc['signature_id']: f"{'✅ FINÁLNÍ' if doc['is_final'] else '🔒 SOUKROMÉ'} | {doc['created_at'].strftime('%d.%m.%Y %H:%M')} | {doc['client_name']}" for doc in my_docs}
            selected_my_id = st.selectbox("Vyber nabídku k zobrazení / úpravě:", options=list(options.keys()), format_func=lambda x: options[x], key="my_docs_sel")

            if selected_my_id:
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    # Zde jsem doplnil do dotazu i vytažení jména klienta
                    v_cursor.execute("SELECT is_final, pdf_file, client_name FROM pdf_archive WHERE signature_id = %s", (selected_my_id,))
                    doc_detail = v_cursor.fetchone()

                current_status = doc_detail['is_final']
                col_btn1, col_btn2, col_spacer = st.columns([2, 1, 1])

                with col_btn1:
                    if not current_status:
                        if st.button("Odemknout pro ostatní (Označit jako Finální)", type="primary", use_container_width=True):
                            with db_conn.cursor() as c:
                                c.execute("UPDATE pdf_archive SET is_final = TRUE WHERE signature_id = %s", (selected_my_id,))
                            st.rerun()
                    else:
                        if st.button("Zamknout (Zrušit finální status)", use_container_width=True):
                            with db_conn.cursor() as c:
                                c.execute("UPDATE pdf_archive SET is_final = FALSE WHERE signature_id = %s", (selected_my_id,))
                            st.rerun()

                with col_btn2:
                    if st.button("🗑️ Zahodit", use_container_width=True):
                        confirm_delete_dialog(selected_my_id)

                st.markdown("---")
                # Voláme s upraveným klíčem a vytahujeme client_name korektně z db dotazu.
                show_pdf(bytes(doc_detail['pdf_file']), filename=f"Kalkulace_{doc_detail['client_name']}.pdf", key=f"dl_my_{selected_my_id}")
        else:
            st.info("Zatím jsi nevygeneroval/a žádné nabídky.")

    with tab2:
        with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
            v_cursor.execute(
                "SELECT signature_id, created_at, client_name, author_email FROM pdf_archive WHERE is_final = TRUE ORDER BY created_at DESC"
            )
            shared_docs = v_cursor.fetchall()

        if shared_docs:
            options_shared = {doc['signature_id']: f"{doc['created_at'].strftime('%d.%m.%Y')} | {doc['client_name']} | (Autor: {doc['author_email']})" for doc in shared_docs}
            selected_shared_id = st.selectbox("Vyber finální nabídku k zobrazení:", options=list(options_shared.keys()), format_func=lambda x: options_shared[x], key="shared_docs_sel")

            if selected_shared_id:
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    # Doplnění client_name
                    v_cursor.execute("SELECT pdf_file, client_name FROM pdf_archive WHERE signature_id = %s", (selected_shared_id,))
                    shared_detail = v_cursor.fetchone()

                st.markdown("---")
                show_pdf(bytes(shared_detail['pdf_file']), filename=f"Kalkulace_{shared_detail['client_name']}.pdf", key=f"dl_shared_{selected_shared_id}")
        else:
            st.info("Nikdo zatím nesdílel žádnou finální nabídku.")

    with tab3:
        st.write("Zadej ID kód dokumentu. Lze tak dohledat i soukromé (nefinální) nabídky kolegů, pokud ti k nim dají klíč.")
        verify_code = st.text_input("Kód dokumentu (ID):", placeholder="např. 4F8A3B2E-...")

        if st.button("Vyhledat a zobrazit", type="primary", icon=":material/search:"):
            if verify_code.strip():
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    v_cursor.execute("SELECT pdf_file, client_name, author_email FROM pdf_archive WHERE signature_id = %s", (verify_code.strip(),))
                    result = v_cursor.fetchone()

                if result:
                    st.success(f"✅ Dokument nalezen (Klient: {result['client_name']}, Autor: {result['author_email']})")
                    show_pdf(bytes(result['pdf_file']), filename=f"Original_{result['client_name']}.pdf", key=f"dl_verify_{verify_code}")
                else:
                    st.error("❌ Dokument s tímto kódem neexistuje.")
            else:
                st.warning("Musíš zadat kód.")


elif page == "Správa systému (Admin)":
    st.title("Správa systému")

    df_users = load_users()
    df_clients = load_clients()
    df_products = load_products()

    main_tabs = st.tabs(["Uživatelé", "Firmy", "Produkty", "Prodeje"])

    with main_tabs[0]:
        st.dataframe(df_users, use_container_width=True, hide_index=True)
        st.markdown("---")
        utab1, utab2, utab3 = st.tabs(["Přidat uživatele", "Upravit uživatele", "Smazat uživatele"])

        with utab1:
            with st.form("add_user_form", clear_on_submit=True):
                n_id = st.text_input("ID uživatele (VARCHAR identifikátor)")
                n_name = st.text_input("Jméno a příjmení")
                n_email = st.text_input("E-mail")
                n_phone = st.text_input("Telefonní číslo")
                n_role = st.selectbox("Role", ["User", "Admin"])
                n_pass = st.text_input("Heslo", type="password")
                if st.form_submit_button("Vytvořit účet"):
                    if all([n_id, n_name, n_email, n_pass]):
                        if add_user(n_id, n_email, n_name, n_role, n_phone, n_pass):
                            st.success("Přidáno!")
                            st.rerun()
                        else:
                            st.error("Uživatel s tímto e-mailem nebo ID už existuje.")
                    else:
                        st.warning("Vyplňte vše kromě telefonu (ten je nepovinný).")

        with utab2:
            u_edit = st.selectbox("Vyber uživatele k úpravě", df_users['email'].tolist(), key="u_edit_sel")
            if u_edit:
                u_row = df_users[df_users['email'] == u_edit].iloc[0]
                with st.form("edit_user_form"):
                    e_id = st.text_input("ID uživatele", value=str(u_row['id']))
                    e_name = st.text_input("Jméno", value=u_row['name'])
                    e_email = st.text_input("E-mail", value=u_row['email'])
                    e_phone_val = "" if pd.isna(u_row.get('phone_number')) else str(u_row.get('phone_number'))
                    e_phone = st.text_input("Telefonní číslo", value=e_phone_val)

                    e_role = st.selectbox("Role", ["User", "Admin"], index=0 if u_row['role'] == "User" else 1)
                    e_pass = st.text_input("Nové heslo (nepovinné)", type="password")
                    if st.form_submit_button("Uložit"):
                        if e_id and e_name and e_email:
                            if update_user(str(u_row['id']), e_id, e_email, e_name, e_role, e_phone,
                                           e_pass if e_pass else None):
                                st.success("Uloženo!")
                                if u_row['email'] == st.session_state['user_email']:
                                    st.session_state.update({'user_name': e_name, 'user_role': e_role, 'user_id': e_id,
                                                             'user_phone': e_phone})
                                st.rerun()
                            else:
                                st.error("ID nebo E-mail koliduje.")
                        else:
                            st.warning("ID, jméno a e-mail musí být vyplněny.")

        with utab3:
            u_del = st.selectbox("Vyber uživatele ke smazání", df_users['email'].tolist(), key="u_del_sel")
            if u_del:
                if u_del == st.session_state["user_email"]:
                    st.warning("Nemůžeš smazat sám sebe.")
                elif st.button("Smazat účet", type="primary"):
                    delete_user(str(df_users[df_users['email'] == u_del].iloc[0]['id']))
                    st.success("Smazáno.")
                    st.rerun()

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
                            df_raw = xls.parse(sheet_name=sheet, header=None, nrows=20)

                            header_idx = 0
                            for idx, row in df_raw.iterrows():
                                row_str = ' '.join([str(val).lower() for val in row.values if pd.notna(val)])
                                if 'ič' in row_str or 'ic' in row_str or 'firma' in row_str or 'název' in row_str or 'odběratel' in row_str:
                                    header_idx = idx
                                    break

                            df_sheet = xls.parse(sheet_name=sheet, header=header_idx)

                            if isinstance(df_sheet, pd.DataFrame):
                                df_sheet = df_sheet.dropna(how='all', axis=1)
                                df_sheet.columns = [str(c).replace('\n', ' ').strip() for c in df_sheet.columns]
                                all_dataframes.append(df_sheet)

                        if not all_dataframes:
                            st.warning("Nebyla nalezena žádná smysluplná data ve vybraných listech.")
                        else:
                            df_import = pd.concat(all_dataframes, ignore_index=True)
                            col_options = df_import.columns.tolist()

                            def_ic = next((c for c in col_options if 'ič' in str(c).lower() or 'ic' in str(c).lower()), col_options[0])
                            def_name = next((c for c in col_options if 'firma' in str(c).lower() or 'název' in str(c).lower() or 'odběratel' in str(c).lower()), col_options[0])
                            def_dealer = next((c for c in col_options if 'dealer' in str(c).lower() or 'zástupce' in str(c).lower()), col_options[0])

                            st.markdown("### 2. Spárování sloupců z Excelu na Databázi")
                            map_ic = st.selectbox("Sloupec s IČ (Povinné):", col_options, index=col_options.index(def_ic))
                            map_name = st.selectbox("Sloupec s Názvem firmy (Povinné):", col_options, index=col_options.index(def_name))
                            map_dealer = st.selectbox("Sloupec s Dealerem:", col_options, index=col_options.index(def_dealer))

                            sum_sales_cols = st.multiselect("Sloupce k sečtení do 'Celkového obratu bez DPH':", col_options,
                                                            default=[c for c in col_options if 'obrat' in str(c).lower() and 'bez dph' in str(c).lower()])
                            sum_prof_cols = st.multiselect("Sloupce k sečtení do 'Ziskovosti (hrubý zisk bez DPH)':", col_options,
                                                           default=[c for c in col_options if 'zisk' in str(c).lower() and 'bez dph' in str(c).lower()])

                            if st.button("Spustit import...", type="primary", icon=":material/rocket_launch:"):
                                runtime_db_conn = get_db_connection()
                                clients_dict = {}

                                for index, row in df_import.iterrows():
                                    c_ic = str(row[map_ic]).strip()
                                    c_name = str(row[map_name]).strip()

                                    if not c_ic or c_ic.lower() == 'nan' or not c_name or c_name.lower() == 'nan':
                                        continue

                                    c_dealer = str(row[map_dealer]).strip() if pd.notna(row[map_dealer]) else ""

                                    excel_total_sales = 0.0
                                    for sc in sum_sales_cols:
                                        if pd.notna(row[sc]):
                                            try:
                                                excel_total_sales += float(row[sc])
                                            except ValueError:
                                                pass

                                    excel_total_prof = 0.0
                                    for pc in sum_prof_cols:
                                        if pd.notna(row[pc]):
                                            try:
                                                excel_total_prof += float(row[pc])
                                            except ValueError:
                                                pass

                                    if c_ic in clients_dict:
                                        clients_dict[c_ic]['sales'] += excel_total_sales
                                        clients_dict[c_ic]['prof'] += excel_total_prof
                                        if c_dealer and not clients_dict[c_ic]['dealer']:
                                            clients_dict[c_ic]['dealer'] = c_dealer
                                    else:
                                        clients_dict[c_ic] = {
                                            'name': c_name,
                                            'dealer': c_dealer,
                                            'sales': excel_total_sales,
                                            'prof': excel_total_prof
                                        }

                                imported_count = 0
                                with runtime_db_conn.cursor() as r_cursor:
                                    for ic_key, data in clients_dict.items():
                                        r_cursor.execute('''
                                                         INSERT INTO clients (ic, name, total_sales, total_profitability, dealer)
                                                         VALUES (%s, %s, %s, %s, %s) ON CONFLICT (ic) DO
                                                         UPDATE
                                                             SET name = EXCLUDED.name,
                                                             total_sales = EXCLUDED.total_sales,
                                                             total_profitability = EXCLUDED.total_profitability,
                                                             dealer = EXCLUDED.dealer
                                                         ''',
                                                         (ic_key, data['name'], data['sales'], data['prof'], data['dealer']))

                                        imported_count += 1

                                load_clients.clear()
                                st.success(f"Úspěšně naimportováno / zaktualizováno {imported_count} unikátních firem (sloučeno ze {len(selected_sheets)} listů)!")
                                st.rerun()

                except Exception as ex:
                    st.error(f"Při zpracování Excelu došlo k chybě: {ex}")

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

        with main_tabs[3]:
            st.subheader("Import prodejů z Excelu")
            st.info("Nahraj soubor s prodeji. Systém automaticky založí chybějící produkty a firmy. U stávajících firem tvrdě aktualizuje Kód dealera podle Excelu.")

            uploaded_sales = st.file_uploader("Nahrát Excel s prodeji", type=["xlsx", "xls"], key="sales_uploader")

            if uploaded_sales:
                try:
                    df_sales = pd.read_excel(uploaded_sales)
                    required_cols = ['Doklad', 'Kód subjektu', 'Jednotková cena', 'Kód zboží', 'Název zboží', 'Datum', 'Množství']
                    missing_cols = [c for c in required_cols if c not in df_sales.columns]

                    if missing_cols:
                        st.error(f"V Excelu chybí tyto povinné sloupce: {', '.join(missing_cols)}. Zkontroluj hlavičku.")
                    else:
                        if st.button("Spustit import prodejů", type="primary", icon=":material/cloud_upload:"):
                            sales_db_conn = get_db_connection()

                            created_products = 0
                            created_clients = 0
                            updated_dealers = 0
                            imported_count = 0
                            skipped_count = 0
                            fk_error_count = 0

                            with sales_db_conn.cursor() as s_cursor:
                                unique_prods = df_sales[['Kód zboží', 'Název zboží']].drop_duplicates().dropna(subset=['Kód zboží'])
                                for _, p_row in unique_prods.iterrows():
                                    p_id = str(p_row['Kód zboží']).strip()
                                    if not p_id or p_id.lower() == 'nan': continue

                                    s_cursor.execute("SELECT id FROM products WHERE id = %s", (p_id,))
                                    if not s_cursor.fetchone():
                                        p_name = str(p_row['Název zboží']).strip()
                                        if not p_name or p_name.lower() == 'nan':
                                            p_name = f"Neznámý produkt {p_id}"

                                        s_cursor.execute("SELECT id FROM products WHERE name = %s", (p_name,))
                                        if s_cursor.fetchone():
                                            p_name = f"{p_name} ({p_id})"

                                        try:
                                            s_cursor.execute("INSERT INTO products (id, name, storage_price) VALUES (%s, %s, %s)", (p_id, p_name, 0.0))
                                            created_products += 1
                                        except Exception:
                                            pass

                                has_dealer_col = 'Kód dealera' in df_sales.columns
                                cols_to_extract = ['Kód subjektu', 'Název subjektu']
                                if has_dealer_col:
                                    cols_to_extract.append('Kód dealera')

                                unique_clients = df_sales[cols_to_extract].drop_duplicates().dropna(subset=['Kód subjektu'])

                                for _, c_row in unique_clients.iterrows():
                                    c_ic = str(c_row['Kód subjektu']).strip()
                                    if not c_ic or c_ic.lower() == 'nan': continue

                                    c_name = str(c_row['Název subjektu']).strip()
                                    if not c_name or c_name.lower() == 'nan':
                                        c_name = f"Neznámá firma ({c_ic})"

                                    c_dealer = ""
                                    if has_dealer_col and pd.notna(c_row.get('Kód dealera')):
                                        c_dealer = str(c_row['Kód dealera']).strip()
                                        if c_dealer.lower() == 'nan': c_dealer = ""

                                    s_cursor.execute("SELECT ic, dealer FROM clients WHERE ic = %s", (c_ic,))
                                    existing_client = s_cursor.fetchone()

                                    if not existing_client:
                                        try:
                                            s_cursor.execute(
                                                "INSERT INTO clients (ic, name, total_sales, total_profitability, dealer) VALUES (%s, %s, %s, %s, %s)",
                                                (c_ic, c_name, 0.0, 0.0, c_dealer)
                                            )
                                            created_clients += 1
                                        except Exception:
                                            pass
                                    else:
                                        db_dealer = existing_client[1]
                                        if c_dealer and str(db_dealer).strip() != c_dealer:
                                            try:
                                                s_cursor.execute("UPDATE clients SET dealer = %s WHERE ic = %s", (c_dealer, c_ic))
                                                updated_dealers += 1
                                            except Exception:
                                                pass

                                for index, row in df_sales.iterrows():
                                    doklad = str(row['Doklad']).strip()
                                    excel_prod_id = str(row['Kód zboží']).strip()
                                    client_ic = str(row['Kód subjektu']).strip()

                                    if not doklad or doklad.lower() == 'nan' or not excel_prod_id or excel_prod_id.lower() == 'nan' or not client_ic or client_ic.lower() == 'nan':
                                        continue

                                    try:
                                        price = int(round(float(row['Jednotková cena']))) if pd.notna(row['Jednotková cena']) else 0
                                        quantity = int(round(float(row['Množství']))) if pd.notna(row['Množství']) else 0
                                    except ValueError:
                                        price, quantity = 0, 0

                                    try:
                                        purchase_date = pd.to_datetime(row['Datum']).date()
                                    except Exception:
                                        purchase_date = None

                                    try:
                                        s_cursor.execute('''
                                                         INSERT INTO invoices (id, client_ic, price, product_id, purchase_date, quantity)
                                                         VALUES (%s, %s, %s, %s, %s, %s)
                                                         ON CONFLICT (id, product_id) DO NOTHING
                                                         ''',
                                                         (doklad, client_ic, price, excel_prod_id, purchase_date, quantity))

                                        if s_cursor.rowcount > 0:
                                            imported_count += 1
                                        else:
                                            skipped_count += 1
                                    except psycopg2.IntegrityError:
                                        fk_error_count += 1

                            load_products.clear()
                            load_clients.clear()
                            load_client_invoices.clear()

                            st.success(f"Hotovo! Naimportováno: {imported_count} nových prodejů. Přeskočeno duplikátů: {skipped_count}.")

                            if created_products > 0 or created_clients > 0 or updated_dealers > 0:
                                st.info(f"✨ Automatické akce na pozadí: založeno **{created_products} nových produktů**, založeno **{created_clients} nových firem** a opraven kód dealera u **{updated_dealers} stávajících firem**.")

                            if fk_error_count > 0:
                                st.warning(f"⚠️ Zahozeno {fk_error_count} záznamů kvůli nějaké neočekávané chybě integrity (foreign key constraint).")

                except Exception as e:
                    st.error(f"Během zpracování Excelu došlo k chybě: {e}")