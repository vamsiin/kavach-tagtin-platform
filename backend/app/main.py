from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, ensure_schema_up_to_date
from .workspaces.service import station_access
from . import models  # noqa: F401  -- ensures models are registered before create_all
from .routers import stations, verify, auth, workflow, documents, observations, reports, checklist, management, tracks, allotment, workspaces, deviations, registers_import, towers


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_up_to_date()
    # FR-006: install any default checklist rules not yet in the DB (never overwrites edits)
    from .database import SessionLocal
    from .rules.store import seed_rules
    from .workspaces.service import ensure_initial_workspace
    with SessionLocal() as db:
        seed_rules(db)
        ensure_initial_workspace(db)
        from .chainage import normalise_existing
        if (n := normalise_existing(db)):
            print(f"[chainage] {n} line/TIN row(s) normalised (lower chainage first / line type filled in)")   # data from before workspaces -> 'SCR'; no-op afterwards   # renames rows seeded under older clause numbers, then adds new defaults
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


app.include_router(stations.router, dependencies=[Depends(station_access)])
app.include_router(verify.router, dependencies=[Depends(station_access)])
app.include_router(auth.router)
app.include_router(workflow.router, dependencies=[Depends(station_access)])
app.include_router(documents.router, dependencies=[Depends(station_access)])
app.include_router(documents.meta_router)
app.include_router(observations.router, dependencies=[Depends(station_access)])
app.include_router(reports.router, dependencies=[Depends(station_access)])
app.include_router(reports.meta_router)
app.include_router(checklist.router, dependencies=[Depends(station_access)])
app.include_router(management.router, dependencies=[Depends(station_access)])
app.include_router(tracks.router, dependencies=[Depends(station_access)])
app.include_router(allotment.router, dependencies=[Depends(station_access)])
app.include_router(workspaces.router, dependencies=[Depends(station_access)])
app.include_router(deviations.router, dependencies=[Depends(station_access)])
app.include_router(registers_import.router, dependencies=[Depends(station_access)])
app.include_router(towers.router, dependencies=[Depends(station_access)])


@app.get("/health")
def health():
    return {"status": "ok"}
