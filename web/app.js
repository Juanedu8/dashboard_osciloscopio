/* PulseScope: frontend sin librerias externas ni Raspberry Pi. */
"use strict";

const $ = (id) => document.getElementById(id);
const formatNumber = (value, decimals = 0) =>
  Number(value).toLocaleString("es-CO", { maximumFractionDigits: decimals });

const state = {
  sampleRate: 1000,
  mode: "simulation",
  physicalSpi: false,
  windowSize: 512,
  refresh: 1,
  paused: false,
  busy: false,
  timer: null,
  samples: null,
  hover: [null, null],
};
const channels = [
  { canvas: $("chart1"), readout: $("readout1"), color: "#55dfd3" },
  { canvas: $("chart2"), readout: $("readout2"), color: "#a394f5" },
];

function showError(message) {
  const box = $("error-box");
  box.hidden = false;
  box.textContent = message;
  const badge = $("api-indicator");
  badge.classList.remove("ok");
  badge.classList.add("error");
  $("api-state-text").textContent = state.mode === "external" ? "Proveedor de muestras no disponible" : "Servidor no disponible";
  $("server-pill").textContent = state.mode === "external" ? "API ACTIVA" : "ERROR";
}

function syncSource() {
  const external = state.mode === "external";
  const real = external && state.physicalSpi;
  $("source-label").textContent = real ? "M5Stack ESP32 por SPI" : (external ? "Proveedor externo de ventanas" : "Generador interno de señales");
  $("source-badge").textContent = real ? "SPI REAL" : (external ? "EXTERNO" : "DEMO");
  $("source-note").textContent = real
    ? "El adaptador de la Raspberry reporta muestras reales y ACK SPI. Voltajes estimados: falta calibración ADC y verificación experimental de la frecuencia."
    : (external ? "Se están usando ventanas enviadas por HTTP desde un proveedor externo. La demo las genera artificialmente; esto NO demuestra todavía funcionamiento del ADC o SPI."
    : "Los voltajes mostrados son ficticios. No se está midiendo todavía con el ESP32 ni transfiriendo por SPI.");
  $("source-footer").textContent = real ? "FUENTE SPI ESP32 · FRECUENCIA FÍSICA POR VERIFICAR"
    : (external ? "MODO EXTERNO · CONEXIÓN SPI AÚN SIN VERIFICAR" : "MODO SIMULACIÓN · NO APTO PARA MEDICIONES REALES");
}

function showConnected() {
  $("error-box").hidden = true;
  const badge = $("api-indicator");
  badge.classList.remove("error");
  badge.classList.add("ok");
  $("api-state-text").textContent = state.mode === "external" ? "API conectada · Fuente externa" : "API conectada · Simulación";
  $("server-pill").textContent = "ACTIVO";
  syncSource();
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`Respuesta no válida de ${url}`); }
  if (!response.ok) throw new Error(data.error || `Error HTTP ${response.status}`);
  return data;
}

function syncControls() {
  $("kpi-rate").textContent = formatNumber(state.sampleRate);
  $("kpi-window").textContent = formatNumber(state.windowSize);
  $("kpi-duration").textContent = formatNumber(state.windowSize * 1000 / state.sampleRate, 2);
  $("kpi-refresh").textContent = String(state.refresh);
  $("window-control").value = String(state.windowSize);
  document.querySelectorAll("[data-rate]").forEach(btn => {
    const selected = Number(btn.dataset.rate) === state.sampleRate;
    btn.classList.toggle("selected", selected);
    btn.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-refresh]").forEach(btn => {
    const selected = Number(btn.dataset.refresh) === state.refresh;
    btn.classList.toggle("selected", selected);
    btn.setAttribute("aria-pressed", String(selected));
  });
}

async function updateConfig(changes) {
  try {
    const config = await requestJSON("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    state.sampleRate = config.sample_rate_hz;
    state.mode = config.mode;
    state.windowSize = config.window_size;
    state.refresh = config.refresh_interval_s;
    syncControls();
    syncSource();
    showConnected();
    await capture();
    scheduleCapture();
  } catch (error) {
    showError(`No se pudo cambiar la configuración: ${error.message}`);
    syncControls();
  }
}

function scheduleCapture() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  if (!state.paused) state.timer = setInterval(capture, state.refresh * 1000);
}

function summary(values, slot) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  $(slot).innerHTML = `<span>MIN <strong>${min.toFixed(2)} V</strong></span><span>MÁX <strong>${max.toFixed(2)} V</strong></span><span>PICO A PICO <strong>${(max - min).toFixed(2)} V</strong></span>`;
}

async function capture() {
  if (state.busy) return;
  state.busy = true;
  try {
    const data = await requestJSON("/api/muestras");
    if ((data.mode !== "simulation" && data.mode !== "external") || data.channel_count !== 2 ||
        !Array.isArray(data.channel_1) || !Array.isArray(data.channel_2) ||
        data.channel_1.length !== data.samples_per_channel ||
        data.channel_2.length !== data.samples_per_channel ||
        !Number.isFinite(data.sample_rate_hz) || data.sample_rate_hz <= 0) {
      throw new Error("La estructura de la captura no coincide con el contrato de la API");
    }
    // Una captura antigua puede llegar mientras se cambia la configuracion.
    // Ignorarla en lugar de reemplazar en pantalla los parametros nuevos.
    if (data.sample_rate_hz !== state.sampleRate || data.samples_per_channel !== state.windowSize) return;
    state.samples = data;
    state.mode = data.mode;
    if (data.mode === "external") {
      try {
        const hw = await requestJSON("/api/estado");
        state.physicalSpi = Boolean(hw.spi_connected && hw.applied_rate_hz === state.sampleRate &&
                                    hw.applied_window_size === state.windowSize);
      } catch { state.physicalSpi = false; }
    } else state.physicalSpi = false;
    syncControls();
    summary(data.channel_1, "stats1");
    summary(data.channel_2, "stats2");
    renderAll();
    $("capture-status").textContent = `Ventana #${data.sequence} · ${data.samples_per_channel} muestras/canal`;
    $("last-update").textContent = `Última captura: ${new Date(data.generated_at_utc).toLocaleTimeString("es-CO", {hour12:false})}`;
    showConnected();
  } catch (error) {
    showError(state.mode === "external"
      ? `Esperando datos del proveedor externo: ${error.message}. Verifica que el emulador o adaptador SBC esté funcionando.`
      : `No se pudieron consultar las muestras: ${error.message}. Comprueba que server.py siga ejecutándose.`);
    $("capture-status").textContent = "Captura no disponible";
  } finally {
    state.busy = false;
  }
}

function plot(index) {
  const data = state.samples;
  if (!data) return;
  const chart = channels[index];
  const canvas = chart.canvas;
  const values = index === 0 ? data.channel_1 : data.channel_2;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width < 30 || height < 30) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const p = { left: 44, top: 14, right: 14, bottom: 29 };
  const plotW = Math.max(1, width - p.left - p.right);
  const plotH = Math.max(1, height - p.top - p.bottom);
  const left = p.left;
  const top = p.top;
  const durationMs = (values.length - 1) / data.sample_rate_hz * 1000;
  const x = (i) => left + (i / (values.length - 1)) * plotW;
  const y = (v) => top + (1 - v / 3.3) * plotH;
  ctx.font = "10px ui-sans-serif,system-ui,sans-serif";
  ctx.textBaseline = "middle";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const yy = top + i * plotH / 3;
    ctx.strokeStyle = "#263349";
    ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(left + plotW, yy); ctx.stroke();
    ctx.fillStyle = "#75859a";
    ctx.textAlign = "right";
    ctx.fillText((3.3 - i * 1.1).toFixed(1), left - 10, yy);
  }
  for (let i = 0; i <= 4; i++) {
    const xx = left + i * plotW / 4;
    ctx.strokeStyle = "#223045";
    ctx.beginPath(); ctx.moveTo(xx, top); ctx.lineTo(xx, top + plotH); ctx.stroke();
    ctx.fillStyle = "#75859a";
    ctx.textAlign = i === 0 ? "left" : (i === 4 ? "right" : "center");
    ctx.textBaseline = "top";
    const label = durationMs * i / 4;
    ctx.fillText(`${formatNumber(label, label < 10 ? 2 : 1)} ms`, xx, top + plotH + 8);
  }
  ctx.save();
  ctx.beginPath(); ctx.rect(left, top, plotW, plotH); ctx.clip();
  const fill = ctx.createLinearGradient(0, top, 0, top + plotH);
  if (index === 0) { fill.addColorStop(0, "#55dfd325"); fill.addColorStop(1, "#55dfd300"); }
  else { fill.addColorStop(0, "#a394f522"); fill.addColorStop(1, "#a394f500"); }
  ctx.beginPath();
  values.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
  ctx.lineTo(x(values.length - 1), top + plotH);
  ctx.lineTo(x(0), top + plotH);
  ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
  ctx.beginPath();
  values.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
  ctx.lineWidth = 1.75;ctx.strokeStyle = chart.color;ctx.shadowColor = chart.color;ctx.shadowBlur = 4;ctx.lineJoin = "round";ctx.stroke();ctx.shadowBlur = 0;
  const hover = state.hover[index];
  if (hover !== null) {
    const i = Math.min(values.length - 1, Math.max(0, hover));
    ctx.beginPath();ctx.setLineDash([3, 5]);ctx.strokeStyle = "#c6d5e999";
    ctx.moveTo(x(i), top);ctx.lineTo(x(i), top + plotH);ctx.stroke();ctx.setLineDash([]);
    ctx.beginPath();ctx.arc(x(i), y(values[i]), 4, 0, Math.PI * 2);ctx.fillStyle = chart.color;ctx.fill();
    chart.readout.textContent = `t ${formatNumber(i / data.sample_rate_hz * 1000, 2)} ms · ${values[i].toFixed(3)} V`;
    chart.readout.classList.add("visible");
  } else chart.readout.classList.remove("visible");
  ctx.restore();
}

function renderAll() { plot(0); plot(1); }

function initHover(index) {
  const canvas = channels[index].canvas;
  canvas.addEventListener("pointermove", event => {
    if (!state.samples) return;
    const rect = canvas.getBoundingClientRect();
    const relative = (event.clientX - rect.left - 44) / Math.max(1, rect.width - 58);
    const n = state.samples.samples_per_channel;
    state.hover[index] = Math.round(Math.min(1, Math.max(0, relative)) * (n - 1));
    plot(index);
  });
  canvas.addEventListener("pointerleave", () => { state.hover[index] = null; plot(index); });
}

function setupListeners() {
  document.querySelectorAll("[data-rate]").forEach(btn => btn.addEventListener("click", () => {
    if (Number(btn.dataset.rate) !== state.sampleRate) updateConfig({ sample_rate_hz: Number(btn.dataset.rate) });
  }));
  document.querySelectorAll("[data-refresh]").forEach(btn => btn.addEventListener("click", () => {
    if (Number(btn.dataset.refresh) !== state.refresh) updateConfig({ refresh_interval_s: Number(btn.dataset.refresh) });
  }));
  $("window-control").addEventListener("change", e => updateConfig({ window_size: Number(e.target.value) }));
  $("capture-btn").addEventListener("click", capture);
  $("pause-btn").addEventListener("click", () => {
    state.paused = !state.paused;
    $("pause-label").textContent = state.paused ? "Reanudar" : "Pausar";
    $("pause-icon").textContent = state.paused ? "▶" : "Ⅱ";
    $("pause-btn").setAttribute("aria-pressed", String(state.paused));
    scheduleCapture();
    if (!state.paused) capture();
  });
  channels.forEach((_, i) => initHover(i));
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(renderAll);
    channels.forEach(ch => observer.observe(ch.canvas));
  } else window.addEventListener("resize", renderAll);
}

async function init() {
  setupListeners();
  syncControls();
  const clock = () => $("clock").textContent = new Date().toLocaleTimeString("es-CO", { hour12: false });
  clock(); setInterval(clock, 1000);
  try {
    const config = await requestJSON("/api/config");
    state.sampleRate = config.sample_rate_hz;
    state.mode = config.mode;
    state.windowSize = config.window_size;
    state.refresh = config.refresh_interval_s;
    syncControls();
    syncSource();
    showConnected();
  } catch (error) { showError(`No se pudo conectar a la API: ${error.message}`); }
  await capture();
  scheduleCapture();
}

init();
