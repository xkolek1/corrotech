import streamlit as st
from groq import Groq


def render_ai_assistant():
    client = Groq(api_key=st.secrets["AI"]["GROQ_API_KEY"])
    MODEL_NAME = "qwen/qwen3.8-27b"

    STRICT_SYSTEM_PROMPT = """Jsi analytický CPQ asistent a poradce pro obchodníky. Striktně dodržuj tato dvě pravidla:

    1. FIREMNÍ DATA A ČÍSLA: Pokud se dotaz týká konkrétních klientů, našich interních marží, ceníků nebo historických prodejů, musíš vycházet výhradně z dodaných faktů. Pokud tato konkrétní data v konverzaci nemáš, nesmíš hádat. Odpověz přesně: 'K tomuto dotazu nemám k dispozici přesná data.'
    2. OBCHODNÍ TAKTIKA A VYJEDNÁVÁNÍ: Pokud se uživatel ptá na obecné prodejní dovednosti, jak obhájit cenu, jak reagovat na tlak na slevu nebo jak argumentovat hodnotou, plně využij své expertní znalosti. Poraď konkrétní B2B taktiky. Buď profesionální, stručný a přesvědčivý."""

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [{"role": "system", "content": STRICT_SYSTEM_PROMPT}]

    with st.popover("💬 Zeptat se AI asistenta", use_container_width=True):
        st.markdown("**Faktický AI Asistent**")

        for msg in st.session_state.chat_history:
            if msg["role"] != "system":
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt := st.chat_input("Zeptej se na obecná fakta k nacenění..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                response_stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=st.session_state.chat_history,
                    temperature=0.0,
                    stream=True,
                )

                # Vytvoření generátoru, který z API dat vytáhne pouze samotný text
                text_stream = (chunk.choices[0].delta.content for chunk in response_stream if
                               chunk.choices[0].delta.content is not None)

                # Streamlit nyní vypíše jen čistý text
                full_response = st.write_stream(text_stream)

            st.session_state.chat_history.append({"role": "assistant", "content": full_response})