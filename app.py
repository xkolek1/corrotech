"""Streamlit aplikace pro CPQ a správu dat CORROTECH."""

# Imports and application configuration
import time
import datetime
from uuid import uuid4
import streamlit as st
import extra_streamlit_components as stx
from psycopg2.extras import RealDictCursor

# Připojení k DB a správa přihlášení
from db_manager import (
    get_db_connection,
    get_user_by_token,
    authenticate_user,
    set_session_token,
    clear_session_token
)

# Pomocné funkce pro veřejnou ověřovací stránku
from helpers import show_pdf, sanitize_filename

# Jednotlivé stránky
from views.dashboard import render_dashboard
from views.clients import render_clients
from views.analytics import render_analytics
from views.dealers import render_dealers
from views.archive import render_archive
from views.profile import render_profile
from views.admin import render_admin

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
# Login & Public Pages
# =============================================================================
def login_form():
    _logo1, _logo2, _logo3 = st.columns([1, 1, 1])
    with _logo2:
        st.image("img/corro.svg", use_container_width=True)

    _col1, _col2, _col3 = st.columns([1, 2, 1])
    with _col2:
        with st.form("login_form"):
            email = st.text_input("E-mail", autocomplete="username")
            password = st.text_input("Heslo", type="password", autocomplete="current-password")
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
                        # Odstraněny parametry secure a samesite, které knihovna nepodporuje
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
                        "SELECT created_at, author_email, client_name, pdf_file, doc_no FROM pdf_archive WHERE signature_id = %s",
                        (verify_code.strip(),)
                    )
                    result = v_cursor.fetchone()

                    if result:
                        st.success("✅ Dokument byl nalezen a ověřen!")
                        pdf_bytes = bytes(result['pdf_file'])

                        date_str = result['created_at'].strftime('%y%m%d')
                        client_first_line = result['client_name'].split('\n')[0].strip() if result.get('client_name') else "Neznamy"
                        comp_name = sanitize_filename(client_first_line)
                        d_no = result.get('doc_no') or "NO-DOC-NO"
                        f_name = f"{date_str}_{comp_name}_{d_no}.pdf"

                        show_pdf(pdf_bytes, filename=f_name, key=f"dl_pub_{verify_code}")

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
    render_dashboard()

elif page == "Odběratelé":
    render_clients()

elif page == "Analýza a Predikce":
    render_analytics()

elif page == "Porovnání dealerů":
    render_dealers()

elif page == "Archiv nabídek":
    render_archive()

elif page == "Můj profil":
    render_profile()

elif page == "Správa systému (Admin)":
    render_admin()