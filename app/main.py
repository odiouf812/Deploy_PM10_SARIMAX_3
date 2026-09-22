from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.pipeline import PipelineError, run_pipeline

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Dashboard PM10 - SARIMAX & Classification d'exposition")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Stockage en memoire des sessions d'analyse (mono-utilisateur / demo)
SESSIONS: dict[str, dict] = {}

NIVEAU_COLORS = {1: "#2e7d32", 2: "#f9a825", 3: "#c62828"}


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    sheet_name: str = Form("Donnees_Completes"),
):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Le fichier doit etre un fichier Excel (.xlsx/.xls).")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Fichier vide.")

    session_id = str(uuid.uuid4())[:8]
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # sauvegarder le fichier uploade
    upload_path = UPLOAD_DIR / f"{session_id}_{file.filename}"
    upload_path.write_bytes(content)

    try:
        result = run_pipeline(content, sheet_name=sheet_name)
    except PipelineError as exc:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Erreur pendant l'analyse : {exc}")

    # --- ecrire les fichiers de sortie ---
    pm10_csv = session_dir / "PM10_forecast.csv"
    class_csv = session_dir / "exposure_classification.csv"
    history_csv = session_dir / "historique_donnees_interpolees.csv"
    summary_json = session_dir / "resume_modele.json"

    result.pm10_forecast.to_csv(pm10_csv, index=False)
    result.classification_table.to_csv(class_csv, index=False)
    result.df_history.to_csv(history_csv, index=False)
    summary_json.write_text(
        json.dumps(
            {
                "model_summary": result.model_summary,
                "tc_forecast": result.tc_forecast,
                "hr_forecast": result.hr_forecast,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # rapport Excel consolide (toutes les tables dans un seul classeur)
    excel_report = session_dir / "rapport_complet.xlsx"
    with pd.ExcelWriter(excel_report, engine="openpyxl") as writer:
        result.df_history.to_excel(writer, sheet_name="Historique", index=False)
        result.pm10_forecast.to_excel(writer, sheet_name="Prevision_PM10", index=False)
        result.classification_table.to_excel(writer, sheet_name="Classification", index=False)
        pd.DataFrame([result.model_summary]).to_excel(writer, sheet_name="Resume_modele", index=False)

    # copier le fichier source uploade dans le dossier de sortie (tracabilite)
    shutil.copy(upload_path, session_dir / f"donnees_source_{file.filename}")

    SESSIONS[session_id] = {
        "result": result,
        "session_dir": str(session_dir),
        "filename": file.filename,
    }

    payload = {
        "session_id": session_id,
        "model_summary": result.model_summary,
        "tc_forecast": result.tc_forecast,
        "hr_forecast": result.hr_forecast,
        "history": {
            "dates": result.df_history["Date"].dt.strftime("%Y-%m-%d").tolist(),
            "PM10": result.df_history["PM10"].round(2).tolist(),
            "TC": result.df_history["TC"].round(2).tolist(),
            "HR": result.df_history["HR"].round(2).tolist(),
        },
        "pm10_forecast": result.pm10_forecast.to_dict(orient="records"),
        "classification_table": result.classification_table.to_dict(orient="records"),
        "dose_distributions": result.dose_distributions,
        "niveau_colors": NIVEAU_COLORS,
        "warnings": result.warnings,
    }
    return JSONResponse(payload)


@app.get("/api/download/{session_id}")
async def download_zip(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable ou expiree.")

    session_dir = Path(session["session_dir"])
    zip_path = session_dir.parent / f"{session_id}_resultats_PM10.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in session_dir.iterdir():
            zf.write(f, arcname=f.name)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="resultats_PM10_dashboard.zip",
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
