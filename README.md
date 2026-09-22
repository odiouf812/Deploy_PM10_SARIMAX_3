# Dashboard PM10 — SARIMAX & Classification d'exposition

Dashboard interactif (FastAPI + tableau de bord web) reprenant le pipeline du script R
`sarimax_pm10_forecast_classification.R` :

1. **Upload** du fichier Excel (colonnes `Date`, `TC`, `HR`, `PM10`).
2. **Modèle SARIMAX** : prévision des variables exogènes (TC, HR) puis ajustement
   d'un SARIMAX (auto-ARIMA + variables exogènes) pour PM10.
3. **Prévisions** PM10 à J+1 et J+2 (moyenne, IC 95 %, P25/P50/P95).
4. **Simulation Monte Carlo** (10 000 tirages) de la dose inhalée pour chaque
   épreuve (800 m, 1500 m, 2000 m steeple, 3000 m, 5000 m marche) et chaque jour.
5. **Classification** de l'exposition (Faible/Modérée/Élevée), niveau provisoire
   (1 à 3) et action recommandée.

Tous les résultats sont téléchargeables en un clic (fichier ZIP contenant les
CSV, le rapport Excel consolidé et le fichier source).

---

## 1. Installation

Prérequis : Python 3.10 ou plus récent.

```bash
# se placer dans le dossier du projet
cd pm10_dashboard

# créer un environnement virtuel (recommandé)
python3 -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate

# installer les dépendances
pip install -r requirements.txt
```

## 2. Lancer le dashboard

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Puis ouvrir dans un navigateur : **http://localhost:8000**

## 3. Utilisation

1. Cliquez sur la zone de dépôt (ou glissez-déposez) pour choisir votre fichier
   Excel. Le nom de la feuille par défaut est `Donnees_Completes` (modifiable
   dans le champ prévu si votre feuille porte un autre nom).
2. Cliquez sur **"Lancer l'analyse complète"**. Le pipeline s'exécute côté
   serveur (SARIMAX, Monte Carlo 10 000 simulations, classification).
3. Consultez :
   - le résumé du modèle SARIMAX (ordre, AIC, prévisions TC/HR) ;
   - le graphique de l'historique interpolé ;
   - le graphique et le tableau des prévisions PM10 (P25/P50/P95) ;
   - la distribution Monte Carlo de la dose inhalée (sélecteur épreuve/jour) ;
   - le tableau complet de classification (couleur par niveau).
4. Cliquez sur **"Télécharger tous les résultats"** en haut de la page pour
   récupérer un fichier ZIP contenant :
   - `PM10_forecast.csv`
   - `exposure_classification.csv`
   - `historique_donnees_interpolees.csv`
   - `rapport_complet.xlsx` (toutes les tables dans un classeur Excel)
   - `resume_modele.json`
   - une copie du fichier Excel source (traçabilité)

## 4. Format du fichier Excel attendu

| Date       | TC   | HR   | PM10 |
|------------|------|------|------|
| 2024-01-01 | 24.1 | 62.0 | 18.4 |
| 2024-01-02 | 23.8 | 65.2 | 21.0 |
| ...        | ...  | ...  | ...  |

- `Date` : date journalière (les dates manquantes dans la série sont comblées
  automatiquement par interpolation linéaire).
- `TC` : température (°C).
- `HR` : humidité relative (%).
- `PM10` : concentration en particules PM10 (µg/m³).

Un fichier d'exemple `sample_data/exemple_donnees_pollution.xlsx` est fourni
pour tester rapidement le dashboard.

## 5. Structure du projet

```
pm10_dashboard/
├── app/
│   ├── main.py          # API FastAPI (upload, analyse, téléchargement)
│   └── pipeline.py       # Pipeline SARIMAX + Monte Carlo + classification
├── templates/
│   └── index.html        # Page du dashboard
├── static/
│   ├── style.css
│   └── app.js             # Graphiques (Chart.js) et interactions
├── sample_data/
│   └── exemple_donnees_pollution.xlsx
├── requirements.txt
└── README.md
```

## 6. Notes techniques

- Le modèle SARIMAX est ajusté avec `pmdarima.auto_arima` (équivalent Python
  de `auto.arima` en R), avec variables exogènes (`X=TC,HR`) et sans
  saisonnalité pour PM10 (comme dans le script R : `seasonal_order=(0,0,0,0)`).
- Les variables exogènes TC et HR sont prévues séparément avec une
  saisonnalité hebdomadaire (`m=7`), avant d'être injectées comme `xreg`
  futur du modèle PM10.
- La dose inhalée est simulée par tirages triangulaires (concentration,
  ventilation, durée) — 10 000 simulations par épreuve et par jour — selon
  la même logique que `Classifications.docx`.
- Chaque session d'analyse crée un sous-dossier dans `outputs/` ; pensez à
  nettoyer ce dossier périodiquement si vous déployez le dashboard pour un
  usage multi-utilisateurs prolongé (cette version est prévue pour un usage
  local / mono-utilisateur).
