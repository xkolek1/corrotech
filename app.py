# =============================================================================
# Imports & App Configuration
# =============================================================================
# Streamlit pro vykreslení frontend UI, psycopg2 pro napojení na PostgreSQL.
# bcrypt používáme pro bezpečné hashování hesel, a pandas klasicky pro práci s daty (tabulky, importy z Excelu).
# Plotly na grafy v dashboardu.
import time
import os
import uuid
import datetime
import tempfile
import streamlit as st
import extra_streamlit_components as stx
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import pandas as pd
import plotly.graph_objects as go
from functools import lru_cache

from pdf_generator import KalkulacePDF

# Tajnosti (hesla, URL) si Streamlit bere ze souboru secrets.toml
DATABASE_URL = st.secrets["postgres"]["DATABASE_URL"]


# =============================================================================
# Database Connection & Initialization
# =============================================================================

def validate_db_connection(db_conn):
    # Rychlá kontrola, jestli nám spojení s databází neumřelo na timeout.
    # Zkusíme poslat jednoduchý dotaz "SELECT 1". Pokud to spadne nebo je spojení zavřené, vrátíme False.
    try:
        if db_conn.closed != 0:
            return False
        with db_conn.cursor() as db_cursor:
            db_cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


# @st.cache_resource drží to spojení otevřené pro všechny uživatele aplikace, dokud to jde,
# abychom se nemuseli přihlašovat k DB při každém kliknutí.
# Argument 'validate' používá funkci výše k ověření, jestli se spojení nemusí vytvořit znovu.
@st.cache_resource(validate=validate_db_connection)
def get_db_connection():
    try:
        # sslmode='require' je často nutnost pro cloudové databáze (Supabase, Neon, atd.)
        db_conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        # Autocommit znamená, že nemusíme po každém INSERT/UPDATE dělat db_conn.commit(). Udělá se to samo.
        db_conn.autocommit = True
        return db_conn
    except Exception as db_err:
        st.error(f"Chyba při připojování k PostgreSQL: {db_err}")
        st.stop()


# =============================================================================
# Cached Data Loading Functions
# =============================================================================
# Streamlit při každé interakci překresluje celou stránku. Abychom databázi neudusili dotazy,
# cachujeme výsledky na 5 minut (ttl=300). Pokud se data změní (třeba admin přidá klienta),
# musíme tuto cache manuálně vyčistit (což děláme dole v CRUD funkcích pomocí např. load_clients.clear()).

@st.cache_data(ttl=300)
def load_clients():
    db_conn = get_db_connection()
    return pd.read_sql_query("SELECT ic, name, total_sales, total_profitability, dealer FROM clients", db_conn)


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


# =============================================================================
# Auth Helpers (Authentication & User Management)
# =============================================================================
# Tyto funkce se starají o přihlašování a správu uživatelů v systému.

def authenticate_user(email, password):
    # Vyhledá uživatele podle e-mailu. RealDictCursor nám vrátí výsledky jako slovník (dictionary),
    # takže se k datům dostaneme přes klíče (např. result['name']) místo číselných indexů.
    db_conn = get_db_connection()
    with db_conn.cursor(cursor_factory=RealDictCursor) as db_cursor:
        db_cursor.execute("SELECT id, name, role, password_hash, phone_number FROM users WHERE email = %s", (email,))
        result = db_cursor.fetchone()

        if result:
            # Bcrypt porovnává byty. Pokud nám databáze vrátila string, převedeme ho na byty.
            pwd_hash = result['password_hash']
            if isinstance(pwd_hash, str):
                pwd_hash = pwd_hash.encode('utf-8')

            # Porovnáme zadané heslo s hashem z DB. Zadané heslo taky musíme převést na byty.
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
    # Vygenerujeme sůl a zahashujeme heslo, ať v DB nejsou hesla v čitelné podobě (plain text).
    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as db_cursor:
            db_cursor.execute(
                "INSERT INTO users (id, email, name, role, phone_number, password_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, email, name, role, phone_number, hashed_pw))
        # Nutné! Po přidání uživatele mažeme cache, ať to admin vidí hned v tabulce.
        load_users.clear()
        return True
    except psycopg2.IntegrityError:
        # Padne sem, pokud už existuje uživatel se stejným ID nebo emailem (jestliže na ně máš v DB UNIQUE constraint).
        return False


def update_user(current_id, new_id, email, name, role, phone_number, new_password=None):
    # Aktualizace uživatele. Rozdělil jsem to na dva bloky: pokud posíláme i nové heslo (pak ho zahashujeme),
    # nebo pokud měníme jen údaje a heslo necháváme staré.
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
# Client & Product Management Helpers (CRUD)
# =============================================================================
# Stejný princip jako u uživatelů – vkládáme, updatujeme nebo mažeme záznamy.
# Vždy nezapomeneme na konci zavolat metodu .clear() na příslušné cache funkci.

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
# Session & Cookie Helpers
# =============================================================================
# Tady ukládáme (a načítáme) vygenerovaný unikátní token do DB. Slouží to k tomu,
# aby si systém pamatoval přihlášeného uživatele i poté, co zavře prohlížeč (díky cookies).

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


# Tohle se ptá DB na konkrétního uživatele na základě tokenu z cookie.
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
# Surface Preparation Constants
# =============================================================================
# Čistě statická data – pole textů (optionů), ze kterých si uživatel vybírá při
# generování PDF nabídky v sekci "Příprava povrchu". Rozděleno do kategorií A až F.

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
# App Initialization & State Management
# =============================================================================
# Nastaví základní layout aplikace (ikonka v tabu, roztáhnutí přes celý monitor).
st.set_page_config(page_title="CORROTECH CPQ", page_icon="img/corro-icon.svg", layout="wide")

# Inicializace stavu (session_state). Pokud tu uživatel je poprvé, nastavíme mu všechny
# proměnné na None a dáme authenticated = False. Tyto proměnné pak aplikace po celou
# dobu používá k tomu, aby věděla, kdo se zrovna kouká (jestli je to třeba Admin).
if "authenticated" not in st.session_state:
    st.session_state.update({
        "authenticated": False,
        "user_id": None,
        "user_email": None,
        "user_name": None,
        "user_role": None,
        "user_phone": None
    })

# Správce cookies. Přes něj čteme, jestli nemá uživatel uložený login token z minula.
cookie_manager = stx.CookieManager()

# Zkusíme autologin, pokud uživatel není ověřený, ale má uloženou session cookie.
if not st.session_state["authenticated"]:
    stored_token = cookie_manager.get("cpq_session")
    if stored_token:
        fetched_user_data = get_user_by_token(stored_token)
        if fetched_user_data:
            # Pokud token z cookie platí a našli jsme k němu uživatele v DB,
            # rovnou ho přihlásíme (nastavíme session state) a provedeme reload stránky (st.rerun).
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
# Login Form Component
# =============================================================================
def login_form():
    # Kód pro vycentrování loga. Používáme sloupce, aby bylo logo uprostřed s nějakými okraji.
    _logo1, _logo2, _logo3 = st.columns([1, 1, 1])
    with _logo2:
        st.image("img/corro.svg", use_container_width=True)

    _col1, _col2, _col3 = st.columns([1, 2, 1])
    with _col2:
        # Samotný formulář s políčky. Vše, co uživatel nakliká, se odešle zaráz po zmáčknutí submitu.
        with st.form("login_form"):
            email = st.text_input("E-mail")
            password = st.text_input("Heslo", type="password")
            remember_me = st.checkbox("Zůstat přihlášen (7 dní)")
            submit = st.form_submit_button("Přihlásit se", use_container_width=True)

            if submit:
                # Při odeslání zkusíme ověřit usera v databázi.
                logged_in_data = authenticate_user(email, password)
                if logged_in_data:
                    # Když se to povede, zapíšeme si ho do session state...
                    st.session_state.update({
                        "authenticated": True,
                        "user_id": logged_in_data["id"],
                        "user_email": logged_in_data["email"],
                        "user_name": logged_in_data["name"],
                        "user_role": logged_in_data["role"],
                        "user_phone": logged_in_data["phone"]
                    })

                    # Pokud chtěl zůstat přihlášen, vygenerujeme mu cookie a hodíme mu ji do prohlížeče
                    if remember_me:
                        new_token = str(uuid.uuid4())
                        set_session_token(logged_in_data["id"], new_token)
                        expire_date = datetime.datetime.now() + datetime.timedelta(days=7)
                        cookie_manager.set("cpq_session", new_token, expires_at=expire_date)

                    time.sleep(0.2)
                    st.rerun()  # Refresh pro přechod do samotné appky.
                else:
                    st.error("Špatný e-mail nebo heslo.")


# Blokování přístupu: Pokud dojdeme až sem a uživatel stále není "authenticated",
# zobrazíme mu login formulář a skript ukončíme přes st.stop(). Nikam dál se nedostane.
if not st.session_state["authenticated"]:
    login_form()
    st.stop()

# =============================================================================
# Sidebar Navigation & Logout
# =============================================================================
# Levý postranní panel. Obsahuje uvítání, tlačítko pro odhlášení a přepínač stránek (radio button).
st.sidebar.image("img/corro.svg", use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.title(f"{st.session_state['user_name']}")
st.sidebar.write(f"Role: {st.session_state['user_role']}")

if st.sidebar.button("Odhlásit se"):
    # Při odhlášení smazeme token z DB i cookie z prohlížeče. Plus vyčistíme session_state.
    if st.session_state.get("user_id"):
        clear_session_token(st.session_state["user_id"])
    if cookie_manager.get("cpq_session"):
        cookie_manager.delete("cpq_session")
    st.session_state.clear()
    time.sleep(0.2)
    st.rerun()

st.sidebar.markdown("---")

nav_options = ["Dashboard", "Můj profil"]
# Pokud je borec Admin, jednoduše mu přidáme další položku do navigačního menu.
if st.session_state["user_role"] == "Admin":
    nav_options.append("Správa systému (Admin)")

page = st.sidebar.radio("Navigace", nav_options)

# =============================================================================
# Main App Routing (Pages)
# =============================================================================

if page == "Dashboard":
    # =========================================================================
    # Page: Dashboard
    # =========================================================================
    # Hlavní pracovní plocha. Nejprve natáhneme do paměti data (z cache, takže je to bleskové).
    df_clients = load_clients()
    df_products = load_products()
    df_hmoty = load_pdf_hmoty()

    # ---- Vyhledávání a profil klienta ----
    st.markdown("<h2 style='text-align: center; margin-bottom: 30px;'>Vyhledávání klienta</h2>", unsafe_allow_html=True)

    layout_col1, layout_col2, layout_col3 = st.columns([1, 2, 1])
    with layout_col2:
        # Tvoříme dropdown ze jmen všech firem (s prázdnou volbou na začátku)
        client_options = [""] + df_clients['name'].tolist()
        selected_client = st.selectbox("Začněte psát název firmy...", client_options, index=0,
                                       label_visibility="collapsed")

    st.markdown("---")

    # Jakmile uživatel vybere nějakou firmu, vyfiltrujeme si z DataFramu ten daný řádek (iloc[0])
    # a poskládáme z něj metriky (IČ, obrat, ziskovost).
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

        raw_dealer = client_row['dealer']
        dealer_str = str(raw_dealer).strip() if pd.notna(raw_dealer) else ""
        st.markdown(f"**Dealer:** {dealer_str if dealer_str else '/'}")

    st.markdown("---")

    # ---- Kalkulace ceny (Pricing Tool) ----
    st.subheader("🔍 Kalkulace cenové nabídky")
    product_options = [""] + df_products['name'].tolist()
    selected_product = st.selectbox("Vyberte produkt k nacenění:", product_options, index=0)

    # Vybrali jsme produkt? Spočítej nějaký nástřel ceny a ukaž grafík.
    if selected_product:
        product_row = df_products[df_products['name'] == selected_product].iloc[0]
        p_storage = float(product_row['storage_price'])

        # Hardcodovaná logika pro cenotvorbu. Tady si nastavíš logiku marží, min a max cen,
        # a my si z toho vymodelujeme "budík" (gauge chart).
        mock_margin_index = 1.5
        p_retail = p_storage * 2
        target_price = p_storage * mock_margin_index
        min_range = max(target_price * 0.85, p_storage)
        max_range = target_price * 1.15

        last_bought_price = target_price * 0.92
        last_bought_date = "N/A"

        st.write("#### Doporučená cena a rozpětí")
        st.info("Výpočet doporučeného cenového indexu: **XX** (Bude implementováno později)")


        # Funkce pro generování grafu. Záměrně u ní máme cachování (@st.cache_data),
        # aby se graf nemusel pracně kreslit znova a znova, když uživatel změní něco nesouvisejícího (třeba dole překlikne vrstvu u PDF).
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
                        {'range': [p_st, min_r], 'color': "rgba(255, 99, 132, 0.4)"},  # Červená zóna - podhodnoceno
                        {'range': [min_r, max_r], 'color': "rgba(75, 192, 192, 0.5)"},  # Zelená zóna - ideal spot
                        {'range': [max_r, p_ret], 'color': "rgba(54, 162, 235, 0.4)"}  # Modrá zóna - střelba vysoko
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


        # Vykreslení Plotly grafu.
        fig = create_gauge_chart(p_storage, p_retail, target_price, min_range, max_range, selected_product,
                                 last_bought_price)
        st.plotly_chart(fig, use_container_width=True)

        met_col1, met_col2, met_col3 = st.columns(3)
        met_col1.metric("Skladová cena (Náklad)", f"{p_storage:,.0f} Kč".replace(",", " "))
        met_col2.metric(f"Poslední nákup ({last_bought_date})", f"{last_bought_price:,.0f} Kč".replace(",", " "))
        met_col3.metric("Maloobchodní cena (Max)", f"{p_retail:,.0f} Kč".replace(",", " "))

        st.success(
            f"💡 **Tip pro obchod:** Ideální prostor pro vyjednávání (zelená zóna na grafu) "
            f"je mezi **{min_range:,.0f} Kč** a **{max_range:,.0f} Kč**.".replace(",", " ")
        )

    st.markdown("---")

    # ---- Generátor PDF (PDF Tool) ----
    st.subheader("📄 Generátor PDF Kalkulace")

    # Všechna hlavičková data, která padnou rovnou do tabulky nahoru do PDF.
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

        # Statické konstanty (vytvořené na začátku scriptu) naservírujeme uživateli ve formě comboboxů (selectboxů).
        st.markdown("#### Příprava povrchu (výběr)")
        prep_a = st.selectbox("A - Základní čištění (vyberte max. 1)", PREP_A)
        prep_b = st.selectbox("B - Abrazivní tryskání plošné (vyberte max. 1)", PREP_B)
        prep_c = st.selectbox("C - Tryskání se specifikací drsnosti (vyberte max. 1)", PREP_C)
        prep_d = st.selectbox("D - Svary a lokální opravy (vyberte max. 1)", PREP_D)
        prep_e = st.selectbox("E - Mechanické a speciální plošné (vyberte max. 1)", PREP_E)
        prep_f = st.multiselect("F - Dodatečné pokyny (můžete vybrat více)", PREP_F)

    st.markdown("#### Nátěrové vrstvy")

    # Vytvoříme placeholder pro vrstvy barev v session_state, protože je chceme
    # vkládat a odebírat dynamicky (tlačítkem + a -).
    if 'pdf_rows' not in st.session_state:
        st.session_state.pdf_rows = []

    types_of_coats = ["Penetrační", "Mlhový nástřik", "Napouštěcí", "Základní", "Podkladní", "Vrchní"]
    hmoty_options = df_hmoty['nazev'].tolist() if not df_hmoty.empty else ["Žádná data v DB"]

    # Výpis aktuálně zadaných vrstev barev z pole v session_state.
    for i, row in enumerate(st.session_state.pdf_rows):
        st.markdown(f"**Vrstva {i + 1}**")
        row_c1, row_c2, row_c3, row_c4 = st.columns(4)
        row_c5, row_c6, row_c7 = st.columns([1, 1, 2])

        # Nastavení indexů s fail-safe mechanismem (vrátí se na index 0, když item zmizne nebo neexistuje).
        safe_coat_index = int(types_of_coats.index(row['typ'])) if row['typ'] in types_of_coats else 0
        safe_hmota_index = int(hmoty_options.index(row['hmota'])) if row['hmota'] in hmoty_options else 0

        # Když uživatel mění hodnoty ve formuláři, natvrdo si je zpětně updatujeme do toho session pole.
        # Máme všude key parameter typu "Název##{i}", abychom měli unikátní widget klíče.
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

        # Tlačítko na smazání dané vrstvy prostě vyhodí z pole prvek na pozici "i" a hned volá st.rerun().
        if st.button(f"Odebrat vrstvu {i + 1}", key=f"remove_{i}"):
            st.session_state.pdf_rows.pop(i)
            st.rerun()
        st.markdown("---")

    # Přidání defaultního nového záznamu na konec seznamu barev.
    if st.button("➕ Přidat vrstvu"):
        st.session_state.pdf_rows.append({
            'typ': 'Základní', 'hmota': hmoty_options[0] if hmoty_options else "",
            'odstin': '', 'dft': 100.0, 'plocha': 100.0, 'c_l': 0.0, 'redeni': 5.0
        })
        st.rerun()

    # ---- Vlastní generování PDF přes vnější skript KalkulacePDF ----
    if st.button("🖨️ Vygenerovat PDF", type="primary"):
        # Spojíme všechny nenulové položky přípravy povrchu do jedné lišty textů.
        final_prep_texts = [p for p in [prep_a, prep_b, prep_c, prep_d, prep_e] if p.strip()] + prep_f

        # Uděláme JSON dictionary z údajů z prvního velkého bloku.
        header_info = {
            "doc_no": pdf_doc_no,
            "project": pdf_project,
            "temp": pdf_temp,
            "corrosion": pdf_corr,
            "substrate": pdf_substrate,
            "client_company": pdf_client,
            "prep_texts": final_prep_texts
        }

        # Podpis uživatele pro finální PDF report.
        user_info = {
            "name": st.session_state.get("user_name", "Neznámý"),
            "phone": st.session_state.get("user_phone", ""),
            "email": st.session_state.get("user_email", "")
        }

        # Projdeme všechny vrstvy, a u každé se ještě dotážeme do dataframe "df_hmoty",
        # jestli náhodou nemá další specifikace (sušinu, typ ředidla atd.)
        products_data = []
        for row in st.session_state.pdf_rows:
            matched = df_hmoty[df_hmoty['nazev'] == row['hmota']]
            if not matched.empty:
                db_susina = matched.iloc[0]['susina']
                db_redidlo = matched.iloc[0]['redidlo']
                db_cislo = matched.iloc[0]['cislo_odstinu']
            else:
                db_susina, db_redidlo, db_cislo = "", "", ""

            # Pro každou barvu pošleme záznam pro samotnou barvu a hned pod tím záznam pro její ředidlo.
            products_data.append({
                "typ": row['typ'],
                "hmota": row['hmota'],
                "cislo": db_cislo,
                "odstin": row['odstin'],
                "dft": row['dft'],
                "susina": db_susina,
                "plocha": row['plocha'],
                "c_l": row['c_l']
            })
            products_data.append({
                "hmota": db_redidlo,
                "redeni": row['redeni']
            })

        # Vytvoření instance třídy KalkulacePDF (kterou bereš importem z vedlejšího scriptu).
        pdf = KalkulacePDF(user_info=user_info, validity_date=pdf_validity, orientation="L", unit="mm", format="A4")
        pdf.add_page()
        pdf.draw_template_grid(header_info)
        pdf.draw_table(products_data, main_loss=int(pdf_loss), celkova_plocha=pdf_area, sys_type=pdf_sys_type,
                       pozn=pdf_pozn)

        # Vytvoříme si dočasný virtuální soubor, necháme do něj to PDF zapsat,
        # pak to z něj načteme zpátky do RAM proměnné (pdf_bytes) a soubor smažeme.
        # Tím máme hotové binární PDF čistě v paměti nachystané na pro download_button, aniž bychom špinili lokální filesystem.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.output(tmp.name)
            with open(tmp.name, "rb") as f:
                pdf_bytes = f.read()
        os.remove(tmp.name)

        file_prefix = selected_client if selected_client else "Kalkulace"
        st.download_button(
            label="📥 Stáhnout PDF Kalkulaci",
            data=pdf_bytes,
            file_name=f"{file_prefix}.pdf",
            mime="application/pdf"
        )


elif page == "Můj profil":
    # =========================================================================
    # Page: Profile
    # =========================================================================
    st.title("👤 Můj profil")
    st.write("Zde si můžeš změnit své heslo pro přístup do systému.")

    with st.form("change_my_password_form"):
        st.subheader("Změna hesla")
        # Políčka pro změnu hesla. Type = password maskuje znaky klasickýma tečkama.
        old_pwd = st.text_input("Stávající heslo", type="password")
        new_pwd1 = st.text_input("Nové heslo", type="password")
        new_pwd2 = st.text_input("Nové heslo znovu (pro kontrolu)", type="password")

        if st.form_submit_button("Změnit heslo"):
            if not old_pwd or not new_pwd1 or not new_pwd2:
                st.warning("Musíš vyplnit všechna pole.")
            elif new_pwd1 != new_pwd2:
                st.error("Nová hesla se neshodují.")
            elif authenticate_user(st.session_state["user_email"], old_pwd):
                # Funkce authenticate_user ti tu ověří, zda to staré heslo vůbec platí, než to updatne.
                update_user(st.session_state["user_id"], st.session_state["user_id"], st.session_state["user_email"],
                            st.session_state["user_name"], st.session_state["user_role"],
                            st.session_state.get("user_phone", ""), new_pwd1)
                st.success("Heslo bylo úspěšně změněno!")
            else:
                st.error("Stávající heslo není správné.")


elif page == "Správa systému (Admin)":
    # =========================================================================
    # Page: Admin Section
    # =========================================================================
    st.title("⚙️ Správa systému")

    # Klasicky vytáhneme base tabulky - protože jsi Admin, uvidíš i surový data.
    df_users = load_users()
    df_clients = load_clients()
    df_products = load_products()

    # Použití tabů pro zpřehlednění UI - v administraci by bez nich byla hrozná nudle (stránka dlouhá jako tejden).
    main_tabs = st.tabs(["👥 Uživatelé", "🏢 Firmy", "🎨 Produkty", "📄 Prodeje"])

    # -------------------------------------------------------------------------
    # TAB 1: Uživatele
    # -------------------------------------------------------------------------
    with main_tabs[0]:
        st.dataframe(df_users, use_container_width=True, hide_index=True)
        st.markdown("---")
        utab1, utab2, utab3 = st.tabs(["Přidat uživatele", "Upravit uživatele", "Smazat uživatele"])

        # Klasická přidávací formulářová logika, to asi nepotřebuje moc vysvětlovat.
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
                            st.rerun()  # Refreshně aplikaci, ať se uživatel ukáže nahoře v tabulce.
                        else:
                            st.error("Uživatel s tímto e-mailem nebo ID už existuje.")
                    else:
                        st.warning("Vyplňte vše kromě telefonu (ten je nepovinný).")

        # Editace uživatele. Vybereš z rolovátka člověka, vytáhne si to jeho data a
        # ty ho s nima předvyplní do formuláře (parametr "value=...")
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
                                # Pokud měním jako admin data sobě samotnému, musím updatnout svůj session state,
                                # abych nebyl hned vykopnut ze systému nebo nedej bože ztratil admin práva z pohledu UI.
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

    # -------------------------------------------------------------------------
    # TAB 2: Firmy (Clients)
    # -------------------------------------------------------------------------
    with main_tabs[1]:
        st.dataframe(df_clients, use_container_width=True, hide_index=True)
        st.markdown("---")
        ctab1, ctab2, ctab3, ctab4 = st.tabs(["Přidat firmu", "Upravit firmu", "Smazat firmu", "📦 Import z Excelu"])

        # Klasická CRUD logika – přidat...
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

        # ... upravit ...
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

        # ... smazat.
        with ctab3:
            c_del = st.selectbox("Vyber firmu ke smazání", df_clients['name'].tolist(), key="c_del_sel", index=None,
                                 placeholder="Vyberte firmu...")
            if c_del and st.button("Smazat firmu", type="primary", key="c_del_btn"):
                delete_client(str(df_clients[df_clients['name'] == c_del].iloc[0]['ic']))
                st.success("Smazáno.")
                st.rerun()

        # ---- Import Excelů s klienty (Mass update/insert) ----
        # Tohle je masivní sekce, co umí sečíst klienty přes několik excelovských listů
        # (např. tržby 2022, 2023, 2024 najednou) a hodit jim to jako sumu do DB.
        with ctab4:
            st.info(
                "Nahrajte soubor s analýzou odběratelů. Lze zpracovat a sečíst více listů (např. prodejních let) najednou.")
            uploaded_file = st.file_uploader("Nahrát Excel s klienty", type=["xlsx", "xls"])

            if uploaded_file:
                try:
                    # Inicializuje se panda excel parser.
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

                        # Iterujeme listy v excelu
                        for sheet in selected_sheets:
                            # Tady je docela tricky logika. Některé debilní excely nemají hlavičku na 1. řádku,
                            # ale třeba jsou první 3 řádky loga a nesmysly. Načteme tedy prvních 20 řádků a hledáme,
                            # kde se objeví typická slova pro tabulky jako "IČ", "firma" atd.
                            df_raw = xls.parse(sheet_name=sheet, header=None, nrows=20)

                            header_idx = 0
                            for idx, row in df_raw.iterrows():
                                row_str = ' '.join([str(val).lower() for val in row.values if pd.notna(val)])
                                if 'ič' in row_str or 'ic' in row_str or 'firma' in row_str or 'název' in row_str or 'odběratel' in row_str:
                                    header_idx = idx
                                    break

                            # Teď už víme, kde má tabulka opravdovou hlavičku (header_idx) a natáhneme ten list pořádně.
                            df_sheet = xls.parse(sheet_name=sheet, header=header_idx)

                            # Pojistka jestli je to opravdu korektní datová struktura, odstranění prázdných sloupců.
                            if isinstance(df_sheet, pd.DataFrame):
                                df_sheet = df_sheet.dropna(how='all', axis=1)
                                df_sheet.columns = [str(c).replace('\n', ' ').strip() for c in df_sheet.columns]
                                all_dataframes.append(df_sheet)

                        if not all_dataframes:
                            st.warning("Nebyla nalezena žádná smysluplná data ve vybraných listech.")
                        else:
                            # Spojíme všechny nasbírané sheets do jednoho mega-dataframe.
                            df_import = pd.concat(all_dataframes, ignore_index=True)
                            col_options = df_import.columns.tolist()

                            # Chytrej "guess" od skriptu – předvybere ti sloupce do mapování, aby na to chudák uživatel nemusel klikat,
                            # pokud to podle jména ('ič', 'název', 'dealer') pozná samo.
                            def_ic = next((c for c in col_options if 'ič' in str(c).lower() or 'ic' in str(c).lower()),
                                          col_options[0])
                            def_name = next((c for c in col_options if
                                             'firma' in str(c).lower() or 'název' in str(
                                                 c).lower() or 'odběratel' in str(
                                                 c).lower()), col_options[0])
                            def_dealer = next(
                                (c for c in col_options if 'dealer' in str(c).lower() or 'zástupce' in str(c).lower()),
                                col_options[0])

                            st.markdown("### 2. Spárování sloupců z Excelu na Databázi")
                            map_ic = st.selectbox("Sloupec s IČ (Povinné):", col_options,
                                                  index=col_options.index(def_ic))
                            map_name = st.selectbox("Sloupec s Názvem firmy (Povinné):", col_options,
                                                    index=col_options.index(def_name))
                            map_dealer = st.selectbox("Sloupec s Dealerem:", col_options,
                                                      index=col_options.index(def_dealer))

                            # Pokud jsou tržby rozepsané ve více sloupcích, uživatel jich tu může vybrat vícero a systém je u daného řádku jednoduše sečte.
                            sum_sales_cols = st.multiselect("Sloupce k sečtení do 'Celkového obratu bez DPH':",
                                                            col_options,
                                                            default=[c for c in col_options if
                                                                     'obrat' in str(c).lower() and 'bez dph' in str(
                                                                         c).lower()])
                            sum_prof_cols = st.multiselect("Sloupce k sečtení do 'Ziskovosti (hrubý zisk bez DPH)':",
                                                           col_options,
                                                           default=[c for c in col_options if
                                                                    'zisk' in str(c).lower() and 'bez dph' in str(
                                                                        c).lower()])

                            if st.button("🚀 Spustit import a sečíst napříč listy", type="primary"):
                                runtime_db_conn = get_db_connection()
                                clients_dict = {}

                                # Projedeme řádek po řádku celý spojený mega-dataframe.
                                for index, row in df_import.iterrows():
                                    c_ic = str(row[map_ic]).strip()
                                    c_name = str(row[map_name]).strip()

                                    # Přeskakujeme řádky, co nemají ičo nebo jméno
                                    if not c_ic or c_ic.lower() == 'nan' or not c_name or c_name.lower() == 'nan':
                                        continue

                                    c_dealer = str(row[map_dealer]).strip() if pd.notna(row[map_dealer]) else ""

                                    # Sečteme všechno z vybraných sales sloupců u tohoto řádku.
                                    excel_total_sales = 0.0
                                    for sc in sum_sales_cols:
                                        if pd.notna(row[sc]):
                                            try:
                                                excel_total_sales += float(row[sc])
                                            except ValueError:
                                                pass

                                    # To samé pro zisk.
                                    excel_total_prof = 0.0
                                    for pc in sum_prof_cols:
                                        if pd.notna(row[pc]):
                                            try:
                                                excel_total_prof += float(row[pc])
                                            except ValueError:
                                                pass

                                    # Ukládáme si to do pomocného slovníku. Pokud už jsme to IČO potkali (např. na jiném listu pro jiný rok),
                                    # jednoduše ty čísla přičteme. Takže to umí aggregovat víc záznamů jednoho klienta.
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

                                # Po sumarizaci pustíme UPSERT (Insert On Conflict Do Update)
                                # – pokud firma neexistuje v databázi, přidáme jí. Pokud ano (dle IČ), updatneme jí obraty.
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
                                                         (ic_key, data['name'], data['sales'], data['prof'],
                                                          data['dealer']))

                                        imported_count += 1

                                load_clients.clear()
                                st.success(
                                    f"🎉 Úspěšně naimportováno / zaktualizováno {imported_count} unikátních firem (sloučeno ze {len(selected_sheets)} listů)!")
                                st.rerun()

                except Exception as ex:
                    st.error(f"Při zpracování Excelu došlo k chybě: {ex}")

    # -------------------------------------------------------------------------
    # TAB 3: Produkty (Products)
    # -------------------------------------------------------------------------
    # Naprosto standardní tab s CRUD operacemi bez žádný větší magie.
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

    # -------------------------------------------------------------------------
    # TAB 4: Prodeje / Invoices (Sales Import)
    # -------------------------------------------------------------------------
    # Tady se dají uploadovat surové exproty faktur a prodejů ze systému typu ESO9, atp.
    # Databáze má tabulku s unikátní kombinací (číslo dokladu + kód zboží), takže brání duplikacím.
    with main_tabs[3]:
        st.subheader("Import prodejů z Excelu")
        st.info(
            "Nahraj soubor s prodeji (např. ESO9_Online_CO_PřehledProdeje.xlsx). Záznamy, které už v databázi jsou (shoda čísla Dokladu a Kódu zboží), se automaticky přeskočí.")

        uploaded_sales = st.file_uploader("Nahrát Excel s prodeji", type=["xlsx", "xls"], key="sales_uploader")

        if uploaded_sales:
            try:
                # Natáhneme excel do dataframe. Pro import prodejů očekáváme, že má nějaké ty pevné formáty.
                df_sales = pd.read_excel(uploaded_sales)

                # Kontrola přítomnosti absolutně nutných sloupů. Pokud to chybí, vyřveme uživatele a dál nepokračujeme.
                required_cols = ['Doklad', 'Kód subjektu', 'Jednotková cena', 'Kód zboží', 'Datum', 'Množství']
                missing_cols = [c for c in required_cols if c not in df_sales.columns]

                if missing_cols:
                    st.error(f"V Excelu chybí tyto povinné sloupce: {', '.join(missing_cols)}. Zkontroluj názvy.")
                else:
                    # Rychlý náhled prvních tří řádků pro kontrolu
                    st.write(f"Náhled dat ({len(df_sales)} řádků):")
                    st.dataframe(df_sales.head(3))

                    if st.button("🚀 Spustit import prodejů", type="primary"):
                        sales_db_conn = get_db_connection()
                        imported_count = 0
                        skipped_count = 0

                        with sales_db_conn.cursor() as s_cursor:
                            # Iteruje všechny řádky, naformátuje a tahá čísla.
                            for index, row in df_sales.iterrows():
                                doklad = str(row['Doklad']).strip()
                                excel_prod_id = str(row['Kód zboží']).strip()

                                # Pokud chybí to nejdůležitější (doklad, zboží), nemá smysl to prát do databáze
                                if not doklad or doklad.lower() == 'nan' or not excel_prod_id or excel_prod_id.lower() == 'nan':
                                    continue

                                client_ic = str(row['Kód subjektu']).strip() if pd.notna(
                                    row['Kód subjektu']) else ""
                                price = float(row['Jednotková cena']) if pd.notna(row['Jednotková cena']) else 0.0
                                quantity = float(row['Množství']) if pd.notna(row['Množství']) else 0.0

                                # Zkouší formátovat datové typy.
                                try:
                                    purchase_date = pd.to_datetime(row['Datum']).date()
                                except Exception:
                                    purchase_date = None

                                # WHERE NOT EXISTS: Překontroluje přímo v SQL dotazu,
                                # jestli už tento doklad pro dané zboží není nasazen. Pokud jo, neinsertuje to nic.
                                s_cursor.execute('''
                                                 INSERT INTO invoices (id, client_ic, price, product_id, purchase_date, quantity)
                                                 SELECT %s,
                                                        %s,
                                                        %s,
                                                        %s,
                                                        %s,
                                                        %s WHERE NOT EXISTS (SELECT 1
                                                                 FROM invoices
                                                                 WHERE id = %s AND product_id = %s)
                                                 ''',
                                                 (doklad, client_ic, price, excel_prod_id, purchase_date, quantity,
                                                  doklad,
                                                  excel_prod_id))

                                # cursor.rowcount nám řekne, kolik řádků reálně prošlo do DB (1 = úspěch, 0 = skipplo se to)
                                if s_cursor.rowcount > 0:
                                    imported_count += 1
                                else:
                                    skipped_count += 1

                        st.success(
                            f"Hotovo! Naimportováno {imported_count} nových záznamů. Přeskočeno {skipped_count} existujících duplikátů.")

            except Exception as e:
                st.error(f"Během zpracování Excelu došlo k chybě: {e}")