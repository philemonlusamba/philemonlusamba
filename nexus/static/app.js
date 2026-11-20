"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  catalog: { engines: [], connectors: [] },
  jobs: [],
  selectedEngine: "sora",
  selectedJob: null,
  view: "create",
  filter: "all",
  polling: null,
};

const STATUS_LABELS = {
  queued: "En file",
  running: "En cours",
  completed: "Terminé",
  failed: "Échec",
  cancelled: "Annulé",
};

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function safeURL(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) || url.origin === window.location.origin
      ? url.href
      : "";
  } catch (_) {
    return "";
  }
}

function engineById(id) {
  return state.catalog.engines.find((engine) => engine.id === id) || {
    id,
    name: id,
    company: "Nexus",
    accent: "#8b5cf6",
    capabilities: [],
  };
}

function initials(name) {
  return name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  let data = {};
  try { data = await response.json(); } catch (_) { /* réponse sans JSON */ }
  if (!response.ok) {
    const error = new Error(data.error || `Erreur HTTP ${response.status}`);
    error.hint = data.hint || "";
    throw error;
  }
  return data;
}

function toast(title, detail = "", type = "info") {
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.innerHTML = `<span>${type === "success" ? "✓" : type === "error" ? "!" : "✦"}</span><div><strong>${escapeHTML(title)}</strong>${detail ? `<small>${escapeHTML(detail)}</small>` : ""}</div>`;
  $("#toast-stack").appendChild(element);
  window.setTimeout(() => element.remove(), 6000);
}

async function bootstrap() {
  bindEvents();
  try {
    const [catalog, jobs, health] = await Promise.all([
      api("/api/catalog"),
      api("/api/jobs"),
      api("/api/health"),
    ]);
    state.catalog = catalog;
    state.jobs = jobs.jobs || [];
    state.selectedJob = state.jobs[0]?.id || null;
    renderCatalog();
    renderConnectors();
    applyHealth(health);
    renderAll();
    startPolling();
  } catch (error) {
    toast("Nexus n'a pas pu démarrer", error.message, "error");
  }
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) showView(viewButton.dataset.view);

    const promptButton = event.target.closest("[data-prompt]");
    if (promptButton) {
      $("#prompt").value = promptButton.dataset.prompt;
      updatePromptCount();
      $("#prompt").focus();
    }

    const engineButton = event.target.closest("[data-engine]");
    if (engineButton) selectEngine(engineButton.dataset.engine);

    const modeButton = event.target.closest("[data-mode]");
    if (modeButton) selectMode(modeButton.dataset.mode);

    const projectAction = event.target.closest("[data-job-action]");
    if (projectAction) handleJobAction(projectAction.dataset.jobAction, projectAction.dataset.jobId);

    const filter = event.target.closest("[data-filter]");
    if (filter) {
      state.filter = filter.dataset.filter;
      $$(".filter").forEach((item) => item.classList.toggle("active", item === filter));
      renderLibrary();
    }
  });

  $("#prompt").addEventListener("input", updatePromptCount);
  $("#generate-form").addEventListener("submit", submitGeneration);
  $("#advanced-toggle").addEventListener("click", toggleAdvanced);
  $("#enhance-prompt").addEventListener("click", enhancePrompt);
  $("#new-project").addEventListener("click", resetComposer);
  $("#download-preview").addEventListener("click", () => {
    const job = state.jobs.find((item) => item.id === state.selectedJob);
    if (job) exportJob(job);
  });
  $("#connector").addEventListener("change", updateRouteHint);
}

function showView(name) {
  if (!document.getElementById(`view-${name}`)) return;
  state.view = name;
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  const titles = {
    create: ["STUDIO UNIFIÉ", "Créer une vidéo"],
    library: ["WORKSPACE", "Projets"],
    engines: ["MODEL MESH", "Moteurs IA"],
  };
  $("#page-eyebrow").textContent = titles[name][0];
  $("#page-title").textContent = titles[name][1];
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function selectMode(mode) {
  $$('[data-mode]').forEach((button) => button.classList.toggle("selected", button.dataset.mode === mode));
  $("#image-field").classList.toggle("hidden", mode !== "image");
  if (mode === "image") $("#image-url").focus();
}

function selectEngine(id) {
  if (!state.catalog.engines.some((engine) => engine.id === id)) return;
  state.selectedEngine = id;
  $$('[data-engine]').forEach((button) => button.classList.toggle("selected", button.dataset.engine === id));
  const engine = engineById(id);
  const supportedDurations = new Set(engine.durations || []);
  $$("#duration option").forEach((option) => {
    option.disabled = supportedDurations.size > 0 && !supportedDurations.has(Number(option.value));
  });
  if ($("#duration").selectedOptions[0]?.disabled) {
    $("#duration").value = String(engine.durations[0] || 5);
  }
}

function renderCatalog() {
  const featuredIds = ["sora", "veo", "runway", "kling", "luma"];
  const featured = featuredIds.map((id) => engineById(id)).filter((engine) => engine.name);
  $("#engine-rail").innerHTML = featured.map((engine) => `
    <button type="button" class="engine-pill ${engine.id === state.selectedEngine ? "selected" : ""}" data-engine="${escapeHTML(engine.id)}" style="--engine-color:${escapeHTML(engine.accent)}">
      <span class="engine-logo">${escapeHTML(initials(engine.name))}</span>
      <strong>${escapeHTML(engine.name)}</strong><small>${escapeHTML(engine.company)}</small>
    </button>`).join("");

  $("#catalog-grid").innerHTML = state.catalog.engines.map((engine) => `
    <article class="catalog-card" style="--card-color:${escapeHTML(engine.accent)}">
      <div class="catalog-head"><span class="catalog-icon">${escapeHTML(initials(engine.name))}</span><div class="catalog-title"><strong>${escapeHTML(engine.name)}</strong><span>${escapeHTML(engine.company)}</span></div></div>
      <p>${escapeHTML(engine.description)}</p>
      <div class="tags">${engine.capabilities.slice(0, 3).map((tag) => `<span>${escapeHTML(tag)}</span>`).join("")}</div>
      <div class="catalog-foot"><span class="type-badge">${escapeHTML(engine.integration)}</span><a href="${escapeHTML(engine.website)}" target="_blank" rel="noreferrer">Site officiel ↗</a></div>
    </article>`).join("");
  $("#engine-total").textContent = state.catalog.engines.length;
  $("#catalog-badge").textContent = `${state.catalog.engines.length} familles recensées`;
}

function renderConnectors() {
  const connectors = state.catalog.connectors || [];
  $("#connector-grid").innerHTML = connectors.map((connector) => `
    <article class="connector-card ${connector.configured ? "connected" : ""}">
      <div class="connector-top"><h3>${escapeHTML(connector.name)}</h3><span class="connector-state">${connector.configured ? "Actif" : "À configurer"}</span></div>
      <p>${escapeHTML(connector.description)}</p>
      ${connector.key_env ? `<code>${escapeHTML(connector.key_env)}</code>` : "<code>Zéro clé · local</code>"}
    </article>`).join("");

  const select = $("#connector");
  select.innerHTML = '<option value="auto">Nexus Auto (recommandé)</option>' + connectors.map((connector) => {
    const disabled = !connector.configured;
    return `<option value="${escapeHTML(connector.id)}" ${disabled ? "disabled" : ""}>${escapeHTML(connector.name)}${disabled ? " — clé requise" : ""}</option>`;
  }).join("");
  updateRouteHint();
}

function applyHealth(health) {
  const active = health.configured_connectors || ["demo"];
  $("#connector-count").textContent = `${active.length} connecteur${active.length > 1 ? "s" : ""} actif${active.length > 1 ? "s" : ""}`;
  const real = active.filter((id) => id !== "demo");
  $("#mode-name").textContent = real.length ? "Mode hybride" : "Mode démo";
  $("#mode-detail").textContent = real.length
    ? `${real.join(", ")} configuré${real.length > 1 ? "s" : ""} côté serveur.`
    : "Aucune clé nécessaire. Aperçu local et gratuit.";
}

function updateRouteHint() {
  const option = $("#connector").selectedOptions[0];
  const label = option?.textContent || "Nexus Auto";
  $("#route-hint").textContent = `${label} · secrets protégés côté serveur`;
}

function updatePromptCount() {
  $("#prompt-count").textContent = $("#prompt").value.length;
}

function toggleAdvanced() {
  const panel = $("#advanced-panel");
  panel.classList.toggle("hidden");
  $("#advanced-toggle").textContent = panel.classList.contains("hidden")
    ? "Réglages avancés +"
    : "Masquer les réglages −";
}

function enhancePrompt() {
  const input = $("#prompt");
  const value = input.value.trim();
  if (!value) {
    toast("Écrivez d'abord une idée", "Nexus ajoutera ensuite le cadrage et la lumière.");
    input.focus();
    return;
  }
  const additions = [];
  if (!/cam[eé]ra|plan|travelling|drone|zoom/i.test(value)) additions.push("travelling cinématographique fluide");
  if (!/lumi[eè]re|éclairage|soleil|n[eé]on/i.test(value)) additions.push("éclairage volumétrique maîtrisé");
  if (!/d[eé]tail|4k|haute qualit[eé]|réaliste/i.test(value)) additions.push("détails précis et cohérence temporelle");
  input.value = additions.length ? `${value}, ${additions.join(", ")}` : value;
  updatePromptCount();
  toast("Prompt enrichi localement", "Aucune IA ni donnée externe n'a été utilisée.", "success");
}

function resetComposer() {
  showView("create");
  $("#generate-form").reset();
  state.selectedEngine = "sora";
  selectEngine("sora");
  selectMode("text");
  updatePromptCount();
  $("#prompt").focus();
}

async function submitGeneration(event) {
  event.preventDefault();
  const button = $("#generate-button");
  const payload = {
    prompt: $("#prompt").value.trim(),
    engine: state.selectedEngine,
    connector: $("#connector").value,
    model_ref: $("#model-ref").value.trim(),
    negative_prompt: $("#negative-prompt").value.trim(),
    image_url: $("#image-url").value.trim(),
    aspect_ratio: $("#aspect-ratio").value,
    resolution: $("#resolution").value,
    duration: Number($("#duration").value),
    style: $("#style").value,
    seed: $("#seed").value,
    generate_audio: $("#audio").checked,
  };
  button.disabled = true;
  button.querySelector("strong").textContent = "Connexion au Nexus…";
  try {
    const response = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    state.jobs.unshift(response.job);
    state.selectedJob = response.job.id;
    renderAll();
    toast("Génération ajoutée", `${engineById(payload.engine).name} · ${response.job.connector}`, "success");
    $("#preview-stage").scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (error) {
    toast("Génération refusée", error.hint ? `${error.message} — ${error.hint}` : error.message, "error");
  } finally {
    button.disabled = false;
    button.querySelector("strong").textContent = "Générer avec Nexus";
  }
}

function startPolling() {
  if (state.polling) clearInterval(state.polling);
  state.polling = setInterval(refreshJobs, 1000);
}

async function refreshJobs() {
  try {
    const data = await api("/api/jobs?limit=100");
    const before = new Map(state.jobs.map((job) => [job.id, job.status]));
    state.jobs = data.jobs || [];
    for (const job of state.jobs) {
      if (before.has(job.id) && before.get(job.id) !== "completed" && job.status === "completed") {
        toast("Votre rendu est prêt", engineById(job.request.engine).name, "success");
      }
    }
    renderAll();
  } catch (_) {
    // Une coupure temporaire ne doit pas effacer l'interface.
  }
}

function renderAll() {
  $("#project-count").textContent = state.jobs.length;
  $("#completed-total").textContent = state.jobs.filter((job) => job.status === "completed").length;
  renderQueue();
  renderPreview();
  renderLibrary();
}

function renderQueue() {
  const active = state.jobs.filter((job) => ["queued", "running"].includes(job.status));
  $("#queue-status").textContent = active.length
    ? `${active.length} tâche${active.length > 1 ? "s" : ""} active${active.length > 1 ? "s" : ""}`
    : "Aucune tâche active";
  $(".queue-dot").classList.toggle("active", active.length > 0);
  if (!active.length) {
    $("#queue-list").innerHTML = '<div class="empty-queue">Les générations actives apparaîtront ici.</div>';
    return;
  }
  $("#queue-list").innerHTML = active.slice(0, 5).map((job) => {
    const engine = engineById(job.request.engine);
    return `<button class="queue-item" type="button" data-job-action="select" data-job-id="${job.id}" style="--q-color:${escapeHTML(engine.accent)}">
      <span class="queue-top"><span class="queue-thumb">${escapeHTML(initials(engine.name))}</span><span class="queue-copy"><strong>${escapeHTML(job.request.prompt)}</strong><span>${escapeHTML(job.stage)}</span></span><span class="queue-percent">${job.progress}%</span></span>
      <span class="mini-bar"><i style="--progress:${job.progress}%"></i></span>
    </button>`;
  }).join("");
}

function renderPreview() {
  const job = state.jobs.find((item) => item.id === state.selectedJob) || state.jobs[0];
  if (!job) return;
  state.selectedJob = job.id;
  const engine = engineById(job.request.engine);
  $("#preview-status").textContent = `${engine.name} · ${STATUS_LABELS[job.status] || job.status}`;
  const mediaURL = safeURL(job.result_url || job.poster_url);
  let media;
  if (job.demo || !job.result_url || job.result_url.endsWith(".svg")) {
    media = `<img src="${escapeHTML(safeURL(job.poster_url))}" alt="Aperçu animé de démonstration Nexus">`;
  } else if (job.status === "completed" && mediaURL) {
    media = `<video src="${escapeHTML(mediaURL)}" controls playsinline poster="${escapeHTML(safeURL(job.poster_url))}"></video>`;
  } else {
    media = `<img src="${escapeHTML(safeURL(job.poster_url))}" alt="Aperçu Nexus">`;
  }
  const overlay = ["queued", "running"].includes(job.status)
    ? `<div class="preview-overlay" style="--progress:${job.progress}%"><strong>${escapeHTML(job.stage)}</strong><span>${job.progress}%</span><div class="bar"><i></i></div></div>`
    : job.status === "failed"
      ? `<div class="preview-overlay"><strong>Échec : ${escapeHTML(job.error || "erreur fournisseur")}</strong></div>`
      : "";
  $("#preview-stage").innerHTML = media + overlay;

  const actions = $("#preview-actions");
  actions.classList.toggle("hidden", job.status !== "completed");
  $("#download-preview").classList.toggle("hidden", !job.demo);
  const open = $("#open-result");
  open.href = mediaURL || safeURL(job.poster_url);
  open.textContent = job.demo ? "Ouvrir l’aperçu" : "Ouvrir la vidéo";
}

function renderLibrary() {
  const jobs = state.filter === "all"
    ? state.jobs
    : state.jobs.filter((job) => job.status === state.filter);
  if (!jobs.length) {
    $("#project-grid").innerHTML = '<div class="empty-projects"><strong>Aucun rendu dans cette catégorie.</strong><p>Créez une première vidéo depuis le studio Nexus.</p></div>';
    return;
  }
  $("#project-grid").innerHTML = jobs.map((job) => {
    const engine = engineById(job.request.engine);
    const mediaURL = safeURL(job.poster_url);
    const created = new Date(job.created_at * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
    const canCancel = ["queued", "running"].includes(job.status);
    return `<article class="project-card">
      <div class="project-media"><img src="${escapeHTML(mediaURL)}" alt="${escapeHTML(job.request.prompt)}"><span class="project-state ${job.status}">${escapeHTML(STATUS_LABELS[job.status] || job.status)}</span></div>
      <div class="project-body"><h3>${escapeHTML(job.request.prompt)}</h3><div class="project-meta"><span>${escapeHTML(engine.name)} · ${escapeHTML(job.connector)}</span><span>${escapeHTML(created)}</span></div>
      <div class="project-actions">
        <button type="button" data-job-action="select" data-job-id="${job.id}">Aperçu</button>
        ${job.demo && job.status === "completed" ? `<button type="button" data-job-action="export" data-job-id="${job.id}">WebM</button>` : ""}
        <button type="button" data-job-action="${canCancel ? "cancel" : "delete"}" data-job-id="${job.id}">${canCancel ? "Annuler" : "Supprimer"}</button>
      </div></div>
    </article>`;
  }).join("");
}

async function handleJobAction(action, jobId) {
  const job = state.jobs.find((item) => item.id === jobId);
  if (action === "select") {
    state.selectedJob = jobId;
    showView("create");
    renderPreview();
    return;
  }
  if (action === "export" && job) {
    exportJob(job);
    return;
  }
  try {
    if (action === "cancel") {
      await api(`/api/jobs/${jobId}/cancel`, { method: "POST", body: "{}" });
      toast("Génération annulée");
    } else if (action === "delete") {
      await api(`/api/jobs/${jobId}`, { method: "DELETE" });
      if (state.selectedJob === jobId) state.selectedJob = null;
      toast("Projet supprimé");
    }
    await refreshJobs();
  } catch (error) {
    toast("Action impossible", error.message, "error");
  }
}

async function exportJob(job) {
  if (!job.demo) {
    const url = safeURL(job.result_url);
    if (url) window.open(url, "_blank", "noopener");
    return;
  }
  if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
    const link = document.createElement("a");
    link.href = safeURL(job.poster_url);
    link.download = `nexus-${job.id}.svg`;
    link.click();
    toast("WebM non supporté", "L'aperçu SVG a été téléchargé à la place.");
    return;
  }

  const overlay = $("#export-overlay");
  overlay.classList.remove("hidden");
  const canvas = document.createElement("canvas");
  canvas.width = 1280;
  canvas.height = 720;
  const context = canvas.getContext("2d");
  const stream = canvas.captureStream(30);
  const mimeCandidates = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
  const mimeType = mimeCandidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 5_000_000 } : undefined);
  const chunks = [];
  recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
  const seconds = Math.min(8, Math.max(3, Number(job.request.duration) || 5));
  const started = performance.now();
  let animationId;

  const draw = (now) => {
    const progress = Math.min(1, (now - started) / (seconds * 1000));
    drawDemoFrame(context, canvas, job, progress, now / 1000);
    $("#export-progress").textContent = `${Math.round(progress * 100)} % · ${seconds}s`;
    if (progress < 1) animationId = requestAnimationFrame(draw);
  };

  const finished = new Promise((resolve) => { recorder.onstop = resolve; });
  recorder.start(250);
  animationId = requestAnimationFrame(draw);
  await new Promise((resolve) => setTimeout(resolve, seconds * 1000 + 100));
  cancelAnimationFrame(animationId);
  recorder.stop();
  await finished;
  stream.getTracks().forEach((track) => track.stop());
  const blob = new Blob(chunks, { type: mimeType || "video/webm" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `nexus-${job.request.engine}-${job.id}.webm`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  overlay.classList.add("hidden");
  toast("Vidéo WebM exportée", "Le rendu de démonstration a été créé dans votre navigateur.", "success");
}

function drawDemoFrame(context, canvas, job, progress, time) {
  const hash = [...`${job.id}${job.request.prompt}`].reduce((acc, char) => ((acc << 5) - acc + char.charCodeAt(0)) | 0, 0);
  const hueA = Math.abs(hash) % 360;
  const hueB = (hueA + 90 + (Math.abs(hash) % 80)) % 360;
  const gradient = context.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, `hsl(${hueA} 65% 10%)`);
  gradient.addColorStop(.5, `hsl(${hueB} 72% 20%)`);
  gradient.addColorStop(1, "#070810");
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.globalCompositeOperation = "screen";
  for (let index = 0; index < 5; index += 1) {
    const x = canvas.width * (.15 + .7 * ((Math.sin(time * (.25 + index * .04) + index) + 1) / 2));
    const y = canvas.height * (.15 + .7 * ((Math.cos(time * (.2 + index * .05) + index * 1.4) + 1) / 2));
    const radius = 170 + index * 35;
    const glow = context.createRadialGradient(x, y, 0, x, y, radius);
    glow.addColorStop(0, `hsla(${(hueA + index * 37) % 360}, 90%, 62%, .22)`);
    glow.addColorStop(1, "transparent");
    context.fillStyle = glow;
    context.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  }
  context.globalCompositeOperation = "source-over";

  context.fillStyle = "rgba(255,255,255,.9)";
  context.font = "800 25px system-ui";
  context.letterSpacing = "7px";
  context.fillText("NEXUS HLP.AI", 65, 70);
  context.font = "700 15px system-ui";
  context.fillStyle = "rgba(165,243,252,.9)";
  context.fillText("DEMO VIDEO", 1090, 68);

  const lines = wrapCanvasText(context, job.request.prompt, 900, "700 42px system-ui");
  context.textAlign = "center";
  context.font = "700 42px system-ui";
  context.fillStyle = "white";
  lines.slice(0, 3).forEach((line, index) => context.fillText(line, canvas.width / 2, 325 + index * 58));
  context.font = "500 18px system-ui";
  context.fillStyle = "rgba(226,232,240,.75)";
  context.fillText(`${job.request.style.toUpperCase()}  ·  ${job.request.aspect_ratio}  ·  ${job.request.resolution}`, canvas.width / 2, 570);
  context.textAlign = "left";

  context.fillStyle = "rgba(255,255,255,.12)";
  context.fillRect(65, 655, 1150, 3);
  const progressGradient = context.createLinearGradient(65, 0, 1215, 0);
  progressGradient.addColorStop(0, "#8b5cf6");
  progressGradient.addColorStop(1, "#38d9ff");
  context.fillStyle = progressGradient;
  context.fillRect(65, 655, 1150 * progress, 3);
}

function wrapCanvasText(context, text, maxWidth, font) {
  context.font = font;
  const words = text.split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  }
  if (line) lines.push(line);
  return lines;
}

bootstrap();
