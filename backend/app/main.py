from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, ensure_schema_up_to_date
from . import models  # noqa: F401  -- ensures models are registered before create_all
from .routers import stations, verify, auth, workflow, documents, observations, reports, checklist, management


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_up_to_date()
    # FR-006: install any default checklist rules not yet in the DB (never overwrites edits)
    from .database import SessionLocal
    from .rules.store import seed_rules
    with SessionLocal() as db:
        seed_rules(db)
    yield


app = FastAPI(
    title="KAVACH RFID Tag/TIN Layout Platform",
    description="Design and verification API for KAVACH RFID Tag/TIN layouts, "
                "codified against RDSO/SPN/196/2020 Annexure-H (Amdt-5).",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Both localhost and 127.0.0.1 are listed explicitly -- browsers treat these as
    # DIFFERENT origins for CORS purposes even though they resolve to the same
    # machine, so a frontend opened at one URL while this only allowed the other
    # would be silently blocked. This bit a real user during setup.
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    # Also allow any private-LAN IPv4 address on port 5173 -- Vite's dev server
    # prints BOTH a "Local: http://localhost:5173" and a "Network:
    # http://<lan-ip>:5173" URL, and it's easy to open the wrong one (this also
    # bit a real user). This regex is scoped to port 5173 specifically, not a
    # blanket allow-any-origin -- still only meaningful for local dev use, never
    # intended for a production deployment reachable from the public internet.
    allow_origin_regex=r"http://(\d{1,3}\.){3}\d{1,3}:5173",
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(stations.router)
app.include_router(verify.router)
app.include_router(auth.router)
app.include_router(workflow.router)
app.include_router(documents.router)
app.include_router(documents.meta_router)
app.include_router(observations.router)
app.include_router(reports.router)
app.include_router(reports.meta_router)
app.include_router(checklist.router)
app.include_router(management.router)


@app.get("/health")
def health():
    return {"status": "ok"}
