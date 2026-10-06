const $ = (selector) => document.querySelector(selector);

const state = {
  course: null,
  students: [],
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