# CORROTECH CPQ

## Overview

CORROTECH CPQ is a Streamlit application for managing customers, products, users, and PDF quotations.
It also includes tools for:

- customer and dealer dashboards,
- PDF quote generation,
- archive and verification of generated PDFs,
- Excel and JSON import workflows for sales data.

## Project structure

- `app.py` – main Streamlit application
- `pdf_generator.py` – PDF layout and calculation logic
- `dbExp.py` – JSON invoice import utility
- `data/` – source JSON exports used by the importer
- `img/` – logos and assets used in the UI and PDF output

## Requirements

- Python 3.12 or newer
- PostgreSQL database
- Streamlit secrets configuration for the app connection

## Configuration

The main app reads the database connection string from Streamlit secrets:

```toml
[postgres]
DATABASE_URL = "postgresql://..."
```

For the import script, you can also provide `DATABASE_URL` through an environment variable.

## Run the application

```powershell
streamlit run app.py
```

## Import invoices from JSON

To import invoice headers and items from the bundled JSON files:

```powershell
python dbExp.py
```

The script expects the following files to exist in `data/`:

- `VydejkyHlav.json`
- `VydejkyZbozi.json`

## Notes

- The PDF generator uses Windows Arial fonts located in `C:\Windows\Fonts`.
- Generated PDFs are archived in PostgreSQL so they can be verified later.
- Cached data in the Streamlit app may need a manual refresh after bulk imports.
