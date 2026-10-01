const $ = (selector) => document.querySelector(selector);

const state = {
  course: null,
  students: [],
  present: new Set(),
  methods: [],
  metrics: null,
  toastTimer: null,
};

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
  toast: $("#toast"),
  dialog: $("#student-dialog"),
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
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
    button.innerHTML = `<span>${busyText}</span>`;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  } else {
    button.innerHTML = button.dataset.label || button.innerHTML;
    delete button.dataset.label;
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
  renderRecentCourses();
}

function renderRecentCourses() {
  const currentValue = state.course ? String(state.course.id) : "";
  const options = readRecentCourses().map((course) =>
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
        <button class="history-link" type="button" data-history-id="${id}">Estado e historial</button>
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

function updateSelectionControls() {
  const presentCount = state.present.size;
  $("#metric-present").textContent = presentCount;
  const fullyPresent = state.students.length > 0 && presentCount === state.students.length;
  elements.toggleAll.textContent = fullyPresent ? "Desmarcar todos" : "Marcar todos";
  elements.runButton.disabled = !state.course || presentCount === 0 || state.students.length === 0;
  elements.selectionNote.textContent = presentCount
    ? `${presentCount} estudiante${presentCount === 1 ? "" : "s"} presente${presentCount === 1 ? "" : "s"}.`
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
  renderStudents();
  if (state.metrics) renderMetrics(state.metrics);
}

async function loadCourse(courseId, { remember = true } = {}) {
  const id = Number(courseId);
  if (!Number.isInteger(id) || id <= 0) throw new Error("Escribe un ID de curso válido.");
  const course = await api(`/courses/${id}`);
  const [students, metrics] = await Promise.all([
    api(`/courses/${id}/students`),
    api(`/courses/${id}/fairness-metrics`).catch(() => null),
  ]);
  state.course = course;
  state.students = students;
  state.present = new Set();
  state.metrics = metrics;
  $("#metric-last-run").textContent = "—";
  elements.resultPanel.hidden = true;
  if (remember) saveRecentCourse(course);
  renderCourse();
}

async function refreshCourse() {
  if (!state.course) return;
  const currentPresent = new Set(state.present);
  const [students, metrics] = await Promise.all([
    api(`/courses/${state.course.id}/students`),
    api(`/courses/${state.course.id}/fairness-metrics`),
  ]);
  state.students = students;
  state.present = new Set(students.filter((student) => currentPresent.has(student.id)).map((student) => student.id));
  renderStudents();
  renderMetrics(metrics);
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

elements.studentList.addEventListener("change", (event) => {
  const input = event.target.closest("[data-attendance-id]");
  if (!input) return;
  const id = Number(input.dataset.attendanceId);
  if (input.checked) state.present.add(id);
  else state.present.delete(id);
  input.closest(".attendance-control").querySelector("span").textContent = input.checked ? "Presente" : "Ausente";
  updateSelectionControls();
});

elements.studentList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-history-id]");
  if (button) openStudentHistory(button.dataset.historyId);
});

elements.toggleAll.addEventListener("click", () => {
  const allPresent = state.students.length > 0 && state.present.size === state.students.length;
  state.present = allPresent ? new Set() : new Set(state.students.map((student) => student.id));
  renderStudents();
});

elements.methodSelect.addEventListener("change", updateMethodFields);
$("#slots-input").addEventListener("change", updateSelectionControls);

$("#selection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course || !state.present.size) return;
  const payload = {
    present_student_ids: [...state.present],
    k: Number($("#slots-input").value),
    method: elements.methodSelect.value,
  };
  if (payload.method === "weighted_softmax") payload.method_params = { tau: Number($("#tau-input").value) };
  const sessionLabel = $("#session-label").value.trim();
  if (sessionLabel) payload.session_label = sessionLabel;
  setBusy(elements.runButton, true, "Seleccionando...");
  try {
    const result = await api(`/courses/${state.course.id}/sessions/select`, {
      method: "POST", body: JSON.stringify(payload),
    });
    renderSelectionResult(result);
    await refreshCourse();
    notify("Decisión guardada correctamente.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(elements.runButton, false);
  }
});

$("#refresh-button").addEventListener("click", async () => {
  try {
    await refreshCourse();
    notify("Curso actualizado.");
  } catch (error) {
    notify(error.message, true);
  }
});

$("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) elements.dialog.close();
});

$("#today-label").textContent = new Intl.DateTimeFormat("es", { dateStyle: "long" }).format(new Date());
renderRecentCourses();
checkApi();
setInterval(checkApi, 30000);
api("/methods").then((response) => {
  state.methods = response.methods;
  renderMethodOptions();
}).catch((error) => notify(error.message, true));