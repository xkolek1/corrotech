import streamlit as st
import pandas as pd
from db_manager import (
    load_users, load_clients, load_products, load_client_invoices, get_db_connection,
    add_user, update_user, delete_user,
    add_client, update_client, delete_client,
    add_product, update_product, delete_product
)

def render_admin():
    st.title("Správa systému")

    df_users = load_users()
    df_clients = load_clients()
    df_products = load_products()

    main_tabs = st.tabs(["Uživatelé", "Firmy", "Produkty", "Prodeje"])

    with main_tabs[0]:
        st.dataframe(df_users, use_container_width=True, hide_index=True)
        st.markdown("---")
        utab1, utab2, utab3 = st.tabs(["Přidat uživatele", "Upravit uživatele", "Smazat uživatele"])

        with utab1:
            with st.form("add_user_form", clear_on_submit=True):
                n_id = st.text_input("ID uživatele (VARCHAR identifikátor)")
                n_name = st.text_input("Jméno a příjmení")
                n_email = st.text_input("E-mail", autocomplete="email")
                n_phone = st.text_input("Telefonní číslo")
                n_role = st.selectbox("Role", ["User", "Admin"])
                n_pass = st.text_input("Heslo", type="password", autocomplete="new-password")
                if st.form_submit_button("Vytvořit účet"):
                    if all([n_id, n_name, n_email, n_pass]):
                        if add_user(n_id, n_email, n_name, n_role, n_phone, n_pass):
                            st.success("Přidáno!")
                            st.rerun()
                        else:
                            st.error("Uživatel s tímto e-mailem nebo ID už existuje.")
                    else:
                        st.warning("Vyplňte vše kromě telefonu (ten je nepovinný).")

        with utab2:
            u_edit = st.selectbox("Vyber uživatele k úpravě", df_users['email'].tolist(), key="u_edit_sel")
            if u_edit:
                u_row = df_users[df_users['email'] == u_edit].iloc[0]
                with st.form("edit_user_form"):
                    e_id = st.text_input("ID uživatele", value=str(u_row['id']))
                    e_name = st.text_input("Jméno", value=u_row['name'])
                    e_email = st.text_input("E-mail", value=u_row['email'])
                    e_phone_val = "" if pd.isna(u_row.get('phone_number')) else str(u_row.get('phone_number'))
                    e_phone = st.text_input("Telefonní číslo", value=e_phone_val)

                    e_role = st.selectbox("Role", ["User", "Admin"], index=0 if u_row['role'] == "User" else 1)
                    e_pass = st.text_input("Nové heslo (nepovinné)", type="password", autocomplete="new-password")
                    if st.form_submit_button("Uložit"):
                        if e_id and e_name and e_email:
                            if update_user(str(u_row['id']), e_id, e_email, e_name, e_role, e_phone,
                                           e_pass if e_pass else None):
                                st.success("Uloženo!")
                                if u_row['email'] == st.session_state['user_email']:
                                    st.session_state.update({'user_name': e_name, 'user_role': e_role, 'user_id': e_id,
                                                             'user_phone': e_phone})
                                st.rerun()
                            else:
                                st.error("ID nebo E-mail koliduje.")
                        else:
                            st.warning("ID, jméno a e-mail musí být vyplněny.")

        with utab3:
            u_del = st.selectbox("Vyber uživatele ke smazání", df_users['email'].tolist(), key="u_del_sel")
            if u_del:
                if u_del == st.session_state["user_email"]:
                    st.warning("Nemůžeš smazat sám sebe.")
                elif st.button("Smazat účet", type="primary"):
                    delete_user(str(df_users[df_users['email'] == u_del].iloc[0]['id']))
                    st.success("Smazáno.")
                    st.rerun()

    with main_tabs[1]:
        st.dataframe(df_clients, use_container_width=True, hide_index=True)
        st.markdown("---")
        ctab1, ctab2, ctab3, ctab4 = st.tabs(["Přidat firmu", "Upravit firmu", "Smazat firmu", "📦 Import z Excelu"])

        with ctab1:
            with st.form("add_client_form", clear_on_submit=True):
                c_ic = st.text_input("IČ (Unikátní identifikátor)")
                c_name = st.text_input("Název firmy")
                c_sales = st.number_input("Celkový obrat bez DPH (Kč)", value=0.0)
                c_prof = st.number_input("Ziskovost (Kč)", value=0.0)
                c_dealer = st.text_input("Dealer")

                if st.form_submit_button("Přidat firmu"):
                    if c_ic and c_name:
                        if add_client(c_ic, c_name, c_sales, c_prof, c_dealer):
                            st.success("Firma přidána!")
                            st.rerun()
                        else:
                            st.error("Firma s tímto IČ už existuje.")
                    else:
                        st.warning("IČ a Název nesmí být prázdné.")

        with ctab2:
            c_edit = st.selectbox("Vyber firmu k úpravě", df_clients['name'].tolist(), key="c_edit_sel", index=None,
                                  placeholder="Vyberte firmu...")
            if c_edit:
                c_row = df_clients[df_clients['name'] == c_edit].iloc[0]
                with st.form("edit_client_form"):
                    st.write(f"Úprava firmy s IČ: **{c_row['ic']}**")
                    ce_name = st.text_input("Název firmy", value=c_row['name'])

                    ce_sales_val = 0.0 if pd.isna(c_row['total_sales']) else float(c_row['total_sales'])
                    ce_sales = st.number_input("Celkový obrat bez DPH (Kč)", value=ce_sales_val)

                    ce_prof_val = 0.0 if pd.isna(c_row['total_profitability']) else float(c_row['total_profitability'])
                    ce_prof = st.number_input("Ziskovost (Kč)", value=ce_prof_val)

                    ce_dealer_val = "" if pd.isna(c_row['dealer']) else str(c_row['dealer'])
                    ce_dealer = st.text_input("Dealer", value=ce_dealer_val)

                    if st.form_submit_button("Uložit"):
                        if ce_name:
                            if update_client(str(c_row['ic']), ce_name, ce_sales, ce_prof, ce_dealer):
                                st.success("Uloženo!")
                                st.rerun()
                            else:
                                st.error("Chyba při ukládání do DB.")
                        else:
                            st.warning("Název nesmí být prázdný.")

        with ctab3:
            c_del = st.selectbox("Vyber firmu ke smazání", df_clients['name'].tolist(), key="c_del_sel", index=None,
                                 placeholder="Vyberte firmu...")
            if c_del and st.button("Smazat firmu", type="primary", key="c_del_btn"):
                delete_client(str(df_clients[df_clients['name'] == c_del].iloc[0]['ic']))
                st.success("Smazáno.")
                st.rerun()

        with ctab4:
            st.info(
                "Nahrajte soubor s analýzou odběratelů. Lze zpracovat a sečíst více listů (např. prodejních let) najednou.")
            uploaded_file = st.file_uploader("Nahrát Excel s klienty", type=["xlsx", "xls"])

            if uploaded_file:
                try:
                    xls = pd.ExcelFile(uploaded_file)
                    sheet_names = xls.sheet_names

                    st.markdown("### 1. Výběr listů ke zpracování")
                    selected_sheets = st.multiselect(
                        "Vyberte listy (např. jednotlivé roky), které se mají sečíst:",
                        sheet_names,
                        default=sheet_names
                    )

                    if selected_sheets:
                        all_dataframes = []

                        for sheet in selected_sheets:
                            df_raw = xls.parse(sheet_name=sheet, header=None, nrows=20)

                            header_idx = 0
                            for idx, row in df_raw.iterrows():
                                row_str = ' '.join([str(val).lower() for val in row.values if pd.notna(val)])
                                if 'ič' in row_str or 'ic' in row_str or 'firma' in row_str or 'název' in row_str or 'odběratel' in row_str:
                                    header_idx = idx
                                    break

                            df_sheet = xls.parse(sheet_name=sheet, header=header_idx)

                            if isinstance(df_sheet, pd.DataFrame):
                                df_sheet = df_sheet.dropna(how='all', axis=1)
                                df_sheet.columns = [str(c).replace('\n', ' ').strip() for c in df_sheet.columns]
                                all_dataframes.append(df_sheet)

                        if not all_dataframes:
                            st.warning("Nebyla nalezena žádná smysluplná data ve vybraných listech.")
                        else:
                            df_import = pd.concat(all_dataframes, ignore_index=True)
                            col_options = df_import.columns.tolist()

                            def_ic = next((c for c in col_options if 'ič' in str(c).lower() or 'ic' in str(c).lower()), col_options[0])
                            def_name = next((c for c in col_options if 'firma' in str(c).lower() or 'název' in str(c).lower() or 'odběratel' in str(c).lower()), col_options[0])
                            def_dealer = next((c for c in col_options if 'dealer' in str(c).lower() or 'zástupce' in str(c).lower()), col_options[0])

                            st.markdown("### 2. Spárování sloupců z Excelu na Databázi")
                            map_ic = st.selectbox("Sloupec s IČ (Povinné):", col_options, index=col_options.index(def_ic))
                            map_name = st.selectbox("Sloupec s Názvem firmy (Povinné):", col_options, index=col_options.index(def_name))
                            map_dealer = st.selectbox("Sloupec s Dealerem:", col_options, index=col_options.index(def_dealer))

                            sum_sales_cols = st.multiselect("Sloupce k sečtení do 'Celkového obratu bez DPH':", col_options,
                                                            default=[c for c in col_options if 'obrat' in str(c).lower() and 'bez dph' in str(c).lower()])
                            sum_prof_cols = st.multiselect("Sloupce k sečtení do 'Ziskovosti (hrubý zisk bez DPH)':", col_options,
                                                           default=[c for c in col_options if 'zisk' in str(c).lower() and 'bez dph' in str(c).lower()])

                            if st.button("Spustit import...", type="primary", icon=":material/rocket_launch:"):
                                runtime_db_conn = get_db_connection()
                                clients_dict = {}

                                for index, row in df_import.iterrows():
                                    c_ic = str(row[map_ic]).strip()
                                    c_name = str(row[map_name]).strip()

                                    if not c_ic or c_ic.lower() == 'nan' or not c_name or c_name.lower() == 'nan':
                                        continue

                                    c_dealer = str(row[map_dealer]).strip() if pd.notna(row[map_dealer]) else ""

                                    excel_total_sales = 0.0
                                    for sc in sum_sales_cols:
                                        if pd.notna(row[sc]):
                                            try:
                                                excel_total_sales += float(row[sc])
                                            except ValueError:
                                                pass

                                    excel_total_prof = 0.0
                                    for pc in sum_prof_cols:
                                        if pd.notna(row[pc]):
                                            try:
                                                excel_total_prof += float(row[pc])
                                            except ValueError:
                                                pass

                                    if c_ic in clients_dict:
                                        clients_dict[c_ic]['sales'] += excel_total_sales
                                        clients_dict[c_ic]['prof'] += excel_total_prof
                                        if c_dealer and not clients_dict[c_ic]['dealer']:
                                            clients_dict[c_ic]['dealer'] = c_dealer
                                    else:
                                        clients_dict[c_ic] = {
                                            'name': c_name,
                                            'dealer': c_dealer,
                                            'sales': excel_total_sales,
                                            'prof': excel_total_prof
                                        }

                                imported_count = 0
                                with runtime_db_conn.cursor() as r_cursor:
                                    for ic_key, data in clients_dict.items():
                                        r_cursor.execute('''
                                                         INSERT INTO clients (ic, name, total_sales, total_profitability, dealer)
                                                         VALUES (%s, %s, %s, %s, %s) ON CONFLICT (ic) DO
                                                         UPDATE
                                                             SET name = EXCLUDED.name,
                                                             total_sales = EXCLUDED.total_sales,
                                                             total_profitability = EXCLUDED.total_profitability,
                                                             dealer = EXCLUDED.dealer
                                                         ''',
                                                         (ic_key, data['name'], data['sales'], data['prof'], data['dealer']))

                                        imported_count += 1

                                load_clients.clear()
                                st.success(f"Úspěšně naimportováno / zaktualizováno {imported_count} unikátních firem (sloučeno ze {len(selected_sheets)} listů)!")
                                st.rerun()

                except Exception as ex:
                    st.error(f"Při zpracování Excelu došlo k chybě: {ex}")

    with main_tabs[2]:
        st.dataframe(df_products, use_container_width=True, hide_index=True)
        st.markdown("---")
        ptab1, ptab2, ptab3 = st.tabs(["Přidat produkt", "Upravit produkt", "Smazat produkt"])

        with ptab1:
            with st.form("add_product_form", clear_on_submit=True):
                p_name = st.text_input("Název produktu")
                p_price = st.number_input("Jednotková skladová cena (Kč)", min_value=0.0, value=0.0)

                if st.form_submit_button("Přidat produkt"):
                    if p_name:
                        if add_product(p_name, p_price):
                            st.success("Produkt přidán!")
                            st.rerun()
                        else:
                            st.error("Produkt s tímto názvem už existuje.")
                    else:
                        st.warning("Název nesmí být prázdný.")

        with ptab2:
            p_edit = st.selectbox("Vyber produkt k úpravě", df_products['name'].tolist(), key="p_edit_sel")
            if p_edit:
                p_row = df_products[df_products['name'] == p_edit].iloc[0]
                with st.form("edit_product_form"):
                    pe_name = st.text_input("Název produktu", value=p_row['name'])
                    pe_price_val = 0.0 if pd.isna(p_row['storage_price']) else float(p_row['storage_price'])

                    pe_price = st.number_input("Jednotková skladová cena (Kč)", min_value=0.0, value=pe_price_val)

                    if st.form_submit_button("Uložit"):
                        if pe_name:
                            if update_product(str(p_row['id']), pe_name, pe_price):
                                st.success("Uloženo!")
                                st.rerun()
                            else:
                                st.error("Kolize názvu.")
                        else:
                            st.warning("Název nesmí být prázdný.")

        with ptab3:
            p_del = st.selectbox("Vyber produkt ke smazání", df_products['name'].tolist(), key="p_del_sel")
            if p_del and st.button("Smazat produkt", type="primary", key="p_del_btn"):
                delete_product(str(df_products[df_products['name'] == p_del].iloc[0]['id']))
                st.success("Smazáno.")
                st.rerun()

        with main_tabs[3]:
            st.subheader("Import prodejů z Excelu")
            st.info("Nahraj soubor s prodeji. Systém automaticky založí chybějící produkty a firmy. U stávajících firem tvrdě aktualizuje Kód dealera podle Excelu.")

            uploaded_sales = st.file_uploader("Nahrát Excel s prodeji", type=["xlsx", "xls"], key="sales_uploader")

            if uploaded_sales:
                try:
                    df_sales = pd.read_excel(uploaded_sales)
                    required_cols = ['Doklad', 'Kód subjektu', 'Jednotková cena', 'Kód zboží', 'Název zboží', 'Datum', 'Množství']
                    missing_cols = [c for c in required_cols if c not in df_sales.columns]

                    if missing_cols:
                        st.error(f"V Excelu chybí tyto povinné sloupce: {', '.join(missing_cols)}. Zkontroluj hlavičku.")
                    else:
                        if st.button("Spustit import prodejů", type="primary", icon=":material/cloud_upload:"):
                            sales_db_conn = get_db_connection()

                            created_products = 0
                            created_clients = 0
                            updated_dealers = 0
                            imported_count = 0
                            skipped_count = 0
                            fk_error_count = 0

                            with sales_db_conn.cursor() as s_cursor:
                                unique_prods = df_sales[['Kód zboží', 'Název zboží']].drop_duplicates().dropna(subset=['Kód zboží'])
                                for _, p_row in unique_prods.iterrows():
                                    p_id = str(p_row['Kód zboží']).strip()
                                    if not p_id or p_id.lower() == 'nan': continue

                                    s_cursor.execute("SELECT id FROM products WHERE id = %s", (p_id,))
                                    if not s_cursor.fetchone():
                                        p_name = str(p_row['Název zboží']).strip()
                                        if not p_name or p_name.lower() == 'nan':
                                            p_name = f"Neznámý produkt {p_id}"

                                        s_cursor.execute("SELECT id FROM products WHERE name = %s", (p_name,))
                                        if s_cursor.fetchone():
                                            p_name = f"{p_name} ({p_id})"

                                        try:
                                            s_cursor.execute("INSERT INTO products (id, name, storage_price) VALUES (%s, %s, %s)", (p_id, p_name, 0.0))
                                            created_products += 1
                                        except Exception:
                                            pass

                                has_dealer_col = 'Kód dealera' in df_sales.columns
                                cols_to_extract = ['Kód subjektu', 'Název subjektu']
                                if has_dealer_col:
                                    cols_to_extract.append('Kód dealera')

                                unique_clients = df_sales[cols_to_extract].drop_duplicates().dropna(subset=['Kód subjektu'])

                                for _, c_row in unique_clients.iterrows():
                                    c_ic = str(c_row['Kód subjektu']).strip()
                                    if not c_ic or c_ic.lower() == 'nan': continue

                                    c_name = str(c_row['Název subjektu']).strip()
                                    if not c_name or c_name.lower() == 'nan':
                                        c_name = f"Neznámá firma ({c_ic})"

                                    c_dealer = ""
                                    if has_dealer_col and pd.notna(c_row.get('Kód dealera')):
                                        c_dealer = str(c_row['Kód dealera']).strip()
                                        if c_dealer.lower() == 'nan': c_dealer = ""

                                    s_cursor.execute("SELECT ic, dealer FROM clients WHERE ic = %s", (c_ic,))
                                    existing_client = s_cursor.fetchone()

                                    if not existing_client:
                                        try:
                                            s_cursor.execute(
                                                "INSERT INTO clients (ic, name, total_sales, total_profitability, dealer) VALUES (%s, %s, %s, %s, %s)",
                                                (c_ic, c_name, 0.0, 0.0, c_dealer)
                                            )
                                            created_clients += 1
                                        except Exception:
                                            pass
                                    else:
                                        db_dealer = existing_client[1]
                                        if c_dealer and str(db_dealer).strip() != c_dealer:
                                            try:
                                                s_cursor.execute("UPDATE clients SET dealer = %s WHERE ic = %s", (c_dealer, c_ic))
                                                updated_dealers += 1
                                            except Exception:
                                                pass

                                for index, row in df_sales.iterrows():
                                    doklad = str(row['Doklad']).strip()
                                    excel_prod_id = str(row['Kód zboží']).strip()
                                    client_ic = str(row['Kód subjektu']).strip()

                                    if not doklad or doklad.lower() == 'nan' or not excel_prod_id or excel_prod_id.lower() == 'nan' or not client_ic or client_ic.lower() == 'nan':
                                        continue

                                    try:
                                        price = int(round(float(row['Jednotková cena']))) if pd.notna(row['Jednotková cena']) else 0
                                        quantity = int(round(float(row['Množství']))) if pd.notna(row['Množství']) else 0
                                    except ValueError:
                                        price, quantity = 0, 0

                                    try:
                                        purchase_date = pd.to_datetime(row['Datum']).date()
                                    except Exception:
                                        purchase_date = None

                                    try:
                                        s_cursor.execute('''
                                                         INSERT INTO invoices (id, client_ic, price, product_id, purchase_date, quantity)
                                                         VALUES (%s, %s, %s, %s, %s, %s)
                                                         ON CONFLICT (id, product_id) DO NOTHING
                                                         ''',
                                                         (doklad, client_ic, price, excel_prod_id, purchase_date, quantity))

                                        if s_cursor.rowcount > 0:
                                            imported_count += 1
                                        else:
                                            skipped_count += 1
                                    except psycopg2.IntegrityError:
                                        fk_error_count += 1

                            load_products.clear()
                            load_clients.clear()
                            load_client_invoices.clear()

                            st.success(f"Hotovo! Naimportováno: {imported_count} nových prodejů. Přeskočeno duplikátů: {skipped_count}.")

                            if created_products > 0 or created_clients > 0 or updated_dealers > 0:
                                st.info(f"✨ Automatické akce na pozadí: založeno **{created_products} nových produktů**, založeno **{created_clients} nových firem** a opraven kód dealera u **{updated_dealers} stávajících firem**.")

                            if fk_error_count > 0:
                                st.warning(f"⚠️ Zahozeno {fk_error_count} záznamů kvůli nějaké neočekávané chybě integrity (foreign key constraint).")

                except Exception as e:
                    st.error(f"Během zpracování Excelu došlo k chybě: {e}")