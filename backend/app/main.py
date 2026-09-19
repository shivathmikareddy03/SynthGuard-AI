import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import create_tables
from app.api.routes import dataset, generate, validation, privacy, export
from app.api.routes import cohort_profile as cohort_profile_route

logger = logging.getLogger("sh405")


def _check_dependencies() -> dict:
    """
    Run at startup. Verifies SDV and CTGAN are importable and logs clearly.
    Returns a dict with availability flags used by the /api/health endpoint.
    """
    result = {
        "sdv_installed": False,
        "sdv_version": None,
        "ctgan_available": False,
        "tvae_available": False,
        "gaussian_copula_available": False,
    }

    print("=" * 60)
    print("  SH-405 Backend — Dependency Check")
    print("=" * 60)

    # SDV core
    try:
        import sdv
        result["sdv_installed"] = True
        result["sdv_version"] = sdv.__version__
        print(f"[DEPENDENCY CHECK] SDV installed:          YES  (v{sdv.__version__})")
    except ImportError as e:
        print(f"[DEPENDENCY CHECK] SDV installed:          NO   ({e})")
        print("  >>> Run: pip install sdv ctgan rdt copulas sdmetrics deepecho")
        print("=" * 60)
        return result

    # CTGAN
    try:
        from sdv.single_table import CTGANSynthesizer  # noqa: F401
        result["ctgan_available"] = True
        print("[DEPENDENCY CHECK] CTGAN available:        YES")
    except ImportError as e:
        print(f"[DEPENDENCY CHECK] CTGAN available:        NO   ({e})")

    # TVAE
    try:
        from sdv.single_table import TVAESynthesizer  # noqa: F401
        result["tvae_available"] = True
        print("[DEPENDENCY CHECK] TVAE available:         YES")
    except ImportError as e:
        print(f"[DEPENDENCY CHECK] TVAE available:         NO   ({e})")

    # GaussianCopula
    try:
        from sdv.single_table import GaussianCopulaSynthesizer  # noqa: F401
        result["gaussian_copula_available"] = True
        print("[DEPENDENCY CHECK] GaussianCopula:         YES")
    except ImportError as e:
        print(f"[DEPENDENCY CHECK] GaussianCopula:         NO   ({e})")

    # Metadata
    try:
        from sdv.metadata import SingleTableMetadata  # noqa: F401
        print("[DEPENDENCY CHECK] SingleTableMetadata:    YES")
    except ImportError as e:
        print(f"[DEPENDENCY CHECK] SingleTableMetadata:    NO   ({e})")

    if result["ctgan_available"]:
        print("[SDV] Ready for synthetic data generation")
    else:
        print("[SDV] WARNING: CTGAN not available — generation will fail")

    print("=" * 60)
    return result


# Store dep check result globally so /api/health can expose it
_dep_status: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global _dep_status
    _dep_status = _check_dependencies()

    create_tables()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.EXPORT_DIR, exist_ok=True)
    yield
    # Shutdown — nothing to clean up for prototype


app = FastAPI(
    title="SH-405 Synthetic Patient Data Platform",
    description=(
        "Privacy-preserving synthetic healthcare data generation using SDV/CTGAN. "
        "This is a research prototype. Synthetic data should not be considered "
        "automatically anonymous or clinically validated."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(dataset.router,    prefix="/api/dataset",    tags=["Dataset"])
app.include_router(cohort_profile_route.router, prefix="/api/dataset", tags=["Dataset"])
app.include_router(generate.router,   prefix="/api",            tags=["Generation"])
app.include_router(validation.router, prefix="/api/validation", tags=["Validation"])
app.include_router(privacy.router,    prefix="/api/privacy",    tags=["Privacy"])
app.include_router(export.router,     prefix="/api/export",     tags=["Export"])


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "SH-405 Backend",
        "dependencies": {
            "sdv_installed":             _dep_status.get("sdv_installed", False),
            "sdv_version":               _dep_status.get("sdv_version"),
            "ctgan_available":           _dep_status.get("ctgan_available", False),
            "tvae_available":            _dep_status.get("tvae_available", False),
            "gaussian_copula_available": _dep_status.get("gaussian_copula_available", False),
            "generation_ready":          _dep_status.get("ctgan_available", False),
        },
    }


@app.get("/api/demo-dataset")
def demo_dataset_info():
    """Return metadata about the bundled demo dataset."""
    demo_path = os.path.join("data", "demo_patient_data.csv")
    return {
        "available": os.path.exists(demo_path),
        "path": demo_path,
        "description": (
            "Synthetic demo dataset of de-identified patient records for testing. "
            "This data is NOT real hospital data."
        ),
    }
