# CORROTECH CPQ

A comprehensive modular Streamlit application for Configure, Price, Quote (CPQ) workflows, customer relationship management, advanced sales analytics, and AI-assisted negotiations.

## Overview

CORROTECH CPQ is a professional sales enablement platform designed for coating and corrosion protection specialists. It combines interactive dashboards, intelligent quoting tools, advanced analytics, and AI assistance to streamline sales workflows and improve decision-making.

### Key Features

- **Interactive Dashboards** – Real-time sales performance, client insights, and product analysis
- **CPQ Workflow** – Configurable coating systems with multi-layer material specifications and automated PDF generation
- **AI Sales Assistant** – Groq-powered chatbot for sales coaching and general guidance (currently read-only; database integration in progress)
- **PDF Quote Management** – Auto-generated specifications with sequence numbering, archiving (PDF + JSON state), and template cloning
- **Advanced Analytics** – YoY comparisons, anomaly detection, seasonality analysis, churn forecasting, Monte Carlo stochastic models
- **Excel-Based Imports** – Automated updates for sales data, clients, products, and pricing
- **Secure Authentication** – Bcrypt password hashing, session tokens with SHA-256 verification, login rate-limiting, and admin alerts
- **Archive & Sharing** – Multi-state quotes (draft/finalized), soft-delete, template reuse, and shareable offer links
- **Public Verification** – PDF authentication and verification without authentication

## Current Limitations ⚠️

### Pricing & Cost Data

- **Buying Price Access**: The system currently cannot access or calculate true buying prices. Pricing recommendations use **mock cost assumptions** (`storage_price` static fields and hardcoded margin multipliers like 1.5x cost or 2x retail).
- **Profit Calculation**: 
  - Dealer profit is synthetic (hardcoded as 20% of turnover) and marked as "Zisk (příprava)" (preparation mode).
  - Client profitability is acknowledged as incomplete in the UI ("není pravda zatím" / "not true yet").
  - Last-purchase pricing is placeholder data (calculated as target × 0.92).

### AI Assistant

- The AI chatbot is **read-only** – it uses a Groq LLM to provide sales coaching and general guidance, but **cannot access database records or customer data**.
- Responses are limited to the system prompt (no data queries, no customer lookups, no historical analysis).
- Chat history is persisted in session state only (not archived to database).

**These limitations are intentional and documented. Future releases will integrate database queries into the AI pipeline.**

## Project Structure

```
corrotech/
├── app.py                    # Main Streamlit router, sidebar navigation, authentication
├── db_manager.py             # Database connections, cached queries, CRUD ops, token management
├── helpers.py                # UI components, constants, PDF display, sanitizers, email notifications
├── pdf_generator.py          # PDF layout and calculation logic (FPDF-based)
├── ai_chat.py                # Groq-powered AI assistant and chat management
├── views/
│   ├── dashboard.py          # Sales dashboard, quoting interface, PDF generation
│   ├── clients.py            # Client management and CRM
│   ├── dealers.py            # Dealer/partner management and performance
│   ├── analytics.py          # Advanced analytics (anomaly, seasonality, forecast, churn)
│   ├── archive.py            # Quote archiving, template cloning, sharing workflows
│   ├── profile.py            # User profile and authentication settings
│   └── admin.py              # System administration, imports, user management
├── .streamlit/
│   └── secrets.toml           # Secrets configuration (database, email, AI API)
├── .devcontainer/
│   └── devcontainer.json     # VS Code dev environment config
├── img/                       # Logos and UI assets (CORROTECH, CORROCOAT, HEMPEL branding)
├── fonts/                     # Local TTF fonts for PDF (Arial, etc.)
└── requirements.txt           # Python dependencies
```

## Requirements

- **Python 3.11+** (3.12 recommended)
- **PostgreSQL 12+** – Main data store
- **Key Dependencies**:
  - `streamlit` – UI framework
  - `pandas`, `numpy` – Data processing
  - `plotly` – Interactive charts
  - `psycopg2-binary` – PostgreSQL adapter
  - `bcrypt`, `fpdf` – Security and PDF generation
  - `groq` – AI assistant integration
  - `extra-streamlit-components` – Enhanced UI
  - `python-dotenv` – Environment variable management

See `requirements.txt` for complete version pinning.

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/xkolek1/corrotech.git
cd corrotech
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Secrets

Create `.streamlit/secrets.toml` in the root directory:

```toml
[postgres]
DATABASE_URL = "postgresql://username:password@host:port/dbname?sslmode=require"

[smtp]
server = "smtp.gmail.com"
port = 587
username = "your-email@gmail.com"
password = "your-app-password"
admin_email = "admin"

[AI]
GROQ_API_KEY = "your-groq-api-key"
```

**Required Secrets:**
- `postgres.DATABASE_URL` – PostgreSQL connection string
- `smtp.server`, `smtp.port`, `smtp.username`, `smtp.password`, `smtp.admin_email` – Email notifications (optional, fallback to console)
- `AI.GROQ_API_KEY` – Groq API key for AI assistant

### 5. Run the Application

```bash
streamlit run app.py
```

The app will start at `http://localhost:8501`.

## Usage

### For Sales Teams

1. **Create Quote** – Navigate to Dashboard → select client and products → configure coating system → generate PDF
2. **View Archive** – Manage past quotes, finalize offers, share with clients, clone as templates
3. **Consult AI** – Use sidebar chatbot for sales coaching (general guidance only, not customer-specific)
4. **Track Analytics** – Monitor sales trends, client performance, and forecasts in the Analytics dashboard

### For Administrators

1. **Import Data** – Admin panel supports Excel bulk import for:
   - Sales transactions (auto-creates missing clients/products)
   - Product catalog with cost and pricing
   - Client master data
2. **Manage Users** – Create, edit, and remove team members; set roles and permissions
3. **Monitor Alerts** – View login lockouts, suspicious activity, and system health

### For Dealers & Partners

1. **View Own Performance** – Dealer dashboard shows turnover, synthetic profit estimate, and territory metrics
2. **Access Quotes** – View shareable offer links generated by CORROTECH team

## Data Workflows

### Quoting (Dashboard)

1. User selects a client and initiates a quote
2. Defines surface area, coating system type, preparation steps
3. Adds material layers with DFT (dry film thickness), solids %, and unit pricing
4. System calculates theoretical and practical consumption, applicator losses, and final cost
5. PDF is generated and archived with full JSON configuration state
6. Quote can be shared via public link or finalized for client delivery

### Archiving & Templates

- **States**: Draft → Finalized → Soft-deleted
- Finalized quotes generate public verification links
- Any archived quote can be cloned as a template for new estimates

### Sales Data Integration

- **CSV/Excel Import** → Dashboard validates, creates missing records, and updates existing entries
- **Conflict handling**: Duplicate detection, field mapping, and user confirmation

### Analytics Pipeline

- **Data aggregation** from transactional tables (sales, clients, dealers)
- **Anomaly detection** (seasonal decomposition, outlier flagging)
- **Forecasting** (Monte Carlo simulation for stochastic projection)
- **Churn prediction** (behavioral markers and cohort analysis)

## Authentication & Security

- **Login**: Username/password with bcrypt hashing
- **Session Management**: 
  - SHA-256 token verification against database
  - "Remember me" cookie option
  - Automatic session cleanup on logout
- **Rate Limiting**: Failed login attempts trigger account lockout; admin is notified
- **Public API**: PDF verification endpoint accessible without authentication

## Configuration & Customization

### Environment Variables

All sensitive data should be stored in `.streamlit/secrets.toml` and referenced via `st.secrets`.

### PDF Customization

- Logos and brand assets in `img/` folder
- Font files in `fonts/` folder (current: Arial, Arial Bold)
- PDF layout and calculations in `pdf_generator.py`

### UI Text & Constants

- Common labels, prompts, and error messages in `helpers.py`
- Page-specific constants within each `views/*.py` module

## Performance Notes

- **Lazy Loading**: Heavy libraries (`pandas`, `plotly`) are imported only within pages that use them, reducing initial app load time
- **Cached Queries**: Database queries are memoized with `@st.cache_data` to avoid redundant fetches
- **Streaming Responses**: AI assistant uses streaming output for responsive UX

## Deployment

### Local Development

```bash
streamlit run app.py
```

### Production (Docker)

A `.devcontainer/devcontainer.json` is provided for consistent development and deployment environments. Adapt for your production CI/CD pipeline.

### Environment-Specific Secrets

Use different `.streamlit/secrets.toml` files per environment, or leverage CI/CD secret injection (e.g., GitHub Secrets, GitLab CI/CD variables).

## Troubleshooting

### "Module not found" errors

Ensure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### Database connection fails

- Verify PostgreSQL is running and accessible
- Check `DATABASE_URL` in `.streamlit/secrets.toml`
- Test connection: `psql "your-connection-string"`

### AI assistant not responding

- Verify `GROQ_API_KEY` is set in secrets
- Check Groq API rate limits and account status
- Review browser console for errors

### Email notifications not sent

- Verify SMTP credentials in `.streamlit/secrets.toml`
- For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833), not your account password
- Check firewall/network rules for SMTP port (typically 587 or 465)

## Development Roadmap

### High Priority
- [ ] Integrate real buying-price data into pricing calculations
- [ ] Enable AI assistant database queries for customer/product lookups
- [ ] Archive chat history to database
- [ ] Implement dynamic profit margin tables

### Medium Priority
- [ ] Multi-currency support
- [ ] Client quote approval workflow
- [ ] Enhanced forecasting models (ML-based)
- [ ] Integration with ERP systems

### Low Priority
- [ ] Mobile app version
- [ ] Advanced user role matrix
- [ ] Custom reporting export formats

## License

© 2026 CORROTECH OSTRAVA s.r.o. – Proprietary software.

## Support

This app can be used free of charge, but only with the owner’s consent.
For questions, bugs, or feature requests contact the owner.
@xkolek1

---

**CORROTECH OSTRAVA s.r.o.**  
Frýdecká 687/406, 719 00 Ostrava - Kunčice, Czech Republic  
Member of the Association of Corrosion Engineers
