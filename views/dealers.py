import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from db_manager import load_dealers_comparison


def render_dealers():
    st.title("Porovnání výkonnosti dealerů")
    df_dealers = load_dealers_comparison()

    if df_dealers.empty:
        st.info("Zatím nejsou k dispozici žádná data z prodejů.")
    else:
        all_dealers = sorted(df_dealers['dealer'].unique().tolist())
        f_col1, f_col2 = st.columns([3, 1])
        with f_col1:
            top_3 = df_dealers.groupby('dealer')['turnover'].sum().sort_values(ascending=False).head(3).index.tolist()
            default_selection = list(set(top_3 + (["DF"] if "DF" in all_dealers else [])))
            selected_dealers = st.multiselect("Vyber dealery k porovnání:", all_dealers, default=default_selection)
        with f_col2:
            metric_to_show = st.selectbox("Zobrazovaná metrika:", ["Obrat", "Zisk (příprava)"])

        if not selected_dealers:
            st.warning("Vyber alespoň jednoho dealera.")
        else:
            val_col = 'turnover' if metric_to_show == "Obrat" else 'profit'
            df_plot = df_dealers[df_dealers['dealer'].isin(selected_dealers)].copy()
            st.markdown("### Meziroční porovnání (Aktuální měsíc vs. Loni)")
            max_month = df_plot['month'].max()

            try:
                yr, mo = max_month.split('-')
                last_year_month = f"{int(yr) - 1}-{mo}"
                kpi_cols = st.columns(len(selected_dealers))
                for idx, dealer in enumerate(selected_dealers):
                    dealer_data = df_plot[df_plot['dealer'] == dealer]
                    val_now = dealer_data[dealer_data['month'] == max_month][val_col].sum()
                    val_last_year = dealer_data[dealer_data['month'] == last_year_month][val_col].sum()
                    delta = val_now - val_last_year
                    delta_pct = (delta / val_last_year * 100) if val_last_year > 0 else 0.0

                    with kpi_cols[idx]:
                        st.metric(
                            label=f"{dealer} ({mo}/{yr})",
                            value=f"{val_now:,.0f} Kč".replace(",", " "),
                            delta=f"{delta:,.0f} Kč ({delta_pct:+.1f} %)".replace(",",
                                                                                  " ") if val_last_year > 0 else "Žádná data z loňska",
                            delta_color="normal"
                        )
            except Exception:
                st.info("Nemám dostatek dat pro meziroční srovnání (YoY).")

            st.markdown("---")

            custom_theme_colors = [
                "#f39c12", "#3498db", "#2ecc71", "#e74c3c", "#95a5a6",
                "#1abc9c", "#f1c40f", "#e67e22", "#2980b9", "#27ae60"
            ]
            dealer_colors = {d: custom_theme_colors[i % len(custom_theme_colors)] for i, d in
                             enumerate(selected_dealers)}

            pivot_time = df_plot.pivot(index='month', columns='dealer', values=val_col).fillna(0)

            tab_g1, tab_g2, tab_g3 = st.tabs(
                ["Srovnání vývoje (Čárový)", "Podíl na celku (Skládané sloupce)", "Kumulativní (Letos vs. Loni)"])

            with tab_g1:
                st.subheader(f"Měsíční vývoj ({metric_to_show}) - Srovnání dealerů")
                fig_time = go.Figure()
                for col in pivot_time.columns:
                    fig_time.add_trace(go.Scatter(
                        x=pivot_time.index, y=pivot_time[col], mode='lines+markers', name=col,
                        line=dict(color=dealer_colors[col], width=3)
                    ))
                fig_time.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Měsíc",
                                       yaxis_title=f"{metric_to_show} (Kč)", hovermode="x unified")
                st.plotly_chart(fig_time, use_container_width=True)

            with tab_g2:
                st.subheader(f"Měsíční vývoj ({metric_to_show}) - Skládaný podíl na celku")
                fig_bar = go.Figure()
                for col in pivot_time.columns:
                    fig_bar.add_trace(go.Bar(
                        x=pivot_time.index, y=pivot_time[col], name=col,
                        marker_color=dealer_colors[col]
                    ))
                fig_bar.update_layout(barmode='stack', height=400, margin=dict(l=20, r=20, t=20, b=20),
                                      xaxis_title="Měsíc", yaxis_title=f"{metric_to_show} (Kč)", hovermode="x unified")
                st.plotly_chart(fig_bar, use_container_width=True)

            with tab_g3:
                st.subheader(f"Kumulativní růst ({metric_to_show}) - Letos vs. Loni")
                current_year = max_month.split('-')[0]
                last_year = str(int(current_year) - 1)

                df_ytd = df_plot[df_plot['month'].str.startswith(current_year)].copy()
                df_lytd = df_plot[df_plot['month'].str.startswith(last_year)].copy()

                fig_ytd = go.Figure()

                def add_cumulative_trace(df_year, year_label, line_dash, is_current_year):
                    if not df_year.empty:
                        df_year = df_year.sort_values(by=['dealer', 'month'])
                        df_year['cumulative'] = df_year.groupby('dealer')[val_col].cumsum()
                        df_year['month_only'] = df_year['month'].apply(lambda x: x.split('-')[1])
                        pivot_cum = df_year.pivot(index='month_only', columns='dealer',
                                                  values='cumulative').ffill().fillna(0)

                        for col in pivot_cum.columns:
                            fig_ytd.add_trace(go.Scatter(
                                x=pivot_cum.index, y=pivot_cum[col],
                                mode='lines+markers' if is_current_year else 'lines',
                                name=f"{col} ({year_label})",
                                line=dict(color=dealer_colors[col], width=3 if is_current_year else 2, dash=line_dash)
                            ))

                add_cumulative_trace(df_ytd, current_year, 'solid', True)
                add_cumulative_trace(df_lytd, last_year, 'dash', False)

                fig_ytd.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Měsíc v roce",
                                      yaxis_title=f"Kumulativní {metric_to_show} (Kč)", hovermode="x unified")
                st.plotly_chart(fig_ytd, use_container_width=True)