# ---------------------------------------------------------------------------
# Pipeline SARIMAX PM10 -> Prevision -> Dose inhalee Monte Carlo -> Classification
#
# Traduction Python fidele du script R "sarimax_pm10_forecast_classification.R"
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm
import pmdarima as pm

warnings.filterwarnings("ignore")

N_SIMULATIONS = 10_000
FORECAST_HORIZON = 2  # J+1, J+2
SEED = 42

# ---------------------------------------------------------------------------
# Parametres evenement (ventilation L/min, duree min) triangulaires (min, mode, max)
# ---------------------------------------------------------------------------
EVENT_PARAMS: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    "800 m":          {"ventilation": (70, 128.8, 210), "duree": (3.67, 4.335, 5.67)},
    "1500 m":         {"ventilation": (70, 122.5, 195), "duree": (3.88, 4.375, 6.67)},
    "2000 m steeple": {"ventilation": (70, 121.3, 190), "duree": (5.58, 6.33, 7.33)},
    "3000 m":         {"ventilation": (65, 112.5, 180), "duree": (8.13, 9.21, 11.58)},
    "5000 m marche":  {"ventilation": (40, 78.8, 135),  "duree": (20.25, 22.75, 25.83)},
}

# Niveau provisoire / Action, cle = "classe_concentration|classe_dose"
NIVEAU_ACTION = {
    "Faible|Faible":   {"niveau": 1, "action": "Routine"},
    "Faible|Elevee":   {"niveau": 2, "action": "Vigilance - exposition liee a l'effort"},
    "Moderee|Faible":  {"niveau": 2, "action": "Vigilance"},
    "Moderee|Elevee":  {"niveau": 3, "action": "Precaution renforcee"},
    "Elevee|Faible":   {"niveau": 3, "action": "Precaution renforcee"},
    "Elevee|Elevee":   {"niveau": 3, "action": "Precaution renforcee"},
}

REQUIRED_COLUMNS = ["Date", "TC", "HR", "PM10"]


class PipelineError(Exception):
    pass


@dataclass
class PipelineResult:
    df_history: pd.DataFrame
    pm10_forecast: pd.DataFrame
    classification_table: pd.DataFrame
    dose_distributions: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    model_summary: Dict[str, str] = field(default_factory=dict)
    tc_forecast: List[float] = field(default_factory=list)
    hr_forecast: List[float] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Chargement des donnees
# ---------------------------------------------------------------------------
def load_data(file_bytes: bytes, sheet_name) -> pd.DataFrame:
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)
    except Exception as exc:
        raise PipelineError(f"Impossible de lire le fichier Excel : {exc}")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise PipelineError(
            f"Colonnes manquantes dans la feuille '{sheet_name}': {missing}. "
            f"Colonnes attendues: {REQUIRED_COLUMNS}."
        )

    df = df[REQUIRED_COLUMNS].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    for col in ["TC", "HR", "PM10"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df["Date"].isna().any():
        raise PipelineError("Des dates invalides ont ete trouvees dans la colonne 'Date'.")

    # Combler les dates manquantes (serie journaliere continue) par interpolation lineaire
    full_range = pd.date_range(df["Date"].min(), df["Date"].max(), freq="D")
    if len(full_range) != len(df):
        df = df.set_index("Date").reindex(full_range)
        df.index.name = "Date"
        df = df.reset_index()

    df[["TC", "HR", "PM10"]] = df[["TC", "HR", "PM10"]].interpolate(
        method="linear", limit_direction="both"
    )

    if df[["TC", "HR", "PM10"]].isna().any().any():
        raise PipelineError(
            "Des valeurs manquantes persistent apres interpolation. "
            "Verifiez qu'il n'y a pas de longues sequences de donnees absentes."
        )

    if len(df) < 20:
        raise PipelineError(
            f"Serie trop courte ({len(df)} jours). Au moins ~20 jours sont recommandes "
            "pour ajuster un modele SARIMAX fiable."
        )

    return df


# ---------------------------------------------------------------------------
# 2. Prevision des variables exogenes (TC, HR) - auto-ARIMA saisonnier (semaine)
# ---------------------------------------------------------------------------
def forecast_exog_series(x: np.ndarray, steps: int = FORECAST_HORIZON):
    model = pm.auto_arima(
        x,
        seasonal=True,
        m=7,
        stepwise=True,
        suppress_warnings=True,
        error_action="ignore",
    )
    fc = model.predict(n_periods=steps)
    return np.asarray(fc, dtype=float), model


# ---------------------------------------------------------------------------
# 3. Ajustement SARIMAX-equivalent pour PM10 (auto-ARIMA + xreg)
# ---------------------------------------------------------------------------
def fit_pm10_model(endog: np.ndarray, exog: np.ndarray):
    model = pm.auto_arima(
        endog,
        X=exog,
        seasonal=False,          # equivaut a seasonal_order=(0,0,0,0)
        stepwise=True,
        suppress_warnings=True,
        error_action="ignore",
    )
    return model


def forecast_pm10(model, xreg_future: np.ndarray, alpha: float = 0.05) -> pd.DataFrame:
    mean_fc, conf_int = model.predict(
        n_periods=xreg_future.shape[0], X=xreg_future, return_conf_int=True, alpha=alpha
    )
    mean_fc = np.asarray(mean_fc, dtype=float)
    lower95 = conf_int[:, 0]
    upper95 = conf_int[:, 1]

    z_975 = norm.ppf(0.975)
    se = (upper95 - mean_fc) / z_975  # deduire l'ecart-type de prevision

    p25 = np.maximum(mean_fc + norm.ppf(0.25) * se, 0)
    p50 = np.maximum(mean_fc, 0)
    p95 = mean_fc + norm.ppf(0.95) * se

    return pd.DataFrame(
        {
            "PM10_forecast_mean": mean_fc,
            "CI_lower_95": np.maximum(lower95, 0),
            "CI_upper_95": upper95,
            "P25": p25,
            "P50": p50,
            "P95": p95,
        }
    )


# ---------------------------------------------------------------------------
# 4. Logique de classification (Classifications.docx)
# ---------------------------------------------------------------------------
def classify_concentration(p50: float) -> str:
    if p50 <= 15:
        return "Faible"
    elif p50 <= 25:
        return "Moderee"
    return "Elevee"


def classify_dose(p50_dose: float) -> str:
    return "Faible" if p50_dose <= 15 else "Elevee"


def simulate_dose(
    p25: float,
    p50: float,
    p95: float,
    ventilation_params: Tuple[float, float, float],
    duree_params: Tuple[float, float, float],
    n_sim: int = N_SIMULATIONS,
    rng: np.random.Generator = None,
) -> np.ndarray:
    rng = rng or np.random.default_rng(SEED)
    ordered = sorted([p25, p50, p95])
    lo, mode, hi = ordered[0], min(max(ordered[1], ordered[0]), ordered[2]), ordered[2]
    if lo == hi:
        hi = lo + 1e-6
    mode = min(max(mode, lo), hi)

    conc_sim = rng.triangular(lo, mode, hi, n_sim)
    vent_sim = rng.triangular(*ventilation_params, n_sim)
    duree_sim = rng.triangular(*duree_params, n_sim)

    return conc_sim * vent_sim * duree_sim * 0.001


def build_classification_table(
    pm10_forecast: pd.DataFrame, day_labels: List[str], seed: int = SEED
) -> Tuple[pd.DataFrame, Dict[str, Dict[str, List[float]]]]:
    rows = []
    dose_distributions: Dict[str, Dict[str, List[float]]] = {}
    rng = np.random.default_rng(seed)

    for i in range(len(pm10_forecast)):
        day_label = day_labels[i]
        p25 = float(pm10_forecast["P25"].iloc[i])
        p50 = float(pm10_forecast["P50"].iloc[i])
        p95 = float(pm10_forecast["P95"].iloc[i])
        conc_class = classify_concentration(p50)

        for event, params in EVENT_PARAMS.items():
            dose_sim = simulate_dose(
                p25, p50, p95, params["ventilation"], params["duree"], rng=rng
            )
            dq25, dq50, dq95 = np.percentile(dose_sim, [25, 50, 95])
            dose_class = classify_dose(dq50)

            key = f"{conc_class}|{dose_class}"
            na_entry = NIVEAU_ACTION[key]

            rows.append(
                {
                    "Day": day_label,
                    "Event": event,
                    "PM10_P25": round(p25, 2),
                    "PM10_P50": round(p50, 2),
                    "PM10_P95": round(p95, 2),
                    "Classification_concentration_PM10": conc_class,
                    "Dose_inhalee_P25_mg": round(float(dq25), 3),
                    "Dose_inhalee_P50_mg": round(float(dq50), 3),
                    "Dose_inhalee_P95_mg": round(float(dq95), 3),
                    "Classification_dose_inhalee": dose_class,
                    "Niveau_provisoire": na_entry["niveau"],
                    "Action": na_entry["action"],
                }
            )

            dose_distributions[f"{day_label}__{event}"] = {
                "values": [round(float(v), 4) for v in dose_sim[:: max(1, len(dose_sim) // 500)]],
                "p25": round(float(dq25), 3),
                "p50": round(float(dq50), 3),
                "p95": round(float(dq95), 3),
            }

    return pd.DataFrame(rows), dose_distributions


# ---------------------------------------------------------------------------
# Orchestration complete
# ---------------------------------------------------------------------------
def run_pipeline(file_bytes: bytes, sheet_name="Donnees_Completes") -> PipelineResult:
    warnings_list: List[str] = []

    df = load_data(file_bytes, sheet_name)

    # --- prevision des variables exogenes ---
    tc_fc, _ = forecast_exog_series(df["TC"].to_numpy())
    hr_fc, _ = forecast_exog_series(df["HR"].to_numpy())

    future_dates = pd.date_range(
        df["Date"].max() + pd.Timedelta(days=1), periods=FORECAST_HORIZON, freq="D"
    )
    xreg_future = np.column_stack([tc_fc, hr_fc])

    # --- ajustement du modele PM10 ~ TC + HR ---
    endog = df["PM10"].to_numpy()
    exog = df[["TC", "HR"]].to_numpy()
    model = fit_pm10_model(endog, exog)

    pm10_forecast = forecast_pm10(model, xreg_future)
    pm10_forecast.insert(0, "Date", future_dates.strftime("%Y-%m-%d"))
    pm10_forecast.insert(1, "Day", [f"J+{i+1}" for i in range(FORECAST_HORIZON)])
    pm10_forecast = pm10_forecast.round(
        {"PM10_forecast_mean": 2, "CI_lower_95": 2, "CI_upper_95": 2, "P25": 2, "P50": 2, "P95": 2}
    )

    class_table, dose_distributions = build_classification_table(
        pm10_forecast, pm10_forecast["Day"].tolist()
    )

    model_summary = {
        "pm10_model_order": str(model.order),
        "pm10_model_seasonal_order": str(getattr(model, "seasonal_order", "(0,0,0,0)")),
        "pm10_model_aic": f"{model.aic():.2f}",
        "n_observations": str(len(df)),
        "date_range": f"{df['Date'].min().date()} -> {df['Date'].max().date()}",
    }

    return PipelineResult(
        df_history=df,
        pm10_forecast=pm10_forecast,
        classification_table=class_table,
        dose_distributions=dose_distributions,
        model_summary=model_summary,
        tc_forecast=[round(float(v), 2) for v in tc_fc],
        hr_forecast=[round(float(v), 2) for v in hr_fc],
        warnings=warnings_list,
    )
