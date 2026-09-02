import json
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
import os

# Database import configuration
DATABASE_URL = os.environ.get("DATABASE_URL",
                              "xx")  # Replace with your actual database URL or use environment variable


def load_json_data(filepath):
    """Načte JSON soubor a vrátí jeho obsah jako Python objekt.

    Funkce používá UTF-8 s BOM kompatibilní dekódování, protože vstupní exporty
    mohou pocházet z různých zdrojů. Při chybě vypíše hlášku a vrátí `None`.
    """
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception as e:
        print(f"Nepodařilo se načíst soubor {filepath}: {e}")
        return None


def import_invoices_from_jsons(headers_path, items_path):
    """Naimportuje výdejky z dvojice JSON souborů do PostgreSQL.

    Hlavičky slouží pro mapování výdejky na IČ klienta, položky obsahují
    samotné prodejní řádky. Funkce doplní chybějící produkty, přeskočí záznamy
    bez odpovídajícího klienta a vloží platné výdejky do tabulky `invoices`.
    """
    print("Načítám JSON soubory ze složky data/...")

    headers_data_raw = load_json_data(headers_path)
    items_data_raw = load_json_data(items_path)

    if not headers_data_raw or not items_data_raw:
        return

    headers_data = headers_data_raw.get('data', [])
    items_data = items_data_raw.get('data', [])

    print(f"Nalezeno {len(headers_data)} hlaviček a {len(items_data)} položek.")

    ico_mapping = {}
    for header in headers_data:
        vydejka_id = str(header.get('Cislo', '')).strip()
        client_ic = str(header.get('icOdber', '')).strip()

        if vydejka_id:
            ico_mapping[vydejka_id] = client_ic

    print("Připojuji se k databázi...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
    except Exception as e:
        print(f"Chyba připojení k DB: {e}")
        return

    cursor.execute("SELECT ic FROM clients")
    existing_clients = {str(row[0]).strip() for row in cursor.fetchall()}
    print(f"V databázi nalezeno {len(existing_clients)} existujících klientů.")

    records_to_insert = []
    unique_products = set()
    reported_missing_invoices = set()

    print("Analyzuji položky...")

    for item in items_data:
        vydejka_id = str(item.get('Cislo', '')).strip()
        product_id = str(item.get('CisloZbozi', '')).strip()

        if not vydejka_id or vydejka_id.lower() == 'nan' or not product_id or product_id.lower() == 'nan':
            continue

        client_ic = ico_mapping.get(vydejka_id, "")

        if not client_ic or client_ic not in existing_clients:
            if vydejka_id not in reported_missing_invoices:
                print(
                    f"⚠️ Ignoruji výdejku {vydejka_id}: Klient s IČ '{client_ic}' neexistuje v DB nebo chybí hlavička.")
                reported_missing_invoices.add(vydejka_id)
            continue

        unique_products.add(product_id)

        try:
            price = float(item.get('PCBD', 0))
        except (ValueError, TypeError):
            price = 0.0

        try:
            quantity = float(item.get('Mn', 0))
        except (ValueError, TypeError):
            quantity = 0.0

        date_str = str(item.get('dPohybu', ''))
        purchase_date = None
        if date_str and len(date_str) == 6:
            try:
                purchase_date = datetime.strptime(date_str, '%d%m%y').date()
            except ValueError:
                purchase_date = None

        if purchase_date is None:
            continue

        records_to_insert.append((
            vydejka_id,
            client_ic,
            product_id,
            purchase_date,
            int(quantity),
            int(price)
        ))

    if not records_to_insert:
        print("Nenalezeny žádné platné záznamy k importu.")
        cursor.close()
        conn.close()
        return

    try:
        products_to_insert = [(p_id, p_id, 0.0) for p_id in unique_products]
        if products_to_insert:
            insert_products_query = """
                                    INSERT INTO products (id, name, storage_price)
                                    VALUES %s ON CONFLICT (id) DO NOTHING; \
                                    """
            execute_values(cursor, insert_products_query, products_to_insert)

        conn.commit()

        print(f"Zapisuji {len(records_to_insert)} záznamů do tabulky invoices...")
        insert_invoices_query = """
                                INSERT INTO invoices (id, client_ic, product_id, purchase_date, quantity, price)
                                VALUES %s ON CONFLICT (id, product_id) DO NOTHING; \
                                """

        execute_values(cursor, insert_invoices_query, records_to_insert)
        conn.commit()

        inserted_count = cursor.rowcount

        print("--------------------------------------------------")
        print(f"🎉 Import dokončen!")
        print(
            f"Do databáze se podařilo vložit {inserted_count} nových záznamů ze {len(records_to_insert)} (zbytek byly duplicity).")
        print(f"Počet přeskočených výdejek kvůli chybějícímu klientovi: {len(reported_missing_invoices)}")

    except psycopg2.Error as e:
        conn.rollback()
        print("--------------------------------------------------")
        print(f"❌ Při zápisu do databáze nastala chyba: {e}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    PATH_HEADERS = "data/VydejkyHlav.json"
    PATH_ITEMS = "data/VydejkyZbozi.json"

    if not os.path.exists(PATH_HEADERS) or not os.path.exists(PATH_ITEMS):
        print(f"CHYBA: Soubory '{PATH_HEADERS}' nebo '{PATH_ITEMS}' nebyly nalezeny ve složce 'data/'.")
    else:
        import_invoices_from_jsons(PATH_HEADERS, PATH_ITEMS)