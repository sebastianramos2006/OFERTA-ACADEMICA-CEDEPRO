// static/matriculas.js — CEDEPRO · Matriculados (pro, UX mejorado)
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  console.log("[Matriculas] Script cargado");

  // === ELEMENTOS DEL DOM ===
  const provinciaSelect = document.getElementById("provincia-select");
  const anioSelect = document.getElementById("anio-select");
  const nivelSelect = document.getElementById("nivel-select");
  const viewMode = document.getElementById("view-mode");

  const btnLoadMat = document.getElementById("btnLoadMat");
  const btnOpenComparisonModal = document.getElementById("btnOpenComparisonModal");
  const btnActualizarOferta = document.getElementById("btnActualizarOferta");

  const matCanvas = document.getElementById("matChart");

  const linkExportCSV = document.getElementById("linkExportCSV");
  const tablaProv = document.getElementById("tabla-prov");

  const badgeOferta = document.getElementById("totalOferta");
  const badgeMatriculados = document.getElementById("totalMatriculados");
  const badgeTitulados = document.getElementById("totalTitulados");
  const badgeCarreras = document.getElementById("totalCarreras");

  // Mapa
  const svgMapa = document.getElementById("mapa-ecuador");
  const mapaWrapper = document.getElementById("mapa-wrapper");
  const mapaTooltip = document.getElementById("mapa-tooltip");
  const mapaFeatures = document.querySelectorAll("#features path, #features circle");

  // Modal comparación
  const bodyEl = document.body;
  const modal = document.getElementById("comparisonModal");
  const modalBackdrop = document.getElementById("comparisonBackdrop");
  const comparisonBody = document.getElementById("comparisonBody");
  const btnCloseModal = document.getElementById("btnCloseComparison");

  // === ENDPOINTS (app.py) ===
  const ENDPOINT_PROVINCIAS = "/api/provincias_list";
  const ENDPOINT_YEARS = "/api/matriculas_years";
  const ENDPOINT_LEVELS = "/api/matriculas_levels";
  const ENDPOINT_TOTAL_OFERTA = "/api/total_oferta_provincia";
  const ENDPOINT_TOTAL_CARRERAS = "/api/total_carreras_provincia";

  const ENDPOINT_COMPARE = "/api/compare"; // { merged: [...] }
  const ENDPOINT_EXPORT = "/api/export_compare_csv";

  // === ESTADO ===
  let currentFilters = {
    provincia: "",
    anio: "ALL",
    nivel: "",
    viewMode: "nacional",
    campo: "",           // histórico (ALL): campo elegido
    campoYear: "",       // año específico: campo elegido (A-Z)
  };

  let mainChart = null;
  let isLoading = false;
  let selectedProvinceElement = null;

  let yearsAllDesc = [];
  const compareCache = new Map();

  // UI expand/collapse (solo mapa al inicio)
  let isExpanded = false;

  // =====================================================
  //  HELPERS
  // =====================================================

  function setLoading(loading) {
    isLoading = loading;

    if (btnLoadMat) {
      btnLoadMat.disabled = loading;
      btnLoadMat.textContent = loading ? "Cargando…" : "Actualizar";
    }
    if (btnOpenComparisonModal) btnOpenComparisonModal.disabled = loading;

    if (provinciaSelect) provinciaSelect.disabled = loading;
    if (anioSelect) anioSelect.disabled = loading;
    if (nivelSelect) nivelSelect.disabled = loading;
    if (viewMode) viewMode.disabled = loading;

    if (campoSelect) campoSelect.disabled = loading || currentFilters.anio !== "ALL";

    // controles año específico
    if (topNSelect) topNSelect.disabled = loading || currentFilters.anio === "ALL";
    if (campoYearSelect) campoYearSelect.disabled = loading || currentFilters.anio === "ALL";
  }

  async function safeFetch(url, options = {}) {
    const resp = await fetch(url, {
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });

    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      console.error("[Matriculas] Error HTTP", resp.status, "en", url, "| body:", text);
      throw new Error(`Error HTTP ${resp.status}: ${text || resp.statusText}`);
    }

    try {
      return await resp.json();
    } catch {
      return await resp.text();
    }
  }

  function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return "0";
    return Number(num).toLocaleString("es-EC");
  }

  function normalizeText(str) {
    if (!str) return "";
    return str
      .toString()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .toUpperCase()
      .trim();
  }

  function normalizeCampo(str) {
    return normalizeText(str);
  }

  function normalizeProvince(str) {
    return normalizeText(str);
  }

  function truncateLabel(label, max = 40) {
    const s = (label ?? "").toString();
    if (s.length <= max) return s;
    return s.slice(0, max - 1) + "…";
  }

  function getTotalCarreras(resp) {
    if (!resp || typeof resp !== "object") return 0;
    const v = resp.total_carreras ?? resp.total_programas ?? resp.total_carreras_provincia ?? resp.carreras ?? resp.programas;
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function getOfertaValue(r) {
    const v =
      r?.oferta ??
      r?.OFERTA ??
      r?.oferta_actual ??
      r?.OFERTA_ACTUAL ??
      r?.oferta_vigente ??
      r?.OFERTA_VIGENTE ??
      r?.programas ??
      r?.PROGRAMAS ??
      r?.total_oferta ??
      r?.TOTAL_OFERTA ??
      0;
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function getMatValue(r) {
    const v = r?.matriculados ?? r?.MATRICULADOS ?? r?.total_matriculados ?? r?.TOTAL_MATRICULADOS ?? 0;
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function getTitValue(r) {
    const v =
      r?.titulados ??
      r?.TITULADOS ??
      r?.titulados_totales ??
      r?.TITULADOS_TOTALES ??
      r?.total_titulados ??
      r?.TOTAL_TITULADOS ??
      0;
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function getCampoRaw(r) {
    return (r?.campo ?? r?.CAMPO_BASE ?? r?.CAMPO_DETALLADO_P ?? r?.campo_detallado_p ?? "").toString();
  }

  function buildQuery(extra = {}) {
    const params = new URLSearchParams();
    if (currentFilters.provincia) params.append("provincia", currentFilters.provincia);
    if (currentFilters.anio && currentFilters.anio !== "ALL") params.append("anio", currentFilters.anio);
    if (currentFilters.nivel) params.append("nivel", currentFilters.nivel);
    if (currentFilters.viewMode) params.append("view", currentFilters.viewMode);

    Object.entries(extra).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") params.append(k, v);
    });

    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }

  function yearsAsc() {
    return [...yearsAllDesc].sort((a, b) => Number(a) - Number(b));
  }

  function cacheKeyCompare({ provincia, anio, nivel }) {
    return ["compare", normalizeProvince(provincia || "NACIONAL"), anio || "ALL", normalizeText(nivel || "ALL")].join("|");
  }

  async function fetchCompare({ provincia, anio, nivel }) {
    const key = cacheKeyCompare({ provincia, anio, nivel });
    if (compareCache.has(key)) return compareCache.get(key);

    const qs = new URLSearchParams();
    if (provincia) qs.append("provincia", provincia);
    if (anio && anio !== "ALL") qs.append("anio", anio);
    if (nivel) qs.append("nivel", nivel);

    const url = qs.toString() ? `${ENDPOINT_COMPARE}?${qs.toString()}` : ENDPOINT_COMPARE;
    const data = await safeFetch(url);
    const merged = Array.isArray(data?.merged) ? data.merged : [];

    compareCache.set(key, merged);
    return merged;
  }

  // =====================================================
  //  UI PRO (re-armar filtros)
  // =====================================================

  function closestCard(el) {
    if (!el) return null;
    return el.closest?.(".card") || el.closest?.(".panel") || el.parentElement || null;
  }

  const filtrosCard = closestCard(provinciaSelect) || closestCard(anioSelect) || closestCard(btnLoadMat);
  const chartCard = matCanvas?.closest(".card") || matCanvas?.parentElement || null;
  const tablaCard = tablaProv?.closest(".card") || tablaProv?.parentElement || null;

  let btnShowNational = null;

  function setDisplay(el, show, display = "") {
    if (!el) return;
    el.style.display = show ? (display || "") : "none";
  }

  function styleAsControl(selectEl) {
    if (!selectEl) return;
    selectEl.style.width = "100%";
    selectEl.style.maxWidth = "360px";
    selectEl.style.minWidth = "220px";
    selectEl.style.boxSizing = "border-box";
  }

  function makeField(labelText, controlEl) {
    const wrap = document.createElement("div");
    wrap.style.display = "flex";
    wrap.style.flexDirection = "column";
    wrap.style.gap = "6px";
    wrap.style.minWidth = "240px";
    wrap.style.flex = "1 1 260px";

    const lab = document.createElement("label");
    lab.textContent = labelText;
    lab.style.fontWeight = "700";
    lab.style.fontSize = "14px";
    lab.style.color = "rgba(31,36,48,0.92)";

    wrap.appendChild(lab);
    wrap.appendChild(controlEl);

    return wrap;
  }

  let proLayoutBuilt = false;
  let proControlsGrid = null;
  let proActionsRow = null;
  let campoWrap = null;
  let campoYearWrap = null;

  function buildProLayout() {
    if (proLayoutBuilt) return;
    if (!filtrosCard) return;

    const card = filtrosCard;

    const root = document.createElement("div");
    root.id = "mat-pro-layout";
    root.style.display = "flex";
    root.style.flexDirection = "column";
    root.style.gap = "14px";
    root.style.marginTop = "10px";

    const topRow = document.createElement("div");
    topRow.style.display = "flex";
    topRow.style.justifyContent = "space-between";
    topRow.style.alignItems = "center";
    topRow.style.gap = "14px";
    topRow.style.flexWrap = "wrap";

    const badgeRow = document.createElement("div");
    badgeRow.style.display = "flex";
    badgeRow.style.gap = "10px";
    badgeRow.style.alignItems = "center";
    badgeRow.style.flexWrap = "wrap";

    // No movemos contenedores de badges para no romper tu HTML (solo estilo aquí si quisieras)
    // (Si ya estaban en DOM, quedan como estaban.)

    proActionsRow = document.createElement("div");
    proActionsRow.style.display = "flex";
    proActionsRow.style.gap = "12px";
    proActionsRow.style.alignItems = "center";
    proActionsRow.style.flexWrap = "wrap";
    proActionsRow.style.justifyContent = "flex-end";

    if (btnOpenComparisonModal) {
      btnOpenComparisonModal.style.padding = "10px 14px";
      btnOpenComparisonModal.style.borderRadius = "12px";
      btnOpenComparisonModal.style.fontWeight = "700";
      btnOpenComparisonModal.style.border = "1px solid rgba(31,36,48,0.14)";
      btnOpenComparisonModal.style.background = "#fff";
      btnOpenComparisonModal.style.cursor = "pointer";
      proActionsRow.appendChild(btnOpenComparisonModal);
    }

    if (linkExportCSV) {
      linkExportCSV.style.fontWeight = "700";
      linkExportCSV.style.textDecoration = "none";
      linkExportCSV.style.padding = "10px 12px";
      linkExportCSV.style.borderRadius = "12px";
      linkExportCSV.style.border = "1px dashed rgba(89,102,177,0.45)";
      linkExportCSV.style.color = "var(--liberty-dark)";
      proActionsRow.appendChild(linkExportCSV);
    }

    const leftSpacer = document.createElement("div");
    leftSpacer.style.flex = "1 1 auto";

    const rightPack = document.createElement("div");
    rightPack.style.display = "flex";
    rightPack.style.gap = "12px";
    rightPack.style.alignItems = "center";
    rightPack.style.flexWrap = "wrap";
    rightPack.style.justifyContent = "flex-end";
    if (badgeRow.childNodes.length) rightPack.appendChild(badgeRow);
    if (proActionsRow.childNodes.length) rightPack.appendChild(proActionsRow);

    topRow.appendChild(leftSpacer);
    topRow.appendChild(rightPack);

    proControlsGrid = document.createElement("div");
    proControlsGrid.style.display = "grid";
    proControlsGrid.style.gridTemplateColumns = "repeat(12, 1fr)";
    proControlsGrid.style.gap = "14px";
    proControlsGrid.style.alignItems = "end";
    proControlsGrid.style.padding = "14px";
    proControlsGrid.style.borderRadius = "14px";
    proControlsGrid.style.background = "rgba(89,102,177,0.05)";
    proControlsGrid.style.border = "1px solid rgba(89,102,177,0.12)";

    const place = (node, colSpan = 4) => {
      const cell = document.createElement("div");
      cell.style.gridColumn = `span ${colSpan}`;
      cell.appendChild(node);
      return cell;
    };

    styleAsControl(provinciaSelect);
    styleAsControl(anioSelect);
    styleAsControl(nivelSelect);
    styleAsControl(viewMode);

    proControlsGrid.appendChild(place(makeField("Provincia", provinciaSelect), 4));
    proControlsGrid.appendChild(place(makeField("Año", anioSelect), 4));
    proControlsGrid.appendChild(place(makeField("Nivel", nivelSelect), 4));
    proControlsGrid.appendChild(place(makeField("Vista", viewMode), 4));

    const btnRow = document.createElement("div");
    btnRow.style.display = "flex";
    btnRow.style.justifyContent = "center";
    btnRow.style.marginTop = "6px";

    if (btnLoadMat) {
      btnLoadMat.style.minWidth = "280px";
      btnLoadMat.style.padding = "12px 18px";
      btnLoadMat.style.borderRadius = "14px";
      btnLoadMat.style.fontWeight = "800";
      btnLoadMat.style.letterSpacing = ".2px";
      btnLoadMat.style.boxShadow = "0 10px 22px rgba(16,24,40,0.12)";
      btnRow.appendChild(btnLoadMat);
    }

    root.appendChild(topRow);
    root.appendChild(proControlsGrid);
    root.appendChild(btnRow);

    // ocultamos lo viejo (sin borrar)
    const children = Array.from(card.children);
    children.forEach((ch) => {
      const isTitle =
        ch.classList?.contains("panel-title") ||
        ch.tagName?.toLowerCase() === "h2" ||
        ch.tagName?.toLowerCase() === "h3";
      const isSmall = ch.classList?.contains("small-title");
      const isText = ch.tagName?.toLowerCase() === "p";
      if (!isTitle && !isSmall && !isText) {
        ch.dataset._mat_hidden = "1";
        ch.style.display = "none";
      }
    });

    card.appendChild(root);

    const onResize = () => {
      const w = window.innerWidth || 1200;
      if (!proControlsGrid) return;
      if (w < 820) {
        proControlsGrid.style.gridTemplateColumns = "repeat(1, 1fr)";
        Array.from(proControlsGrid.children).forEach((c) => (c.style.gridColumn = "auto"));
      } else if (w < 1100) {
        proControlsGrid.style.gridTemplateColumns = "repeat(2, 1fr)";
        Array.from(proControlsGrid.children).forEach((c) => (c.style.gridColumn = "auto"));
      } else {
        proControlsGrid.style.gridTemplateColumns = "repeat(12, 1fr)";
        const spans = [4, 4, 4, 4, 8, 8]; // los últimos se setean al crear selects
        Array.from(proControlsGrid.children).forEach((c, i) => (c.style.gridColumn = `span ${spans[i] || 4}`));
      }
    };
    window.addEventListener("resize", onResize);
    onResize();

    proLayoutBuilt = true;
  }

  // =====================================================
  //  UI: Solo MAPA al inicio
  // =====================================================

  function ensureNationalButton() {
    if (!mapaWrapper) return;
    if (btnShowNational) return;

    btnShowNational = document.createElement("button");
    btnShowNational.type = "button";
    btnShowNational.id = "btnShowNational";
    btnShowNational.textContent = "Ver histórico nacional";

    btnShowNational.style.marginTop = "12px";
    btnShowNational.style.padding = "10px 14px";
    btnShowNational.style.borderRadius = "14px";
    btnShowNational.style.border = "1px solid rgba(31,36,48,0.14)";
    btnShowNational.style.background = "#fff";
    btnShowNational.style.color = "var(--liberty-dark)";
    btnShowNational.style.cursor = "pointer";
    btnShowNational.style.fontWeight = "800";
    btnShowNational.style.boxShadow = "0 10px 22px rgba(16,24,40,0.10)";

    const wrap = document.createElement("div");
    wrap.style.display = "flex";
    wrap.style.justifyContent = "center";
    wrap.appendChild(btnShowNational);

    mapaWrapper.appendChild(wrap);

    btnShowNational.addEventListener("click", async () => {
      if (provinciaSelect) provinciaSelect.value = "";
      currentFilters.provincia = "";
      if (anioSelect) anioSelect.value = "ALL";
      currentFilters.anio = "ALL";

      expandPanel(true);
      toggleCampoUI();
      toggleYearControlsUI();
      compareCache.clear();

      await buildCampoOptionsHistorico_AZ();
      await loadResumen();
    });
  }

  function expandPanel(shouldExpand) {
    isExpanded = !!shouldExpand;

    setDisplay(filtrosCard, isExpanded, "");
    setDisplay(chartCard, isExpanded, "");
    setDisplay(tablaCard, isExpanded, "");

    if (!isExpanded) {
      destroyChart();
      if (tablaProv) tablaProv.innerHTML = "";
      updateBadges({ oferta: 0, carreras: 0, matriculados: 0, titulados: 0 });
    }

    if (btnShowNational) btnShowNational.parentElement.style.display = isExpanded ? "none" : "flex";
  }

  function initCollapsedUI() {
    ensureNationalButton();
    expandPanel(false);
  }

  // =====================================================
  //  SELECT CAMPO HISTÓRICO (A–Z) + SELECT CAMPO AÑO (A–Z)
  // =====================================================

  let campoSelect = document.getElementById("campo-select");
  let campoYearSelect = null;

  function ensureCampoSelect() {
    buildProLayout();

    // --- histórico (ALL)
    if (!campoSelect) {
      campoSelect = document.createElement("select");
      campoSelect.id = "campo-select";
    }

    if (!campoWrap) {
      styleAsControl(campoSelect);
      campoWrap = makeField("Campo (Histórico )", campoSelect);

      if (proControlsGrid) {
        const cell = document.createElement("div");
        cell.style.gridColumn = "span 8";
        cell.appendChild(campoWrap);
        proControlsGrid.appendChild(cell);
      }
    }

    campoSelect.addEventListener("change", () => {
      currentFilters.campo = campoSelect.value || "";
      if (isExpanded) loadResumen();
    });

    // --- año específico (A–Z)
    if (!campoYearSelect) {
      campoYearSelect = document.createElement("select");
      campoYearSelect.id = "campo-year-select";
      styleAsControl(campoYearSelect);

      campoYearWrap = makeField("Campo (Año específico · A–Z)", campoYearSelect);
      if (proControlsGrid) {
        const cell = document.createElement("div");
        cell.style.gridColumn = "span 8";
        cell.appendChild(campoYearWrap);
        proControlsGrid.appendChild(cell);
      }

      campoYearSelect.addEventListener("change", () => {
        currentFilters.campoYear = campoYearSelect.value || "";
        if (isExpanded) loadResumen();
      });
    }
  }

  function toggleCampoUI() {
    const isHistorico = currentFilters.anio === "ALL";
    if (campoWrap) campoWrap.style.display = isHistorico ? "flex" : "none";
    if (campoSelect) campoSelect.disabled = !isHistorico || isLoading;

    // año específico: visible SOLO cuando anio != ALL
    const isYear = currentFilters.anio !== "ALL";
    if (campoYearWrap) campoYearWrap.style.display = isYear ? "flex" : "none";
    if (campoYearSelect) campoYearSelect.disabled = !isYear || isLoading;
  }

  // =====================================================
  //  CONTROLES AÑO: TopN (se mantiene)
  // =====================================================

  let yearControlsHost = null;
  let topNSelect = null;

  function ensureYearControls() {
    if (!matCanvas) return;

    const parent = matCanvas.parentElement || chartCard || null;
    if (!parent) return;

    if (!yearControlsHost) {
      yearControlsHost = document.createElement("div");
      yearControlsHost.id = "year-controls-host";
      yearControlsHost.style.display = "flex";
      yearControlsHost.style.gap = "12px";
      yearControlsHost.style.flexWrap = "wrap";
      yearControlsHost.style.alignItems = "end";
      yearControlsHost.style.justifyContent = "flex-start";
      yearControlsHost.style.margin = "10px 0 8px 0";

      const topBox = document.createElement("div");
      topBox.style.display = "flex";
      topBox.style.flexDirection = "column";
      topBox.style.gap = "6px";
      topBox.style.minWidth = "160px";

      const topLab = document.createElement("label");
      topLab.textContent = "Top (campos)";
      topLab.style.fontWeight = "800";
      topLab.style.fontSize = "14px";
      topLab.style.color = "rgba(31,36,48,0.92)";

      topNSelect = document.createElement("select");
      topNSelect.id = "topn-select";
      topNSelect.style.padding = "10px 12px";
      topNSelect.style.borderRadius = "12px";
      topNSelect.style.border = "1px solid rgba(31,36,48,0.18)";
      topNSelect.style.background = "#fff";
      topNSelect.style.fontWeight = "700";
      [10, 20, 30, 50].forEach((n) => {
        const opt = document.createElement("option");
        opt.value = String(n);
        opt.textContent = String(n);
        topNSelect.appendChild(opt);
      });
      topNSelect.value = "20";

      topBox.appendChild(topLab);
      topBox.appendChild(topNSelect);

      yearControlsHost.appendChild(topBox);

      parent.insertBefore(yearControlsHost, matCanvas);

      topNSelect.addEventListener("change", () => loadResumen());
    }
  }

  function toggleYearControlsUI() {
    const isYear = currentFilters.anio !== "ALL";
    if (!yearControlsHost) return;
    yearControlsHost.style.display = isYear ? "flex" : "none";
  }

  // =====================================================
  //  CHART
  // =====================================================

  function ensureChartVisible() {
    if (!matCanvas) return;
    const parent = matCanvas.parentElement;
    if (parent) {
      parent.style.minHeight = "460px";
      parent.style.height = "460px";
      parent.style.width = "100%";
    }
    matCanvas.height = 430;
  }

  function destroyChart() {
    if (mainChart) {
      mainChart.destroy();
      mainChart = null;
    }
  }

  function makeTrendGradient(ctx) {
    const h = ctx.canvas.height || 420;
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, "rgba(37, 99, 235, 0.22)");
    g.addColorStop(1, "rgba(37, 99, 235, 0.02)");
    return g;
  }

  function makeBarGradient(ctx) {
    const h = ctx.canvas.height || 420;
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, "rgba(246, 162, 48, 0.85)");
    g.addColorStop(1, "rgba(246, 162, 48, 0.20)");
    return g;
  }

  function chartTitleText() {
    const prov = currentFilters.provincia || "NACIONAL";
    const niv = currentFilters.nivel ? ` · ${currentFilters.nivel}` : "";
    if (currentFilters.anio === "ALL") return `Histórico · ${prov}${niv}`;
    return `Año ${currentFilters.anio} · ${prov}${niv}`;
  }

  const baseChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    animation: { duration: 650 },
    layout: { padding: { top: 10, right: 18, bottom: 20, left: 10 } },
    plugins: {
      legend: {
        position: "top",
        labels: { usePointStyle: true, boxWidth: 10, padding: 16 },
      },
      title: {
        display: true,
        text: () => chartTitleText(),
        font: { size: 14, weight: "600" },
        padding: { bottom: 6 },
      },
      tooltip: {
        backgroundColor: "rgba(18, 18, 20, 0.92)",
        padding: 12,
        cornerRadius: 10,
        callbacks: {
          title: (items) => (items?.[0]?.label ? `${items[0].label}` : ""),
          label: (ctx) => `${ctx.dataset.label}: ${formatNumber(ctx.parsed?.y ?? ctx.parsed?.x ?? 0)}`,
        },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
      yMat: {
        position: "left",
        beginAtZero: true,
        title: { display: true, text: "Matriculados" },
        grid: { color: "rgba(140, 140, 160, 0.14)" },
        ticks: { callback: (v) => formatNumber(v) },
      },
      yOf: {
        position: "right",
        beginAtZero: true,
        title: { display: true, text: "Oferta (programas)" },
        grid: { drawOnChartArea: false },
        ticks: { callback: (v) => formatNumber(v) },
      },
    },
  };

  function renderHistoricoChart({ years, mats, oferta, tits, campoLabel }) {
    if (!matCanvas || typeof Chart === "undefined") return;
    ensureChartVisible();
    destroyChart();

    const ctx = matCanvas.getContext("2d");
    const trendFill = makeTrendGradient(ctx);
    const barFill = makeBarGradient(ctx);

    mainChart = new Chart(ctx, {
      data: {
        labels: years,
        datasets: [
          {
            type: "bar",
            label: "Oferta (programas)",
            data: oferta,
            yAxisID: "yOf",
            backgroundColor: barFill,
            borderColor: "rgba(246, 162, 48, 0.9)",
            borderWidth: 1.2,
            borderRadius: 10,
            categoryPercentage: 0.68,
            barPercentage: 0.86,
          },
          {
            type: "line",
            label: `${campoLabel} · Matriculados`,
            data: mats,
            yAxisID: "yMat",
            cubicInterpolationMode: "monotone",
            tension: 0.42,
            borderWidth: 3,
            borderColor: "rgba(37, 99, 235, 0.95)",
            pointRadius: 3.2,
            pointHoverRadius: 5.2,
            pointBackgroundColor: "rgba(37, 99, 235, 0.95)",
            fill: true,
            backgroundColor: trendFill,
          },
          ...(Array.isArray(tits) && tits.some((x) => Number(x) > 0)
            ? [{
                type: "line",
                label: `${campoLabel} · Titulados (corte)`,
                data: tits,
                yAxisID: "yMat",
                cubicInterpolationMode: "monotone",
                tension: 0.42,
                borderWidth: 2.5,
                borderColor: "rgba(147, 51, 234, 0.85)",
                pointRadius: 2.8,
                pointHoverRadius: 4.8,
                pointBackgroundColor: "rgba(147, 51, 234, 0.85)",
                fill: false,
              }]
            : []),
        ],
      },
      options: {
        ...baseChartOptions,
        plugins: {
          ...baseChartOptions.plugins,
          title: { ...baseChartOptions.plugins.title, text: () => chartTitleText() },
          tooltip: {
            ...baseChartOptions.plugins.tooltip,
            callbacks: {
              title: (items) => (items?.[0]?.label ? `Año: ${items[0].label}` : ""),
              label: (ctx) => `${ctx.dataset.label}: ${formatNumber(ctx.parsed?.y ?? 0)}`,
            },
          },
        },
      },
    });
  }

  function renderYearCampoChartHorizontal({ labels, mats, oferta, tits, topN = 20 }) {
    if (!matCanvas || typeof Chart === "undefined") return;
    ensureChartVisible();
    destroyChart();

    const ctx = matCanvas.getContext("2d");
    const barFill = makeBarGradient(ctx);

    const L = labels.slice(0, topN);
    const M = mats.slice(0, topN);
    const O = oferta.slice(0, topN);
    const T = (tits || []).slice(0, topN);

    mainChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: L.map((x) => truncateLabel(x, 52)),
        datasets: [
          {
            label: "Oferta actual (programas)",
            data: O,
            borderRadius: 10,
            backgroundColor: barFill,
            borderColor: "rgba(246, 162, 48, 0.9)",
            borderWidth: 1.2,
          },
          {
            label: `Matriculados (${currentFilters.anio})`,
            data: M,
            borderRadius: 10,
            backgroundColor: "rgba(37, 99, 235, 0.22)",
            borderColor: "rgba(37, 99, 235, 0.75)",
            borderWidth: 1.2,
          },
          {
            label: `Titulados (corte)`,
            data: T.length ? T : new Array(M.length).fill(0),
            borderRadius: 10,
            backgroundColor: "rgba(147, 51, 234, 0.18)",
            borderColor: "rgba(147, 51, 234, 0.60)",
            borderWidth: 1.2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: "y",
        interaction: { mode: "index", intersect: false },
        animation: { duration: 650 },
        layout: { padding: { top: 10, right: 18, bottom: 18, left: 10 } },
        plugins: {
          legend: { position: "top", labels: { usePointStyle: true, boxWidth: 10, padding: 16 } },
          title: {
            display: true,
            text: () => chartTitleText(),
            font: { size: 14, weight: "600" },
            padding: { bottom: 6 },
          },
          tooltip: {
            ...baseChartOptions.plugins.tooltip,
            callbacks: {
              title: (items) => (items?.[0]?.label ? `Campo: ${items[0].label}` : ""),
              label: (ctx) => `${ctx.dataset.label}: ${formatNumber(ctx.parsed?.x ?? 0)}`,
            },
          },
        },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: "rgba(140, 140, 160, 0.14)" },
            ticks: { callback: (v) => formatNumber(v) },
          },
          y: { grid: { display: false }, ticks: { autoSkip: false } },
        },
      },
    });
  }

  function updateBadges(totales) {
    if (!totales) return;
    if (badgeOferta && totales.oferta !== undefined) badgeOferta.textContent = formatNumber(totales.oferta);
    if (badgeCarreras && totales.carreras !== undefined) badgeCarreras.textContent = formatNumber(totales.carreras);
    if (badgeMatriculados && totales.matriculados !== undefined) badgeMatriculados.textContent = formatNumber(totales.matriculados);
    if (badgeTitulados && totales.titulados !== undefined) badgeTitulados.textContent = formatNumber(totales.titulados);
  }

  function updateTabla(rows) {
    if (!tablaProv) return;

    if (!rows || !rows.length) {
      tablaProv.innerHTML = `
        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Provincia</th>
                <th>Campo</th>
                <th>Oferta</th>
                <th>Matriculados</th><th>Titulados</th><th>Relación M/O</th><th>Relación T/O</th>
              </tr>
            </thead>
            <tbody>
              <tr><td colspan="7" style="text-align:center;padding:0.75rem;">Sin datos.</td></tr>
            </tbody>
          </table>
        </div>`;
      return;
    }

    const html = [
      '<div class="table-scroll">',
      '<table class="data-table">',
      "<thead><tr><th>Provincia</th><th>Campo</th><th>Oferta</th><th>Matriculados</th><th>Titulados</th><th>Relación M/O</th><th>Relación T/O</th></tr></thead>",
      "<tbody>",
      ...rows.map((r) => {
        const prov = currentFilters.provincia || "NACIONAL";
        const campo = r.campo || "";
        const oferta = Number(r.oferta || 0);
        const mat = Number(r.matriculados || 0);
        const tit = Number(r.titulados || 0);
        const ratioMO = oferta > 0 ? (mat / oferta).toFixed(2) : "";
        const ratioTO = oferta > 0 ? (tit / oferta).toFixed(2) : "";
        return `<tr>
          <td>${prov}</td>
          <td title="${(campo || "").toString().replace(/"/g, "&quot;")}">${truncateLabel(campo, 60)}</td>
          <td>${formatNumber(oferta)}</td>
          <td>${formatNumber(mat)}</td>
          <td>${formatNumber(tit)}</td>
          <td>${ratioMO}</td>
          <td>${ratioTO}</td>
        </tr>`;
      }),
      "</tbody></table></div>",
    ].join("");

    tablaProv.innerHTML = html;
  }

  // =====================================================
  //  Construcción de campos A–Z
  // =====================================================

  function sortAZ(arr) {
    return arr.sort((a, b) =>
      (a || "").toString().localeCompare((b || "").toString(), "es", { sensitivity: "base" })
    );
  }

  // Histórico: campos A–Z (consolidado desde años)
  async function buildCampoOptionsHistorico_AZ() {
    if (!campoSelect) return;
    const yAsc = yearsAsc();
    if (!yAsc.length) return;

    const provincia = currentFilters.provincia || "";
    const nivel = currentFilters.nivel || "";

    const mergedAll = await Promise.all(yAsc.map((y) => fetchCompare({ provincia, anio: String(y), nivel })));

    // set único por key
    const map = new Map(); // key -> display
    mergedAll.forEach((merged) => {
      merged.forEach((r) => {
        const raw = getCampoRaw(r);
        const key = normalizeCampo(raw);
        if (!key) return;
        if (!map.has(key)) map.set(key, raw);
      });
    });

    const campos = sortAZ(Array.from(map.values()).filter(Boolean));

    campoSelect.innerHTML = "";

    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Selecciona un campo…";
    campoSelect.appendChild(opt0);

    campos.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = truncateLabel(c, 58);
      opt.title = c;
      campoSelect.appendChild(opt);
    });

    // mantener selección si existe
    if (currentFilters.campo) {
      campoSelect.value = currentFilters.campo;
      if (campoSelect.value !== currentFilters.campo) {
        // si ya no existe, limpia
        currentFilters.campo = "";
        campoSelect.value = "";
      }
    }
  }

  // Año específico: campos A–Z (solo del año)
  async function buildCampoYearOptions_AZ(merged) {
    if (!campoYearSelect) return;
    if (!Array.isArray(merged)) return;

    const map = new Map();
    merged.forEach((r) => {
      const raw = getCampoRaw(r);
      const key = normalizeCampo(raw);
      if (!key) return;
      if (!map.has(key)) map.set(key, raw);
    });

    const campos = sortAZ(Array.from(map.values()).filter(Boolean));

    campoYearSelect.innerHTML = "";

    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Todos los campos (A–Z)…";
    campoYearSelect.appendChild(opt0);

    campos.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = truncateLabel(c, 58);
      opt.title = c;
      campoYearSelect.appendChild(opt);
    });

    // mantener selección
    if (currentFilters.campoYear) {
      campoYearSelect.value = currentFilters.campoYear;
      if (campoYearSelect.value !== currentFilters.campoYear) {
        currentFilters.campoYear = "";
        campoYearSelect.value = "";
      }
    } else {
      campoYearSelect.value = "";
    }
  }

  // =====================================================
  //  CARGA PRINCIPAL (RESUMEN)
  // =====================================================

  async function loadResumen() {
    if (isLoading) return;
    if (!isExpanded) return;

    try {
      setLoading(true);

      const provincia = currentFilters.provincia || "";
      const nivel = currentFilters.nivel || "";

      const qsProv = provincia ? `?provincia=${encodeURIComponent(provincia)}` : "";
      const [totOferta, totCarr] = await Promise.all([
        safeFetch(`${ENDPOINT_TOTAL_OFERTA}${qsProv}`),
        safeFetch(`${ENDPOINT_TOTAL_CARRERAS}${qsProv}`),
      ]);

      // === HISTÓRICO ===
      if (currentFilters.anio === "ALL") {
        const campoElegido = campoSelect?.value || currentFilters.campo || "";
        currentFilters.campo = campoElegido;

        const yAsc = yearsAsc();
        if (!yAsc.length) throw new Error("No hay años disponibles para histórico.");

        if (!campoElegido) {
          updateTabla([]);
          updateBadges({
            oferta: totOferta?.total_oferta ?? 0,
            carreras: getTotalCarreras(totCarr),
            matriculados: 0,
            titulados: 0,
          });
          destroyChart();
          if (linkExportCSV) linkExportCSV.href = `${ENDPOINT_EXPORT}${buildQuery()}`;
          return;
        }

        const campoKey = normalizeCampo(campoElegido);
        const mergedAll = await Promise.all(yAsc.map((y) => fetchCompare({ provincia, anio: String(y), nivel })));

        const matsArr = [];
        const ofertaArr = [];
        const titArr = [];
        let totalMatHistorico = 0;
        let totalTitHistorico = 0;

        mergedAll.forEach((merged) => {
          let matVal = 0;
          let ofVal = 0;
          let titVal = 0;

          merged.forEach((r) => {
            const campoRaw = getCampoRaw(r);
            if (normalizeCampo(campoRaw) === campoKey) {
              matVal += getMatValue(r);
              ofVal += getOfertaValue(r);
              titVal += getTitValue(r);
            }
          });

          matsArr.push(matVal);
          ofertaArr.push(ofVal);
          titArr.push(titVal);
          totalMatHistorico += matVal;
          totalTitHistorico += titVal;
        });

        updateTabla([
          {
            campo: campoElegido,
            oferta: ofertaArr.reduce((a, b) => a + b, 0),
            matriculados: totalMatHistorico,
            titulados: totalTitHistorico,
          },
        ]);

        renderHistoricoChart({
          years: yAsc,
          mats: matsArr,
          oferta: ofertaArr,
          tits: titArr,
          campoLabel: campoElegido,
        });

        updateBadges({
          oferta: totOferta?.total_oferta ?? 0,
          carreras: getTotalCarreras(totCarr),
          matriculados: totalMatHistorico,
          titulados: totalTitHistorico,
        });

        if (linkExportCSV) linkExportCSV.href = `${ENDPOINT_EXPORT}${buildQuery()}`;
        return;
      }

      // === AÑO ESPECÍFICO ===
      ensureYearControls();

      const merged = await fetchCompare({ provincia, anio: currentFilters.anio, nivel });
      await buildCampoYearOptions_AZ(merged);

      // agregar por campo
      const agg = new Map();
      merged.forEach((r) => {
        const campoRaw = getCampoRaw(r);
        const k = normalizeCampo(campoRaw);
        if (!k) return;
        if (!agg.has(k)) agg.set(k, { campo: campoRaw, oferta: 0, matriculados: 0, titulados: 0 });
        const it = agg.get(k);
        it.oferta += getOfertaValue(r);
        it.matriculados += getMatValue(r);
        it.titulados += getTitValue(r);
      });

      let rows = Array.from(agg.values()).sort((a, b) => {
        const ao = Number(a.oferta || 0);
        const bo = Number(b.oferta || 0);
        if (bo !== ao) return bo - ao;
        const bm = Number(b.matriculados || 0);
        const am = Number(a.matriculados || 0);
        if (bm !== am) return bm - am;
        return Number(b.titulados || 0) - Number(a.titulados || 0);
      });

      // filtro por campoYear (si se selecciona uno)
      const campoYear = campoYearSelect?.value || currentFilters.campoYear || "";
      currentFilters.campoYear = campoYear;

      if (campoYear) {
        const k = normalizeCampo(campoYear);
        rows = rows.filter((r) => normalizeCampo(r.campo) === k);
      }

      updateTabla(rows.slice(0, 80));

      const totalMatYear = rows.reduce((a, r) => a + Number(r.matriculados || 0), 0);
      const totalTitYear = rows.reduce((a, r) => a + Number(r.titulados || 0), 0);

      if (rows.length) {
        const topN = campoYear ? Math.min(rows.length, 1) : Math.min(rows.length, Number(topNSelect?.value || 20));
        const labels = rows.map((r) => r.campo);
        const mats = rows.map((r) => Number(r.matriculados || 0));
        const oferta = rows.map((r) => Number(r.oferta || 0));
        const tits = rows.map((r) => Number(r.titulados || 0));
        renderYearCampoChartHorizontal({ labels, mats, oferta, tits, topN });
      } else {
        destroyChart();
      }

      updateBadges({
        oferta: totOferta?.total_oferta ?? 0,
        carreras: getTotalCarreras(totCarr),
        matriculados: totalMatYear,
        titulados: totalTitYear,
      });

      if (linkExportCSV) linkExportCSV.href = `${ENDPOINT_EXPORT}${buildQuery()}`;
    } catch (err) {
      console.error("[Matriculas] Error loadResumen:", err);
      alert("Error cargando datos.");
    } finally {
      setLoading(false);
    }
  }

  // =====================================================
  //  INIT FILTROS
  // =====================================================

  async function initFiltros() {
    try {
      setLoading(true);

      // provincias
      if (provinciaSelect) {
        const provs = await safeFetch(ENDPOINT_PROVINCIAS);
        const list = Array.isArray(provs?.provincias) ? provs.provincias : Array.isArray(provs) ? provs : [];
        provinciaSelect.innerHTML = "";
        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = "TODAS (Mapa)";
        provinciaSelect.appendChild(opt0);

        list.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p;
          opt.textContent = p;
          provinciaSelect.appendChild(opt);
        });

        provinciaSelect.value = "";
        currentFilters.provincia = "";
      }

      // años
      if (anioSelect) {
        const years = await safeFetch(ENDPOINT_YEARS);
        const list = Array.isArray(years?.years) ? years.years : Array.isArray(years) ? years : [];
        yearsAllDesc = [...list].sort((a, b) => Number(b) - Number(a));

        anioSelect.innerHTML = "";
        const optAll = document.createElement("option");
        optAll.value = "ALL";
        optAll.textContent = "TODOS (Histórico)";
        anioSelect.appendChild(optAll);

        yearsAllDesc.forEach((a) => {
          const opt = document.createElement("option");
          opt.value = String(a);
          opt.textContent = String(a);
          anioSelect.appendChild(opt);
        });

        anioSelect.value = "ALL";
        currentFilters.anio = "ALL";
      }

      // niveles
      if (nivelSelect) {
        const levels = await safeFetch(ENDPOINT_LEVELS);
        const list = Array.isArray(levels?.levels) ? levels.levels : Array.isArray(levels) ? levels : [];
        nivelSelect.innerHTML = "";
        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = "TODOS";
        nivelSelect.appendChild(opt0);

        list.forEach((lv) => {
          const opt = document.createElement("option");
          opt.value = lv;
          opt.textContent = lv;
          nivelSelect.appendChild(opt);
        });

        nivelSelect.value = "";
        currentFilters.nivel = "";
      }

      // vista
      if (viewMode) {
        if (!viewMode.value) viewMode.value = "nacional";
        currentFilters.viewMode = viewMode.value || "nacional";
      }

      ensureCampoSelect();
      toggleCampoUI();
      ensureYearControls();
      toggleYearControlsUI();

      // cargar campos A–Z para histórico
      await buildCampoOptionsHistorico_AZ();
    } catch (err) {
      console.error("[Matriculas] Error initFiltros:", err);
      alert("Error inicializando filtros.");
    } finally {
      setLoading(false);
    }
  }

  // =====================================================
  //  MAPA
  // =====================================================

  function highlightProvince(el) {
    if (!el) return;
    if (selectedProvinceElement) {
      selectedProvinceElement.classList?.remove("selected");
      selectedProvinceElement.style.strokeWidth = "";
      selectedProvinceElement.style.filter = "";
    }
    selectedProvinceElement = el;
    selectedProvinceElement.classList?.add("selected");
    selectedProvinceElement.style.strokeWidth = "2.2";
    selectedProvinceElement.style.filter = "drop-shadow(0 10px 18px rgba(16,24,40,.20))";
  }

  async function handleProvinceClick(evt) {
    const target = evt.currentTarget;
    const rawName = (target.getAttribute("name") || target.id || "").toString().trim();
    const normName = normalizeProvince(rawName);

    let provinciaValue = rawName;
    if (provinciaSelect) {
      const opt = Array.from(provinciaSelect.options).find((o) => {
        const valNorm = normalizeProvince(o.value);
        const txtNorm = normalizeProvince(o.textContent);
        return valNorm === normName || txtNorm === normName;
      });
      if (opt) {
        provinciaSelect.value = opt.value;
        provinciaValue = opt.value;
      }
    }

    currentFilters.provincia = provinciaValue;
    highlightProvince(target);

    expandPanel(true);

    // scroll suave hacia los filtros/gráfico (como tu versión anterior)
    try { (filtrosCard || chartCard || matCanvas)?.scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}

    compareCache.clear();
    toggleCampoUI();
    toggleYearControlsUI();

    if (currentFilters.anio === "ALL") {
      await buildCampoOptionsHistorico_AZ();
    }

    await loadResumen();
  }

  function handleProvinceMouseMove(evt) {
    if (!mapaWrapper || !mapaTooltip) return;
    const target = evt.currentTarget;
    const provinciaNombre = target.getAttribute("name") || target.id || "";
    const wrapperRect = mapaWrapper.getBoundingClientRect();
    mapaTooltip.textContent = provinciaNombre;
    mapaTooltip.style.display = "block";
    mapaTooltip.style.left = `${evt.clientX - wrapperRect.left + 8}px`;
    mapaTooltip.style.top = `${evt.clientY - wrapperRect.top + 8}px`;
  }

  function handleProvinceMouseLeave() {
    if (!mapaTooltip) return;
    mapaTooltip.style.display = "none";
  }

  function initMapa() {
    if (!svgMapa || !mapaFeatures.length) return;
    mapaFeatures.forEach((el) => {
      el.addEventListener("click", handleProvinceClick);
      el.addEventListener("mousemove", handleProvinceMouseMove);
      el.addEventListener("mouseleave", handleProvinceMouseLeave);
    });
  }

  // =====================================================
  //  MODAL
  // =====================================================

  function openModal() {
    if (!modal || !modalBackdrop) return;
    bodyEl.classList.add("modal-open");
    modal.style.display = "flex";
    modalBackdrop.style.display = "block";
  }

  function closeModal() {
    if (!modal || !modalBackdrop) return;
    bodyEl.classList.remove("modal-open");
    modal.style.display = "none";
    modalBackdrop.style.display = "none";
  }

  async function openComparison() {
    if (isLoading || !comparisonBody) return;
    try {
      setLoading(true);
      comparisonBody.innerHTML = '<p class="muted">Cargando comparación…</p>';

      const provincia = currentFilters.provincia || "";
      const nivel = currentFilters.nivel || "";
      const anio = currentFilters.anio === "ALL" ? String(yearsAllDesc?.[0] || "") : currentFilters.anio;

      const merged = await fetchCompare({ provincia, anio, nivel });

      const totalOferta = merged.reduce((a, r) => a + getOfertaValue(r), 0);
      const totalMat = merged.reduce((a, r) => a + getMatValue(r), 0);
      const totalTit = merged.reduce((a, r) => a + getTitValue(r), 0);
      const ratioMO = totalOferta > 0 ? (totalMat / totalOferta).toFixed(2) : "";
      const ratioTO = totalOferta > 0 ? (totalTit / totalOferta).toFixed(2) : "";

      comparisonBody.innerHTML = `
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Provincia</th>
                <th>Año</th>
                <th>Oferta</th>
                <th>Matriculados</th>
                <th>Titulados</th>
                <th>Relación M/O</th>
                <th>Relación T/O</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>${provincia || "NACIONAL"}</td>
                <td>${anio || "-"}</td>
                <td>${formatNumber(totalOferta)}</td>
                <td>${formatNumber(totalMat)}</td>
                <td>${formatNumber(totalTit)}</td>
                <td>${ratioMO}</td>
                <td>${ratioTO}</td>
              </tr>
            </tbody>
          </table>
        </div>
      `;
      openModal();
    } catch (err) {
      console.error("[Matriculas] Error openComparison:", err);
      alert("Error cargando la comparación.");
    } finally {
      setLoading(false);
    }
  }

  // =====================================================
  //  LISTENERS
  // =====================================================

  if (provinciaSelect) {
    provinciaSelect.addEventListener("change", async () => {
      currentFilters.provincia = provinciaSelect.value || "";
      compareCache.clear();

      if (!isExpanded) expandPanel(true);

      if (currentFilters.anio === "ALL") {
        await buildCampoOptionsHistorico_AZ();
      }
      await loadResumen();
    });
  }

  if (anioSelect) {
    anioSelect.addEventListener("change", async () => {
      currentFilters.anio = anioSelect.value || "ALL";
      currentFilters.campoYear = ""; // reset campo año
      toggleCampoUI();
      ensureYearControls();
      toggleYearControlsUI();

      if (!isExpanded) expandPanel(true);

      compareCache.clear();
      if (currentFilters.anio === "ALL") {
        await buildCampoOptionsHistorico_AZ();
      }
      await loadResumen();
    });
  }

  if (nivelSelect) {
    nivelSelect.addEventListener("change", async () => {
      currentFilters.nivel = nivelSelect.value || "";
      compareCache.clear();
      if (!isExpanded) expandPanel(true);

      if (currentFilters.anio === "ALL") {
        await buildCampoOptionsHistorico_AZ();
      }
      await loadResumen();
    });
  }

  if (viewMode) {
    viewMode.addEventListener("change", async () => {
      currentFilters.viewMode = viewMode.value || "nacional";
      compareCache.clear();
      if (!isExpanded) expandPanel(true);

      if (currentFilters.anio === "ALL") {
        await buildCampoOptionsHistorico_AZ();
      }
      await loadResumen();
    });
  }

  if (btnLoadMat) btnLoadMat.addEventListener("click", loadResumen);
  if (btnOpenComparisonModal) btnOpenComparisonModal.addEventListener("click", openComparison);
  if (btnCloseModal) btnCloseModal.addEventListener("click", closeModal);
  if (modalBackdrop) modalBackdrop.addEventListener("click", closeModal);

  if (btnActualizarOferta) btnActualizarOferta.style.display = "none";

  // =====================================================
  //  ARRANQUE
  // =====================================================

  buildProLayout();
  ensureCampoSelect();
  initCollapsedUI();
  initFiltros();
  initMapa();
});
