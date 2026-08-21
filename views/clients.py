import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db_manager import load_monthly_sales

def render_clients():
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