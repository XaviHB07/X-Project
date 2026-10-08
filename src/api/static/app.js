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
};

const selectionAnimationDuration = 5500;
const visualPalette = ["#df795e", "#f3c86a", "#5ca28e", "#b9d996", "#60876f", "#e7a9a0"];

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
  $("#ball-machine").classList.remove("mixing");
  $("#ball-tray").classList.remove("is-final");
  $("#ball-tray").innerHTML = candidates.map((student, index) =>
    `<span class="draw-ball" data-student-index="${index}" role="img" aria-label="Bolilla de ${escapeHtml(student.display_name)}" title="${escapeHtml(student.display_name)}" style="--ball-color:${visualPalette[index % visualPalette.length]};--ball-delay:${index * -35}ms"><span>${escapeHtml(student.display_name)}</span></span>`,
  ).join("");
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
      } else {
        const machine = $("#ball-machine");
        machine.classList.add("mixing");
        machine.style.setProperty("--ball-duration", `${0.28 + easedProgress * 1.1}s`);
        $("#ball-tray").querySelectorAll(".draw-ball").forEach((ball, ballIndex) => {
          ball.classList.toggle("active", ballIndex === activeIndex);
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
  $("#stage-result").hidden = false;
  $("#stage-done").hidden = false;
  elements.stageClose.hidden = false;
  if (error) {
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
  if (stage.mode === "roulette") {
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
  } else {
    const selectedIds = new Set(winners.map((winner) => Number(winner.id)));
    $("#ball-tray").classList.add("is-final");
    $("#ball-tray").querySelectorAll(".draw-ball").forEach((ball) => {
      const candidate = stage.candidates[Number(ball.dataset.studentIndex)];
      const selected = selectedIds.has(Number(candidate.id));
      ball.classList.toggle("winner", selected);
      ball.classList.toggle("eliminated", !selected);
    });
    $("#ball-count").textContent = `${winners.length} ${winners.length === 1 ? "SELECCIONADA" : "SELECCIONADAS"}`;
    $("#ball-machine-footer").textContent = winners.length ? "Bolilla seleccionada" : "No hubo bolillas seleccionadas";
  }
  $("#stage-status").textContent = "DECISIÓN REGISTRADA";
  $("#stage-heading").textContent = winners.length ? "¡Ya tenemos resultado!" : "Ronda completada";
  $("#stage-winners").innerHTML = winners.length
    ? winners.map((student, index) => `<div class="stage-winner" style="animation-delay:${index * 90}ms"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(student.name)}</strong><small>ID ${student.id}</small></div>`).join("")
    : '<p class="stage-empty-result">No hubo estudiantes seleccionados.</p>';
  $("#stage-result-meta").textContent = `Sesión #${result.class_session_id} · Decisión #${result.decision_run_id}`;
  $("#stage-footnote").textContent = "Esta decisión ya quedó guardada en el curso.";
}

function closeSelectionStage() {
  if (elements.selectionStage.open) elements.selectionStage.close();
}

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