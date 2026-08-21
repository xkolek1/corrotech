import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import calendar
import numpy as np
import datetime
from db_manager import load_monthly_sales, get_db_connection


def render_analytics():
    st.title("Časové řady, Anomálie a Predikce")

    df_monthly = load_monthly_sales()

    if df_monthly.empty:
        st.info("Zatím nejsou k dispozici žádná data.")
    else:
        df_monthly['month_dt'] = pd.to_datetime(df_monthly['month'])

        db_conn = get_db_connection()
        with db_conn.cursor() as cur:
            cur.execute("SELECT MAX(purchase_date) FROM invoices")
            max_date_val = cur.fetchone()[0]

        if not max_date_val:
            max_date_val = datetime.date.today()

        current_month_str = max_date_val.strftime('%Y-%m')

        main_view = st.radio("Základní pohled:", ["Celkový trh (Včetně anomálií)", "Výběr konkrétních firem"],
                             horizontal=True)

        if main_view == "Celkový trh (Včetně anomálií)":
            tab1, tab2, tab3, tab4, tab5 = st.tabs(
                ["Vývoj a Šoky", "Sezónnost", "Podíl firem na trhu", "Predikce (Monte Carlo)", "Hlídač výpadků"])

            ts_overall = df_monthly.groupby('month_dt')['monthly_turnover'].sum().reset_index()
            ts_overall = ts_overall.sort_values('month_dt')
            ts_overall['month_num'] = ts_overall['month_dt'].dt.month

            current_month_dt = pd.to_datetime(current_month_str)
            ts_completed = ts_overall[ts_overall['month_dt'] < current_month_dt].copy()

            if not ts_completed.empty:
                monthly_avg = ts_completed.groupby('month_num')['monthly_turnover'].mean()
                overall_avg = ts_completed['monthly_turnover'].mean()
                season_index = (monthly_avg / overall_avg).to_dict()
            else:
                season_index = {i: 1.0 for i in range(1, 13)}

            ts_completed['season_index'] = ts_completed['month_num'].map(season_index).fillna(1.0)
            ts_completed['adj_turnover'] = ts_completed['monthly_turnover'] / ts_completed['season_index']

            window_size = 6
            ts_completed['trend'] = ts_completed['adj_turnover'].rolling(window=window_size, min_periods=1).mean()
            ts_completed['std'] = ts_completed['adj_turnover'].rolling(window=window_size, min_periods=3).std().fillna(
                0)
            ts_completed['upper_bound'] = ts_completed['trend'] + (1.96 * ts_completed['std'])
            ts_completed['lower_bound'] = ts_completed['trend'] - (1.96 * ts_completed['std'])

            anomalies_high = ts_completed[ts_completed['adj_turnover'] > ts_completed['upper_bound']]
            anomalies_low = ts_completed[
                (ts_completed['adj_turnover'] < ts_completed['lower_bound']) & (ts_completed['adj_turnover'] > 0)]

            with tab1:
                st.markdown("### Historický vývoj obratu (Bez aktuálního měsíce)")
                fig_ts = go.Figure()
                fig_ts.add_trace(
                    go.Scatter(x=ts_completed['month_dt'], y=ts_completed['monthly_turnover'], mode='lines',
                               name='Reálný obrat', line=dict(color='rgba(31, 119, 180, 0.7)', width=2)))
                fig_ts.add_trace(go.Scatter(x=ts_completed['month_dt'], y=ts_completed['adj_turnover'], mode='lines',
                                            name='Sezónně očištěný obrat', line=dict(color='#f39c12', width=3)))
                fig_ts.add_trace(go.Scatter(x=ts_completed['month_dt'], y=ts_completed['trend'], mode='lines',
                                            name='Trend (6M očištěný)',
                                            line=dict(color='#e74c3c', width=2, dash='dot')))
                fig_ts.add_trace(
                    go.Scatter(x=anomalies_high['month_dt'], y=anomalies_high['adj_turnover'], mode='markers',
                               name='Pozitivní šok',
                               marker=dict(color='green', size=10, symbol='circle-open', line=dict(width=2))))
                fig_ts.add_trace(
                    go.Scatter(x=anomalies_low['month_dt'], y=anomalies_low['adj_turnover'], mode='markers',
                               name='Negativní šok', marker=dict(color='red', size=10, symbol='x', line=dict(width=2))))

                fig_ts.update_layout(height=450, hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_ts, use_container_width=True)

            with tab2:
                st.markdown("### Sezónnost (Průměrný výkon v měsících)")
                cz_months = {1: 'Leden', 2: 'Únor', 3: 'Březen', 4: 'Duben', 5: 'Květen', 6: 'Červen', 7: 'Červenec',
                             8: 'Srpen', 9: 'Září', 10: 'Říjen', 11: 'Listopad', 12: 'Prosinec'}
                seasonality = ts_completed.groupby('month_num')['monthly_turnover'].mean().reindex(range(1, 13)).fillna(
                    0).reset_index()
                seasonality['month_name'] = seasonality['month_num'].map(cz_months)

                fig_season = go.Figure(go.Bar(
                    x=seasonality['month_name'],
                    y=seasonality['monthly_turnover'],
                    marker_color='#2ecc71',
                    text=seasonality['monthly_turnover'].apply(
                        lambda x: f"{x:,.0f} Kč".replace(",", " ") if x > 0 else ""),
                    textposition='auto'
                ))
                fig_season.update_layout(height=400, xaxis_title="", yaxis_title="Průměrný obrat (Kč)")
                st.plotly_chart(fig_season, use_container_width=True)

            with tab3:
                st.markdown("### Zásluha firem na celkovém obratu")
                sp_col1, sp_col2, sp_col3 = st.columns([1, 1, 2])
                with sp_col1:
                    share_period_type = st.radio("Časový úsek:", ["Celý rok", "Konkrétní měsíc"])
                with sp_col2:
                    if share_period_type == "Celý rok":
                        available_years = sorted(df_monthly['month_dt'].dt.year.unique().tolist(), reverse=True)
                        selected_period = st.selectbox("Vyber rok:", available_years)
                        df_share = df_monthly[df_monthly['month_dt'].dt.year == selected_period]
                    else:
                        available_months = sorted(df_monthly['month'].unique().tolist(), reverse=True)
                        available_months = [m for m in available_months if m != current_month_str]
                        selected_period = st.selectbox("Vyber měsíc:", available_months)
                        df_share = df_monthly[df_monthly['month'] == selected_period]
                with sp_col3:
                    top_share_n = st.slider("Oddělit do grafu Top X firem:", 1, 20, 5)

                if df_share.empty:
                    st.info("Pro vybrané období nejsou data.")
                else:
                    firm_totals = df_share.groupby('client_name')['monthly_turnover'].sum().sort_values(ascending=False)
                    total_turnover = firm_totals.sum()
                    top_firms_share = firm_totals.head(top_share_n)
                    others_share = firm_totals.iloc[top_share_n:].sum()
                    labels = top_firms_share.index.tolist()
                    values = top_firms_share.values.tolist()
                    if others_share > 0:
                        labels.append(f"Ostatní firmy ({len(firm_totals) - top_share_n})")
                        values.append(others_share)

                    fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.4, textinfo='percent+label',
                                                     hovertemplate="<b>%{label}</b><br>Obrat: %{value:,.0f} Kč<br>Podíl: %{percent}<extra></extra>")])
                    fig_pie.update_layout(height=550, margin=dict(l=0, r=0, t=20, b=120), showlegend=True)
                    st.plotly_chart(fig_pie, use_container_width=True)
                    st.metric(f"Celkový obrat trhu ({selected_period})", f"{total_turnover:,.0f} Kč".replace(",", " "))

            with tab4:
                st.markdown("### Stochastická predikce (Monte Carlo)")
                st.info(
                    "Z výpočtu je zcela vyřazen aktuální (neuzavřený) měsíc. Simulace počítá 1000 možných scénářů na základě historické volatility Month-over-Month a ukazuje medián a 90% interval spolehlivosti.")

                if len(ts_completed) >= 12:
                    ts_completed['growth'] = ts_completed['monthly_turnover'].pct_change().dropna()
                    mu = ts_completed['growth'].mean()
                    sigma = ts_completed['growth'].std()

                    last_val = ts_completed['monthly_turnover'].iloc[-1]
                    last_date = ts_completed['month_dt'].iloc[-1]

                    simulations = 1000
                    months_to_predict = 6

                    np.random.seed(42)
                    random_returns = np.random.normal(mu, sigma, (months_to_predict, simulations))

                    price_paths = np.zeros_like(random_returns)
                    price_paths[0] = last_val * (1 + random_returns[0])
                    for t in range(1, months_to_predict):
                        price_paths[t] = price_paths[t - 1] * (1 + random_returns[t])

                    future_dates = [last_date + pd.DateOffset(months=i) for i in range(1, months_to_predict + 1)]

                    p5 = np.percentile(price_paths, 5, axis=1)
                    p50 = np.percentile(price_paths, 50, axis=1)
                    p95 = np.percentile(price_paths, 95, axis=1)

                    fig_pred = go.Figure()

                    hist_plot = ts_completed.tail(12)
                    fig_pred.add_trace(go.Scatter(x=hist_plot['month_dt'], y=hist_plot['monthly_turnover'],
                                                  mode='lines+markers', name='Uzavřená historie',
                                                  line=dict(color='#1f77b4', width=2)))

                    x_ci = [last_date] + future_dates + future_dates[::-1] + [last_date]
                    y_ci = [last_val] + list(p95) + list(p5[::-1]) + [last_val]

                    fig_pred.add_trace(go.Scatter(
                        x=x_ci, y=y_ci, fill='toself', fillcolor='rgba(155, 89, 182, 0.2)',
                        line=dict(color='rgba(255,255,255,0)'), showlegend=False, name='90% Interval spolehlivosti'
                    ))

                    pred_x = [last_date] + future_dates
                    pred_y = [last_val] + list(p50)

                    fig_pred.add_trace(go.Scatter(x=pred_x, y=pred_y, mode='lines+markers',
                                                  name='Očekávaný vývoj (Medián)',
                                                  line=dict(color='#9b59b6', width=3, dash='dash')))

                    fig_pred.update_layout(height=450, hovermode="x unified")
                    st.plotly_chart(fig_pred, use_container_width=True)
                else:
                    st.warning("Pro Monte Carlo simulaci potřebuje systém uzavřená data za více než 12 měsíců.")

            with tab5:
                st.markdown("### Hlídač výpadků (Riziko ztráty klienta)")

                df_completed_churn = df_monthly[df_monthly['month_dt'] < current_month_dt]

                if not df_completed_churn.empty:
                    pivot_churn = df_completed_churn.pivot_table(index='client_name', columns='month_dt',
                                                                 values='monthly_turnover', aggfunc='sum').fillna(0)
                    churn_alerts = []
                    for client, row in pivot_churn.iterrows():
                        recent_6m = row.tail(6)
                        if len(recent_6m) == 6:
                            last_2m = recent_6m.tail(2).sum()
                            prev_4m = recent_6m.head(4).sum()
                            if prev_4m > 50000 and last_2m == 0:
                                churn_alerts.append({
                                    'Firma': client,
                                    'Obrat (4 měsíce před výpadkem)': prev_4m,
                                    'Obrat (poslední 2 uzavřené měsíce)': last_2m,
                                    'Status': '🔴 Kritický výpadek'
                                })
                    if churn_alerts:
                        df_churn = pd.DataFrame(churn_alerts).sort_values('Obrat (4 měsíce před výpadkem)',
                                                                          ascending=False)
                        df_churn['Obrat (4 měsíce před výpadkem)'] = df_churn['Obrat (4 měsíce před výpadkem)'].apply(
                            lambda x: f"{x:,.0f} Kč".replace(",", " "))
                        df_churn['Obrat (poslední 2 uzavřené měsíce)'] = "0 Kč"
                        st.dataframe(df_churn, use_container_width=True, hide_index=True)
                    else:
                        st.success(
                            "Vypadá to skvěle! Žádný z významných klientů nemá v posledních plných měsících kritický výpadek nákupů.")
                else:
                    st.info("Zatím není dostatek uzavřených měsíců pro výpočet výpadků.")


        elif main_view == "Výběr konkrétních firem":
            st.markdown("---")
            col_sel1, col_sel2 = st.columns([1, 1])
            selected_firms = []

            with col_sel1:
                selection_method = st.radio("Jak vybrat firmy:", ["Zadat ručně", "Top X firem automaticky"],
                                            horizontal=True)
                if selection_method == "Top X firem automaticky":
                    top_x_num = st.slider("Počet firem (Top X):", 1, 30, 5)
                    selected_firms = df_monthly.groupby('client_name')['monthly_turnover'].sum().nlargest(
                        top_x_num).index.tolist()
                    st.info(f"**Vybráno:** {', '.join(selected_firms)}")
                else:
                    all_clients = sorted(df_monthly["client_name"].unique().tolist())
                    selected_firms = st.multiselect("Vyber firmy ke srovnání:", all_clients)

            with col_sel2:
                display_type = st.radio("Způsob výpisu v grafu:",
                                        ["Jednotlivé čáry (max 10 firem)", "Souhrnný graf (Průměr vybraných)"],
                                        horizontal=True)
                plot_individual = display_type == "Jednotlivé čáry (max 10 firem)"
                show_average = not plot_individual

                if plot_individual and len(selected_firms) > 10:
                    st.warning("Při výběru více než 10 firem by byl graf nepřehledný. Bude zobrazeno pouze prvních 10.")
                    selected_firms = selected_firms[:10]

                if plot_individual:
                    normalize_trend = st.checkbox("Porovnat pouze trend (Normalizace do stejného měřítka 0-100 %)",
                                                  help="Eliminuje rozdíly v objemech peněz.")
                else:
                    normalize_trend = False

            df_plot = df_monthly[df_monthly['client_name'].isin(selected_firms)].copy()

            tab_v1, tab_v2 = st.tabs(["Porovnání vývoje", "Porovnání sezónnosti"])

            with tab_v1:
                if df_plot.empty or not selected_firms:
                    st.info("Vyber alespoň jednu firmu pro zobrazení dat.")
                else:
                    fig_ts = go.Figure()
                    y_axis_title = "Obrat (% z historického maxima)" if normalize_trend else "Obrat (Kč)"

                    if plot_individual:
                        for firm in selected_firms:
                            f_data = df_plot[df_plot['client_name'] == firm].groupby('month_dt')[
                                'monthly_turnover'].sum().reset_index()
                            if normalize_trend and f_data['monthly_turnover'].max() > 0:
                                f_data['plot_val'] = (f_data['monthly_turnover'] / f_data[
                                    'monthly_turnover'].max()) * 100
                            else:
                                f_data['plot_val'] = f_data['monthly_turnover']
                            fig_ts.add_trace(
                                go.Scatter(x=f_data['month_dt'], y=f_data['plot_val'], mode='lines+markers', name=firm,
                                           line=dict(width=2)))

                    elif show_average:
                        agg_data = df_plot.groupby(['month_dt', 'client_name'])['monthly_turnover'].sum().reset_index()
                        avg_data = agg_data.groupby('month_dt')['monthly_turnover'].mean().reset_index()
                        avg_data['plot_val'] = avg_data['monthly_turnover']

                        fig_ts.add_trace(
                            go.Scatter(x=avg_data['month_dt'], y=avg_data['plot_val'], mode='lines+markers',
                                       name='Průměr vybraných firem', line=dict(width=3, color='#9b59b6')))

                    fig_ts.update_layout(height=450, hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0),
                                         yaxis_title=y_axis_title)
                    st.plotly_chart(fig_ts, use_container_width=True)

            with tab_v2:
                cz_months = {1: 'Leden', 2: 'Únor', 3: 'Březen', 4: 'Duben', 5: 'Květen', 6: 'Červen', 7: 'Červenec',
                             8: 'Srpen', 9: 'Září', 10: 'Říjen', 11: 'Listopad', 12: 'Prosinec'}
                df_completed = df_plot[df_plot['month_dt'] < pd.to_datetime(current_month_str)].copy()

                if not df_completed.empty:
                    df_completed['month_num'] = df_completed['month_dt'].dt.month
                    fig_season = go.Figure()
                    y_axis_title_season = "Průměrný obrat (% z nejsilnějšího měsíce)" if normalize_trend else "Průměrný obrat (Kč)"

                    if plot_individual:
                        for firm in selected_firms:
                            f_season = df_completed[df_completed['client_name'] == firm].groupby('month_num')[
                                'monthly_turnover'].mean().reindex(range(1, 13)).fillna(0).reset_index()
                            f_season['month_name'] = f_season['month_num'].map(cz_months)

                            if normalize_trend and f_season['monthly_turnover'].max() > 0:
                                f_season['plot_val'] = (f_season['monthly_turnover'] / f_season[
                                    'monthly_turnover'].max()) * 100
                            else:
                                f_season['plot_val'] = f_season['monthly_turnover']

                            fig_season.add_trace(go.Bar(x=f_season['month_name'], y=f_season['plot_val'], name=firm))

                    elif show_average:
                        agg_season = df_completed.groupby(['month_num', 'client_name'])[
                            'monthly_turnover'].sum().reset_index()
                        avg_season = agg_season.groupby('month_num')['monthly_turnover'].mean().reindex(
                            range(1, 13)).fillna(0).reset_index()
                        avg_season['month_name'] = avg_season['month_num'].map(cz_months)
                        avg_season['plot_val'] = avg_season['monthly_turnover']

                        fig_season.add_trace(go.Bar(x=avg_season['month_name'], y=avg_season['plot_val'], name='Průměr',
                                                    marker_color='#9b59b6'))

                    fig_season.update_layout(height=400, barmode='group', xaxis_title="",
                                             yaxis_title=y_axis_title_season)
                    st.plotly_chart(fig_season, use_container_width=True)
                else:
                    st.info("Nedostatek uzavřených měsíců pro výpočet sezónnosti u těchto firem.")