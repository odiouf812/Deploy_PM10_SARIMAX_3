let currentPayload = null;
let charts = {};

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const fileNameEl = document.getElementById("fileName");
const uploadForm = document.getElementById("uploadForm");
const errorBox = document.getElementById("errorBox");
const loadingBox = document.getElementById("loadingBox");
const analyzeBtn = document.getElementById("analyzeBtn");
const resultsEl = document.getElementById("results");
const downloadBtn = document.getElementById("downloadBtn");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    updateFileName();
  }
});
fileInput.addEventListener("change", updateFileName);

function updateFileName() {
  fileNameEl.textContent = fileInput.files.length ? fileInput.files[0].name : "";
}

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.classList.remove("hidden");
}
function clearError() {
  errorBox.classList.add("hidden");
  errorBox.textContent = "";
}

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();

  if (!fileInput.files.length) {
    showError("Veuillez sélectionner un fichier Excel.");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("sheet_name", document.getElementById("sheetName").value || "Donnees_Completes");

  analyzeBtn.disabled = true;
  loadingBox.classList.remove("hidden");
  resultsEl.classList.add("hidden");
  downloadBtn.disabled = true;

  try {
    const resp = await fetch("/api/analyze", { method: "POST", body: formData });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || "Erreur inconnue pendant l'analyse.");
    }
    currentPayload = data;
    renderAll(data);
    resultsEl.classList.remove("hidden");
    downloadBtn.disabled = false;
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(err.message);
  } finally {
    analyzeBtn.disabled = false;
    loadingBox.classList.add("hidden");
  }
});

downloadBtn.addEventListener("click", () => {
  if (!currentPayload) return;
  window.location.href = `/api/download/${currentPayload.session_id}`;
});

function renderAll(data) {
  renderModelSummary(data);
  renderHistoryChart(data);
  renderForecastChart(data);
  renderForecastTable(data);
  renderClassificationTable(data);
  setupDoseControls(data);
}

function renderModelSummary(data) {
  const s = data.model_summary;
  const el = document.getElementById("modelSummary");
  const items = [
    ["Observations", s.n_observations],
    ["Période", s.date_range],
    ["Ordre ARIMA (p,d,q)", s.pm10_model_order],
    ["Ordre saisonnier", s.pm10_model_seasonal_order],
    ["AIC", s.pm10_model_aic],
    ["Prév. TC (J+1/J+2)", data.tc_forecast.join(" / ")],
    ["Prév. HR (J+1/J+2)", data.hr_forecast.join(" / ")],
  ];
  el.innerHTML = items.map(([label, value]) => `
    <div class="summary-item">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
    </div>`).join("");
}

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

function renderHistoryChart(data) {
  destroyChart("history");
  const ctx = document.getElementById("historyChart");
  charts.history = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.history.dates,
      datasets: [
        { label: "PM10 (µg/m³)", data: data.history.PM10, borderColor: "#2f6fed", backgroundColor: "rgba(47,111,237,0.08)", fill: true, tension: 0.25, pointRadius: 0, yAxisID: "y" },
        { label: "TC (°C)", data: data.history.TC, borderColor: "#e07b39", pointRadius: 0, tension: 0.25, yAxisID: "y1", borderDash: [4,3] },
        { label: "HR (%)", data: data.history.HR, borderColor: "#4caf9e", pointRadius: 0, tension: 0.25, yAxisID: "y1", borderDash: [2,2] },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: { title: { display: true, text: "Historique des données interpolées" } },
      scales: {
        y: { type: "linear", position: "left", title: { display: true, text: "PM10 (µg/m³)" } },
        y1: { type: "linear", position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "TC / HR" } },
      },
    },
  });
}

function renderForecastChart(data) {
  destroyChart("forecast");
  const ctx = document.getElementById("forecastChart");
  const labels = data.pm10_forecast.map(r => `${r.Day} (${r.Date})`);
  charts.forecast = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "P25", data: data.pm10_forecast.map(r => r.P25), backgroundColor: "rgba(47,111,237,0.25)" },
        { label: "P50 (médiane)", data: data.pm10_forecast.map(r => r.P50), backgroundColor: "rgba(47,111,237,0.65)" },
        { label: "P95", data: data.pm10_forecast.map(r => r.P95), backgroundColor: "rgba(198,40,40,0.35)" },
      ],
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: "Prévision PM10 — quantiles P25 / P50 / P95" } },
      scales: { y: { title: { display: true, text: "PM10 (µg/m³)" }, beginAtZero: true } },
    },
  });
}

function renderForecastTable(data) {
  const table = document.getElementById("forecastTable");
  const cols = ["Date","Day","PM10_forecast_mean","CI_lower_95","CI_upper_95","P25","P50","P95"];
  const labels = { Date:"Date", Day:"Jour", PM10_forecast_mean:"Moyenne", CI_lower_95:"IC 95% (bas)", CI_upper_95:"IC 95% (haut)", P25:"P25", P50:"P50", P95:"P95" };
  table.innerHTML = `
    <thead><tr>${cols.map(c => `<th>${labels[c]}</th>`).join("")}</tr></thead>
    <tbody>${data.pm10_forecast.map(row => `
      <tr>${cols.map(c => `<td>${row[c]}</td>`).join("")}</tr>
    `).join("")}</tbody>`;
}

function renderClassificationTable(data) {
  const table = document.getElementById("classificationTable");
  const cols = ["Day","Event","PM10_P25","PM10_P50","PM10_P95","Classification_concentration_PM10",
                "Dose_inhalee_P25_mg","Dose_inhalee_P50_mg","Dose_inhalee_P95_mg",
                "Classification_dose_inhalee","Niveau_provisoire","Action"];
  const labels = {
    Day:"Jour", Event:"Épreuve", PM10_P25:"PM10 P25", PM10_P50:"PM10 P50", PM10_P95:"PM10 P95",
    Classification_concentration_PM10:"Classe concentration",
    Dose_inhalee_P25_mg:"Dose P25 (mg)", Dose_inhalee_P50_mg:"Dose P50 (mg)", Dose_inhalee_P95_mg:"Dose P95 (mg)",
    Classification_dose_inhalee:"Classe dose", Niveau_provisoire:"Niveau", Action:"Action",
  };
  table.innerHTML = `
    <thead><tr>${cols.map(c => `<th>${labels[c]}</th>`).join("")}</tr></thead>
    <tbody>${data.classification_table.map(row => `
      <tr>${cols.map(c => {
        if (c === "Niveau_provisoire") return `<td><span class="badge badge-${row[c]}">Niveau ${row[c]}</span></td>`;
        return `<td>${row[c]}</td>`;
      }).join("")}</tr>
    `).join("")}</tbody>`;
}

function setupDoseControls(data) {
  const eventSelect = document.getElementById("eventSelect");
  const daySelect = document.getElementById("daySelect");

  const events = [...new Set(data.classification_table.map(r => r.Event))];
  const days = [...new Set(data.classification_table.map(r => r.Day))];

  eventSelect.innerHTML = events.map(e => `<option value="${e}">${e}</option>`).join("");
  daySelect.innerHTML = days.map(d => `<option value="${d}">${d}</option>`).join("");

  const update = () => renderDoseChart(data, daySelect.value, eventSelect.value);
  eventSelect.onchange = update;
  daySelect.onchange = update;
  update();
}

function renderDoseChart(data, day, event) {
  const key = `${day}__${event}`;
  const dist = data.dose_distributions[key];
  if (!dist) return;

  // histogramme cote client a partir de l'echantillon transmis
  const values = dist.values;
  const nbins = 25;
  const min = Math.min(...values), max = Math.max(...values);
  const width = (max - min) / nbins || 1;
  const bins = new Array(nbins).fill(0);
  values.forEach(v => {
    let idx = Math.floor((v - min) / width);
    if (idx >= nbins) idx = nbins - 1;
    if (idx < 0) idx = 0;
    bins[idx]++;
  });
  const binLabels = bins.map((_, i) => (min + i * width).toFixed(2));

  destroyChart("dose");
  const ctx = document.getElementById("doseChart");
  charts.dose = new Chart(ctx, {
    type: "bar",
    data: {
      labels: binLabels,
      datasets: [{ label: `Dose inhalée (mg) — ${event}, ${day}`, data: bins, backgroundColor: "rgba(47,111,237,0.55)", barPercentage: 1, categoryPercentage: 1 }],
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: `Distribution simulée (échantillon) — ${event} · ${day}` }, legend: { display: false } },
      scales: {
        x: { title: { display: true, text: "Dose inhalée (mg)" }, ticks: { maxTicksLimit: 10 } },
        y: { title: { display: true, text: "Fréquence (échantillon)" } },
      },
    },
  });

  document.getElementById("doseQuantiles").innerHTML = `
    <div class="q-box"><div class="label">P25</div><div class="value">${dist.p25} mg</div></div>
    <div class="q-box"><div class="label">P50 (médiane)</div><div class="value">${dist.p50} mg</div></div>
    <div class="q-box"><div class="label">P95</div><div class="value">${dist.p95} mg</div></div>
  `;
}
