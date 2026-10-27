import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db_manager import load_products
from helpers import show_pdf
from generate_hempel_pdf import get_hempel_pdfs


def render_calculations():
    st.title("Kalkulace a tvorba ceníků")
    df_products = load_products()

    st.subheader("Kalkulace marže (Gauge Chart)")
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

    st.subheader("Hempel – Barevný ceník RAL")
    st.write("Vygeneruje se PDF s vypočtenými cenami pro jednotlivé odstíny RAL a základy.")

    pdf_type = st.radio("Typ ceníku:", ["Digital (dlouhá obrazovka)", "Print (A4 na šířku)"])

    if st.button("Vygenerovat ceník Hempel", type="primary", icon=":material/palette:"):
        with st.spinner("Generuji PDF soubory..."):
            try:
                pdfs = get_hempel_pdfs("hempel_export/hempel_colors.csv")

                if "Digital" in pdf_type:
                    st.session_state["hempel_pdf_bytes"] = pdfs["digital"]
                    st.session_state["hempel_pdf_name"] = "hempel_cenik_digital.pdf"
                else:
                    st.session_state["hempel_pdf_bytes"] = pdfs["print"]
                    st.session_state["hempel_pdf_name"] = "hempel_cenik_tisk.pdf"

            except Exception as e:
                st.error(f"Chyba při generování Hempel ceníku: {e}")

    # Render via show_pdf right here on the frontend
    if "hempel_pdf_bytes" in st.session_state:
        st.success("✅ Ceník Hempel byl úspěšně vygenerován!")
        show_pdf(
            pdf_binary=st.session_state["hempel_pdf_bytes"],
            filename=st.session_state["hempel_pdf_name"]
        )