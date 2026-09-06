"""Modul pro správu databáze a CRUD operace."""

import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import pandas as pd
import bcrypt
import hashlib
import re
import unicodedata
from functools import lru_cache
import datetime
from helpers import send_admin_notification

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
# Dummy hash has the same work factor to prevent Timing attacks
DUMMY_HASH = bcrypt.hashpw(b"dummy_password", bcrypt.gensalt())

def authenticate_user(email, password):
    db_conn = get_db_connection()

    with db_conn.cursor(cursor_factory=RealDictCursor) as db_cursor:

        # 1. Cleanup starých pokusů
        db_cursor.execute("DELETE FROM login_attempts WHERE attempt_time < NOW() - INTERVAL '10 minutes'")
        db_conn.commit()

        # 2. Rate limiting podle e-mailu
        db_cursor.execute("SELECT COUNT(*) as attempts FROM login_attempts WHERE email = %s", (email,))
        recent_attempts = db_cursor.fetchone()['attempts']

        generic_error = {"status": "error", "msg": "Nesprávný e-mail nebo heslo."}

        # Zablokujeme konkrétní účet na 10 minut
        if recent_attempts >= 5:
            return {"status": "locked", "msg": "Tento účet je na 10 minut uzamčen z důvodu příliš mnoha pokusů."}

        # 3. Vyhledání uživatele
        db_cursor.execute("SELECT id, name, role, password_hash, phone_number FROM users WHERE email = %s", (email,))
        result = db_cursor.fetchone()

        is_valid_password = False

        if result:
            pwd_hash = result['password_hash']
            if isinstance(pwd_hash, str):
                pwd_hash = pwd_hash.encode('utf-8')
            is_valid_password = bcrypt.checkpw(password.encode('utf-8'), pwd_hash)
        else:
            # 4. Ochrana proti Timing attacku a okamžitá notifikace na neznámý mail
            bcrypt.checkpw(password.encode('utf-8'), DUMMY_HASH)
            send_admin_notification(
                "Bezpečnostní varování: Neznámý e-mail v CPQ",
                f"Pokus o přihlášení s neexistujícím e-mailem: {email}."
            )

        # 5. Vyhodnocení
        if is_valid_password:
            # Čistý štít pro daný e-mail
            db_cursor.execute("DELETE FROM login_attempts WHERE email = %s", (email,))
            db_conn.commit()
            return {
                "status": "success",
                "user": {
                    "id": result['id'], "name": result['name'], "role": result['role'],
                    "email": email, "phone": result['phone_number']
                }
            }
        else:
            # Zapíšeme chybný pokus na vrub e-mailu
            db_cursor.execute("INSERT INTO login_attempts (email) VALUES (%s)", (email,))
            db_conn.commit()

            # Pokud to byl právě 5. pokus, pošleme varování o zamknutí
            if recent_attempts + 1 == 5:
                send_admin_notification(
                    "Bezpečnostní varování: Účet uzamčen",
                    f"Zaznamenáno 5 neúspěšných pokusů o přihlášení. Účet {email} byl na 10 minut uzamčen."
                )

            return generic_error

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
# Session Token & Utils
# =============================================================================
def set_session_token(user_id, token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("UPDATE users SET session_token = %s WHERE id = %s", (token_hash, user_id))
    load_users.clear()

def clear_session_token(user_id):
    db_conn = get_db_connection()
    with db_conn.cursor() as db_cursor:
        db_cursor.execute("UPDATE users SET session_token = NULL WHERE id = %s", (user_id,))
    load_users.clear()

def get_user_by_token(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    db_conn = get_db_connection()
    with db_conn.cursor(cursor_factory=RealDictCursor) as db_cursor:
        db_cursor.execute("SELECT id, email, name, role, phone_number FROM users WHERE session_token = %s", (token_hash,))
        result = db_cursor.fetchone()
        if result:
            return {
                "id": result['id'], "email": result['email'],
                "name": result['name'], "role": result['role'],
                "phone": result['phone_number']
            }
    return None

def generate_doc_number(user_id):
    if not user_id or str(user_id).strip() == "" or str(user_id).lower() == "nan":
        dealer_safe = "XX"
    else:
        dealer_safe = unicodedata.normalize('NFKD', str(user_id)).encode('ASCII', 'ignore').decode('utf-8')
        dealer_safe = re.sub(r'[^A-Za-z0-9]', '', dealer_safe).upper()
        if not dealer_safe:
            dealer_safe = "XX"

    db_conn = get_db_connection()
    with db_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO pdf_doc_sequence (seq_date, dealer, last_seq)
            VALUES (CURRENT_DATE, %s, 1)
            ON CONFLICT (seq_date, dealer)
            DO UPDATE SET last_seq = pdf_doc_sequence.last_seq + 1
            RETURNING last_seq, CURRENT_DATE;
        """, (dealer_safe,))
        last_seq, seq_date = cur.fetchone()

    date_str = seq_date.strftime('%y%m%d')
    return f"{dealer_safe}-{date_str}-{last_seq:04d}"


def load_chat_history(user_id):
    """Načte historii chatu pro konkrétního uživatele."""
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as cur:
            cur.execute("SELECT chat_data FROM ai_chat_logs WHERE user_id = %s", (str(user_id),))
            result = cur.fetchone()
            if result and result[0]:
                return result[0]
        return None
    except Exception as e:
        print(f"Chyba při načítání chatu: {e}")
        return None

def save_chat_history(user_id, chat_data):
    """Uloží historii chatu uživatele do databáze."""
    try:
        db_conn = get_db_connection()
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ai_chat_logs (user_id, chat_data, last_updated) 
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE 
                SET chat_data = EXCLUDED.chat_data, last_updated = CURRENT_TIMESTAMP
            """, (str(user_id), json.dumps(chat_data)))
    except Exception as e:
        print(f"Chyba při ukládání chatu: {e}")
