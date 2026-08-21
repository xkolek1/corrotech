import streamlit as st
import re
from db_manager import authenticate_user, update_user


def render_profile():
    st.title("Můj profil")
    st.write("Zde si můžeš změnit své heslo pro přístup do systému.")

    st.subheader("Změna hesla")

    old_pwd = st.text_input("Stávající heslo", type="password", autocomplete="current-password")
    new_pwd1 = st.text_input("Nové heslo", type="password", autocomplete="new-password")

    req_length = len(new_pwd1) >= 8
    req_upper = bool(re.search(r"[A-Z]", new_pwd1))
    req_digit = bool(re.search(r"\d", new_pwd1))
    req_spec = bool(re.search(r"[!@#$%^&*(),.?\":{}|<>\-_+=\[\]\/\\]", new_pwd1))

    st.markdown(f"""
    **Požadavky na nové heslo:**
    - {'✅' if req_length else '❌'} Alespoň 8 znaků
    - {'✅' if req_upper else '❌'} Alespoň jedno velké písmeno
    - {'✅' if req_digit else '❌'} Alespoň jedno číslo
    - {'✅' if req_spec else '❌'} Alespoň jeden speciální znak
    """)

    new_pwd2 = st.text_input("Nové heslo znovu (pro kontrolu)", type="password", autocomplete="new-password")

    all_reqs_met = req_length and req_upper and req_digit and req_spec

    if st.button("Změnit heslo", type="primary"):
        if not old_pwd or not new_pwd1 or not new_pwd2:
            st.warning("Musíš vyplnit všechna pole.")
        elif new_pwd1 != new_pwd2:
            st.error("Nová hesla se neshodují.")
        elif not all_reqs_met:
            st.error("Nové heslo nesplňuje všechny bezpečnostní požadavky.")
        elif authenticate_user(st.session_state["user_email"], old_pwd):
            update_user(st.session_state["user_id"], st.session_state["user_id"], st.session_state["user_email"],
                        st.session_state["user_name"], st.session_state["user_role"],
                        st.session_state.get("user_phone", ""), new_pwd1)
            st.success("Heslo bylo úspěšně změněno!")
        else:
            st.error("Stávající heslo není správné.")