const $ = (selector) => document.querySelector(selector);

const state = {
  course: null,
  availableCourses: [],
  session: null,
  proposal: null,
  students: [],
  managementStudents: [],
  role: "profesor",
  present: new Set(),
  methods: [],
  metrics: null,
  toastTimer: null,
  visualTimer: null,
  ballMachine: null,
};

const selectionAnimationDuration = 5500;
const visualPalette = ["#df795e", "#f3c86a", "#2f6fe0", "#8ec5f5", "#1e3a8a", "#e7a9a0"];

const elements = {
  apiDot: $("#api-dot"),
  apiStatus: $("#api-status"),
  courseTitle: $("#course-title"),
  courseMeta: $("#course-meta"),
  breadcrumbCourse: $("#breadcrumb-course"),
  todayLabel: $("#today-label"),
  emptyState: $("#empty-state"),
  workspace: $("#workspace"),
  recentCourses: $("#recent-courses"),
  courseIdInput: $("#course-id-input"),
  studentList: $("#student-list"),
  listEmpty: $("#list-empty"),
  toggleAll: $("#toggle-all-button"),
  runButton: $("#run-button"),
  selectionNote: $("#selection-note"),
  methodSelect: $("#method-select"),
  tauField: $("#tau-field"),
  resultPanel: $("#result-panel"),
  selectionStage: $("#selection-stage"),
  stageClose: $("#stage-close"),
  toast: $("#toast"),
  dialog: $("#student-dialog"),
  editDialog: $("#edit-dialog"),
  sessionFormView: $("#session-form-view"),
  sessionActiveView: $("#session-active-view"),
  sessionTopic: $("#session-topic"),
  rosterFile: $("#roster-file"),
  importButton: $("#import-button"),
  importResult: $("#import-result"),
  attendanceView: $("#attendance-view"),
  managementView: $("#management-view"),
  attendanceTab: $("#attendance-tab"),
  managementTab: $("#management-tab"),
  adminStudentList: $("#admin-student-list"),
  activeRole: $("#active-role"),
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    // Con FormData el navegador fija el Content-Type (con su boundary).
    headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((item) => item.msg).join("; ")
      : body?.detail;
    throw new Error(detail || `Error ${response.status}: no se pudo completar la solicitud.`);
  }
  return body;
}

function notify(message, isError = false) {
  clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("visible");
  state.toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 3600);
}

function setBusy(button, busy, busyText = "Procesando...") {
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.dataset.wasDisabled = String(button.disabled);
    button.innerHTML = `<span>${busyText}</span>`;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  } else {
    button.innerHTML = button.dataset.label || button.innerHTML;
    button.disabled = button.dataset.wasDisabled === "true";
    delete button.dataset.label;
    delete button.dataset.wasDisabled;
    button.removeAttribute("aria-busy");
    updateSelectionControls();
  }
}

function readRecentCourses() {
  try {
    return JSON.parse(localStorage.getItem("aula-recent-courses") || "[]");
  } catch {
    return [];
  }
}

function saveRecentCourse(course) {
  const courses = readRecentCourses().filter((item) => item.id !== course.id);
  courses.unshift({ id: course.id, name: course.name });
  localStorage.setItem("aula-recent-courses", JSON.stringify(courses.slice(0, 8)));
  state.availableCourses = [
    course,
    ...state.availableCourses.filter((item) => item.id !== course.id),
  ];
  renderRecentCourses();
}

function renderRecentCourses() {
  const currentValue = state.course ? String(state.course.id) : "";
  const coursesById = new Map(state.availableCourses.map((course) => [course.id, course]));
  readRecentCourses().forEach((course) => {
    if (!coursesById.has(course.id)) coursesById.set(course.id, course);
  });
  const options = [...coursesById.values()].map((course) =>
    `<option value="${course.id}">${escapeHtml(course.name)} · #${course.id}</option>`,
  ).join("");
  elements.recentCourses.innerHTML = `<option value="">Selecciona un curso</option>${options}`;
  elements.recentCourses.value = currentValue;
}

function renderMethodOptions() {
  const descriptions = {
    bayesian_fairness: "Bayesian fairness",
    roulette: "Roulette",
    weighted_softmax: "Weighted softmax",
  };
  const current = elements.methodSelect.value;
  elements.methodSelect.innerHTML = state.methods.map((method) =>
    `<option value="${escapeHtml(method)}">${escapeHtml(descriptions[method] || method)}</option>`,
  ).join("");
  if (state.methods.includes(current)) elements.methodSelect.value = current;
  if (!elements.methodSelect.value && state.methods.length) elements.methodSelect.value = state.methods[0];
  updateMethodFields();
}

function updateMethodFields() {
  elements.tauField.hidden = elements.methodSelect.value !== "weighted_softmax";
}

function renderStudents() {
  const students = state.students;
  $("#roster-count").textContent = students.length;
  $("#metric-students").textContent = students.length;
  elements.studentList.innerHTML = students.map((student, index) => {
    const id = Number(student.id);
    const present = state.present.has(id);
    const initial = (student.display_name || "?").trim().charAt(0).toUpperCase() || "?";
    return `<article class="student-row" style="animation-delay:${Math.min(index * 22, 220)}ms">
      <div class="student-identity">
        <span class="student-avatar" aria-hidden="true">${escapeHtml(initial)}</span>
        <div class="student-name-block">
          <div class="student-name">${escapeHtml(student.display_name)}</div>
          <div class="student-meta">${escapeHtml(student.external_ref)} · ID ${id}</div>
        </div>
      </div>
      <div class="student-actions">
        <label class="attendance-control">
          <input type="checkbox" data-attendance-id="${id}" ${present ? "checked" : ""} aria-label="Marcar presente a ${escapeHtml(student.display_name)}" />
          <span>${present ? "Presente" : "Ausente"}</span>
        </label>
      </div>
    </article>`;
  }).join("");
  elements.listEmpty.hidden = students.length > 0;
  elements.toggleAll.disabled = students.length === 0;
  updateSelectionControls();
}

function renderManagementStudents() {
  const students = state.managementStudents;
  $("#management-count").textContent = students.length;
  elements.adminStudentList.innerHTML = students.map((student) => {
    const id = Number(student.id);
    const contact = [student.phone_number, student.email].filter(Boolean).map(escapeHtml).join(" · ");
    return `<article class="student-row admin-student-row">
      <div class="student-identity">
        <span class="student-avatar" aria-hidden="true">${escapeHtml((student.display_name || "?").trim().charAt(0).toUpperCase() || "?")}</span>
        <div class="student-name-block">
          <div class="student-name">${escapeHtml(student.display_name)}${student.active ? "" : ' <span class="inactive-badge">Retirado</span>'}</div>
          <div class="student-meta">${escapeHtml(student.external_ref)} · ${contact || "Sin datos de contacto"}</div>
        </div>
      </div>
      <div class="student-actions">
        <button class="history-link" type="button" data-history-id="${id}">Historial</button>
        <button class="history-link" type="button" data-edit-id="${id}">Editar</button>
      </div>
    </article>`;
  }).join("");
  $("#admin-list-empty").hidden = students.length > 0;
}

function updateSelectionControls() {
  const presentCount = state.present.size;
  $("#metric-present").textContent = presentCount;
  const fullyPresent = state.students.length > 0 && presentCount === state.students.length;
  elements.toggleAll.textContent = fullyPresent ? "Desmarcar todos" : "Marcar todos";
  elements.runButton.disabled = !state.course || presentCount === 0 || state.students.length === 0;
  const sessionNote = state.session ? " Se guarda en la sesión en curso." : " Inicia una sesión para guardar la asistencia.";
  elements.selectionNote.textContent = presentCount
    ? `${presentCount} estudiante${presentCount === 1 ? "" : "s"} presente${presentCount === 1 ? "" : "s"}.${sessionNote}`
    : "Marca la asistencia para habilitar la selección.";
  const slots = $("#slots-input");
  slots.max = String(Math.max(1, presentCount));
  if (presentCount && Number(slots.value) > presentCount) slots.value = String(presentCount);
}

function renderMetrics(metrics) {
  state.metrics = metrics;
  const coverage = Number(metrics?.coverage || 0);
  const percent = Math.max(0, Math.min(100, coverage * 100));
  $("#metric-coverage").textContent = `${Math.round(percent)}%`;
  $("#fairness-bar-fill").style.width = `${percent}%`;
  $("#fairness-caption").textContent = metrics?.n_students
    ? `${Math.round(percent)}% de cobertura · ${metrics.n_students} estudiantes`
    : "Sin estudiantes matriculados.";
}

function renderCourse() {
  const course = state.course;
  const isLoaded = Boolean(course);
  elements.emptyState.hidden = isLoaded;
  elements.workspace.hidden = !isLoaded;
  $("#refresh-button").disabled = !isLoaded;
  elements.courseTitle.textContent = course?.name || "Panel de selección";
  elements.courseMeta.textContent = course ? `Curso #${course.id}` : "Crea un curso o carga uno existente para comenzar.";
  elements.breadcrumbCourse.textContent = course ? `CURSO #${course.id}` : "SIN CURSO";
  renderRecentCourses();
  if (!isLoaded) return;
  setCourseView("attendance");
  renderSessionBox();
  renderStudents();
  renderManagementStudents();
  if (state.metrics) renderMetrics(state.metrics);
}

function setCourseView(view) {
  const management = view === "management";
  elements.attendanceView.hidden = management;
  elements.managementView.hidden = !management;
  elements.attendanceTab.classList.toggle("active", !management);
  elements.managementTab.classList.toggle("active", management);
  elements.attendanceTab.setAttribute("aria-selected", String(!management));
  elements.managementTab.setAttribute("aria-selected", String(management));
}

function renderSessionBox() {
  const session = state.session;
  elements.sessionFormView.hidden = Boolean(session);
  elements.sessionActiveView.hidden = !session;
  if (session) {
    $("#session-active-title").textContent = session.topic ? `Sesión #${session.id} · ${session.topic}` : `Sesión #${session.id}`;
    $("#session-active-meta").textContent = `${formatDay(session.session_date)} · ${session.present_count} de ${session.total_count} presentes`;
    return;
  }
  const proposal = state.proposal;
  $("#session-date-label").textContent = proposal ? formatDay(proposal.session_date) : "";
  $("#session-hint").textContent = proposal?.suggested_topic
    ? "Tema propuesto desde el sílabo: puedes confirmarlo o corregirlo."
    : "Este curso no tiene tema en el sílabo para hoy: escribe uno o déjalo vacío.";
}

function formatDay(value) {
  if (!value) return "";
  // `value` llega como YYYY-MM-DD: se interpreta como fecha local, sin desfase de zona horaria.
  const [year, month, day] = String(value).split("-").map(Number);
  return new Intl.DateTimeFormat("es", { dateStyle: "medium" }).format(new Date(year, month - 1, day));
}

async function loadProposal() {
  if (!state.course) return;
  try {
    state.proposal = await api(`/courses/${state.course.id}/class-sessions/proposal`);
    elements.sessionTopic.value = state.proposal.suggested_topic || "";
  } catch {
    state.proposal = null;
  }
  renderSessionBox();
}

async function loadCourse(courseId, { remember = true } = {}) {
  const id = Number(courseId);
  if (!Number.isInteger(id) || id <= 0) throw new Error("Escribe un ID de curso válido.");
  const course = await api(`/courses/${id}`);
  const [students, managementStudents, metrics] = await Promise.all([
    api(`/courses/${id}/students`),
    api(`/courses/${id}/students?include_inactive=true`),
    api(`/courses/${id}/fairness-metrics`).catch(() => null),
  ]);
  state.course = course;
  state.students = students;
  state.managementStudents = managementStudents;
  state.present = new Set();
  state.session = null;
  state.proposal = null;
  state.metrics = metrics;
  $("#metric-last-run").textContent = "—";
  elements.resultPanel.hidden = true;
  elements.importResult.hidden = true;
  elements.sessionTopic.value = "";
  if (remember) saveRecentCourse(course);
  renderCourse();
  loadProposal();
}

async function refreshCourse() {
  if (!state.course) return;
  const currentPresent = new Set(state.present);
  const [students, managementStudents, metrics] = await Promise.all([
    api(`/courses/${state.course.id}/students`),
    api(`/courses/${state.course.id}/students?include_inactive=true`),
    api(`/courses/${state.course.id}/fairness-metrics`),
  ]);
  state.students = students;
  state.managementStudents = managementStudents;
  if (state.session) {
    await syncSession();
  } else {
    state.present = new Set(students.filter((student) => currentPresent.has(student.id)).map((student) => student.id));
  }
  renderSessionBox();
  renderStudents();
  renderManagementStudents();
  renderMetrics(metrics);
}

// La asistencia de una sesión en curso vive en el servidor: se vuelve a leer de ahí.
async function syncSession() {
  const detail = await api(`/class-sessions/${state.session.id}`);
  state.session = detail;
  state.present = new Set(detail.attendance.filter((entry) => entry.present).map((entry) => entry.student_id));
}

async function saveAttendance(marks) {
  const detail = await api(`/class-sessions/${state.session.id}/attendance`, {
    method: "PUT",
    body: JSON.stringify({ attendance: marks.map(([student_id, present]) => ({ student_id, present })) }),
  });
  state.session = detail;
  state.present = new Set(detail.attendance.filter((entry) => entry.present).map((entry) => entry.student_id));
  renderSessionBox();
}

function setApiStatus(isOnline) {
  elements.apiDot.classList.toggle("online", isOnline);
  elements.apiDot.classList.toggle("offline", !isOnline);
  elements.apiStatus.textContent = isOnline ? "API conectada" : "API sin conexión";
}

async function checkApi() {
  try {
    await api("/health");
    setApiStatus(true);
  } catch {
    setApiStatus(false);
  }
}

function formatDate(value) {
  return new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

async function openStudentHistory(studentId) {
  const student = state.students.find((item) => item.id === Number(studentId));
  if (!student) return;
  $("#dialog-student-name").textContent = student.display_name;
  $("#dialog-student-ref").textContent = `${student.external_ref} · ID ${student.id}`;
  $("#dialog-state").innerHTML = `<div class="state-stat"><span>ALPHA</span><strong>…</strong></div>
    <div class="state-stat"><span>BETA</span><strong>…</strong></div>
    <div class="state-stat"><span>PRESENTE</span><strong>…</strong></div>
    <div class="state-stat"><span>SELECCIONADO</span><strong>…</strong></div>`;
  $("#dialog-history").innerHTML = '<p class="history-none">Cargando historial…</p>';
  elements.dialog.showModal();
  try {
    const [studentState, history] = await Promise.all([
      api(`/students/${student.id}/state`),
      api(`/students/${student.id}/history?limit=50`),
    ]);
    $("#dialog-state").innerHTML = [
      ["ALPHA", studentState.alpha], ["BETA", studentState.beta],
      ["PRESENTE", studentState.n_present], ["SELECCIONADO", studentState.n_selected],
    ].map(([label, value]) => `<div class="state-stat"><span>${label}</span><strong>${Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 2)}</strong></div>`).join("");
    $("#dialog-history-count").textContent = `${history.length} ${history.length === 1 ? "evento" : "eventos"}`;
    $("#dialog-history").innerHTML = history.length ? history.map((event) => `
      <article class="history-event ${event.selected ? "selected" : ""}">
        <span class="history-event-dot" aria-hidden="true"></span>
        <div><strong>${event.selected ? "Seleccionado" : "Presente, no seleccionado"}</strong>
          <small>Alpha ${event.alpha_before} → ${event.alpha_after} · Beta ${event.beta_before} → ${event.beta_after}</small></div>
        <time>${escapeHtml(formatDate(event.created_at))}</time>
      </article>`).join("") : '<p class="history-none">Todavía no hay decisiones registradas.</p>';
  } catch (error) {
    $("#dialog-history").innerHTML = `<p class="history-none">${escapeHtml(error.message)}</p>`;
  }
}

function renderSelectionResult(result) {
  const names = new Map(state.students.map((student) => [student.id, student.display_name]));
  $("#metric-last-run").textContent = `#${result.decision_run_id}`;
  $("#result-title").textContent = result.selected_student_ids.length
    ? `${result.selected_student_ids.length} seleccionado${result.selected_student_ids.length === 1 ? "" : "s"}`
    : "Sin estudiantes seleccionados";
  $("#result-meta").textContent = `Sesión #${result.class_session_id} · Decisión #${result.decision_run_id}`;
  $("#selected-list").innerHTML = result.selected_student_ids.map((id) => {
    const name = names.get(id) || `Estudiante ${id}`;
    return `<div class="selected-person"><span aria-hidden="true">✓</span>${escapeHtml(name)} <small>ID ${id}</small></div>`;
  }).join("");
  elements.resultPanel.hidden = false;
  abrirPanelParticipacion(result);
}

/* --------------------------------------------------------------------------
   HU-P4 — registrar la participación de quien acaba de salir del sorteo.

   El flujo es deliberadamente de dos pasos: el sorteo YA se registró (es la
   traza del algoritmo), y la participación se guarda después, cuando el
   docente sabe qué preguntó y qué le respondieron. Meterlo todo en el mismo
   clic obligaría a escribir la pregunta antes de ver a quién le tocó, que es
   al revés de como se da la clase.

   "Volver a sortear" conserva lo escrito: el docente puede cambiar de
   estudiante sin perder la pregunta que ya tenía preparada. Es el criterio de
   HU-P1 ("permitir volver a realizar la selección cuando corresponda").
   -------------------------------------------------------------------------- */

function abrirPanelParticipacion(result) {
  const panel = $("#participation-panel");
  if (!panel || !state.session) { panel && (panel.hidden = true); return; }

  const sel = $("#participation-student");
  sel.innerHTML = result.selected_student_ids.map((id) => {
    const nombre = (state.students.find((s) => Number(s.id) === Number(id)) || {}).display_name;
    return `<option value="${id}">${escapeHtml(nombre || `Estudiante ${id}`)}</option>`;
  }).join("");

  panel.hidden = false;
  state.lastDecisionRunId = result.decision_run_id;

  // Se vacía la respuesta pero NO la pregunta: si el docente ya la tenía
  // escrita y solo quiere cambiar de estudiante, no la pierde.
  $("#participation-answer").value = "";
  cargarHistorialSesion();
}

async function cargarHistorialSesion() {
  if (!state.session) return;
  const sid = state.session.id;
  try {
    const [lista, resumen] = await Promise.all([
      api(`/class-sessions/${sid}/participations`),
      api(`/class-sessions/${sid}/participations/summary`),
    ]);
    $("#participation-count").textContent = resumen.total;
    $("#participation-history-count").textContent = lista.length;
    $("#participation-history").innerHTML = lista.length
      ? lista.map((p) => `<li>
          <strong>${escapeHtml(p.student_name)}</strong>
          <span class="ph-q">${escapeHtml(p.question)}</span>
          ${p.answer ? `<span class="ph-a">→ ${escapeHtml(p.answer)}</span>` : ""}
        </li>`).join("")
      : `<li class="ph-empty">Todavía no hay participaciones en esta sesión.</li>`;
  } catch (err) {
    console.warn("No se pudo cargar el historial:", err);
  }
}

async function guardarParticipacion() {
  const sel = $("#participation-student");
  const pregunta = $("#participation-question").value.trim();
  const boton = $("#participation-save");

  if (!state.session) { notify("Abrí una sesión primero.", true); return; }
  if (!sel.value) { notify("No hay ningún estudiante seleccionado.", true); return; }
  if (!pregunta) { notify("Escribí la pregunta.", true); return; }

  setBusy(boton, true, "Guardando...");
  try {
    await api(`/class-sessions/${state.session.id}/participations`, {
      method: "POST",
      body: JSON.stringify({
        student_id: Number(sel.value),
        question: pregunta,
        answer: $("#participation-answer").value.trim() || null,
        decision_run_id: state.lastDecisionRunId || null,
        created_by: "docente",
      }),
    });
    notify("Participación registrada ✓");
    $("#participation-answer").value = "";
    await cargarHistorialSesion();
    // `refreshCourse` es la recarga completa que ya usa el botón "Actualizar":
    // vuelve a traer estudiantes, métricas de equidad y sesión. Se reutiliza
    // en vez de inventar una segunda vía de refresco, que terminaría
    // actualizando una parte de la pantalla y dejando otra vieja.
    await refreshCourse();
  } catch (err) {
    notify(`No se pudo guardar: ${err.message}`, true);
  } finally {
    setBusy(boton, false);
  }
}

function presentStudents() {
  return state.students.filter((student) => state.present.has(Number(student.id)));
}

/* ==========================================================================
   Bolillero: física 2D en <canvas>.
   - Las bolillas llevan el NÚMERO DE ORDEN del estudiante (orden alfabético
     por display_name, ver studentOrderMap); el nombre NO se dibuja.
   - Mientras se espera el resultado las bolillas "chocolatean": chorro de
     aire desde abajo, choques entre bolillas y contra las paredes.
   - Con el resultado, la bolilla elegida se destaca, baja hasta el orificio
     del piso y rueda por el canal hacia abajo a la derecha. Recién cuando
     termina de salir se invoca onDone y se muestra el nombre.
   ========================================================================== */
const BALL_W = 520;
const BALL_H = 330;
const BALL_BOX = { x: 14, y: 8, w: 400, h: 250, r: 14 };
const BALL_TUBE_X = 360;   // eje del tramo vertical del canal (bajo la caja)
const BALL_TUBE_Y = 296;   // eje del tramo horizontal
const BALL_TUBE_END = 504; // boca de salida (derecha)

function studentOrderMap() {
  const sorted = [...state.students].sort((a, b) =>
    String(a.display_name).trim().localeCompare(String(b.display_name).trim(), "es", { sensitivity: "base" }));
  return new Map(sorted.map((student, index) => [Number(student.id), index + 1]));
}

function createBallMachine(canvas, candidates, orderMap, reduceMotion) {
  const ctx = canvas.getContext("2d");
  const left = BALL_BOX.x + 8;
  const right = BALL_BOX.x + BALL_BOX.w - 8;
  const top = BALL_BOX.y + 8;
  const floor = BALL_BOX.y + BALL_BOX.h - 8;
  const count = Math.max(candidates.length, 1);
  const radius = Math.max(8, Math.min(20, Math.sqrt(0.3 * (right - left) * (floor - top) / (count * Math.PI))));
  const tubeW = Math.max(2 * radius + 8, 30);
  const floorLine = BALL_BOX.y + BALL_BOX.h;

  // Colocación inicial: apiladas en el fondo, como si acabaran de caer.
  const perRow = Math.max(1, Math.floor((right - left) / (2 * radius + 1)));
  const balls = candidates.map((student, index) => ({
    id: Number(student.id),
    num: orderMap.get(Number(student.id)) ?? index + 1,
    color: visualPalette[index % visualPalette.length],
    x: left + radius + (index % perRow) * (2 * radius + 1) + Math.random() * 1.5,
    y: floor - radius - Math.floor(index / perRow) * (2 * radius + 1),
    vx: 0, vy: 0, ghost: false, chosen: false, exit: null,
  }));

  let intensity = reduceMotion ? 0 : 1;
  let intensityTarget = intensity;
  let clock = 0;
  let last = 0;
  let raf = 0;
  let stopped = false;
  let gateOpen = false;
  let doneAt = null;
  let doneFired = false;
  let onDone = null;
  let stopAt = Infinity;

  function step(dt) {
    const gravity = 900;
    for (const b of balls) {
      if (b.ghost) continue;
      let ay = gravity;
      if (intensity > 0.01) {
        const depth = (b.y - top) / (floor - top);
        ay -= intensity * (1700 + 1500 * Math.random()) * Math.max(0, depth - 0.15);
        b.vx += intensity * (Math.sin(clock * 5 + b.y * 0.045) * 520 + (Math.random() - 0.5) * 1700) * dt;
        if (Math.random() < 0.012 * intensity) {
          b.vx += (Math.random() - 0.5) * 760;
          b.vy -= Math.random() * 420;
        }
      }
      b.vy += ay * dt;
      const damping = 1 - 0.4 * dt;
      b.vx *= damping; b.vy *= damping;
      const speed = Math.hypot(b.vx, b.vy);
      if (speed > 650) { b.vx *= 650 / speed; b.vy *= 650 / speed; }
      b.x += b.vx * dt; b.y += b.vy * dt;
      if (b.x < left + radius) { b.x = left + radius; b.vx = Math.abs(b.vx) * 0.85; }
      if (b.x > right - radius) { b.x = right - radius; b.vx = -Math.abs(b.vx) * 0.85; }
      if (b.y < top + radius) { b.y = top + radius; b.vy = Math.abs(b.vy) * 0.85; }
      if (b.y > floor - radius) { b.y = floor - radius; b.vy = -Math.abs(b.vy) * 0.55; }
    }
    const min = 2 * radius;
    for (let i = 0; i < balls.length; i += 1) {
      const a = balls[i];
      if (a.ghost) continue;
      for (let j = i + 1; j < balls.length; j += 1) {
        const c = balls[j];
        if (c.ghost) continue;
        const dx = c.x - a.x; const dy = c.y - a.y;
        const distSq = dx * dx + dy * dy;
        if (distSq >= min * min || distSq === 0) continue;
        const dist = Math.sqrt(distSq);
        const nx = dx / dist; const ny = dy / dist;
        const push = (min - dist) / 2;
        a.x -= nx * push; a.y -= ny * push; c.x += nx * push; c.y += ny * push;
        const rel = (c.vx - a.vx) * nx + (c.vy - a.vy) * ny;
        if (rel < 0) {
          const impulse = -(1 + 0.9) * rel / 2;
          a.vx -= impulse * nx; a.vy -= impulse * ny; c.vx += impulse * nx; c.vy += impulse * ny;
        }
      }
    }
  }

  // Recorrido de salida de una bolilla: del piso de la caja por el canal.
  function exitPath(slot) {
    const slotX = Math.max(BALL_TUBE_X + radius + 18, BALL_TUBE_END - radius - 4 - slot * (2 * radius + 3));
    return [
      { x: BALL_TUBE_X, y: floor - radius },
      { x: BALL_TUBE_X, y: BALL_TUBE_Y - 16 },
      { x: BALL_TUBE_X + 16, y: BALL_TUBE_Y },
      { x: slotX, y: BALL_TUBE_Y },
    ];
  }
  function along(path, u) {
    const lengths = [];
    let total = 0;
    for (let i = 1; i < path.length; i += 1) {
      const len = Math.hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y);
      lengths.push(len); total += len;
    }
    let dist = u * total;
    for (let i = 0; i < lengths.length; i += 1) {
      if (dist <= lengths[i] || i === lengths.length - 1) {
        const k = lengths[i] ? Math.min(1, dist / lengths[i]) : 1;
        return { x: path[i].x + (path[i + 1].x - path[i].x) * k, y: path[i].y + (path[i + 1].y - path[i].y) * k };
      }
      dist -= lengths[i];
    }
    return path[path.length - 1];
  }
  const easeInOut = (u) => (u < 0.5 ? 2 * u * u : 1 - ((-2 * u + 2) ** 2) / 2);

  const LIFT = 0.9;  // s: la elegida sube/baja hasta la boca del canal
  const ROLL = 1.3;  // s: rueda por el canal

  function updateExits() {
    for (const b of balls) {
      if (!b.exit) continue;
      const e = b.exit;
      const t = clock - e.start;
      if (t < 0) continue;
      if (!b.ghost) {
        b.ghost = true; b.chosen = true; e.from = { x: b.x, y: b.y }; gateOpen = true;
      }
      if (t < LIFT) {
        const k = easeInOut(t / LIFT);
        b.x = e.from.x + (e.path[0].x - e.from.x) * k;
        b.y = e.from.y + (e.path[0].y - e.from.y) * k;
        b.scale = 1 + 0.3 * Math.sin(Math.PI * k);
      } else if (t < LIFT + ROLL) {
        const u = (t - LIFT) / ROLL;
        const p = along(e.path, u * u * (3 - 2 * u));
        b.x = p.x; b.y = p.y; b.scale = 1;
      } else {
        const p = e.path[e.path.length - 1];
        b.x = p.x; b.y = p.y; b.scale = 1;
      }
    }
  }

  function fit() {
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    if (canvas.width !== width) { canvas.width = width; canvas.height = Math.round(width * BALL_H / BALL_W); }
    const s = canvas.width / BALL_W;
    ctx.setTransform(s, 0, 0, s, 0, 0);
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawTube() {
    ctx.save();
    ctx.lineJoin = "round"; ctx.lineCap = "butt";
    ctx.beginPath();
    ctx.moveTo(BALL_TUBE_X, floorLine);
    ctx.lineTo(BALL_TUBE_X, BALL_TUBE_Y - 16);
    ctx.lineTo(BALL_TUBE_X + 16, BALL_TUBE_Y);
    ctx.lineTo(BALL_TUBE_END, BALL_TUBE_Y);
    ctx.strokeStyle = "#17398a"; ctx.lineWidth = tubeW + 10; ctx.stroke();
    ctx.strokeStyle = "#d6e8fb"; ctx.lineWidth = tubeW; ctx.stroke();
    ctx.restore();
    // boca de salida
    ctx.fillStyle = "#17398a";
    roundRect(BALL_TUBE_END - 4, BALL_TUBE_Y - tubeW / 2 - 8, 11, tubeW + 16, 4);
    ctx.fill();
  }

  function drawBox() {
    const { x, y, w, h, r } = BALL_BOX;
    const glass = ctx.createLinearGradient(0, y, 0, y + h);
    glass.addColorStop(0, "rgba(255,255,255,.85)");
    glass.addColorStop(1, "rgba(173,208,247,.55)");
    roundRect(x, y, w, h, r);
    ctx.fillStyle = glass; ctx.fill();
    ctx.lineWidth = 4; ctx.strokeStyle = "#17398a"; ctx.stroke();
    if (gateOpen) { // orificio abierto en el piso
      ctx.fillStyle = "#d6e8fb";
      ctx.fillRect(BALL_TUBE_X - tubeW / 2, floorLine - 3, tubeW, 7);
    }
  }

  function drawBall(b) {
    const r = radius * (b.scale || 1);
    ctx.save();
    ctx.translate(b.x, b.y);
    ctx.fillStyle = "rgba(13,37,87,.16)";
    ctx.beginPath(); ctx.ellipse(1.5, r * 0.92, r * 0.85, r * 0.28, 0, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = b.color; ctx.fill();
    const shade = ctx.createRadialGradient(-r * 0.35, -r * 0.4, r * 0.05, 0, 0, r);
    shade.addColorStop(0, "rgba(255,255,255,.7)");
    shade.addColorStop(0.5, "rgba(255,255,255,0)");
    shade.addColorStop(1, "rgba(0,20,70,.3)");
    ctx.fillStyle = shade; ctx.fill();
    if (b.chosen) {
      ctx.shadowColor = "#e66e55"; ctx.shadowBlur = 12;
      ctx.lineWidth = 3; ctx.strokeStyle = "#e66e55";
      ctx.beginPath(); ctx.arc(0, 0, r + 2.5, 0, Math.PI * 2); ctx.stroke();
      ctx.shadowBlur = 0;
    }
    ctx.fillStyle = "#fff";
    ctx.beginPath(); ctx.arc(0, 0, r * 0.62, 0, Math.PI * 2); ctx.fill();
    const text = String(b.num);
    const size = r * (text.length === 1 ? 0.98 : text.length === 2 ? 0.8 : 0.62);
    ctx.fillStyle = "#0d2557";
    ctx.font = `700 ${size}px "DM Sans", "Trebuchet MS", sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, 0, size * 0.04);
    ctx.restore();
  }

  function draw() {
    fit();
    ctx.clearRect(0, 0, BALL_W, BALL_H);
    drawTube();
    drawBox();
    for (const b of balls) if (!b.ghost) drawBall(b);
    ctx.save(); // brillo del vidrio
    roundRect(BALL_BOX.x, BALL_BOX.y, BALL_BOX.w, BALL_BOX.h, BALL_BOX.r); ctx.clip();
    ctx.fillStyle = "rgba(255,255,255,.14)";
    ctx.beginPath(); ctx.moveTo(BALL_BOX.x + 40, BALL_BOX.y); ctx.lineTo(BALL_BOX.x + 110, BALL_BOX.y);
    ctx.lineTo(BALL_BOX.x + 40, BALL_BOX.y + BALL_BOX.h); ctx.lineTo(BALL_BOX.x - 30, BALL_BOX.y + BALL_BOX.h); ctx.fill();
    ctx.restore();
    for (const b of balls) if (b.ghost) drawBall(b);
  }

  function frame(now) {
    if (stopped) return;
    const dt = Math.min(0.033, last ? (now - last) / 1000 : 0.016);
    last = now; clock += dt;
    intensity += (intensityTarget - intensity) * Math.min(1, dt * 4);
    step(dt / 2); step(dt / 2);
    updateExits();
    draw();
    if (doneAt !== null && !doneFired && clock >= doneAt) { doneFired = true; if (onDone) onDone(); }
    if (clock > stopAt) return; // ya terminó: se deja el último cuadro
    raf = requestAnimationFrame(frame);
  }

  // Con "reducir movimiento": se asientan sin animar y se dibuja una vez.
  if (reduceMotion) { for (let i = 0; i < 240; i += 1) step(1 / 120); draw(); } else { raf = requestAnimationFrame(frame); }

  return {
    release(ids, done) {
      onDone = done;
      const chosen = ids.map((id) => balls.find((b) => b.id === Number(id))).filter(Boolean);
      if (reduceMotion) {
        chosen.forEach((b, slot) => {
          const path = exitPath(slot); const p = path[path.length - 1];
          b.ghost = true; b.chosen = true; b.x = p.x; b.y = p.y; b.scale = 1;
        });
        gateOpen = chosen.length > 0; draw(); done(); return;
      }
      intensityTarget = 0.35;          // baja el aire: se calma el chocolateo
      const settle = clock + 0.9;
      chosen.forEach((b, slot) => { b.exit = { start: settle + slot * 0.95, path: exitPath(slot), from: null }; });
      const lastStart = settle + Math.max(0, chosen.length - 1) * 0.95;
      doneAt = chosen.length ? lastStart + LIFT + ROLL + 0.6 : clock + 0.8;
      stopAt = doneAt + 3;
      if (chosen.length) setTimeout(() => { if (!stopped) intensityTarget = 0.15; }, 900);
      setTimeout(() => { if (!stopped) intensityTarget = 0; }, (doneAt - clock) * 1000);
    },
    stop() { stopped = true; cancelAnimationFrame(raf); },
  };
}

function stopBallMachine() {
  if (state.ballMachine) { state.ballMachine.stop(); state.ballMachine = null; }
}

function prepareSelectionStage() {
  const mode = document.querySelector('input[name="selection-visual"]:checked').value;
  const candidates = presentStudents();
  $("#stage-status").textContent = "SELECCIÓN EN CURSO";
  $("#stage-heading").textContent = mode === "roulette" ? "La ruleta está en marcha" : "Las bolillas se están mezclando";
  $("#stage-footnote").textContent = "El resultado se calcula con el método seleccionado.";
  $("#stage-result").hidden = true;
  elements.stageClose.hidden = true;
  $("#stage-done").hidden = true;
  $("#roulette-visual").hidden = mode !== "roulette";
  $("#balls-visual").hidden = mode !== "balls";
  elements.selectionStage.showModal();
  $("#roulette-hub-label").textContent = "EN JUEGO";
  $("#roulette-winner").textContent = "Ruleta";
  const wheel = $("#roulette-wheel");
  wheel.classList.remove("spinning");
  wheel.style.transition = "none";
  wheel.style.transform = "rotate(0deg)";
  const wheelSegments = candidates.map((student, index) => {
    const start = index * 100 / candidates.length;
    const end = (index + 1) * 100 / candidates.length;
    return `${visualPalette[index % visualPalette.length]} ${start}% ${end}%`;
  });
  wheel.style.background = `conic-gradient(from -90deg, ${wheelSegments.join(",")})`;
  const rouletteBounds = $("#roulette-visual").getBoundingClientRect();
  const manyCandidates = candidates.length > 8;
  $("#roulette-visual").classList.toggle("many-candidates", manyCandidates);
  const labelWidth = Math.min(128, rouletteBounds.width * (manyCandidates ? 0.22 : 0.34));
  const outerRadius = Math.max(58, Math.min(184, Math.min(rouletteBounds.width, rouletteBounds.height) / 2 - labelWidth / 2 - 8));
  $("#roulette-orbit").innerHTML = candidates.map((student, index) => {
    let x;
    let y;
    let maxWidth;
    if (manyCandidates) {
      const perColumn = Math.ceil(candidates.length / 2);
      const column = index >= perColumn ? 1 : 0;
      const indexInColumn = index - column * perColumn;
      const namesInColumn = Math.min(perColumn, candidates.length - column * perColumn);
      x = (column === 0 ? -1 : 1) * (rouletteBounds.width / 2 - labelWidth / 2 - 5);
      y = (indexInColumn - (namesInColumn - 1) / 2) * (rouletteBounds.height - 40) / Math.max(namesInColumn - 1, 1);
      maxWidth = labelWidth;
    } else {
      const angle = (index / candidates.length) * Math.PI * 2 - Math.PI / 2;
      const safeRadius = Math.min(outerRadius, rouletteBounds.width / 2 - labelWidth / 2 - 8);
      x = Math.cos(angle) * safeRadius;
      y = Math.sin(angle) * safeRadius;
      maxWidth = Math.max(60, Math.min(labelWidth, 2 * safeRadius * Math.sin(Math.PI / candidates.length) * 0.72));
    }
    const cssOffset = (value) => `calc(50% ${value < 0 ? "-" : "+"} ${Math.abs(value)}px)`;
    return `<span class="roulette-name" data-student-index="${index}" title="${escapeHtml(student.display_name)}" style="left:${cssOffset(x)};top:${cssOffset(y)};width:${maxWidth}px;max-width:${maxWidth}px">${escapeHtml(student.display_name)}</span>`;
  }).join("");
  stopBallMachine();
  if (mode === "balls") {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    state.ballMachine = createBallMachine($("#ball-canvas"), candidates, studentOrderMap(), reduce);
  }
  $("#ball-count").textContent = `${candidates.length} ${candidates.length === 1 ? "BOLILLA" : "BOLILLAS"}`;
  $("#ball-machine-footer").textContent = "Mezclando participantes";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const startedAt = performance.now();
  let index = 0;
  const advanceAnimation = () => {
    const elapsed = performance.now() - startedAt;
    const progress = Math.min(1, elapsed / selectionAnimationDuration);
    const easedProgress = progress ** 2.5;
    const activeIndex = index % candidates.length;
    if (!reduceMotion) {
      if (mode === "roulette") {
        wheel.classList.add("spinning");
        wheel.style.setProperty("--spin-duration", `${0.3 + easedProgress * 1.5}s`);
        $("#roulette-orbit").querySelectorAll(".roulette-name").forEach((name, nameIndex) => {
          name.classList.toggle("active", nameIndex === activeIndex);
        });
      }
    }
    index += 1;
    if (elapsed >= selectionAnimationDuration) {
      wheel.classList.remove("spinning");
      $("#ball-machine").classList.remove("mixing");
      $("#stage-status").textContent = "CONFIRMANDO RESULTADO";
      $("#stage-footnote").textContent = "La selección está terminando.";
      state.visualTimer = null;
      return;
    }
    const nextDelay = 55 + easedProgress * 850;
    state.visualTimer = setTimeout(advanceAnimation, Math.min(nextDelay, selectionAnimationDuration - elapsed));
  };
  advanceAnimation();
  return { mode, candidates, startedAt };
}

function finishSelectionStage(result, stage, error = null) {
  clearTimeout(state.visualTimer);
  state.visualTimer = null;
  const wheel = $("#roulette-wheel");
  wheel.classList.remove("spinning");
  wheel.style.transition = "transform 850ms cubic-bezier(.16,.75,.24,1)";
  $("#ball-machine").classList.remove("mixing");
  const revealResult = () => {
    $("#stage-result").hidden = false;
    $("#stage-done").hidden = false;
    elements.stageClose.hidden = false;
  };
  if (error) {
    stopBallMachine();
    revealResult();
    $("#roulette-visual").hidden = true;
    $("#balls-visual").hidden = true;
    $("#stage-status").textContent = "NO SE PUDO COMPLETAR";
    $("#stage-heading").textContent = "No hubo resultado";
    $("#stage-winners").innerHTML = `<p class="stage-error">${escapeHtml(error.message)}</p>`;
    $("#stage-result-meta").textContent = "La selección no quedó registrada.";
    $("#stage-footnote").textContent = "Cierra esta ventana e inténtalo de nuevo.";
    return;
  }
  const names = new Map(state.students.map((student) => [Number(student.id), student.display_name]));
  const winners = result.selected_student_ids.map((id) => ({ id, name: names.get(Number(id)) || `Estudiante ${id}` }));
  $("#roulette-visual").hidden = stage.mode !== "roulette";
  $("#balls-visual").hidden = stage.mode !== "balls";
  // Texto final con el/los nombres. En la ruleta sale de inmediato; en el
  // bolillero solo después de que la bolilla termina de salir por el canal.
  const showFinalText = () => {
    $("#stage-status").textContent = "DECISIÓN REGISTRADA";
    $("#stage-heading").textContent = winners.length ? "¡Ya tenemos resultado!" : "Ronda completada";
    $("#stage-winners").innerHTML = winners.length
      ? winners.map((student, index) => `<div class="stage-winner" style="animation-delay:${index * 90}ms"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(student.name)}</strong><small>ID ${student.id}</small></div>`).join("")
      : '<p class="stage-empty-result">No hubo estudiantes seleccionados.</p>';
    $("#stage-result-meta").textContent = `Sesión #${result.class_session_id} · Decisión #${result.decision_run_id}`;
    $("#stage-footnote").textContent = "Esta decisión ya quedó guardada en el curso.";
  };
  if (stage.mode === "roulette") {
    revealResult();
    const winnerIndex = stage.candidates.findIndex((student) => Number(student.id) === Number(winners[0]?.id));
    const targetAngle = winnerIndex < 0 ? 0 : 360 - (360 * (winnerIndex + 0.5)) / stage.candidates.length;
    wheel.style.transform = `rotate(${targetAngle + 1440}deg)`;
    $("#roulette-hub-label").textContent = winners.length ? "RESULTADO" : "FINALIZADO";
    $("#roulette-winner").textContent = winners.length === 1 ? winners[0].name : winners.length ? `${winners.length} ganadores` : "Sin selección";
    $("#roulette-orbit").querySelectorAll(".roulette-name").forEach((name) => {
      const candidate = stage.candidates[Number(name.dataset.studentIndex)];
      const selected = winners.some((winner) => Number(winner.id) === Number(candidate.id));
      name.classList.toggle("active", selected);
      name.classList.toggle("not-selected", !selected);
    });
    showFinalText();
    return;
  }
  const orderMap = studentOrderMap();
  const numbers = winners.map((winner) => String(orderMap.get(Number(winner.id)) ?? "?").padStart(2, "0"));
  $("#stage-status").textContent = winners.length ? "SALE LA BOLILLA" : "CONFIRMANDO RESULTADO";
  $("#stage-heading").textContent = winners.length ? "Saliendo la bolilla elegida" : "Ronda completada";
  $("#stage-footnote").textContent = "El nombre aparece cuando la bolilla termina de salir.";
  $("#ball-machine-footer").textContent = winners.length ? `Bolilla n.º ${numbers.join(", ")} en camino` : "No hubo bolillas seleccionadas";
  const finish = () => {
    $("#ball-count").textContent = `${winners.length} ${winners.length === 1 ? "SELECCIONADA" : "SELECCIONADAS"}`;
    $("#ball-machine-footer").textContent = winners.length ? `Bolilla seleccionada: n.º ${numbers.join(", ")}` : "No hubo bolillas seleccionadas";
    showFinalText();
    revealResult();
  };
  if (state.ballMachine) state.ballMachine.release(winners.map((winner) => Number(winner.id)), finish);
  else finish();
}

function closeSelectionStage() {
  if (elements.selectionStage.open) elements.selectionStage.close();
}

elements.selectionStage.addEventListener("close", stopBallMachine);

$("#create-course-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const name = $("#course-name").value.trim();
  if (!name) return;
  setBusy(button, true, "Creando...");
  try {
    const course = await api("/courses", { method: "POST", body: JSON.stringify({ name }) });
    await loadCourse(course.id);
    form.reset();
    notify(`Curso “${course.name}” creado.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#load-course-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadCourse(elements.courseIdInput.value);
    notify(`Curso #${state.course.id} cargado.`);
  } catch (error) {
    notify(error.message, true);
  }
});

elements.recentCourses.addEventListener("change", async () => {
  if (!elements.recentCourses.value) return;
  try {
    await loadCourse(elements.recentCourses.value);
  } catch (error) {
    notify(error.message, true);
  }
});

$("#enroll-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course) return;
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const payload = {
    external_ref: $("#student-ref").value.trim(),
    display_name: $("#student-name").value.trim(),
    phone_number: $("#student-phone").value.trim() || null,
    email: $("#student-email").value.trim() || null,
  };
  setBusy(button, true, "Guardando...");
  try {
    const student = await api(`/courses/${state.course.id}/students`, { method: "POST", body: JSON.stringify(payload) });
    await refreshCourse();
    form.reset();
    notify(`${student.display_name} quedó matriculado.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

elements.studentList.addEventListener("change", async (event) => {
  const input = event.target.closest("[data-attendance-id]");
  if (!input) return;
  const id = Number(input.dataset.attendanceId);
  if (state.session) {
    // Con sesión en curso, la marca se guarda en el servidor (HU-S2).
    input.disabled = true;
    try {
      await saveAttendance([[id, input.checked]]);
    } catch (error) {
      notify(error.message, true);
    }
    renderStudents();
    return;
  }
  if (input.checked) state.present.add(id);
  else state.present.delete(id);
  input.closest(".attendance-control").querySelector("span").textContent = input.checked ? "Presente" : "Ausente";
  updateSelectionControls();
});

elements.toggleAll.addEventListener("click", async () => {
  const allPresent = state.students.length > 0 && state.present.size === state.students.length;
  if (state.session) {
    try {
      await saveAttendance(state.students.map((student) => [student.id, !allPresent]));
    } catch (error) {
      notify(error.message, true);
    }
    renderStudents();
    return;
  }
  state.present = allPresent ? new Set() : new Set(state.students.map((student) => student.id));
  renderStudents();
});

elements.methodSelect.addEventListener("change", updateMethodFields);
$("#slots-input").addEventListener("change", updateSelectionControls);

$("#selection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course || !state.present.size) return;
  const payload = {
    k: Number($("#slots-input").value),
    method: elements.methodSelect.value,
  };
  if (state.session) {
    // El servidor elige entre los presentes guardados en la sesión (HU-S2).
    payload.class_session_id = state.session.id;
  } else {
    payload.present_student_ids = [...state.present];
    const sessionLabel = $("#session-label").value.trim();
    if (sessionLabel) payload.session_label = sessionLabel;
  }
  if (payload.method === "weighted_softmax") payload.method_params = { tau: Number($("#tau-input").value) };
  const stageStartedAt = prepareSelectionStage();
  setBusy(elements.runButton, true, "Seleccionando...");
  try {
    const result = await api(`/courses/${state.course.id}/sessions/select`, {
      method: "POST", body: JSON.stringify(payload),
    });
    renderSelectionResult(result);
    const remainingAnimation = Math.max(0, selectionAnimationDuration - (performance.now() - stageStartedAt.startedAt));
    if (remainingAnimation) await new Promise((resolve) => setTimeout(resolve, remainingAnimation));
    finishSelectionStage(result, stageStartedAt);
    try {
      await refreshCourse();
      notify("Decisión guardada correctamente.");
    } catch (error) {
      notify(`Decisión guardada, pero no se pudo actualizar el curso: ${error.message}`, true);
    }
  } catch (error) {
    finishSelectionStage(null, stageStartedAt, error);
    notify(error.message, true);
  } finally {
    setBusy(elements.runButton, false);
  }
});

elements.stageClose.addEventListener("click", closeSelectionStage);
$("#stage-done").addEventListener("click", closeSelectionStage);

$("#session-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course) return;
  const button = $("#session-start-button");
  const payload = { topic: elements.sessionTopic.value.trim() || null };
  if (state.proposal?.session_date) payload.session_date = state.proposal.session_date;
  // Si el docente ya marcó asistencia antes de iniciar, se respeta; si no, todos quedan presentes.
  if (state.present.size) payload.present_student_ids = [...state.present];
  setBusy(button, true, "Iniciando...");
  try {
    const detail = await api(`/courses/${state.course.id}/class-sessions`, { method: "POST", body: JSON.stringify(payload) });
    state.session = detail;
    state.present = new Set(detail.attendance.filter((entry) => entry.present).map((entry) => entry.student_id));
    renderSessionBox();
    renderStudents();
    notify(`Sesión #${detail.id} iniciada.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#session-end-button").addEventListener("click", async () => {
  state.session = null;
  state.present = new Set();
  elements.resultPanel.hidden = true;
  renderSessionBox();
  renderStudents();
  await loadProposal();
  notify("Sesión terminada. Puedes iniciar otra.");
});

elements.rosterFile.addEventListener("change", () => {
  const file = elements.rosterFile.files[0];
  $("#roster-file-label").textContent = file ? `↑ ${file.name}` : "↑ Elegir Excel (.xlsx)";
  elements.importButton.disabled = !file;
});

function renderImportResult(result) {
  const parts = [`${result.created} nuevo${result.created === 1 ? "" : "s"}`, `${result.updated} actualizado${result.updated === 1 ? "" : "s"}`, `${result.unchanged} sin cambios`];
  const errors = result.errors.map((error) => `<li>Fila ${error.row}: ${escapeHtml(error.message)}</li>`).join("");
  elements.importResult.innerHTML = `<strong>${result.total_rows} fila${result.total_rows === 1 ? "" : "s"} leída${result.total_rows === 1 ? "" : "s"}:</strong> ${parts.join(" · ")}`
    + (errors ? `<p class="import-errors-title">${result.errors.length} fila${result.errors.length === 1 ? "" : "s"} con problemas (no se importaron):</p><ul>${errors}</ul>` : "");
  elements.importResult.classList.toggle("has-errors", result.errors.length > 0);
  elements.importResult.hidden = false;
}

elements.importButton.addEventListener("click", async () => {
  const file = elements.rosterFile.files[0];
  if (!state.course || !file) return;
  const form = new FormData();
  form.append("file", file);
  setBusy(elements.importButton, true, "Cargando...");
  try {
    const result = await api(`/courses/${state.course.id}/students/import`, { method: "POST", body: form });
    renderImportResult(result);
    await refreshCourse();
    elements.rosterFile.value = "";
    $("#roster-file-label").textContent = "↑ Elegir Excel (.xlsx)";
    elements.importButton.disabled = true;
    notify(result.errors.length ? "Lista cargada con observaciones." : "Lista cargada correctamente.", result.errors.length > 0);
  } catch (error) {
    elements.importResult.hidden = true;
    notify(error.message, true);
  } finally {
    setBusy(elements.importButton, false);
    elements.importButton.disabled = !elements.rosterFile.files[0];
  }
});

let editingStudentId = null;

elements.adminStudentList.addEventListener("click", (event) => {
  const historyButton = event.target.closest("[data-history-id]");
  if (historyButton) {
    openStudentHistory(historyButton.dataset.historyId);
    return;
  }
  const button = event.target.closest("[data-edit-id]");
  if (!button) return;
  const student = state.managementStudents.find((item) => item.id === Number(button.dataset.editId));
  if (!student) return;
  editingStudentId = student.id;
  $("#edit-name").value = student.display_name;
  $("#edit-ref").value = student.external_ref;
  $("#edit-phone").value = student.phone_number || "";
  $("#edit-email").value = student.email || "";
  $("#edit-withdraw").textContent = student.active ? "Retirar del curso" : "Reincorporar al curso";
  elements.editDialog.showModal();
});

$("#edit-close").addEventListener("click", () => elements.editDialog.close());

async function patchStudent(changes, successMessage) {
  try {
    await api(`/students/${editingStudentId}`, { method: "PATCH", body: JSON.stringify(changes) });
    elements.editDialog.close();
    await refreshCourse();
    notify(successMessage);
  } catch (error) {
    notify(error.message, true);
  }
}

$("#edit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  patchStudent(
    {
      display_name: $("#edit-name").value.trim(),
      external_ref: $("#edit-ref").value.trim(),
      phone_number: $("#edit-phone").value.trim(),
      email: $("#edit-email").value.trim(),
    },
    "Estudiante actualizado.",
  );
});

$("#edit-withdraw").addEventListener("click", () => {
  const student = state.managementStudents.find((item) => item.id === editingStudentId);
  if (!student) return;
  const active = !student.active;
  const action = active ? "reincorporar" : "retirar";
  if (!window.confirm(`¿${action} a ${student.display_name} ${active ? "al" : "del"} curso? Conserva su historial.`)) return;
  patchStudent({ active }, active
    ? `${student.display_name} fue reincorporado al curso.`
    : `${student.display_name} fue retirado del curso.`);
});

elements.attendanceTab.addEventListener("click", () => setCourseView("attendance"));
elements.managementTab.addEventListener("click", () => setCourseView("management"));
elements.activeRole.addEventListener("change", () => {
  state.role = elements.activeRole.value;
  localStorage.setItem("aula-active-role", state.role);
  notify(`Rol seleccionado: ${state.role === "administrador" ? "Administrador" : "Profesor"}.`);
});

$("#refresh-button").addEventListener("click", async () => {
  try {
    await refreshCourse();
    notify("Curso actualizado.");
  } catch (error) {
    notify(error.message, true);
  }
});

// --- HU-P4: registrar participación -----------------------------------------
$("#participation-save").addEventListener("click", guardarParticipacion);

// "Volver a sortear" reutiliza el envío del formulario de decisión, que es el
// mismo camino que el botón normal. Así el sorteo se rehace con la MISMA
// estrategia y las MISMAS reglas, y no por un atajo que podría desviarse.
$("#participation-resortear").addEventListener("click", () => {
  const form = $("#selection-form");
  if (!form || !presentStudents().length) {
    notify("No hay presentes a quienes sortear.", true);
    return;
  }
  form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { cancelable: true }));
});

$("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) elements.dialog.close();
});

$("#today-label").textContent = new Intl.DateTimeFormat("es", { dateStyle: "long" }).format(new Date());
renderRecentCourses();
state.role = localStorage.getItem("aula-active-role") || "profesor";
elements.activeRole.value = ["profesor", "administrador"].includes(state.role) ? state.role : "profesor";
state.role = elements.activeRole.value;
checkApi();
setInterval(checkApi, 30000);
api("/methods").then((response) => {
  state.methods = response.methods;
  renderMethodOptions();
}).catch((error) => notify(error.message, true));
api("/courses").then((courses) => {
  state.availableCourses = courses;
  renderRecentCourses();
}).catch((error) => notify(`No se pudieron cargar los cursos: ${error.message}`, true));