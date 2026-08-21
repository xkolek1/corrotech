# CORROTECH CPQ (nearly done)

## Overview

CORROTECH CPQ is a modular Streamlit application designed for Configure, Price, Quote (CPQ) workflows, customer relationship management, and advanced sales analytics. 

The system provides tools for:
- Interactive dashboards for customers and dealers.
- PDF quote generation with automated sequence numbering.
- Secure quote archiving (saving both the PDF binary and the JSON state for future template usage).
- Advanced analytics including YoY comparisons, churn detection, and Monte Carlo stochastic forecasting.
- Excel-based imports for automated updates of sales data, clients, and products.
- Secure user authentication with bcrypt and SHA-256 hashed session tokens.

## Project Structure

The application has been refactored for lazy-loading and modularity to ensure high performance:

- `app.py` – Main Streamlit router, layout, and sidebar navigation.
- `db_manager.py` – Database connections, cached queries, CRUD operations, and token management.
- `helpers.py` – UI components, text constants, PDF display functions, and sanitizers.
- `pdf_generator.py` – PDF layout and calculation logic (using FPDF).
- `views/` – Directory containing individual page modules (`dashboard.py`, `clients.py`, `analytics.py`, `dealers.py`, `archive.py`, `profile.py`, `admin.py`).
- `dbExp.py` – Legacy JSON invoice import utility.
- `data/` – Source JSON exports used by the legacy importer.
- `img/` – Logos and assets used in the UI and PDF output.
- `fonts/` – Local TTF fonts used by the PDF generator (e.g., Arial).

## Requirements

- Python 3.12 or newer
- PostgreSQL database
- Key Python libraries: `streamlit`, `pandas`, `plotly`, `numpy`, `psycopg2-binary`, `bcrypt`, `fpdf`, `extra-streamlit-components`

## Configuration

The main app reads the database connection string from Streamlit secrets. Create a `.streamlit/secrets.toml` file in the root directory:

```toml
[postgres]
DATABASE_URL = "postgresql://username:password@host:port/dbname?sslmode=require"
```

## Running the Application

To start the application locally, run:

```powershell
streamlit run app.py
```

## Imports & Data Updates

- **Sales Data:** You can import sales and invoice data directly via the UI in the Admin panel using Excel files. The system automatically creates missing products and clients.
- **Legacy JSON Import:** To import invoice headers and items from the bundled JSON files, run `python dbExp.py`. The script expects `VydejkyHlav.json` and `VydejkyZbozi.json` in the `data/` folder.

## Notes

- **Performance:** Heavy libraries like `pandas` and `plotly` are lazy-loaded only within the views that actually require them, significantly speeding up the initial app load.
- **Security:** Session cookies are verified against SHA-256 hashes stored in the database to prevent session hijacking.
- **Archiving:** When a PDF is generated, its full configuration state is saved as JSON in the database. This allows users to load old quotes as templates without needing to parse the PDF text.
