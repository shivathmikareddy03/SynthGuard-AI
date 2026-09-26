# SynthGuard-AI - Synthetic Patient Data Generation Platform

> **Research Prototype** · Hackathon submission
>
> Generate realistic synthetic healthcare datasets for research, testing, and analytics
> without directly exposing source patient records.

---

## ⚠ Important Privacy Notice

This platform is a **research prototype**. Synthetic data generated here is:

- **Not automatically anonymous** — statistical similarity does not equal anonymity
- **Not clinically validated** — scores are prototype-level indicators only
- **Not a replacement** for a formal privacy impact assessment

Always consult a qualified privacy and data-protection expert before using synthetic data
in any clinical, regulatory, or production context.

---

## What It Does

| Step | Description |
|------|-------------|
| **Upload** | Accept CSV / XLSX de-identified healthcare datasets |
| **Profile** | Detect column types, missing values, and potentially identifying columns |
| **Preprocess** | Handle missing values, duplicates, and type coercion |
| **Generate** | Train CTGAN (SDV) and produce a large synthetic dataset |
| **Cohort control** | Resample to match researcher-specified cohort proportions |
| **Validate** | KS tests, chi-square, correlation preservation across all columns |
| **Privacy check** | Exact and near-duplicate detection with risk-level scoring |
| **Export** | Download synthetic data as CSV or Excel + validation report |

---

## Architecture

```
React + TypeScript (Vite)
        ↓  HTTP / REST
FastAPI (Python)
        ↓
Data Processing   →  pandas, numpy, scipy, scikit-learn
Synthetic Gen     →  SDV / CTGAN  (fallback: TVAE → GaussianCopula)
Validation        →  KS test, chi-square, Pearson correlation
Privacy Engine    →  exact duplicate check, L2 near-duplicate heuristic
Export            →  pandas / openpyxl (CSV + XLSX)
        ↓
SQLite  (dataset, generation, validation, privacy records)
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Recharts, Zustand |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Data processing | pandas, numpy, scipy, scikit-learn |
| Synthetic data | SDV 1.9, CTGAN 0.9 |
| Database | SQLite (via SQLAlchemy) |
| File I/O | openpyxl, pandas |

---

## Project Structure

```
synthgen/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Settings (pydantic-settings)
│   │   ├── database.py                # SQLAlchemy models + SQLite
│   │   ├── api/routes/
│   │   │   ├── dataset.py             # Upload, profile, preprocess
│   │   │   ├── generate.py            # Generate, status, preview
│   │   │   ├── validation.py          # Statistical validation
│   │   │   ├── privacy.py             # Privacy risk checks
│   │   │   └── export.py              # CSV / XLSX download
│   │   ├── models/
│   │   │   └── schemas.py             # Pydantic request/response models
│   │   └── services/
│   │       ├── data_processing.py     # Load, profile, preprocess
│   │       ├── synthetic_generation.py # CTGAN / TVAE / GaussianCopula
│   │       ├── cohort.py              # Cohort resampling
│   │       ├── validation.py          # KS, chi-square, correlation
│   │       ├── privacy.py             # Duplicate detection
│   │       └── export.py              # File export
│   ├── data/
│   │   └── demo_patient_data.csv      # Bundled demo dataset (synthetic)
│   ├── uploads/                       # Uploaded files (auto-created)
│   ├── exports/                       # Generated synthetic files (auto-created)
│   ├── generate_demo_data.py          # Script to regenerate demo data
│   ├── requirements.txt
│   └── .env
│
└── frontend/
    ├── src/
    │   ├── App.tsx
    │   ├── main.tsx
    │   ├── store.ts                   # Zustand global state
    │   ├── index.css                  # Tailwind + design system
    │   ├── components/
    │   │   ├── Layout.tsx             # Sidebar + nav
    │   │   ├── StatCard.tsx
    │   │   ├── ProgressBar.tsx
    │   │   ├── ScoreGauge.tsx
    │   │   └── RiskBadge.tsx
    │   ├── pages/
    │   │   ├── Landing.tsx
    │   │   ├── Upload.tsx
    │   │   ├── Generate.tsx
    │   │   ├── Dashboard.tsx
    │   │   ├── Validation.tsx
    │   │   ├── Privacy.tsx
    │   │   ├── SyntheticData.tsx
    │   │   └── Reports.tsx
    │   ├── services/
    │   │   └── api.ts                 # axios API client
    │   └── types/
    │       └── index.ts               # TypeScript interfaces
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    └── tsconfig.json
```

---

## Setup & Installation

### Prerequisites

- **Python 3.10+** (3.11 recommended)
- **Node.js 18+** and npm

### 1 · Backend

```bash
cd synthgen/backend

# Create a virtual environment (recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install core Python dependencies
pip install -r requirements.txt

# Install SDV/CTGAN (large download, ~5 min)
pip install -r requirements-sdv.txt

# Generate the demo dataset (run once)
python generate_demo_data.py

# Copy environment file
copy .env.example .env    # Windows
# cp .env.example .env    # macOS/Linux

# Start the backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at **http://localhost:8000**  
Interactive docs: **http://localhost:8000/docs**

### 2 · Frontend

```bash
cd synthgen/frontend

npm install

# Start the development server
npm run dev
```

The app will be available at **http://localhost:5173**

> The Vite dev server proxies all `/api` requests to `http://localhost:8000`,
> so no CORS configuration is needed during development.

---

## Demo Scenario (End-to-End)

This exact workflow is tested and working:

1. Open **http://localhost:5173**
2. Click **"Use Demo Dataset"** on the Upload page
3. Review the 12 columns — pre-sensitive flagging highlights none (demo data is clean)
4. Click **Confirm & Preprocess** → 2,000 rows preprocessed
5. Go to **Generate Data**
6. Set:
   - Synthetic records = **10,000**
   - Older patients = **40%**
   - Diabetic patients = **30%**
   - Model = **CTGAN**
7. Click **Generate** — progress bar updates every 2 seconds
8. Generation completes (typically 3–8 minutes for CTGAN on the demo dataset)
9. **Dashboard** opens automatically, showing:
   - Distribution similarity score
   - Correlation preservation score
   - Source vs synthetic comparison charts
   - Cohort accuracy (requested vs achieved %)
10. **Validation** page shows KS tests and chi-square results
11. **Privacy** page shows exact/near duplicate counts and risk level
12. **Synthetic Data** page shows paginated, searchable, sortable table
13. **Reports** page — click **Download Excel (.xlsx)**

---

## Configuration

All backend settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_HOST` | `0.0.0.0` | Host to bind |
| `BACKEND_PORT` | `8000` | Port to bind |
| `UPLOAD_DIR` | `uploads` | Directory for uploaded files |
| `EXPORT_DIR` | `exports` | Directory for generated files |
| `DATABASE_URL` | `sqlite:///./synthgen.db` | SQLite database path |
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum upload size |
| `CTGAN_EPOCHS` | `300` | Default CTGAN training epochs |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed CORS origins |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/dataset/upload` | Upload CSV/XLSX |
| `POST` | `/api/dataset/upload-demo` | Load bundled demo dataset |
| `GET`  | `/api/dataset/{id}/profile` | Column profile and statistics |
| `POST` | `/api/dataset/{id}/preprocess` | Preprocess with column selection |
| `POST` | `/api/generate` | Start synthetic generation |
| `GET`  | `/api/generation/{id}/status` | Poll generation progress |
| `GET`  | `/api/generation/{id}/preview` | Paginated synthetic data preview |
| `POST` | `/api/validation/{id}` | Run statistical validation |
| `GET`  | `/api/validation/{id}/report` | Get validation report |
| `POST` | `/api/privacy/{id}` | Run privacy risk checks |
| `GET`  | `/api/privacy/{id}/report` | Get privacy report |
| `GET`  | `/api/export/{id}/csv` | Download synthetic data as CSV |
| `GET`  | `/api/export/{id}/xlsx` | Download synthetic data as Excel |
| `GET`  | `/api/export/{id}/report-xlsx` | Download validation report as Excel |

Full interactive documentation available at `http://localhost:8000/docs`

---

## Synthetic Data Generation Details

### Model selection

| Model | Notes |
|-------|-------|
| **CTGAN** | Default. Conditional GAN — best for preserving complex relationships |
| **TVAE** | Variational autoencoder. Automatic fallback if CTGAN fails |
| **GaussianCopula** | Fastest. Second fallback. Assumes simpler distributions |

The system automatically falls back: **CTGAN → TVAE → GaussianCopula**

### Cohort resampling

Cohort targets are satisfied by **post-generation stratified resampling**, not by overwriting values. This preserves learned inter-variable relationships while approximately meeting requested proportions.

### Validation metrics

| Metric | Method |
|--------|--------|
| Distribution similarity | 1 − KS statistic, expressed as % |
| KS pass rate | % of columns where KS p-value > 0.05 |
| Correlation preservation | 1 − mean absolute correlation difference |
| Overall quality | Weighted average of the above |
| Category similarity | 1 − Total Variation Distance (TVD) |

---

## Privacy Check Details

| Check | Method |
|-------|--------|
| Exact duplicates | String-tuple matching across all columns |
| Near duplicates | Sampled L2 distance on normalised feature vectors |
| Risk level | **Low** / **Medium** / **High** based on duplicate rates |

**These are prototype-level heuristics, not a formal re-identification risk assessment.**

---

## Known Limitations

- CTGAN training can take **3–10 minutes** on the demo dataset (2,000 rows, 300 epochs). Reduce epochs for faster demos.
- Generation runs in a **background thread** — not suitable for multi-user production deployment. Use Celery + Redis for production.
- SQLite is not suitable for concurrent write-heavy production use.
- Privacy checks use **sampled** near-duplicate detection (500 records each side) for performance.
- Datetime columns are converted to ordinal integers before training. The synthetic output will contain ordinal values, not formatted dates.
- The overall quality score is a **composite prototype metric** — not a clinical or regulatory standard.

---

## Physiological Constraint Enforcement

### Why it is needed
Synthetic models (like CTGAN) can generate statistically realistic but physiologically impossible combinations. For example, a model might correctly learn the overall distribution of blood pressures but occasionally output a record where systolic BP is lower than diastolic BP.

### How it works
Generated data passes through a deterministic rule engine before being accepted into the final synthetic dataset. This engine evaluates every row against configurable medical and physiological boundaries.

### Example
Systolic BP = 120
Diastolic BP = 130

→ **Rejected** because systolic BP must be greater than diastolic BP.

### Status Categories
The system distinguishes between three levels of severity:
- **Valid**: Fully within physiological and clinical norms.
- **Warning (Abnormal but possible)**: Medically unusual values (e.g., extremely high heart rate) that are kept in the dataset but flagged.
- **Rejected (Impossible)**: Physically impossible or logically invalid combinations (e.g., negative age, SpO2 > 100). These records are excluded from the final output.

---

## Future Improvements

- [ ] Add support for CTGAN conditional generation to directly enforce cohort constraints during sampling
- [ ] Replace background threads with a proper task queue (Celery + Redis)
- [ ] Add support for multi-table relational datasets (SDV `HMASynthesizer`)
- [ ] Add formal differential privacy options (e.g., DP-CTGAN)
- [ ] Add time-series aware synthesizers for longitudinal data
- [ ] Add user authentication and per-user dataset isolation
- [ ] Replace SQLite with PostgreSQL for production
- [ ] Add automated report PDF generation
- [ ] Add column-level sensitivity scoring using NLP

---

## Licence & Attribution

Research prototype built for hackathon SynthGen.  
Uses [SDV (Synthetic Data Vault)](https://sdv.dev/) — MIT licence.  
Demo dataset is **procedurally generated synthetic data** and does not represent real patients.
