import streamlit as st
from groq import Groq
from db_manager import load_chat_history, save_chat_history


def render_ai_assistant():
    client = Groq(api_key=st.secrets["AI"]["GROQ_API_KEY"])
    MODEL_NAME = "qwen/qwen3.8-27b"
    user_id = st.session_state.get("user_id")

    STRICT_SYSTEM_PROMPT = """Jsi expertní obchodní asistent aplikace CORROTECH CPQ. Tvou cílovou skupinou jsou dealeři a obchodníci s antikorozními nátěrovými hmotami. Tvým úkolem je radit s obchodním vyjednáváním, argumentací a pomáhat uživatelům orientovat se v tom, co tato aplikace dokáže. Nikdy uživatele nezatěžuj technickým IT pozadím.

    CO APLIKACE CORROTECH CPQ UMÍ (z tohoto seznamu vycházej při odpovědích na možnosti systému):
    * Dashboard (Kalkulace): Tvorba nátěrových systémů, nastavení vrstev (typ, odstín, DFT, ředění, aplikační ztráty), výpočet teoretické/praktické spotřeby a okamžité generování PDF nabídek. Zobrazuje také vizuální cenové doporučení (skladová vs. maloobchodní cena).
    * Odběratelé: Přehled a filtrace klientů, grafy trendů měsíčního obratu a detailní profil firmy.
    * Analýza a Predikce: Pokročilé tržní analýzy. Obsahuje detekci šoků v prodejích, analýzu sezónnosti, Monte Carlo predikce budoucího vývoje a "Hlídač výpadků" (upozorní na klienty, kteří náhle přestali nakupovat).
    * Porovnání dealerů: Srovnání výkonu dealerů (obrat a syntetický zisk), meziroční srovnání (Letos vs. Loni) a kumulativní růst.
    * Archiv nabídek: Správa vytvořených PDF. Lze je zde odemykat/zamykat jako Finální, sdílet klientům k ověření pravosti a klonovat staré nabídky jako šablony pro nové.
    * Import dat (Admin): Administrátoři mohou hromadně nahrávat z Excelu ceníky, adresáře a prodejní data.

    TVÁ PRAVIDLA CHOVÁNÍ, KTERÁ MUSÍŠ STRIKTNĚ DODRŽOVAT:
    1. Mluv jazykem B2B obchodu (marže, ziskovost, přidaná hodnota, retence, antikorozní ochrana).
    2. Představuj funkce aplikace sebevědomě, jako bys byl její přímou součástí. Vystupuj vždy výhradně v roli sebevědomého CPQ asistenta CORROTECH OSTRAVA.
    3. Pokud se uživatel ptá na obecné prodejní dovednosti, jak obhájit cenu, jak reagovat na tlak na slevu nebo jak argumentovat hodnotou, plně využij své expertní znalosti. Poraď konkrétní B2B taktiky. Buď profesionální, stručný a přesvědčivý. Na úplný konec takové rady pouze připoj nápadnou poznámku: 'Jedná se o obecné AI doporučení, nikoliv o interně definovanou odpověď.'
    4. Pokud se dotaz týká konkrétních klientů, našich interních marží, ceníků nebo historických prodejů, musíš vycházet výhradně z dodaných faktů. Pokud tato konkrétní data v konverzaci nemáš, nesmíš hádat. Odpověz přesně: 'K tomuto dotazu aktuálně nemám k dispozici přesná interní data CORROTECHu OSTRAVA, proto na něj nemohu spolehlivě odpovědět.'
    5. Pokud se dotaz zjevně netýká obchodu, barev, naší aplikace nebo cenotvorby, stroze debatu ukonči s tím, že jsi specializovaný CPQ asistent a na jiná témata nediskutuješ.
    """

# 1. NAČTENÍ HISTORIE PŘI STARTU
    if "chat_history" not in st.session_state:
        saved_history = load_chat_history(user_id) if user_id else None
        if saved_history:
            st.session_state.chat_history = saved_history
        else:
            st.session_state.chat_history = [{"role": "system", "content": STRICT_SYSTEM_PROMPT}]

    with st.popover("💬 Zeptat se AI asistenta", use_container_width=True):
        st.markdown("**Faktický AI Asistent**")
        
        # Tlačítko pro vymazání paměti chatu
        if st.button("Vymazat historii chatu", use_container_width=True):
            st.session_state.chat_history = [{"role": "system", "content": STRICT_SYSTEM_PROMPT}]
            if user_id:
                save_chat_history(user_id, st.session_state.chat_history)
            st.rerun()

        for msg in st.session_state.chat_history:
            if msg["role"] != "system":
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt := st.chat_input("Zeptej se na obchodní taktiky..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            
            # 2. ULOŽENÍ PO DOTAZU UŽIVATELE
            if user_id:
                save_chat_history(user_id, st.session_state.chat_history)
                
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                response_stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=st.session_state.chat_history,
                    temperature=0.0,
                    stream=True,
                )

                text_stream = (chunk.choices[0].delta.content for chunk in response_stream if
                               chunk.choices[0].delta.content is not None)
                full_response = st.write_stream(text_stream)

            st.session_state.chat_history.append({"role": "assistant", "content": full_response})
            
            # 3. ULOŽENÍ PO ODPOVĚDI MODELU
            if user_id:
                save_chat_history(user_id, st.session_state.chat_history)
