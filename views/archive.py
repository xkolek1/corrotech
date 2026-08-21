import streamlit as st
import time
from psycopg2.extras import RealDictCursor
from db_manager import get_db_connection
from helpers import sanitize_filename, show_pdf
from zoneinfo import ZoneInfo

def to_cz_time(dt):
    """Převede UTC čas z databáze na český lokální čas."""
    if not dt: return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("Europe/Prague"))

def render_archive():
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
                "SELECT signature_id, created_at, client_name, is_final, doc_no FROM pdf_archive WHERE author_email = %s ORDER BY created_at DESC",
                (st.session_state["user_email"],)
            )
            my_docs = v_cursor.fetchall()

        if my_docs:
            options = {doc[
                           'signature_id']: f"{'✅ FINÁLNÍ' if doc['is_final'] else '🔒 SOUKROMÉ'} | {to_cz_time(doc['created_at']).strftime('%d.%m.%Y %H:%M')} | {doc['client_name'].split(chr(10))[0]}"
                       for doc in my_docs}
            selected_my_id = st.selectbox("Vyber nabídku k zobrazení / úpravě:", options=list(options.keys()),
                                          format_func=lambda x: options[x], key="my_docs_sel")

            if selected_my_id:
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    v_cursor.execute(
                        "SELECT is_final, pdf_file, client_name, doc_no, created_at, form_data FROM pdf_archive WHERE signature_id = %s",
                        (selected_my_id,))
                    doc_detail = v_cursor.fetchone()

                current_status = doc_detail['is_final']
                col_btn1, col_btn2, col_spacer = st.columns([2, 1, 1])

                with col_btn1:
                    if not current_status:
                        if st.button("Odemknout pro ostatní (Označit jako Finální)", type="primary",
                                     use_container_width=True):
                            with db_conn.cursor() as c:
                                c.execute("UPDATE pdf_archive SET is_final = TRUE WHERE signature_id = %s",
                                          (selected_my_id,))
                            st.rerun()
                    else:
                        if st.button("Zamknout (Zrušit finální status)", use_container_width=True):
                            with db_conn.cursor() as c:
                                c.execute("UPDATE pdf_archive SET is_final = FALSE WHERE signature_id = %s",
                                          (selected_my_id,))
                            st.rerun()

                with col_btn2:
                    if st.button("🗑️ Zahodit", use_container_width=True):
                        confirm_delete_dialog(selected_my_id)

                f_data = doc_detail.get('form_data')
                if f_data:
                    if 'pdf_rows' in f_data and f_data['pdf_rows']:
                        st.markdown("📦 **Použité materiály:**")
                        for r in f_data['pdf_rows']:
                            st.markdown(f"- {r['hmota']} *(Cena: {r['c_l']} Kč/l)*")

                    if st.button("📝 Vytvořit novou verzi (Použít jako šablonu)", icon=":material/content_copy:",
                                 use_container_width=True):
                        st.session_state['loaded_template'] = f_data
                        st.session_state['pdf_rows'] = f_data.get('pdf_rows', [])
                        st.session_state.current_page = "Dashboard"
                        st.rerun()
                st.markdown("---")

                date_str = doc_detail['created_at'].strftime('%y%m%d')
                client_first_line = doc_detail['client_name'].split('\n')[0].strip() if doc_detail.get(
                    'client_name') else "Neznamy"
                comp_name = sanitize_filename(client_first_line)
                d_no = doc_detail.get('doc_no') or "NO-DOC-NO"
                f_name = f"{date_str}_{comp_name}_{d_no}.pdf"

                show_pdf(bytes(doc_detail['pdf_file']), filename=f_name, key=f"dl_my_{selected_my_id}")
        else:
            st.info("Zatím jsi nevygeneroval/a žádné nabídky.")

    with tab2:
        with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
            v_cursor.execute(
                "SELECT signature_id, created_at, client_name, author_email, doc_no FROM pdf_archive WHERE is_final = TRUE ORDER BY created_at DESC"
            )
            shared_docs = v_cursor.fetchall()

        if shared_docs:
            options_shared = {doc[
                                  'signature_id']: f"{to_cz_time(doc['created_at']).strftime('%d.%m.%Y')} | {doc['client_name'].split(chr(10))[0]} | (Autor: {doc['author_email']})"
                              for doc in shared_docs}
            selected_shared_id = st.selectbox("Vyber finální nabídku k zobrazení:", options=list(options_shared.keys()),
                                              format_func=lambda x: options_shared[x], key="shared_docs_sel")

            if selected_shared_id:
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    v_cursor.execute(
                        "SELECT pdf_file, client_name, doc_no, created_at, form_data FROM pdf_archive WHERE signature_id = %s",
                        (selected_shared_id,))
                    shared_detail = v_cursor.fetchone()

                f_data = shared_detail.get('form_data')
                if f_data:
                    if 'pdf_rows' in f_data and f_data['pdf_rows']:
                        st.markdown("📦 **Použité materiály:**")
                        for r in f_data['pdf_rows']:
                            st.markdown(f"- {r['hmota']} *(Cena: {r['c_l']} Kč/l)*")

                    if st.button("📝 Vytvořit novou verzi (Použít jako šablonu)", icon=":material/content_copy:",
                                 use_container_width=True, key="clone_shared"):
                        st.session_state['loaded_template'] = f_data
                        st.session_state['pdf_rows'] = f_data.get('pdf_rows', [])
                        st.session_state.current_page = "Dashboard"
                        st.rerun()
                st.markdown("---")

                date_str = shared_detail['created_at'].strftime('%y%m%d')
                client_first_line = shared_detail['client_name'].split('\n')[0].strip() if shared_detail.get(
                    'client_name') else "Neznamy"
                comp_name = sanitize_filename(client_first_line)
                d_no = shared_detail.get('doc_no') or "NO-DOC-NO"
                f_name = f"{date_str}_{comp_name}_{d_no}.pdf"

                show_pdf(bytes(shared_detail['pdf_file']), filename=f_name, key=f"dl_shared_{selected_shared_id}")
        else:
            st.info("Nikdo zatím nesdílel žádnou finální nabídku.")

    with tab3:
        st.write(
            "Zadej ID kód dokumentu. Lze tak dohledat i soukromé (nefinální) nabídky kolegů, pokud ti k nim dají klíč.")
        verify_code = st.text_input("Kód dokumentu (ID):", placeholder="např. 4F8A3B2E-...")

        if st.button("Vyhledat a zobrazit", type="primary", icon=":material/search:"):
            if verify_code.strip():
                with db_conn.cursor(cursor_factory=RealDictCursor) as v_cursor:
                    v_cursor.execute(
                        "SELECT created_at, pdf_file, client_name, author_email, doc_no FROM pdf_archive WHERE signature_id = %s",
                        (verify_code.strip(),))
                    result = v_cursor.fetchone()

                if result:
                    st.success(
                        f"✅ Dokument nalezen (Klient: {result['client_name'].split(chr(10))[0]}, Autor: {result['author_email']})")

                    date_str = result['created_at'].strftime('%y%m%d')
                    client_first_line = result['client_name'].split('\n')[0].strip() if result.get(
                        'client_name') else "Neznamy"
                    comp_name = sanitize_filename(client_first_line)
                    d_no = result.get('doc_no') or "NO-DOC-NO"
                    f_name = f"{date_str}_{comp_name}_{d_no}.pdf"

                    show_pdf(bytes(result['pdf_file']), filename=f_name, key=f"dl_verify_{verify_code}")
                else:
                    st.error("❌ Dokument s tímto kódem neexistuje.")
            else:
                st.warning("Musíš zadat kód.")