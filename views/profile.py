import streamlit as st
from db_manager import authenticate_user, update_user
from helpers import validate_password_complexity

def render_profile():
    st.title("Můj profil")
    st.write("Zde si můžeš změnit své heslo pro přístup do systému.")

    with st.form("change_my_password_form"):
        st.subheader("Změna hesla")
        old_pwd = st.text_input("Stávající heslo", type="password", autocomplete="current-password")
        new_pwd1 = st.text_input("Nové heslo", type="password", autocomplete="new-password")
        new_pwd2 = st.text_input("Nové heslo znovu (pro kontrolu)", type="password", autocomplete="new-password")

        if st.form_submit_button("Změnit heslo"):
            if not old_pwd or not new_pwd1 or not new_pwd2:
                st.warning("Musíš vyplnit všechna pole.")
            elif new_pwd1 != new_pwd2:
                st.error("Nová hesla se neshodují.")
            else:
                pwd_error = validate_password_complexity(new_pwd1)
                if pwd_error:
                    st.error(pwd_error)
                elif authenticate_user(st.session_state["user_email"], old_pwd):
                    update_user(st.session_state["user_id"], st.session_state["user_id"], st.session_state["user_email"],
                                st.session_state["user_name"], st.session_state["user_role"],
                                st.session_state.get("user_phone", ""), new_pwd1)
                    st.success("Heslo bylo úspěšně změněno!")
                else:
                    st.error("Stávající heslo není správné.")