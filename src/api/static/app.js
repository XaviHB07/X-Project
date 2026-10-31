const $ = (selector) => document.querySelector(selector);

const state = {
  course: null,
  availableCourses: [],
  cycles: [],
  activeCycleId: null,
  authenticatedUser: null,
  viewAs: "administrador",
  teachers: [],
  studentAccounts: [],
  studentCourses: [],
  selectedStudentCourse: null,
  appView: "daily",
  courseView: "attendance",
  groupPlans: [],
  gradeCycleId: null,
  gradeCourseId: null,
  gradeMatrix: null,
  activeGroupPlanId: null,
  groupPlanDraft: null,
  groupPlanEditing: false,
  draftGroups: [],
  groupMaxSize: 4,
  draggedStudentId: null,
  session: null,
  proposal: null,
  sessionAttendanceSnapshot: new Set(),
  students: [],
  managementStudents: [],
  role: "profesor",
  present: new Set(),
  roundEligibleStudentIds: new Set(),
  lastSelectedStudentIds: new Set(),
  replacementEnabled: true,
  methods: [],
  metrics: null,
  participationPending: false,
  participationDecisionRunId: null,
  toastTimer: null,
  visualTimer: null,
  ballMachine: null,
  stageFlow: null,
};

const selectionAnimationDuration = 5500;
const visualPalette = ["#df795e", "#f3c86a", "#2f6fe0", "#8ec5f5", "#1e3a8a", "#e7a9a0"];

const elements = {
  apiDot: $("#api-dot"),
  apiStatus: $("#api-status"),
  loginScreen: $("#login-screen"),
  appShell: $("#app-shell"),
  loginForm: $("#login-form"),
  loginSubmit: $("#login-submit"),
  loginError: $("#login-error"),
  passwordChangeForm: $("#password-change-form"),
  passwordChangeError: $("#password-change-error"),
  passwordChangeSubmit: $("#password-change-submit"),
  courseTitle: $("#course-title"),
  courseMeta: $("#course-meta"),
  pageEyebrow: $("#page-eyebrow"),
  breadcrumbCourse: $("#breadcrumb-course"),
  todayLabel: $("#today-label"),
  emptyState: $("#empty-state"),
  workspace: $("#workspace"),
  academicSetupPage: $("#academic-setup-page"),
  cyclesSetupPage: $("#cycles-setup-page"),
  teacherManagementPage: $("#teacher-management-page"),
  courseCreationPage: $("#course-creation-page"),
  studentAccountsPage: $("#student-accounts-page"),
  studentPortal: $("#student-portal"),
  studentCoursesViewButton: $("#student-courses-view-button"),
  dailyViewButton: $("#daily-view-button"),
  gradesViewButton: $("#grades-view-button"),
  cyclesViewButton: $("#cycles-view-button"),
  teachersViewButton: $("#teachers-view-button"),
  studentAccountsViewButton: $("#student-accounts-view-button"),
  coursesViewButton: $("#courses-view-button"),
  enrollmentViewButton: $("#enrollment-view-button"),
  recentCourses: $("#recent-courses"),
  activeCycle: $("#active-cycle"),
  courseCreationCycle: $("#course-creation-cycle"),
  dailyCycle: $("#daily-cycle"),
  dailyCourse: $("#daily-course"),
  enrollmentCourse: $("#enrollment-course"),
  courseIdInput: $("#course-id-input"),
  studentList: $("#student-list"),
  listEmpty: $("#list-empty"),
  toggleAll: $("#toggle-all-button"),
  markSessionPresent: $("#mark-session-present-button"),
  startRound: $("#start-round-button"),
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
  temporaryPasswordDialog: $("#temporary-password-dialog"),
  sessionFormView: $("#session-form-view"),
  sessionActiveView: $("#session-active-view"),
  sessionTopic: $("#session-topic"),
  rosterFile: $("#roster-file"),
  importButton: $("#import-button"),
  importResult: $("#import-result"),
  attendanceView: $("#attendance-view"),
  managementView: $("#management-view"),
  setupCourseEmpty: $("#setup-course-empty"),
  attendanceTab: $("#attendance-tab"),
  participationsTab: $("#participations-tab"),
  groupsTab: $("#groups-tab"),
  gradesView: $("#grades-view"),
  gradeCycle: $("#grade-cycle"),
  gradeCourse: $("#grade-course"),
  gradeAnalysisNote: $("#grade-analysis-note"),
  gradeMatrixScroll: $("#grade-matrix-scroll"),
  gradeMatrixHead: $("#grade-matrix-head"),
  gradeMatrixBody: $("#grade-matrix-body"),
  gradeLegend: $("#grade-legend"),
  gradeDetailDialog: $("#grade-detail-dialog"),
  gradeDetailTitle: $("#grade-detail-title"),
  gradeDetailSubtitle: $("#grade-detail-subtitle"),
  gradeDetailSummary: $("#grade-detail-summary"),
  gradeDetailList: $("#grade-detail-list"),
  adminStudentList: $("#admin-student-list"),
  participationsView: $("#participations-view"),
  participationHistoryBody: $("#participation-history-body"),
  participationHistoryEmpty: $("#participation-history-empty"),
  groupsView: $("#groups-view"),
  groupPlanSelect: $("#group-plan-select"),
  groupEditor: $("#group-editor"),
  groupEditorNote: $("#group-editor-note"),
  editGroupPlanButton: $("#edit-group-plan-button"),
  cancelGroupEditsButton: $("#cancel-group-edits-button"),
  groupValidationMessage: $("#group-validation-message"),
  groupSetupChoices: $("#group-setup-choices"),
  groupGenerationForm: $("#group-generation-form"),
  autoGroupPlanName: $("#auto-group-plan-name"),
  groupMaxSize: $("#group-max-size"),
  groupPlanName: $("#group-plan-name"),
  manualGroupPlanName: $("#manual-group-plan-name"),
  manualGroupSetup: $("#manual-group-setup"),
  manualGroupCount: $("#manual-group-count"),
  manualGroupSizePreview: $("#manual-group-size-preview"),
  prepareManualGroupsButton: $("#prepare-manual-groups-button"),
  generateGroupsButton: $("#generate-groups-button"),
  createManualGroupsButton: $("#create-manual-groups-button"),
  addGroupButton: $("#add-group-button"),
  groupPlanNameField: $(".group-plan-name-field"),
  saveGroupPlanButton: $("#save-group-plan-button"),
  deleteGroupPlanButton: $("#delete-group-plan-button"),
  activeRole: $("#active-role"),
  sidebarUser: $("#sidebar-user"),
  teacherAssignmentCard: $("#teacher-assignment-card"),
  assignmentTeacher: $("#assignment-teacher"),
  assignmentCourseList: $("#assignment-course-list"),
  saveAssignmentsButton: $("#save-assignments-button"),
  createTeacherForm: $("#create-teacher-form"),
  createTeacherCourseList: $("#create-teacher-course-list"),
  createTeacherSubmit: $("#create-teacher-submit"),
  teacherDirectoryList: $("#teacher-directory-list"),
  teacherManagementHome: $("#teacher-management-home"),
  registerTeacherButton: $("#register-teacher-button"),
  cancelTeacherRegistration: $("#cancel-teacher-registration"),
  studentAccountList: $("#student-account-list"),
  studentAccountForm: $("#create-student-account-form"),
  studentCourseIndex: $("#student-course-index"),
  studentCourseDetail: $("#student-course-detail"),
  studentWeeks: $("#student-weeks"),
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
    if (response.status === 401 && !path.startsWith("/auth/")) {
      showLogin("La sesión expiró. Inicia sesión nuevamente.");
    }
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((item) => item.msg).join("; ")
      : body?.detail;
    throw new Error(detail || `Error ${response.status}: no se pudo completar la solicitud.`);
  }
  return body;
}

function showLogin(message = "") {
  state.authenticatedUser = null;
  state.course = null;
  state.availableCourses = [];
  state.cycles = [];
  state.teachers = [];
  state.students = [];
  state.managementStudents = [];
  state.session = null;
  state.proposal = null;
  state.groupPlans = [];
  state.activeGroupPlanId = null;
  state.groupPlanEditing = false;
  state.draftGroups = [];
  state.appView = "daily";
  elements.appShell.classList.remove("student-mode");
  elements.loginScreen.hidden = false;
  elements.appShell.hidden = true;
  $("#login-title").textContent = "Iniciar sesión";
  elements.loginForm.hidden = false;
  elements.passwordChangeForm.hidden = true;
  elements.passwordChangeError.hidden = true;
  elements.loginError.textContent = message;
  elements.loginError.hidden = !message;
  $("#login-password").value = "";
}

function showPasswordChange() {
  elements.loginScreen.hidden = false;
  elements.appShell.hidden = true;
  $("#login-title").textContent = "Configurar contraseña";
  elements.loginForm.hidden = true;
  elements.passwordChangeForm.hidden = false;
  elements.passwordChangeError.hidden = true;
  $("#new-password").value = "";
  $("#confirm-new-password").value = "";
  $("#new-password").focus();
}

async function loadAuthenticatedData(user) {
  if (user.must_change_password) {
    showPasswordChange();
    return;
  }
  state.authenticatedUser = user;
  state.viewAs = user.role === "administrador" ? "administrador" : "docente";
  if (user.role !== "estudiante") elements.activeRole.value = state.viewAs;
  elements.loginScreen.hidden = true;
  elements.appShell.hidden = false;
  if (user.role === "estudiante") {
    state.appView = "studentPortal";
    setAppView(state.appView);
    try {
      state.studentCourses = await api("/student/courses");
      renderStudentPortal();
    } catch (error) {
      notify(`No se pudieron cargar tus cursos: ${error.message}`, true);
    }
    return;
  }
  setAppView(state.appView);
  try {
    const [methods, courses, cycles] = await Promise.all([
      api("/methods"),
      api("/courses"),
      api("/cycles"),
    ]);
    state.methods = methods.methods;
    state.availableCourses = courses;
    state.cycles = cycles;
    renderMethodOptions();
    renderRecentCourses();
    renderCycles();
    if (user.role === "administrador") {
      [state.teachers, state.studentAccounts] = await Promise.all([
        api("/admin/teachers"),
        api("/admin/students"),
      ]);
      renderTeacherAssignments();
      renderStudentAccounts();
    } else {
      state.teachers = [];
      state.studentAccounts = [];
    }
    setAppView(state.appView);
  } catch (error) {
    notify(`No se pudieron cargar los datos de la cuenta: ${error.message}`, true);
  }
}

function renderTeacherAssignments() {
  if (!elements.assignmentTeacher || !elements.assignmentCourseList) return;
  const courseOptions = state.availableCourses.length
    ? state.availableCourses.map((course) => `
        <label class="assignment-course">
          <input type="checkbox" value="${course.id}" />
          <span>${escapeHtml(course.name)} <small>#${course.id}</small></span>
        </label>
      `).join("")
    : '<p class="form-note">Crea un curso antes de asignarlo a un docente.</p>';
  elements.createTeacherCourseList.innerHTML = courseOptions;
  elements.createTeacherSubmit.disabled = !state.availableCourses.length;
  filterCourseOptions($("#create-teacher-course-search"), elements.createTeacherCourseList);
  elements.teacherDirectoryList.innerHTML = state.teachers.length
    ? state.teachers.map((teacher) => {
        const courses = state.availableCourses
          .filter((course) => teacher.course_ids.includes(course.id))
          .map((course) => course.name);
        return `<details class="teacher-directory-item">
          <summary class="teacher-directory-summary">
            <span><strong>${escapeHtml(teacher.full_name)}</strong><small>${escapeHtml(teacher.username)}</small></span>
            <span class="teacher-details-toggle" aria-hidden="true">＋</span>
          </summary>
          <div class="teacher-directory-details">
            <span>Teléfono: ${escapeHtml(teacher.phone_number || "No registrado")}</span>
            <span>Correo: ${escapeHtml(teacher.email || "No registrado")}</span>
            <span>Cursos: ${escapeHtml(courses.join(", ") || "Sin cursos")}</span>
            <button class="button button-quiet" type="button" data-reset-teacher="${teacher.id}">
              Restablecer contraseña
            </button>
          </div>
        </details>`;
      }).join("")
    : '<p class="form-note">Todavía no hay docentes registrados.</p>';
  const selectedTeacherId = Number(elements.assignmentTeacher.value) || null;
  elements.assignmentTeacher.innerHTML = `<option value="">Selecciona un docente</option>${state.teachers
    .map((teacher) => `<option value="${teacher.id}">${escapeHtml(teacher.full_name)} · ${escapeHtml(teacher.username)}</option>`)
    .join("")}`;
  if (selectedTeacherId && state.teachers.some((teacher) => teacher.id === selectedTeacherId)) {
    elements.assignmentTeacher.value = String(selectedTeacherId);
  }
  const teacher = state.teachers.find(
    (item) => item.id === Number(elements.assignmentTeacher.value),
  );
  elements.assignmentCourseList.innerHTML = teacher
    ? state.availableCourses.map((course) => `
        <label class="assignment-course">
          <input type="checkbox" value="${course.id}" ${
            teacher.course_ids.includes(course.id) ? "checked" : ""
          } />
          <span>${escapeHtml(course.name)} <small>#${course.id}</small></span>
        </label>
      `).join("")
    : `<p class="form-note">${
        state.teachers.length
          ? "Selecciona un docente para configurar sus cursos."
          : "No hay cuentas activas con rol Docente. Agrega docentes en la base de datos."
      }</p>`;
  filterCourseOptions($("#assignment-course-search"), elements.assignmentCourseList);
  elements.saveAssignmentsButton.disabled = !teacher;
}

function renderStudentAccounts() {
  if (!elements.studentAccountList) return;
  $("#student-account-count").textContent = state.studentAccounts.length;
  elements.studentAccountList.innerHTML = state.studentAccounts.map((student) => {
    const courses = state.availableCourses
      .filter((course) => student.course_ids.includes(course.id))
      .map((course) => course.name);
    return `<article class="student-account-row">
      <div>
        <strong>${escapeHtml(student.full_name)}</strong>
        <span>${escapeHtml(student.email || "Sin correo")}</span>
        <span>Usuario: ${escapeHtml(student.username)}</span>
        <span>Cursos: ${escapeHtml(courses.join(", ") || "Sin matrículas")}</span>
      </div>
      <button class="button button-quiet" type="button" data-reset-student-account="${student.id}">
        Restablecer contraseña
      </button>
    </article>`;
  }).join("");
  $("#student-account-empty").hidden = state.studentAccounts.length > 0;
}

function renderStudentPortal() {
  const groups = new Map();
  state.studentCourses.forEach((course) => {
    const key = course.cycle_id ?? "uncycled";
    if (!groups.has(key)) groups.set(key, { name: course.cycle_name || "Sin ciclo académico", courses: [] });
    groups.get(key).courses.push(course);
  });
  elements.studentCourseIndex.innerHTML = [...groups.entries()].map(([cycleId, group]) => `
    <section class="student-cycle-group">
      <div class="student-cycle-heading">
        <h2>${escapeHtml(group.name)}</h2>
        <span>${group.courses.length} curso${group.courses.length === 1 ? "" : "s"}</span>
      </div>
      <div class="student-course-cards">
        ${group.courses.map((course) => `
          <button class="student-course-card" type="button" data-open-student-course="${course.course_id}">
            <span class="student-course-icon" aria-hidden="true">▦</span>
            <span><strong>${escapeHtml(course.course_name)}</strong><small>Ver sesiones por semana</small></span>
            <span aria-hidden="true">→</span>
          </button>
        `).join("")}
      </div>
    </section>
  `).join("");
  $("#student-courses-empty").hidden = state.studentCourses.length > 0;
  elements.studentCourseIndex.hidden = state.studentCourses.length === 0;
  elements.studentCourseDetail.hidden = true;
}

async function openStudentCourse(event) {
  const button = event.target.closest("[data-open-student-course]");
  if (!button) return;
  const course = state.studentCourses.find(
    (item) => item.course_id === Number(button.dataset.openStudentCourse),
  );
  if (!course) return;
  state.selectedStudentCourse = course;
  button.disabled = true;
  try {
    const response = await api(`/student/courses/${course.course_id}/weeks`);
    $("#student-detail-title").textContent = course.course_name;
    $("#student-detail-cycle").textContent = course.cycle_name || "Sin ciclo académico";
    renderStudentWeeks(response);
    elements.studentCourseIndex.hidden = true;
    elements.studentCourseDetail.hidden = false;
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderStudentWeeks(data) {
  elements.studentWeeks.innerHTML = data.weeks.map((week) => `
    <section class="student-week-card">
      <h3>Semana ${week.week_number}</h3>
      ${week.sessions.length
        ? `<ul>${week.sessions.map((session) => `
            <li>
              <strong>${escapeHtml(session.topic || session.label || "Sesión de clase")}</strong>
              <span>${session.session_date
                ? new Date(`${session.session_date}T00:00:00`).toLocaleDateString("es", { dateStyle: "long" })
                : "Sin fecha registrada"}</span>
            </li>`).join("")}</ul>`
        : '<p class="form-note">No hay sesiones registradas.</p>'}
    </section>
  `).join("");
  const unassigned = data.unassigned_sessions || [];
  const container = $("#student-unassigned-sessions");
  container.hidden = unassigned.length === 0;
  container.innerHTML = unassigned.length ? `
    <h3>Sesiones fuera de las 16 semanas</h3>
    <p class="form-note">Estas sesiones no tienen fecha o están fuera del periodo del ciclo.</p>
    <ul>${unassigned.map((session) => `
      <li>${escapeHtml(session.topic || session.label || "Sesión de clase")} · ${
        session.session_date
          ? new Date(`${session.session_date}T00:00:00`).toLocaleDateString("es")
          : "sin fecha"
      }</li>`).join("")}</ul>` : "";
}

function filterCourseOptions(searchInput, optionsContainer) {
  const search = searchInput.value.trim().toLocaleLowerCase();
  optionsContainer.querySelectorAll(".assignment-course").forEach((option) => {
    option.hidden = !option.textContent.toLocaleLowerCase().includes(search);
  });
}

function showTemporaryPassword(password, description, username = "") {
  $("#temporary-password-value").value = password;
  $("#temporary-password-description").textContent = description;
  $("#temporary-account-username").hidden = !username;
  $("#temporary-account-username").textContent = username ? `Usuario: ${username}` : "";
  elements.temporaryPasswordDialog.showModal();
}

function clearTemporaryPassword() {
  $("#temporary-password-value").value = "";
  $("#temporary-password-description").textContent = "";
  $("#temporary-account-username").textContent = "";
  $("#temporary-account-username").hidden = true;
}

function showTeacherManagementHome() {
  elements.createTeacherForm.hidden = true;
  elements.teacherManagementHome.hidden = false;
  elements.registerTeacherButton.hidden = false;
}

async function initializeAuthentication() {
  try {
    const user = await api("/auth/me");
    if (user.must_change_password) showPasswordChange();
    else await loadAuthenticatedData(user);
  } catch (error) {
    if (error.message !== "Inicia sesión para continuar.") {
      elements.loginError.textContent = "No se pudo verificar la sesión. Comprueba que la API esté disponible.";
      elements.loginError.hidden = false;
    }
    elements.loginScreen.hidden = false;
    elements.appShell.hidden = true;
  }
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
  renderTeacherAssignments();
}

function renderRecentCourses() {
  const currentValue = state.course ? String(state.course.id) : "";
  const coursesById = new Map(state.availableCourses.map((course) => [course.id, course]));
  const recentIds = readRecentCourses()
    .filter((course) => coursesById.has(course.id))
    .map((course) => course.id);
  const orderedCourses = [
    ...recentIds.map((id) => coursesById.get(id)),
    ...[...coursesById.values()].filter((course) => !recentIds.includes(course.id)),
  ];
  const options = orderedCourses.map((course) =>
    `<option value="${course.id}">${escapeHtml(course.name)} · #${course.id}</option>`,
  ).join("");
  elements.recentCourses.innerHTML = `<option value="">Selecciona un curso</option>${options}`;
  elements.recentCourses.value = currentValue;
  renderWorkCourseSelectors();
}

function renderCycles(preferredCycleId = state.activeCycleId) {
  const storedCycleId = Number(localStorage.getItem("aula-active-cycle"));
  const selectedCycleId = state.cycles.some((cycle) => cycle.id === preferredCycleId)
    ? preferredCycleId
    : state.cycles.some((cycle) => cycle.id === storedCycleId)
      ? storedCycleId
      : state.cycles[0]?.id || null;
  state.activeCycleId = selectedCycleId;
  elements.activeCycle.innerHTML = `<option value="">Selecciona un ciclo</option>${state.cycles
    .map((cycle) => `<option value="${cycle.id}">${escapeHtml(cycle.name)}</option>`)
    .join("")}`;
  elements.activeCycle.value = selectedCycleId ? String(selectedCycleId) : "";
  elements.courseCreationCycle.innerHTML = `<option value="">Selecciona un ciclo</option>${state.cycles
    .map((cycle) => `<option value="${cycle.id}">${escapeHtml(cycle.name)}</option>`)
    .join("")}`;
  if (!state.cycles.some((cycle) => cycle.id === Number(elements.courseCreationCycle.value))) {
    elements.courseCreationCycle.value = selectedCycleId ? String(selectedCycleId) : "";
  }
  const createCourseButton = $("#create-course-form button[type=submit]");
  createCourseButton.disabled = !Number(elements.courseCreationCycle.value);
  $("#course-cycle-hint").hidden = Boolean(Number(elements.courseCreationCycle.value));
  $("#cycle-count").textContent = state.cycles.length;
  renderCourseCreation();
  $("#cycle-list").innerHTML = state.cycles.map((cycle) => `
    <article class="cycle-row">
      <span class="cycle-mark" aria-hidden="true">◷</span>
      <div>
        <strong>${escapeHtml(cycle.name)}</strong>
        <span>Creado ${new Date(cycle.created_at).toLocaleDateString("es")}</span>
      </div>
      <label class="cycle-start-control">
        <span>Inicio del ciclo</span>
        <input class="field" type="date" data-cycle-start="${cycle.id}" value="${cycle.starts_on || ""}" />
      </label>
      <button class="button button-quiet" type="button" data-save-cycle-start="${cycle.id}">Guardar fecha</button>
    </article>
  `).join("");
  $("#cycle-list-empty").hidden = state.cycles.length > 0;
  renderTeacherAssignments();
  renderWorkCourseSelectors();
  if (selectedCycleId) localStorage.setItem("aula-active-cycle", String(selectedCycleId));
  if (state.appView === "cycles") setAppView("cycles");
}

function renderCourseCreation() {
  const selectedCycleId = Number(elements.courseCreationCycle.value) || null;
  const cycleById = new Map(state.cycles.map((cycle) => [cycle.id, cycle.name]));
  const courses = state.availableCourses.filter(
    (course) => !selectedCycleId || course.cycle_id === selectedCycleId,
  );
  $("#course-creation-list").innerHTML = courses.length
    ? courses.map((course) => `
        <article class="course-creation-row">
          <strong>${escapeHtml(course.name)}</strong>
          <span>${escapeHtml(cycleById.get(course.cycle_id) || "Sin ciclo")} · #${course.id}</span>
        </article>
      `).join("")
    : '<p class="setup-empty">No hay cursos en este ciclo todavía.</p>';
  $("#course-creation-count").textContent = courses.length;
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
  updateReplacementStatusFromEligibility();
  const students = state.students;
  $("#roster-count").textContent = students.length;
  $("#metric-students").textContent = students.length;
  elements.studentList.innerHTML = students.map((student, index) => {
    const id = Number(student.id);
    const roundEligible = state.roundEligibleStudentIds.has(id);
    const initial = (student.display_name || "?").trim().charAt(0).toUpperCase() || "?";
    return `<article class="student-row roster-student-row" style="animation-delay:${Math.min(index * 22, 220)}ms">
      <div class="student-identity">
        <span class="student-avatar" aria-hidden="true">${escapeHtml(initial)}</span>
        <div class="student-name-block">
          <div class="student-name">${escapeHtml(student.display_name)}</div>
          <div class="student-meta">${escapeHtml(student.external_ref)} · ID ${id}</div>
        </div>
      </div>
      <div class="student-actions">
        <label class="attendance-control">
          <input type="checkbox" data-round-id="${id}" ${roundEligible ? "checked" : ""} aria-label="Incluir a ${escapeHtml(student.display_name)} en la ronda" />
          <span>Presente</span>
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
  const rosterImported = Boolean(state.course?.roster_imported);
  $("#roster-import-note").textContent = rosterImported
    ? "La lista inicial de este curso ya fue cargada para el ciclo. Puedes seguir matriculando, editando o retirando estudiantes individualmente."
    : state.course?.cycle_id
      ? "El Excel admite NRO, CÓDIGO, ALUMNO, ESP, CONDICION, CORREO UNI y VECES REPETIDAS. El correo enlaza o crea la cuenta del alumno. La lista se carga una sola vez por ciclo."
      : "Curso histórico sin ciclo académico: conserva el comportamiento de carga anterior.";
  elements.importButton.disabled = rosterImported || !elements.rosterFile.files[0];
  elements.adminStudentList.innerHTML = students.map((student) => {
    const id = Number(student.id);
    const details = [
      student.roster_number && `NRO ${student.roster_number}`,
      student.specialty && `ESP ${student.specialty}`,
      student.student_condition,
      student.times_repeated && `Veces repetidas: ${student.times_repeated}`,
    ].filter(Boolean).map(escapeHtml).join(" · ");
    const contact = [student.phone_number, student.email].filter(Boolean).map(escapeHtml).join(" · ");
    return `<article class="student-row admin-student-row">
      <div class="student-identity">
        <span class="student-avatar" aria-hidden="true">${escapeHtml((student.display_name || "?").trim().charAt(0).toUpperCase() || "?")}</span>
        <div class="student-name-block">
          <div class="student-name">${escapeHtml(student.display_name)}${student.active ? "" : ' <span class="inactive-badge">Retirado</span>'}</div>
          <div class="student-meta">${escapeHtml(student.external_ref)} · ${contact || "Sin datos de contacto"}${details ? ` · ${details}` : ""}</div>
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
  const eligibleCount = roundEligibleStudents().length;
  $("#metric-present").textContent = presentCount;
  const allSelected = state.students.length > 0 && eligibleCount === state.students.length;
  elements.toggleAll.textContent = allSelected ? "Desmarcar todos" : "Marcar todos";
  elements.markSessionPresent.disabled = !state.session || state.students.length === 0;
  elements.startRound.disabled = !state.course || state.students.length === 0;
  elements.runButton.disabled = !state.course || eligibleCount === 0 || state.students.length === 0 || state.participationPending;
  const replacementButton = $("#replacement-toggle-button");
  replacementButton.disabled = state.lastSelectedStudentIds.size === 0;
  replacementButton.setAttribute("aria-pressed", String(state.replacementEnabled));
  replacementButton.textContent = `Reposición: ${state.replacementEnabled ? "Sí" : "No"}`;
  $("#replacement-note").textContent = state.lastSelectedStudentIds.size
    ? "Marca o desmarca a la última selección para próximas rondas."
    : "Disponible después de una ronda.";
  elements.selectionNote.textContent = eligibleCount
    ? `${eligibleCount} estudiante${eligibleCount === 1 ? "" : "s"} marcado${eligibleCount === 1 ? "" : "s"} para esta ronda. La asistencia se registra por separado.`
    : "Marca estudiantes en la lista para habilitar la selección.";
  const slots = $("#slots-input");
  slots.max = String(Math.max(1, eligibleCount));
  if (eligibleCount && Number(slots.value) > eligibleCount) slots.value = String(eligibleCount);
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
  renderRecentCourses();
  setAppView(state.appView);
  elements.managementView.hidden = !isLoaded;
  elements.setupCourseEmpty.hidden = isLoaded;
  $("#management-title").textContent = course ? `Matrícula · ${course.name}` : "Matrícula inicial";
  if (!isLoaded) return;
  setCourseView(state.courseView);
  renderSessionBox();
  renderStudents();
  renderManagementStudents();
  renderGroupPlans();
  if (state.metrics) renderMetrics(state.metrics);
}

function clearCourseSelection() {
  state.course = null;
  state.students = [];
  state.managementStudents = [];
  state.session = null;
  state.sessionAttendanceSnapshot = new Set();
  state.proposal = null;
  state.groupPlans = [];
  state.activeGroupPlanId = null;
  state.groupPlanEditing = false;
  state.draftGroups = [];
  state.present = new Set();
  state.roundEligibleStudentIds = new Set();
  state.lastSelectedStudentIds = new Set();
  state.metrics = null;
  renderCourse();
}

function renderWorkCourseSelectors() {
  const cycleOptions = `<option value="">Selecciona un ciclo</option>${state.cycles
    .map((cycle) => `<option value="${cycle.id}">${escapeHtml(cycle.name)}</option>`)
    .join("")}`;
  elements.dailyCycle.innerHTML = cycleOptions;
  elements.dailyCycle.value = state.activeCycleId ? String(state.activeCycleId) : "";

  const filteredCourses = state.activeCycleId
    ? state.availableCourses.filter((course) => course.cycle_id === state.activeCycleId)
    : state.availableCourses;
  const courseOptions = `<option value="">Selecciona un curso</option>${filteredCourses
    .map((course) => `<option value="${course.id}">${escapeHtml(course.name)} · #${course.id}</option>`)
    .join("")}`;
  elements.dailyCourse.innerHTML = courseOptions;
  elements.enrollmentCourse.innerHTML = courseOptions;
  const selectedCourseId = filteredCourses.some((course) => course.id === state.course?.id)
    ? String(state.course.id)
    : "";
  elements.dailyCourse.value = selectedCourseId;
  elements.enrollmentCourse.value = selectedCourseId;
  renderGradeSelectors();
}

function renderGradeSelectors() {
  elements.gradeCycle.innerHTML = `<option value="">Selecciona un ciclo</option>${state.cycles
    .map((cycle) => `<option value="${cycle.id}">${escapeHtml(cycle.name)}</option>`).join("")}`;
  elements.gradeCycle.value = state.gradeCycleId ? String(state.gradeCycleId) : "";
  const courses = state.gradeCycleId
    ? state.availableCourses.filter((course) => course.cycle_id === state.gradeCycleId)
    : [];
  elements.gradeCourse.innerHTML = `<option value="">Selecciona un curso</option>${courses
    .map((course) => `<option value="${course.id}">${escapeHtml(course.name)} · #${course.id}</option>`).join("")}`;
  elements.gradeCourse.value = state.gradeCourseId ? String(state.gradeCourseId) : "";
}

function formatGradeRange(startOn, endOn) {
  return `${formatDay(startOn)} - ${formatDay(endOn)}`;
}

function gradeCellStyle(value) {
  if (value === null || value === undefined) return "";
  const ratio = Math.max(0, Math.min(1, Number(value) / 5));
  const hue = 6 + ratio * 204;
  return `background: hsl(${hue} 72% ${87 - ratio * 17}%);`;
}

function renderGradeMatrix(matrix) {
  elements.gradeMatrixHead.innerHTML = `<tr><th class="grade-student-heading">Estudiante</th>${matrix.weeks
    .map((week) => `<th><span>${week.label}</span><small>${formatGradeRange(week.start_on, week.end_on)}</small></th>`).join("")}</tr>`;
  elements.gradeMatrixBody.innerHTML = matrix.students.map((student) => `
    <tr>
      <th class="grade-student-name"><span>${escapeHtml(student.display_name)}</span><small>${escapeHtml(student.external_ref)}</small></th>
      ${student.averages.map((value, index) => value === null
        ? '<td class="grade-missing" title="Sin participación">-</td>'
        : `<td class="grade-value" style="${gradeCellStyle(value)}"><button class="grade-cell-button" type="button" data-grade-student="${student.student_id}" data-grade-week="${index + 1}" title="Ver participaciones de la Semana ${index + 1}">${Number(value).toFixed(2)}</button></td>`).join("")}
    </tr>`).join("");
  elements.gradeMatrixScroll.hidden = false;
  elements.gradeLegend.hidden = false;
}

function renderGradeDetails(details) {
  elements.gradeDetailTitle.textContent = details.student_name;
  elements.gradeDetailSubtitle.textContent =
    `Semana ${details.week} · ${formatGradeRange(details.start_on, details.end_on)}`;
  elements.gradeDetailSummary.innerHTML =
    `<strong>${details.total}</strong><span>participación${details.total === 1 ? "" : "es"} registradas</span>`;
  elements.gradeDetailList.innerHTML = details.participations.map((item, index) => `
    <article class="grade-detail-card">
      <div class="grade-detail-card-heading">
        <h3>Participación ${index + 1}</h3>
        <time datetime="${item.occurred_at}">${escapeHtml(formatDate(item.occurred_at))}</time>
      </div>
      <dl class="grade-detail-fields">
        <div><dt>Pregunta</dt><dd>${escapeHtml(item.question || "—")}</dd></div>
        <div><dt>Nota (0 a 5)</dt><dd>${Number(item.score).toLocaleString("es", { maximumFractionDigits: 2 })}</dd></div>
        <div><dt>Comentario</dt><dd>${escapeHtml(item.comment || "—")}</dd></div>
        <div><dt>Presente</dt><dd><span class="attendance-badge ${item.present ? "is-present" : "is-absent"}">${item.present ? "Sí" : "No"}</span></dd></div>
      </dl>
    </article>`).join("");
  elements.gradeDetailDialog.showModal();
}

async function loadGradeDetails(studentId, week) {
  const cycleId = Number(elements.gradeCycle.value) || state.gradeCycleId;
  const courseId = state.gradeMatrix?.course_id;
  if (!cycleId || !courseId) return;
  elements.gradeDetailTitle.textContent = "Cargando detalle...";
  elements.gradeDetailSubtitle.textContent = "";
  elements.gradeDetailSummary.innerHTML = "";
  elements.gradeDetailList.innerHTML = "";
  elements.gradeDetailDialog.showModal();
  try {
    const details = await api(
      `/courses/${courseId}/weekly-grades/details?cycle_id=${cycleId}&student_id=${studentId}&week=${week}`,
    );
    renderGradeDetails(details);
  } catch (error) {
    elements.gradeDetailDialog.close();
    notify(error.message, true);
  }
}

async function loadGradeMatrix() {
  const cycleId = Number(elements.gradeCycle.value) || state.gradeCycleId || null;
  const selectedCourseId = Number(elements.gradeCourse.value) || null;
  const activeCourseId = Number(elements.recentCourses.value)
    || Number(elements.dailyCourse.value)
    || state.course?.id
    || null;
  const activeCourse = state.availableCourses.find(
    (course) => course.id === activeCourseId && course.cycle_id === cycleId,
  );
  const courseId = selectedCourseId || activeCourse?.id || null;
  state.gradeCycleId = cycleId;
  state.gradeCourseId = selectedCourseId;
  renderGradeSelectors();
  elements.gradeMatrixScroll.hidden = true;
  elements.gradeLegend.hidden = true;
  if (!cycleId || !courseId) {
    elements.gradeAnalysisNote.textContent = cycleId
      ? "Selecciona un curso para mostrar el análisis."
      : "Selecciona un ciclo y un curso para mostrar el análisis.";
    return;
  }
  elements.gradeAnalysisNote.textContent = "Cargando análisis semanal...";
  try {
    state.gradeMatrix = await api(`/courses/${courseId}/weekly-grades?cycle_id=${cycleId}`);
    renderGradeMatrix(state.gradeMatrix);
    elements.gradeAnalysisNote.textContent = `${state.gradeMatrix.students.length} estudiantes activos · escala de 0 a 5`;
  } catch (error) {
    elements.gradeAnalysisNote.textContent = error.message;
  }
}

function setAppView(view) {
  const previousView = state.appView;
  const isStudent = state.authenticatedUser?.role === "estudiante";
  elements.appShell.classList.toggle("student-mode", isStudent);
  if (isStudent) {
    if (previousView !== "studentPortal") window.scrollTo(0, 0);
    state.appView = "studentPortal";
    elements.studentPortal.hidden = false;
    document.querySelector(".app-navigation").hidden = false;
    elements.studentCoursesViewButton.hidden = false;
    elements.studentCoursesViewButton.classList.add("active");
    elements.studentCoursesViewButton.setAttribute("aria-current", "page");
    [
      elements.dailyViewButton,
      elements.gradesViewButton,
      elements.cyclesViewButton,
      elements.teachersViewButton,
      elements.studentAccountsViewButton,
      elements.coursesViewButton,
      elements.enrollmentViewButton,
    ].forEach((button) => {
      button.hidden = true;
      button.classList.remove("active");
      button.removeAttribute("aria-current");
    });
    elements.cyclesSetupPage.hidden = true;
    elements.teacherManagementPage.hidden = true;
    elements.studentAccountsPage.hidden = true;
    elements.courseCreationPage.hidden = true;
    elements.academicSetupPage.hidden = true;
    $("#daily-course-picker").hidden = true;
    elements.workspace.hidden = true;
    elements.emptyState.hidden = true;
    $("#refresh-button").hidden = true;
    document.querySelector(".topbar").hidden = true;
    document.querySelector(".page-heading").hidden = true;
    document.querySelector(".sidebar-section").hidden = true;
    document.querySelector(".sidebar-role").hidden = true;
    document.querySelector(".sidebar-bottom").hidden = true;
    elements.sidebarUser.textContent = `${state.authenticatedUser.full_name} · Estudiante`;
    return;
  }
  elements.studentPortal.hidden = true;
  elements.studentCoursesViewButton.hidden = true;
  elements.studentCoursesViewButton.classList.remove("active");
  elements.studentCoursesViewButton.removeAttribute("aria-current");
  elements.dailyViewButton.hidden = false;
  elements.enrollmentViewButton.hidden = false;
  document.querySelector(".topbar").hidden = false;
  document.querySelector(".page-heading").hidden = false;
  document.querySelector(".app-navigation").hidden = false;
  document.querySelector(".sidebar-section").hidden = false;
  document.querySelector(".sidebar-bottom").hidden = false;
  $("#refresh-button").hidden = false;
  const isAdminView = state.authenticatedUser?.role === "administrador"
    && state.viewAs === "administrador";
  const teacherView = state.authenticatedUser?.role === "docente" || state.viewAs === "docente";
  if (!teacherView && (view === "daily" || view === "grades")) {
    view = "cycles";
  }
  if (!isAdminView && ["cycles", "teachers", "studentAccounts", "createCourse"].includes(view)) {
    view = "enrollment";
  }
  if (previousView !== view) window.scrollTo(0, 0);
  state.appView = view;
  const cycles = view === "cycles";
  const teachers = view === "teachers";
  const studentAccounts = view === "studentAccounts";
  const createCourse = view === "createCourse";
  const enrollment = view === "enrollment";
  const daily = view === "daily";
  const grades = view === "grades";
  const course = state.course;
  const cycle = state.cycles.find((item) => item.id === course?.cycle_id);
  elements.cyclesSetupPage.hidden = !cycles;
  elements.teacherManagementPage.hidden = !teachers;
  elements.studentAccountsPage.hidden = !studentAccounts;
  elements.courseCreationPage.hidden = !createCourse;
  if (createCourse) renderCourseCreation();
  elements.academicSetupPage.hidden = !enrollment;
  $("#daily-course-picker").hidden = !daily;
  elements.workspace.hidden = !daily || !course;
  elements.gradesView.hidden = !grades;
  elements.emptyState.hidden = !daily || Boolean(course);
  $("#refresh-button").disabled = !daily || !course;
  elements.dailyViewButton.classList.toggle("active", daily);
  elements.gradesViewButton.classList.toggle("active", grades);
  elements.cyclesViewButton.classList.toggle("active", cycles);
  elements.teachersViewButton.classList.toggle("active", teachers);
  elements.studentAccountsViewButton.classList.toggle("active", studentAccounts);
  elements.coursesViewButton.classList.toggle("active", createCourse);
  elements.enrollmentViewButton.classList.toggle("active", enrollment);
  [
    elements.dailyViewButton,
    elements.gradesViewButton,
    elements.cyclesViewButton,
    elements.teachersViewButton,
    elements.studentAccountsViewButton,
    elements.coursesViewButton,
    elements.enrollmentViewButton,
  ]
    .forEach((button) => button.removeAttribute("aria-current"));
  const activeButton = daily
    ? elements.dailyViewButton
    : grades
      ? elements.gradesViewButton
    : cycles
      ? elements.cyclesViewButton
      : teachers
        ? elements.teachersViewButton
        : studentAccounts
          ? elements.studentAccountsViewButton
          : createCourse
            ? elements.coursesViewButton
            : elements.enrollmentViewButton;
  activeButton.setAttribute("aria-current", "page");
  elements.dailyViewButton.hidden = !teacherView;
  elements.gradesViewButton.hidden = !teacherView;
  elements.cyclesViewButton.hidden = !isAdminView;
  elements.teachersViewButton.hidden = !isAdminView;
  elements.studentAccountsViewButton.hidden = !isAdminView;
  elements.coursesViewButton.hidden = !isAdminView;
  elements.activeRole.closest(".sidebar-role").hidden = state.authenticatedUser?.role !== "administrador";
  elements.studentAccountForm.hidden = !isAdminView;
  $("#create-cycle-form button[type=submit]").disabled = !isAdminView;
  $("#create-course-form button[type=submit]").disabled =
    !isAdminView || !Number(elements.courseCreationCycle.value);
  elements.participationsTab.hidden = teacherView;
  elements.sidebarUser.textContent = `${state.authenticatedUser?.full_name || ""} · ${
    state.authenticatedUser?.role === "administrador" ? "Administrador" : "Docente"
  }`;
  if (grades) loadGradeMatrix();
  if (cycles) {
    elements.courseTitle.textContent = "Ciclos académicos";
    elements.pageEyebrow.firstChild.textContent = "PERIODOS ACADÉMICOS ";
    elements.courseMeta.textContent = `${state.cycles.length} ciclo${state.cycles.length === 1 ? "" : "s"} registrado${state.cycles.length === 1 ? "" : "s"}.`;
    elements.breadcrumbCourse.textContent = "CICLOS";
  } else if (enrollment) {
    elements.courseTitle.textContent = "Matrícula de estudiantes";
    elements.pageEyebrow.firstChild.textContent = "CONFIGURACIÓN DE CURSOS ";
    elements.courseMeta.textContent = course
      ? `${course.name} · Curso #${course.id}${cycle ? ` · Ciclo ${cycle.name}` : ""}`
      : "Selecciona un ciclo y un curso para administrar su lista.";
    elements.breadcrumbCourse.textContent = "MATRÍCULA";
  } else if (teachers) {
    elements.courseTitle.textContent = "Gestión de docentes";
    elements.pageEyebrow.firstChild.textContent = "ADMINISTRACIÓN ";
    elements.courseMeta.textContent = `${state.teachers.length} docente${state.teachers.length === 1 ? "" : "s"} registrado${state.teachers.length === 1 ? "" : "s"}.`;
    elements.breadcrumbCourse.textContent = "DOCENTES";
  } else if (studentAccounts) {
    elements.courseTitle.textContent = "Cuentas de alumnos";
    elements.pageEyebrow.firstChild.textContent = "USUARIOS ESTUDIANTILES ";
    elements.courseMeta.textContent = `${state.studentAccounts.length} cuenta${state.studentAccounts.length === 1 ? "" : "s"} registrada${state.studentAccounts.length === 1 ? "" : "s"}.`;
    elements.breadcrumbCourse.textContent = "ALUMNOS";
  } else if (createCourse) {
    elements.courseTitle.textContent = "Crear cursos";
    elements.pageEyebrow.firstChild.textContent = "ADMINISTRACIÓN ";
    elements.courseMeta.textContent = "Crea cursos y asígnalos a un ciclo académico.";
    elements.breadcrumbCourse.textContent = "CURSOS";
  } else if (grades) {
    elements.courseTitle.textContent = "Análisis de notas";
    elements.pageEyebrow.firstChild.textContent = "SEGUIMIENTO ACADÉMICO ";
    elements.courseMeta.textContent = "Consulta el promedio semanal de los estudiantes por ciclo y curso.";
    elements.breadcrumbCourse.textContent = "NOTAS";
  } else {
    elements.courseTitle.textContent = course?.name || "Panel de selección";
    elements.pageEyebrow.firstChild.textContent = "SELECCIÓN EQUITATIVA ";
    elements.courseMeta.textContent = course
      ? `Curso #${course.id}${cycle ? ` · Ciclo ${cycle.name}` : ""}`
      : "Selecciona un curso o créalo desde Matrícula de estudiantes para comenzar.";
    elements.breadcrumbCourse.textContent = course ? `CURSO #${course.id}` : "SIN CURSO";
  }
}

function setCourseView(view) {
  if (
    (state.authenticatedUser?.role === "docente" || state.viewAs === "docente")
    && view === "participations"
  ) {
    view = "attendance";
  }
  state.courseView = view;
  const attendance = view === "attendance";
  const participations = view === "participations";
  const groups = view === "groups";
  elements.attendanceView.hidden = participations || groups;
  elements.participationsView.hidden = !participations;
  elements.groupsView.hidden = !groups;
  elements.attendanceTab.classList.toggle("active", attendance);
  elements.participationsTab.classList.toggle("active", participations);
  elements.groupsTab.classList.toggle("active", groups);
  elements.attendanceTab.setAttribute("aria-selected", String(attendance));
  elements.participationsTab.setAttribute("aria-selected", String(participations));
  elements.groupsTab.setAttribute("aria-selected", String(groups));
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
  if (state.participationPending) {
    throw new Error("Guarda la participación pendiente antes de cargar otro curso.");
  }
  const course = await api(`/courses/${id}`);
  const [students, managementStudents, metrics] = await Promise.all([
    api(`/courses/${id}/students`),
    api(`/courses/${id}/students?include_inactive=true`),
    api(`/courses/${id}/fairness-metrics`).catch(() => null),
  ]);
  state.course = course;
  state.course = course;
  if (course.cycle_id !== null && course.cycle_id !== undefined) {
    renderCycles(course.cycle_id);
  }
  state.students = students;
  state.groupPlans = [];
  state.activeGroupPlanId = null;
  state.groupPlanEditing = false;
  state.draftGroups = [];
  state.managementStudents = managementStudents;
  state.present = new Set();
  state.roundEligibleStudentIds = new Set(students.map((student) => Number(student.id)));
  state.lastSelectedStudentIds = new Set();
  state.replacementEnabled = true;
  state.session = null;
  state.sessionAttendanceSnapshot = new Set();
  state.proposal = null;
  state.metrics = metrics;
  state.participationPending = false;
  state.participationDecisionRunId = null;
  $("#metric-last-run").textContent = "—";
  elements.resultPanel.hidden = true;
  elements.importResult.hidden = true;
  elements.sessionTopic.value = "";
  if (remember) saveRecentCourse(course);
  renderCourse();
  loadProposal();
  loadGroupPlans();
}

async function refreshCourse() {
  if (!state.course) return;
  const currentPresent = new Set(state.present);
  const currentRoundEligible = new Set(state.roundEligibleStudentIds);
  const knownStudentIds = new Set(state.students.map((student) => Number(student.id)));
  const [course, students, managementStudents, metrics] = await Promise.all([
    api(`/courses/${state.course.id}`),
    api(`/courses/${state.course.id}/students`),
    api(`/courses/${state.course.id}/students?include_inactive=true`),
    api(`/courses/${state.course.id}/fairness-metrics`),
  ]);
  state.students = students;
  state.managementStudents = managementStudents;
  state.roundEligibleStudentIds = new Set(students
    .filter((student) => currentRoundEligible.has(Number(student.id)) || !knownStudentIds.has(Number(student.id)))
    .map((student) => Number(student.id)));
  if (state.session) {
    await syncSession();
  } else {
    state.present = new Set(students.filter((student) => currentPresent.has(student.id)).map((student) => student.id));
  }
  renderSessionBox();
  renderStudents();
  renderManagementStudents();
  renderMetrics(metrics);
  if (state.activeGroupPlanId) {
    ensureDraftRosterCoverage();
    renderGroupEditor();
  }
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

async function loadParticipationHistory() {
  if (!state.course) return;
  elements.participationHistoryEmpty.textContent = "Cargando historial…";
  elements.participationHistoryEmpty.hidden = false;
  try {
    const records = await api(`/courses/${state.course.id}/participations`);
    elements.participationHistoryBody.innerHTML = records.map((record) => `
      <tr>
        <td>${escapeHtml(record.external_ref)}</td>
        <td>${escapeHtml(record.display_name)}</td>
        <td class="participation-note">${escapeHtml(record.question || "—")}</td>
        <td>${Number(record.score).toLocaleString("es", { maximumFractionDigits: 2 })}</td>
        <td class="participation-note">${escapeHtml(record.comment || "—")}</td>
        <td>${escapeHtml(formatDate(record.created_at))}</td>
        <td><span class="attendance-badge ${record.present ? "is-present" : "is-absent"}">${record.present ? "Presente" : "Ausente"}</span></td>
      </tr>`).join("");
    elements.participationHistoryEmpty.hidden = records.length > 0;
    if (!records.length) elements.participationHistoryEmpty.textContent = "Todavía no hay participaciones registradas.";
  } catch (error) {
    elements.participationHistoryBody.innerHTML = "";
    elements.participationHistoryEmpty.textContent = error.message;
    elements.participationHistoryEmpty.hidden = false;
  }
}

function ensureDraftRosterCoverage() {
  const activeIds = new Set(state.students.map((student) => Number(student.id)));
  state.draftGroups.forEach((group) => {
    group.student_ids = group.student_ids.filter((id) => activeIds.has(Number(id)));
  });
}

function getUnassignedStudents() {
  const assignedIds = new Set(state.draftGroups.flatMap((group) => group.student_ids.map(Number)));
  return state.students.filter((student) => !assignedIds.has(Number(student.id)));
}

function moveStudentToGroup(studentId, targetIndex) {
  const sourceIndex = state.draftGroups.findIndex((group) => group.student_ids.includes(studentId));
  const isUnassigned = getUnassignedStudents().some((student) => Number(student.id) === studentId);
  if (
    (sourceIndex < 0 && !isUnassigned)
    || targetIndex < -1
    || targetIndex >= state.draftGroups.length
  ) return false;
  if (sourceIndex === targetIndex) return true;
  if (sourceIndex >= 0) {
    state.draftGroups[sourceIndex].student_ids =
      state.draftGroups[sourceIndex].student_ids.filter((id) => Number(id) !== studentId);
  }
  if (targetIndex >= 0) state.draftGroups[targetIndex].student_ids.push(studentId);
  return true;
}

function groupPlanValidation() {
  const maxSize = Number(elements.groupMaxSize.value);
  if (!Number.isInteger(maxSize) || maxSize < 1 || maxSize > 1000) {
    return "El máximo por grupo debe ser entre 1 y 1000.";
  }
  if (!state.draftGroups.length || state.draftGroups.length > 100) {
    return "La propuesta debe tener entre 1 y 100 grupos.";
  }
  if (state.groupPlanEditing && !elements.groupPlanName.value.trim()) {
    return "Asigna un nombre a la propuesta.";
  }
  const names = state.draftGroups.map((group) => group.name.trim().toLocaleLowerCase());
  if (names.some((name) => !name) || new Set(names).size !== names.length) {
    return "Completa los nombres de los grupos sin repetirlos.";
  }
  const assignedIds = state.draftGroups.flatMap((group) => group.student_ids.map(Number));
  const activeIds = state.students.map((student) => Number(student.id));
  if (new Set(assignedIds).size !== assignedIds.length || assignedIds.some((id) => !activeIds.includes(id))) {
    return "Cada estudiante solo puede estar una vez y debe estar matriculado activamente.";
  }
  return "";
}

function renderGroupEditor() {
  const editable = state.groupPlanEditing;
  const studentsById = new Map(state.students.map((student) => [Number(student.id), student]));
  elements.groupEditor.innerHTML = state.draftGroups.map((group, groupIndex) => {
    const members = group.student_ids.map((studentId) => studentsById.get(Number(studentId))).filter(Boolean);
    const memberRows = members.length
      ? members.map((student) => `
          <div class="group-member-row" ${editable ? `draggable="true" data-group-drag="${student.id}"` : ""}>
            <span class="group-member-name">${escapeHtml(student.display_name)}<small>${escapeHtml(student.external_ref)}</small></span>
            ${editable ? `<select class="field" data-group-student="${student.id}" aria-label="Grupo de ${escapeHtml(student.display_name)}">
              <option value="-1">Sin grupo</option>
              ${state.draftGroups.map((option, optionIndex) => `
                <option value="${optionIndex}" ${optionIndex === groupIndex ? "selected" : ""}>${escapeHtml(option.name)}</option>
              `).join("")}
            </select>` : ""}
          </div>`).join("")
      : `<p class="group-empty">${editable
        ? "Sin estudiantes. Puedes asignarlos desde el carril sin grupo."
        : "Sin estudiantes."}</p>`;
    return `
      <section class="group-card" data-group-drop="${groupIndex}">
        <div class="group-card-heading">
          ${editable
            ? `<input class="field" type="text" maxlength="100" value="${escapeHtml(group.name)}" data-group-name="${groupIndex}" aria-label="Nombre del grupo ${groupIndex + 1}" />`
            : `<h3>${escapeHtml(group.name)}</h3>`}
          <span>${members.length} estudiante${members.length === 1 ? "" : "s"}</span>
          ${editable ? `<button class="icon-button group-remove-button" type="button" data-remove-group="${groupIndex}" aria-label="Eliminar grupo" title="Eliminar grupo">×</button>` : ""}
        </div>
        <div class="group-member-list">${memberRows}</div>
      </section>`;
  }).join("") + (state.activeGroupPlanId && getUnassignedStudents().length
    ? `<section class="group-card unassigned-group" data-group-drop="-1">
        <div class="group-card-heading">
          <h3>Alumnos sin grupo</h3>
          <span>${getUnassignedStudents().length} estudiante${getUnassignedStudents().length === 1 ? "" : "s"}</span>
        </div>
        <div class="group-member-list">${getUnassignedStudents().map((student) => `
          <div class="group-member-row" ${editable ? `draggable="true" data-group-drag="${student.id}"` : ""}>
            <span class="group-member-name">${escapeHtml(student.display_name)}<small>${escapeHtml(student.external_ref)}</small></span>
            ${editable ? `<select class="field" data-group-student="${student.id}" aria-label="Grupo de ${escapeHtml(student.display_name)}">
              <option value="-1" selected>Sin grupo</option>
              ${state.draftGroups.map((group, index) => `<option value="${index}">${escapeHtml(group.name)}</option>`).join("")}
            </select>` : ""}
          </div>`).join("")}</div>
      </section>`
    : "");
  const validation = (state.activeGroupPlanId || state.groupPlanDraft)
    ? groupPlanValidation()
    : "";
  const unassignedCount = getUnassignedStudents().length;
  elements.groupValidationMessage.textContent = validation
    || (state.activeGroupPlanId
      ? unassignedCount
        ? `${unassignedCount} estudiante${unassignedCount === 1 ? "" : "s"} sin grupo.`
        : "Todos los estudiantes activos tienen grupo."
      : state.course && state.students.length
        ? "Crea una propuesta aleatoria o una distribución manual para comenzar."
        : "Matricula estudiantes activos para poder crear grupos.");
  elements.saveGroupPlanButton.hidden = !editable;
  elements.saveGroupPlanButton.disabled = !editable || !state.activeGroupPlanId || Boolean(validation);
  elements.saveGroupPlanButton.textContent = state.groupPlanDraft
    ? "Confirmar y guardar propuesta"
    : "Guardar cambios";
  elements.saveGroupPlanButton.disabled = !editable || Boolean(validation);
  elements.groupPlanName.disabled = !editable;
  elements.groupPlanNameField.hidden = !editable;
  elements.editGroupPlanButton.hidden = editable || !state.activeGroupPlanId;
  elements.editGroupPlanButton.disabled = !state.activeGroupPlanId;
  elements.cancelGroupEditsButton.hidden = !editable;
  elements.addGroupButton.hidden = !editable;
  elements.addGroupButton.disabled = !editable || state.draftGroups.length >= 100;
}

function showGroupSetup(mode = null) {
  elements.groupSetupChoices.hidden = Boolean(mode);
  elements.groupGenerationForm.hidden = mode !== "random";
  elements.manualGroupSetup.hidden = mode !== "manual";
}

function nextGroupName() {
  const names = new Set(state.draftGroups.map((group) => group.name.toLocaleLowerCase()));
  let index = 1;
  while (names.has(`grupo ${index}`)) index += 1;
  return `Grupo ${index}`;
}

function applyGroupPlan(plan) {
  state.activeGroupPlanId = plan?.id ?? null;
  state.groupPlanDraft = plan?.id ? null : plan;
  state.groupPlanEditing = Boolean(plan && !plan.id);
  elements.groupSetupChoices.hidden = Boolean(plan);
  elements.groupGenerationForm.hidden = Boolean(plan);
  elements.manualGroupSetup.hidden = Boolean(plan);
  elements.deleteGroupPlanButton.disabled = !state.activeGroupPlanId;
  if (!plan) {
    state.draftGroups = [];
    elements.groupPlanName.value = "";
    renderGroupEditor();
    elements.groupEditorNote.textContent = state.groupPlans.length
      ? "Selecciona una propuesta guardada."
      : "Genera una propuesta aleatoria para comenzar.";
    return;
  }
  elements.groupPlanSelect.value = String(plan.id);
  state.groupMaxSize = plan.max_group_size;
  elements.groupMaxSize.value = String(plan.max_group_size);
  elements.groupPlanName.value = plan.name;
  state.draftGroups = plan.groups.map((group) => ({
    name: group.name,
    student_ids: group.student_ids.map(Number),
  }));
  ensureDraftRosterCoverage();
  elements.groupEditorNote.textContent = plan.id
    ? `Propuesta guardada el ${formatDate(plan.created_at)}.`
    : "Borrador sin guardar: edita la distribución y confírmala cuando estés conforme.";
  renderGroupEditor();
}

function renderGroupPlans() {
  const options = state.groupPlans.map((plan) =>
    `<option value="${plan.id}">${escapeHtml(plan.name)} · ${formatDate(plan.created_at)}</option>`,
  ).join("");
  elements.groupPlanSelect.innerHTML = options || '<option value="">Todavía no hay propuestas</option>';
  elements.groupPlanSelect.disabled = !state.groupPlans.length;
  const hasActivePlan = Boolean(state.activeGroupPlanId || state.groupPlanDraft);
  elements.groupSetupChoices.hidden = hasActivePlan;
  elements.groupGenerationForm.hidden = hasActivePlan;
  elements.manualGroupSetup.hidden = hasActivePlan;
  elements.deleteGroupPlanButton.disabled = !state.activeGroupPlanId;
  elements.generateGroupsButton.disabled = !state.course || !state.students.length;
  elements.createManualGroupsButton.disabled = !state.course || !state.students.length;
  elements.manualGroupCount.max = String(Math.min(100, state.students.length || 1));
  if (!Number(elements.manualGroupCount.value) || Number(elements.manualGroupCount.value) > state.students.length) {
    elements.manualGroupCount.value = String(Math.min(5, state.students.length || 1));
  }
  updateManualGroupSizePreview();
  if (state.activeGroupPlanId) elements.groupPlanSelect.value = String(state.activeGroupPlanId);
  renderGroupEditor();
}

async function loadGroupPlans() {
  if (!state.course) return;
  try {
    state.groupPlans = await api(`/courses/${state.course.id}/group-plans`);
    const selected = state.groupPlans.find((plan) => plan.id === state.activeGroupPlanId)
      || state.groupPlans[0]
      || null;
    renderGroupPlans();
    if (selected) {
      elements.groupPlanSelect.value = String(selected.id);
      applyGroupPlan(selected);
    } else {
      applyGroupPlan(null);
    }
  } catch (error) {
    elements.groupEditorNote.textContent = error.message;
    notify(`No se pudieron cargar las propuestas de grupos: ${error.message}`, true);
  }
}

async function createGroupPlan(mode, event) {
  if (event) event.preventDefault();
  if (!state.course) return;
  const maxGroupSize = Number(elements.groupMaxSize.value);
  if (mode === "random" && (!Number.isInteger(maxGroupSize) || maxGroupSize < 1 || maxGroupSize > 1000)) {
    notify("El máximo por grupo debe ser entre 1 y 1000.", true);
    return;
  }
  const manualGroupCount = Number(elements.manualGroupCount.value);
  if (mode === "manual" && (
    !Number.isInteger(manualGroupCount)
    || manualGroupCount < 1
    || manualGroupCount > Math.min(100, state.students.length)
  )) {
    notify(`Elige entre 1 y ${Math.min(100, state.students.length)} grupos.`, true);
    return;
  }
  const planName = mode === "manual"
    ? elements.manualGroupPlanName.value.trim()
    : elements.autoGroupPlanName.value.trim();
  const confirmation = mode === "manual"
    ? `Se preparará un borrador con ${manualGroupCount} grupos para que puedas editarlo. ¿Continuar?`
    : `Se generará un borrador aleatorio con máximo ${maxGroupSize} estudiantes por grupo para que puedas editarlo. ¿Continuar?`;
  if (!window.confirm(confirmation)) return;
  const button = mode === "manual"
    ? elements.prepareManualGroupsButton
    : elements.generateGroupsButton;
  setBusy(button, true, mode === "manual" ? "Creando..." : "Generando...");
  try {
    const suffix = mode === "manual" ? "/manual" : "";
    const payload = mode === "manual"
      ? {
          group_count: Number(elements.manualGroupCount.value),
          name: planName || null,
        }
      : {
          max_group_size: maxGroupSize,
          name: planName || null,
        };
    const plan = await api(`/courses/${state.course.id}/group-plans${suffix}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.groupPlans = [plan, ...state.groupPlans.filter((item) => item.id !== plan.id)];
    renderGroupPlans();
    applyGroupPlan(plan);
    notify("Borrador generado. Puedes editarlo antes de confirmarlo.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
    renderGroupPlans();
  }
}

function generateGroupPlan(event) {
  return createGroupPlan("random", event);
}

function updateManualGroupSizePreview() {
  const studentCount = state.students.length;
  const groupCount = Number(elements.manualGroupCount.value);
  if (!studentCount) {
    elements.manualGroupSizePreview.textContent = "Primero matricula estudiantes en este curso.";
    elements.prepareManualGroupsButton.disabled = true;
    return;
  }
  if (!Number.isInteger(groupCount) || groupCount < 1 || groupCount > Math.min(100, studentCount)) {
    elements.manualGroupSizePreview.textContent =
      `Elige entre 1 y ${Math.min(100, studentCount)} grupos para ${studentCount} estudiantes.`;
    elements.prepareManualGroupsButton.disabled = true;
    return;
  }
  const smallerGroups = Math.floor(studentCount / groupCount);
  const largerGroupCount = studentCount % groupCount;
  const smallerGroupCount = groupCount - largerGroupCount;
  const parts = [];
  if (largerGroupCount) {
    parts.push(`${largerGroupCount} grupo${largerGroupCount === 1 ? "" : "s"} de ${smallerGroups + 1}`);
  }
  if (smallerGroupCount) {
    parts.push(`${smallerGroupCount} grupo${smallerGroupCount === 1 ? "" : "s"} de ${smallerGroups}`);
  }
  elements.manualGroupSizePreview.textContent =
    `${studentCount} estudiantes en ${groupCount} grupos: ${parts.join(" y ")}.`;
  elements.prepareManualGroupsButton.disabled = false;
}

async function saveGroupPlan() {
  if (!state.course || !state.groupPlanEditing) return;
  const validation = groupPlanValidation();
  if (validation) {
    notify(validation, true);
    return;
  }
  const unassigned = getUnassignedStudents();
  const groupSizes = state.draftGroups.map((group) => group.student_ids.length);
  const unbalanced = Math.max(...groupSizes) - Math.min(...groupSizes) > 1;
  const details = [
    ...state.draftGroups.map((group) => `${group.name}: ${group.student_ids.length}`),
    ...(unassigned.length ? [`Alumnos sin grupo: ${unassigned.length}`] : []),
  ].join("\n");
  const notice = unbalanced ? "Los grupos tienen tamaños diferentes.\n" : "";
  const isDraft = Boolean(state.groupPlanDraft);
  if (!window.confirm(`${notice}${details}\n\n¿${isDraft ? "Confirmar y guardar" : "Guardar"} esta propuesta?`)) return;
  setBusy(elements.saveGroupPlanButton, true, "Guardando...");
  try {
    const plan = await api(
      isDraft
        ? `/courses/${state.course.id}/group-plans/confirm`
        : `/courses/${state.course.id}/group-plans/${state.activeGroupPlanId}`,
      {
        method: isDraft ? "POST" : "PUT",
        body: JSON.stringify({
          name: elements.groupPlanName.value.trim(),
          max_group_size: Number(elements.groupMaxSize.value),
          groups: state.draftGroups,
        }),
      },
    );
    state.groupPlans = [plan, ...state.groupPlans.filter((item) => item.id !== plan.id)];
    applyGroupPlan(plan);
    renderGroupPlans();
    notify(isDraft ? "Propuesta confirmada y guardada." : "Distribución de grupos guardada.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(elements.saveGroupPlanButton, false);
    renderGroupEditor();
  }
}

async function deleteGroupPlan() {
  if (!state.course || !state.activeGroupPlanId) return;
  const selected = state.groupPlans.find((plan) => plan.id === state.activeGroupPlanId);
  if (!window.confirm(`¿Eliminar la propuesta "${selected?.name || ""}"?`)) return;
  try {
    await api(`/courses/${state.course.id}/group-plans/${state.activeGroupPlanId}`, {
      method: "DELETE",
    });
    state.groupPlans = state.groupPlans.filter((plan) => plan.id !== state.activeGroupPlanId);
    applyGroupPlan(state.groupPlans[0] || null);
    renderGroupPlans();
    notify("Propuesta eliminada.");
  } catch (error) {
    notify(error.message, true);
  }
}

function startGroupPlanEditing() {
  if (!state.activeGroupPlanId || state.groupPlanEditing) return;
  state.groupPlanEditing = true;
  elements.groupEditorNote.textContent =
    "Modo de edición: reorganiza los estudiantes o incorpora a los que aparecen sin grupo.";
  renderGroupEditor();
}

function cancelGroupPlanEditing() {
  if (!state.groupPlanEditing) return;
  if (!window.confirm("¿Descartar los cambios que todavía no guardaste?")) return;
  if (state.groupPlanDraft) {
    applyGroupPlan(null);
    renderGroupPlans();
    notify("Borrador descartado.");
    return;
  }
  if (!state.activeGroupPlanId) return;
  const plan = state.groupPlans.find((item) => item.id === state.activeGroupPlanId);
  applyGroupPlan(plan || null);
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
  state.lastSelectedStudentIds = new Set(result.selected_student_ids.map(Number));
  state.replacementEnabled = true;
  $("#metric-last-run").textContent = `#${result.decision_run_id}`;
  $("#result-title").textContent = result.selected_student_ids.length
    ? `${result.selected_student_ids.length} seleccionado${result.selected_student_ids.length === 1 ? "" : "s"}`
    : "Sin estudiantes seleccionados";
  $("#result-meta").textContent = `Sesión #${result.class_session_id} · Decisión #${result.decision_run_id}`;
  $("#selected-list").innerHTML = result.selected_student_ids.map((id) => {
    const name = names.get(id) || `Estudiante ${id}`;
    const wasPresent = state.present.has(Number(id));
    return `<article class="participation-entry">
      <div class="selected-person"><span aria-hidden="true">✓</span>${escapeHtml(name)} <small>ID ${id}</small></div>
      <div class="participation-score-field">
        <label class="participation-score-label" for="participation-score-${id}">Nota (0 al 5)</label>
        <input class="field participation-score" id="participation-score-${id}" data-score-id="${id}" type="password"
          inputmode="decimal" autocomplete="new-password" maxlength="6" pattern="[0-9]+([.,][0-9]+)?"
          aria-label="Nota de ${escapeHtml(name)}, de 0 a 5" required />
      </div>
      <label class="participation-attendance" for="participation-present-${id}">
        <input id="participation-present-${id}" data-presence-id="${id}" type="checkbox" ${wasPresent ? "checked" : ""} />
        Presente
      </label>
    </article>`;
  }).join("");
  const saveButton = $("#participation-save");
  state.participationDecisionRunId = result.decision_run_id;
  saveButton.hidden = result.selected_student_ids.length === 0;
  saveButton.textContent = "Guardar participaciones";
  saveButton.disabled = false;
  $("#participation-form").hidden = result.selected_student_ids.length === 0;
  state.participationPending = result.selected_student_ids.length > 0;
  updateSelectionControls();
  elements.resultPanel.hidden = false;
}

function roundEligibleStudents() {
  return state.students.filter((student) => state.roundEligibleStudentIds.has(Number(student.id)));
}

function updateReplacementStatusFromEligibility() {
  if (!state.lastSelectedStudentIds.size) return;
  state.replacementEnabled = [...state.lastSelectedStudentIds].every((studentId) =>
    state.roundEligibleStudentIds.has(studentId));
}

$("#replacement-toggle-button").addEventListener("click", () => {
  if (!state.lastSelectedStudentIds.size) return;
  const replacementEnabled = !state.replacementEnabled;
  state.lastSelectedStudentIds.forEach((studentId) => {
    if (replacementEnabled) state.roundEligibleStudentIds.add(studentId);
    else state.roundEligibleStudentIds.delete(studentId);
  });
  renderStudents();
});

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

function rouletteLabelName(displayName) {
  const names = String(displayName || "").trim().split(/\s+/).filter(Boolean);
  if (names.length <= 2) return names.join(" ");
  return `${names[0]} ${names[names.length - 2]}`;
}

function roulettePoint(angleDegrees, radius) {
  const angle = angleDegrees * Math.PI / 180;
  return {
    x: 300 + Math.cos(angle) * radius,
    y: 300 + Math.sin(angle) * radius,
  };
}

function renderRouletteWheel(candidates) {
  const wheel = $("#roulette-wheel");
  const count = candidates.length;
  const radius = 292;
  const labelRadius = radius * 0.67;
  wheel.setAttribute(
    "aria-label",
    `Ruleta con ${count} estudiante${count === 1 ? "" : "s"} elegible${count === 1 ? "" : "s"}.`
  );
  wheel.innerHTML = candidates.map((student, index) => {
    const slice = 360 / count;
    const startAngle = -90 + index * slice;
    const endAngle = startAngle + slice;
    const middleAngle = startAngle + slice / 2;
    const start = roulettePoint(startAngle, radius);
    const end = roulettePoint(endAngle, radius);
    const label = roulettePoint(middleAngle, labelRadius);
    let labelRotation = middleAngle;
    if (labelRotation > 90 && labelRotation < 270) labelRotation -= 180;
    const labelName = rouletteLabelName(student.display_name);
    const words = labelName.split(/\s+/);
    const availableWidth = Math.max(14, 2 * labelRadius * Math.sin(Math.PI / count) * 0.78);
    const longestLine = Math.max(...words.map((word) => word.length), 1);
    const fontSize = Math.max(5, Math.min(17, availableWidth / (longestLine * 0.62)));
    const textMarkup = words.length > 1
      ? `<tspan x="0" dy="-0.12em">${escapeHtml(words[0])}</tspan><tspan x="0" dy="1.12em">${escapeHtml(words[1])}</tspan>`
      : `<tspan x="0">${escapeHtml(words[0] || "")}</tspan>`;
    const sector = count === 1
      ? `<circle cx="300" cy="300" r="${radius}" fill="${visualPalette[index % visualPalette.length]}" />`
      : `<path d="M 300 300 L ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${radius} ${radius} 0 ${slice > 180 ? 1 : 0} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)} Z" fill="${visualPalette[index % visualPalette.length]}" />`;
    return `<g class="roulette-name" data-student-index="${index}" role="listitem" aria-label="${escapeHtml(student.display_name)}">
      ${sector}
      <g transform="translate(${label.x.toFixed(2)} ${label.y.toFixed(2)}) rotate(${labelRotation.toFixed(2)})">
        <text text-anchor="middle" dominant-baseline="middle" style="font-size:${fontSize.toFixed(1)}px">${textMarkup}</text>
      </g>
      <title>${escapeHtml(student.display_name)}</title>
    </g>`;
  }).join("");
}

function prepareSelectionStage(candidates = roundEligibleStudents()) {
  const mode = document.querySelector('input[name="selection-visual"]:checked').value;
  $("#stage-status").textContent = "SELECCIÓN EN CURSO";
  $("#stage-heading").textContent = mode === "roulette" ? "La ruleta está en marcha" : "Las bolillas se están mezclando";
  $("#stage-footnote").textContent = "El resultado se calcula con el método seleccionado.";
  $("#stage-result").hidden = true;
  $("#stage-pick-form").hidden = true;
  elements.selectionStage.querySelector(".selection-stage-frame").classList.remove("has-pick");
  elements.stageClose.hidden = true;
  $("#stage-done").hidden = true;
  $("#roulette-visual").hidden = mode !== "roulette";
  $("#balls-visual").hidden = mode !== "balls";
  if (!elements.selectionStage.open) elements.selectionStage.showModal();
  $("#roulette-hub-label").textContent = "EN JUEGO";
  $("#roulette-winner").textContent = "Ruleta";
  const wheel = $("#roulette-wheel");
  wheel.classList.remove("spinning");
  wheel.style.transition = "none";
  wheel.style.transform = "rotate(0deg)";
  renderRouletteWheel(candidates);
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
        wheel.querySelectorAll(".roulette-name").forEach((name, nameIndex) => {
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
    $("#stage-footnote").textContent = "La selección quedó registrada. Completa los datos o quita al estudiante.";
    showStagePick(result, winners);
  };
  if (stage.mode === "roulette") {
    revealResult();
    const winnerIndex = stage.candidates.findIndex((student) => Number(student.id) === Number(winners[0]?.id));
    const targetAngle = winnerIndex < 0 ? 0 : 360 - (360 * (winnerIndex + 0.5)) / stage.candidates.length;
    wheel.style.transform = `rotate(${targetAngle + 1440}deg)`;
    $("#roulette-hub-label").textContent = winners.length ? "RESULTADO" : "FINALIZADO";
    $("#roulette-winner").textContent = winners.length === 1 ? winners[0].name : winners.length ? `${winners.length} ganadores` : "Sin selección";
    wheel.querySelectorAll(".roulette-name").forEach((name) => {
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

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("#login-username").value.trim();
  const password = $("#login-password").value;
  elements.loginError.hidden = true;
  setBusy(elements.loginSubmit, true, "Ingresando...");
  try {
    const user = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    $("#login-password").value = "";
    if (user.must_change_password) showPasswordChange();
    else await loadAuthenticatedData(user);
  } catch (error) {
    elements.loginError.textContent = error.message;
    elements.loginError.hidden = false;
  } finally {
    setBusy(elements.loginSubmit, false);
  }
});

elements.passwordChangeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const newPassword = $("#new-password").value;
  if (newPassword !== $("#confirm-new-password").value) {
    elements.passwordChangeError.textContent = "Las contraseñas no coinciden.";
    elements.passwordChangeError.hidden = false;
    return;
  }
  elements.passwordChangeError.hidden = true;
  setBusy(elements.passwordChangeSubmit, true, "Guardando...");
  try {
    const user = await api("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
    elements.passwordChangeForm.reset();
    await loadAuthenticatedData(user);
  } catch (error) {
    elements.passwordChangeError.textContent = error.message;
    elements.passwordChangeError.hidden = false;
  } finally {
    setBusy(elements.passwordChangeSubmit, false);
  }
});

$("#logout-button").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch (error) {
    showLogin(`Se cerró esta vista, pero no se pudo confirmar el cierre en el servidor: ${error.message}`);
    return;
  }
  showLogin();
});

$("#create-course-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.participationPending) {
    notify("Guarda la participación pendiente antes de crear otro curso.", true);
    return;
  }
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const name = $("#course-name").value.trim();
  const cycleId = Number(elements.courseCreationCycle.value) || null;
  if (!name || !cycleId) return;
  setBusy(button, true, "Creando...");
  try {
    const course = await api("/courses", {
      method: "POST",
      body: JSON.stringify({ name, cycle_id: cycleId }),
    });
    await loadCourse(course.id);
    form.reset();
    setAppView("enrollment");
    notify(`Curso “${course.name}” creado.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#create-cycle-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const name = $("#cycle-name").value.trim();
  const startsOn = $("#cycle-starts-on").value;
  if (!name || !startsOn) return;
  setBusy(button, true, "Creando...");
  try {
    const cycle = await api("/cycles", {
      method: "POST",
      body: JSON.stringify({ name, starts_on: startsOn }),
    });
    state.cycles = [...state.cycles, cycle];
    renderCycles(cycle.id);
    form.reset();
    notify(`Ciclo “${cycle.name}” creado con inicio el ${startsOn}.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#cycle-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-save-cycle-start]");
  if (!button) return;
  const cycleId = Number(button.dataset.saveCycleStart);
  const input = document.querySelector(`[data-cycle-start="${cycleId}"]`);
  if (!input?.value) {
    notify("Selecciona la fecha de inicio del ciclo.", true);
    return;
  }
  setBusy(button, true, "Guardando...");
  try {
    const updated = await api(`/cycles/${cycleId}`, {
      method: "PATCH",
      body: JSON.stringify({ starts_on: input.value }),
    });
    state.cycles = state.cycles.map((cycle) => cycle.id === cycleId ? updated : cycle);
    renderCycles(state.activeCycleId);
    notify(`Fecha de inicio de “${updated.name}” guardada.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

elements.studentAccountForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#create-student-account-submit");
  const payload = {
    username: $("#account-student-code").value.trim(),
    full_name: $("#account-student-name").value.trim(),
    email: $("#account-student-email").value.trim(),
  };
  setBusy(button, true, "Registrando...");
  try {
    const created = await api("/admin/students", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const { temporary_password, ...account } = created;
    state.studentAccounts = [...state.studentAccounts, account];
    renderStudentAccounts();
    elements.studentAccountForm.reset();
    showTemporaryPassword(
      temporary_password,
      `Contraseña temporal de ${account.full_name}. Comparte el usuario y la contraseña por un canal privado.`,
      account.username,
    );
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

elements.studentAccountList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-reset-student-account]");
  if (!button) return;
  const student = state.studentAccounts.find(
    (item) => item.id === Number(button.dataset.resetStudentAccount),
  );
  if (!student || !window.confirm(`¿Generar una nueva contraseña temporal para ${student.full_name}?`)) return;
  setBusy(button, true, "Generando...");
  try {
    const result = await api(`/admin/students/${student.id}/reset-password`, { method: "POST" });
    showTemporaryPassword(
      result.temporary_password,
      `Contraseña temporal de ${student.full_name}. Comparte el acceso por un canal privado.`,
      student.username,
    );
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

elements.importResult.addEventListener("click", async (event) => {
  if (!event.target.closest("#copy-import-passwords")) return;
  const accounts = [...elements.importResult.querySelectorAll(".import-account-credentials li")]
    .map((item) => item.textContent.trim())
    .join("\n");
  try {
    if (!navigator.clipboard?.writeText) throw new Error("El portapapeles no está disponible.");
    await navigator.clipboard.writeText(accounts);
    notify("Accesos temporales copiados.");
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(elements.importResult.querySelector(".import-account-credentials"));
    selection.removeAllRanges();
    selection.addRange(range);
    notify("No se pudo copiar automáticamente. Los accesos quedaron seleccionados.", true);
  }
});

elements.activeCycle.addEventListener("change", () => {
  const nextCycleId = Number(elements.activeCycle.value) || null;
  if (state.participationPending) {
    notify("Guarda la participación pendiente antes de cambiar el ciclo.", true);
    renderCycles(state.activeCycleId);
    return;
  }
  state.activeCycleId = nextCycleId;
  if (state.activeCycleId) localStorage.setItem("aula-active-cycle", String(state.activeCycleId));
  if (state.course && state.course.cycle_id !== state.activeCycleId) {
    clearCourseSelection();
  }
  renderCycles(state.activeCycleId);
});

elements.courseCreationCycle.addEventListener("change", () => {
  const hasCycle = Boolean(Number(elements.courseCreationCycle.value));
  $("#create-course-form button[type=submit]").disabled = !hasCycle;
  $("#course-cycle-hint").hidden = hasCycle;
  renderCourseCreation();
});

elements.dailyCycle.addEventListener("change", () => {
  const nextCycleId = Number(elements.dailyCycle.value) || null;
  if (state.participationPending) {
    notify("Guarda la participación pendiente antes de cambiar el ciclo.", true);
    renderWorkCourseSelectors();
    return;
  }
  state.activeCycleId = nextCycleId;
  if (state.activeCycleId) localStorage.setItem("aula-active-cycle", String(state.activeCycleId));
  if (state.course && state.course.cycle_id !== state.activeCycleId) {
    clearCourseSelection();
  }
  renderCycles(state.activeCycleId);
});

async function selectCourseFromPicker(courseId) {
  if (!courseId) {
    if (state.participationPending) {
      notify("Guarda la participación pendiente antes de cambiar el curso.", true);
      renderWorkCourseSelectors();
      return;
    }
    if (state.course) clearCourseSelection();
    return;
  }
  try {
    await loadCourse(courseId);
  } catch (error) {
    renderWorkCourseSelectors();
    notify(error.message, true);
  }
}

elements.dailyCourse.addEventListener("change", () => {
  selectCourseFromPicker(elements.dailyCourse.value);
});
elements.enrollmentCourse.addEventListener("change", () => {
  selectCourseFromPicker(elements.enrollmentCourse.value);
});

elements.assignmentTeacher.addEventListener("change", renderTeacherAssignments);
$("#create-teacher-course-search").addEventListener("input", (event) => {
  filterCourseOptions(event.currentTarget, elements.createTeacherCourseList);
});
$("#assignment-course-search").addEventListener("input", (event) => {
  filterCourseOptions(event.currentTarget, elements.assignmentCourseList);
});
elements.registerTeacherButton.addEventListener("click", () => {
  elements.teacherManagementHome.hidden = true;
  elements.registerTeacherButton.hidden = true;
  elements.createTeacherForm.hidden = false;
  $("#teacher-full-name").focus();
});
elements.cancelTeacherRegistration.addEventListener("click", () => {
  elements.createTeacherForm.reset();
  $("#create-teacher-course-search").value = "";
  filterCourseOptions($("#create-teacher-course-search"), elements.createTeacherCourseList);
  showTeacherManagementHome();
});
elements.assignmentCourseList.addEventListener("change", () => {
  elements.saveAssignmentsButton.disabled = !elements.assignmentTeacher.value;
});
elements.createTeacherForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const courseIds = [...elements.createTeacherCourseList.querySelectorAll("input:checked")]
    .map((checkbox) => Number(checkbox.value));
  if (!courseIds.length) {
    notify("Selecciona al menos un curso para el docente.", true);
    return;
  }
  setBusy(elements.createTeacherSubmit, true, "Registrando...");
  try {
    const teacher = await api("/admin/teachers", {
      method: "POST",
      body: JSON.stringify({
        full_name: $("#teacher-full-name").value.trim(),
        username: $("#teacher-username").value.trim(),
        phone_number: $("#teacher-phone").value.trim() || null,
        email: $("#teacher-email").value.trim(),
        course_ids: courseIds,
      }),
    });
    const { temporary_password: temporaryPassword, ...teacherDetails } = teacher;
    state.teachers = [...state.teachers, teacherDetails];
    elements.createTeacherForm.reset();
    $("#create-teacher-course-search").value = "";
    renderTeacherAssignments();
    showTeacherManagementHome();
    showTemporaryPassword(
      temporaryPassword,
      `Cuenta creada para ${teacher.full_name} (${teacher.username}).`,
    );
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(elements.createTeacherSubmit, false);
    renderTeacherAssignments();
  }
});

elements.teacherDirectoryList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-reset-teacher]");
  if (!button) return;
  const teacher = state.teachers.find((item) => item.id === Number(button.dataset.resetTeacher));
  if (!teacher) return;
  if (!window.confirm(`Se generará una nueva contraseña temporal para ${teacher.full_name}. La contraseña actual dejará de funcionar y se mostrará una sola vez. ¿Continuar?`)) return;
  setBusy(button, true, "Generando...");
  try {
    const result = await api(`/admin/teachers/${teacher.id}/reset-password`, { method: "POST" });
    showTemporaryPassword(
      result.temporary_password,
      `Contraseña temporal nueva para ${teacher.full_name} (${teacher.username}).`,
    );
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

elements.saveAssignmentsButton.addEventListener("click", async () => {
  const teacherId = Number(elements.assignmentTeacher.value);
  if (!teacherId) return;
  const courseIds = [...elements.assignmentCourseList.querySelectorAll("input:checked")]
    .map((checkbox) => Number(checkbox.value));
  setBusy(elements.saveAssignmentsButton, true, "Guardando...");
  try {
    const teacher = await api(`/admin/teachers/${teacherId}/courses`, {
      method: "PUT",
      body: JSON.stringify({ course_ids: courseIds }),
    });
    state.teachers = state.teachers.map((item) => item.id === teacher.id ? teacher : item);
    renderTeacherAssignments();
    notify(`Cursos asignados a ${teacher.full_name}.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(elements.saveAssignmentsButton, false);
    elements.saveAssignmentsButton.disabled = !elements.assignmentTeacher.value;
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
    if (student.temporary_password) {
      showTemporaryPassword(
        student.temporary_password,
        `Acceso creado para ${student.display_name}. La persona deberá cambiar la contraseña al ingresar.`,
        student.account_username,
      );
    } else {
      notify(`${student.display_name} quedó matriculado con el usuario ${student.account_username}.`);
    }
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

elements.studentList.addEventListener("change", async (event) => {
  const roundInput = event.target.closest("[data-round-id]");
  if (!roundInput) return;
  const id = Number(roundInput.dataset.roundId);
  if (state.session) {
    roundInput.disabled = true;
    try {
      await saveAttendance([[id, roundInput.checked]]);
    } catch (error) {
      notify(error.message, true);
      renderStudents();
      return;
    }
  } else if (roundInput.checked) {
    state.present.add(id);
  } else {
    state.present.delete(id);
  }
  if (roundInput.checked) state.roundEligibleStudentIds.add(id);
  else state.roundEligibleStudentIds.delete(id);
  updateReplacementStatusFromEligibility();
  renderStudents();
});

elements.startRound.addEventListener("click", () => {
  state.roundEligibleStudentIds = new Set(state.students.map((student) => Number(student.id)));
  updateReplacementStatusFromEligibility();
  renderStudents();
});

document.addEventListener("input", (event) => {
  const input = event.target.closest("[data-score-id]");
  if (!input) return;
  const normalized = input.value.replace(",", ".");
  const validFormat = /^\d*(?:\.\d*)?$/.test(normalized);
  const validRange = normalized === "" || Number(normalized) <= 5;
  if (!validFormat || !validRange) {
    input.value = input.dataset.lastValid || "";
    return;
  }
  input.dataset.lastValid = input.value;
});

elements.toggleAll.addEventListener("click", async () => {
  const allPresent = state.students.length > 0 && state.present.size === state.students.length;
  const nextPresent = !allPresent;
  if (state.session) {
    try {
      await saveAttendance(state.students.map((student) => [student.id, nextPresent]));
    } catch (error) {
      notify(error.message, true);
      return;
    }
  } else {
    state.present = nextPresent
      ? new Set(state.students.map((student) => Number(student.id)))
      : new Set();
  }
  state.roundEligibleStudentIds = nextPresent
    ? new Set(state.students.map((student) => Number(student.id)))
    : new Set();
  updateReplacementStatusFromEligibility();
  renderStudents();
});

elements.methodSelect.addEventListener("change", updateMethodFields);
$("#slots-input").addEventListener("change", updateSelectionControls);

/* ==========================================================================
   Flujo continuo dentro del menú de la ruleta/bolillero.
   Cada giro elige UN estudiante (k = 1). El docente completa pregunta, nota y
   comentario en el mismo menú, o lo quita; luego se elige otro al azar hasta
   que pulse "Salir". Los ya atendidos (guardados o quitados) no se repiten
   dentro de esta tanda. Todos los giros reutilizan la misma sesión de clase.
   ========================================================================== */
function stageCandidates() {
  const flow = state.stageFlow;
  return roundEligibleStudents().filter((student) => !flow.excluded.has(Number(student.id)));
}

async function runStageSpin() {
  const flow = state.stageFlow;
  const candidates = stageCandidates();
  if (!state.course || !candidates.length) return;
  const payload = {
    k: 1,
    method: elements.methodSelect.value,
    present_student_ids: candidates.map((student) => Number(student.id)),
  };
  if (flow.classSessionId) {
    payload.class_session_id = flow.classSessionId;
  } else if (state.session) {
    // Se envía el subconjunto elegible; la asistencia de la sesión no se modifica.
    payload.class_session_id = state.session.id;
  } else {
    const sessionLabel = $("#session-label").value.trim();
    if (sessionLabel) payload.session_label = sessionLabel;
  }
  if (payload.method === "weighted_softmax") payload.method_params = { tau: Number($("#tau-input").value) };
  const stage = prepareSelectionStage(candidates);
  try {
    const result = await api(`/courses/${state.course.id}/sessions/select`, {
      method: "POST", body: JSON.stringify(payload),
    });
    flow.classSessionId = result.class_session_id;
    $("#metric-last-run").textContent = `#${result.decision_run_id}`;
    const remainingAnimation = Math.max(0, selectionAnimationDuration - (performance.now() - stage.startedAt));
    if (remainingAnimation) await new Promise((resolve) => setTimeout(resolve, remainingAnimation));
    finishSelectionStage(result, stage);
  } catch (error) {
    finishSelectionStage(null, stage, error);
    notify(error.message, true);
  }
}

function showStagePick(result, winners) {
  const flow = state.stageFlow;
  const form = $("#stage-pick-form");
  const winner = winners[0];
  if (!flow || !winner) { form.hidden = true; return; }
  flow.pick = { decisionRunId: result.decision_run_id, studentId: Number(winner.id) };
  form.reset();
  $("#stage-score").dataset.lastValid = "";
  $("#stage-present").checked = state.present.has(Number(winner.id));
  elements.selectionStage.querySelector(".selection-stage-frame").classList.add("has-pick");
  form.hidden = false;
  $("#stage-footnote").textContent =
    `Guardados: ${flow.saved} · Quitados: ${flow.removed} · Quedan ${Math.max(0, stageCandidates().length - 1)} por elegir.`;
  $("#stage-score").focus({ preventScroll: true });
  form.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function advanceStage() {
  const flow = state.stageFlow;
  flow.pick = null;
  $("#stage-pick-form").hidden = true;
  if (!stageCandidates().length) {
    $("#stage-status").textContent = "RONDA COMPLETADA";
    $("#stage-heading").textContent = "Ya no quedan estudiantes por elegir";
    $("#stage-winners").innerHTML = "";
    $("#stage-result-meta").textContent = `Guardados: ${flow.saved} · Quitados: ${flow.removed}`;
    $("#stage-footnote").textContent = "Pulsa Salir para volver a la pantalla principal.";
    return;
  }
  await runStageSpin();
}

function requestStageExit() {
  const flow = state.stageFlow;
  if (flow?.pick && !window.confirm("El estudiante elegido aún no tiene su participación guardada. ¿Salir sin guardarla?")) return;
  closeSelectionStage();
}

$("#selection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course || !roundEligibleStudents().length) return;
  state.stageFlow = { classSessionId: null, excluded: new Set(), pick: null, saved: 0, removed: 0, busy: false };
  setBusy(elements.runButton, true, "Seleccionando...");
  try {
    await runStageSpin();
  } finally {
    setBusy(elements.runButton, false);
  }
});

$("#stage-score").addEventListener("input", (event) => {
  const input = event.currentTarget;
  const normalized = input.value.replace(",", ".");
  const validFormat = /^\d*(?:\.\d*)?$/.test(normalized);
  const validRange = normalized === "" || Number(normalized) <= 5;
  if (!validFormat || !validRange) {
    input.value = input.dataset.lastValid || "";
    return;
  }
  input.dataset.lastValid = input.value;
});

$("#stage-pick-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const flow = state.stageFlow;
  if (!state.course || !flow?.pick || flow.busy) return;
  const rawScore = $("#stage-score").value.trim().replace(",", ".");
  const score = Number(rawScore);
  if (rawScore === "" || !Number.isFinite(score) || score < 0 || score > 5) {
    notify("La nota debe ser un número entre 0 y 5.", true);
    return;
  }
  const { decisionRunId, studentId } = flow.pick;
  const button = $("#stage-save");
  flow.busy = true;
  setBusy(button, true, "Guardando...");
  try {
    await api(`/courses/${state.course.id}/decision-runs/${decisionRunId}/participations`, {
      method: "POST",
      body: JSON.stringify({
        participations: [{
          student_id: studentId,
          score,
          present: $("#stage-present").checked,
          question: $("#stage-question").value.trim() || null,
          comment: $("#stage-comment").value.trim() || null,
        }],
      }),
    });
    flow.saved += 1;
    flow.excluded.add(studentId);
    notify("Participación guardada.");
    loadParticipationHistory();
    refreshCourse().catch(() => {});
  } catch (error) {
    notify(error.message, true);
    flow.busy = false;
    setBusy(button, false);
    return;
  }
  flow.busy = false;
  setBusy(button, false);
  await advanceStage();
});

$("#stage-remove").addEventListener("click", async () => {
  const flow = state.stageFlow;
  if (!flow?.pick || flow.busy) return;
  flow.excluded.add(flow.pick.studentId);
  flow.removed += 1;
  notify("Estudiante quitado de esta ronda.");
  await advanceStage();
});

elements.stageClose.addEventListener("click", requestStageExit);
$("#stage-done").addEventListener("click", requestStageExit);
elements.selectionStage.addEventListener("cancel", (event) => {
  // Esc solo funciona cuando el botón de salida está disponible (no durante un giro).
  event.preventDefault();
  if (!elements.stageClose.hidden) requestStageExit();
});
elements.selectionStage.addEventListener("close", () => {
  const hadFlow = Boolean(state.stageFlow);
  state.stageFlow = null;
  if (hadFlow) refreshCourse().catch(() => {});
});

$("#participation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course) return;
  const decisionRunId = state.participationDecisionRunId;
  const scores = [...document.querySelectorAll("[data-score-id]")];
  const participations = scores.map((input) => {
    const rawScore = input.value.trim().replace(",", ".");
    return {
      student_id: Number(input.dataset.scoreId),
      score: Number(rawScore),
      present: document.querySelector(`[data-presence-id="${input.dataset.scoreId}"]`).checked,
    };
  });
  if (participations.some((item) => !Number.isFinite(item.score) || item.score < 0 || item.score > 5)) {
    notify("Cada nota debe ser un número entre 0 y 5.", true);
    return;
  }
  const button = $("#participation-save");
  setBusy(button, true, "Guardando...");
  try {
    await api(`/courses/${state.course.id}/decision-runs/${decisionRunId}/participations`, {
      method: "POST",
      body: JSON.stringify({ participations }),
    });
    state.participationPending = false;
    scores.forEach((input) => { input.disabled = true; });
    document.querySelectorAll("[data-presence-id]").forEach((input) => { input.disabled = true; });
    button.textContent = "Participaciones guardadas";
    updateSelectionControls();
    await loadParticipationHistory();
    notify("Notas y asistencia guardadas.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
    if (!state.participationPending) {
      button.textContent = "Participaciones guardadas";
      button.disabled = true;
    }
  }
});

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
    state.sessionAttendanceSnapshot = new Set(
      detail.attendance.filter((entry) => entry.present).map((entry) => entry.student_id),
    );
    state.present = new Set(state.sessionAttendanceSnapshot);
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
  state.sessionAttendanceSnapshot = new Set();
  state.present = new Set();
  state.lastSelectedStudentIds = new Set();
  state.replacementEnabled = true;
  elements.resultPanel.hidden = true;
  renderSessionBox();
  renderStudents();
  await loadProposal();
  notify("Sesión terminada. Puedes iniciar otra.");
});

elements.markSessionPresent.addEventListener("click", async () => {
  if (!state.session) return;
  setBusy(elements.markSessionPresent, true, "Marcando...");
  try {
    await saveAttendance(
      state.students.map((student) => [
        student.id,
        state.sessionAttendanceSnapshot.has(Number(student.id)),
      ]),
    );
    state.roundEligibleStudentIds = new Set(state.sessionAttendanceSnapshot);
    updateReplacementStatusFromEligibility();
    renderStudents();
    notify("Asistencia inicial de la sesión restaurada.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(elements.markSessionPresent, false);
  }
});

elements.rosterFile.addEventListener("change", () => {
  const file = elements.rosterFile.files[0];
  $("#roster-file-label").textContent = file ? `↑ ${file.name}` : "↑ Elegir Excel (.xlsx)";
  elements.importButton.disabled = !file || Boolean(state.course?.roster_imported);
});

function renderImportResult(result) {
  const parts = [`${result.created} nuevo${result.created === 1 ? "" : "s"}`, `${result.updated} actualizado${result.updated === 1 ? "" : "s"}`, `${result.unchanged} sin cambios`];
  const errors = result.errors.map((error) => `<li>Fila ${error.row}: ${escapeHtml(error.message)}</li>`).join("");
  const warnings = (result.warnings || []).map((warning) => `<li>Fila ${warning.row}: ${escapeHtml(warning.message)}</li>`).join("");
  const accounts = (result.created_accounts || []).map((account) => `
    <li><strong>${escapeHtml(account.full_name)}</strong> · ${escapeHtml(account.email || "Sin correo")}
      · Usuario: <code>${escapeHtml(account.username)}</code>
      · Contraseña temporal: <code>${escapeHtml(account.temporary_password)}</code></li>
  `).join("");
  const updatedAccounts = (result.updated_accounts || []).map((account) => `
    <li>Fila ${account.row_number}: <strong>${escapeHtml(account.full_name)}</strong>
      · nuevo usuario: <code>${escapeHtml(account.username)}</code>
      · conserva su contraseña actual</li>
  `).join("");
  elements.importResult.innerHTML = `<strong>${result.total_rows} fila${result.total_rows === 1 ? "" : "s"} leída${result.total_rows === 1 ? "" : "s"}:</strong> ${parts.join(" · ")}`
    + (errors ? `<p class="import-errors-title">${result.errors.length} fila${result.errors.length === 1 ? "" : "s"} con problemas (no se importaron):</p><ul>${errors}</ul>` : "")
    + (warnings ? `<p class="import-errors-title">Observaciones</p><ul>${warnings}</ul>` : "")
    + (accounts ? `<div class="import-account-credentials"><p><strong>Contraseñas temporales</strong> · Cópialas ahora; no volverán a mostrarse.</p><button class="button button-quiet" id="copy-import-passwords" type="button">Copiar accesos</button><ul>${accounts}</ul></div>` : "")
    + (updatedAccounts ? `<div class="import-account-credentials"><p><strong>Usuarios de cuentas existentes</strong> · La contraseña no cambió.</p><ul>${updatedAccounts}</ul></div>` : "");
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
    notify(result.errors.length ? "Lista cargada con observaciones." : "Lista cargada correctamente.", result.errors.length > 0);
  } catch (error) {
    elements.importResult.hidden = true;
    notify(error.message, true);
  } finally {
    setBusy(elements.importButton, false);
    elements.importButton.disabled = !elements.rosterFile.files[0] || Boolean(state.course?.roster_imported);
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
  $("#edit-reset-password").hidden = !student.user_id;
  $("#edit-withdraw").textContent = student.active ? "Retirar del curso" : "Reincorporar al curso";
  elements.editDialog.showModal();
});

$("#edit-reset-password").addEventListener("click", async () => {
  const student = state.managementStudents.find((item) => item.id === editingStudentId);
  if (!student?.user_id) return;
  if (!window.confirm(`¿Generar una nueva contraseña temporal para ${student.display_name}?`)) return;
  try {
    const result = await api(`/students/${student.id}/reset-password`, { method: "POST" });
    showTemporaryPassword(
      result.temporary_password,
      `Acceso temporal de ${student.display_name}. Comparte la contraseña por un canal privado.`,
      student.external_ref,
    );
  } catch (error) {
    notify(error.message, true);
  }
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

elements.dailyViewButton.addEventListener("click", () => setAppView("daily"));
elements.cyclesViewButton.addEventListener("click", () => setAppView("cycles"));
elements.teachersViewButton.addEventListener("click", () => setAppView("teachers"));
elements.studentAccountsViewButton.addEventListener("click", () => setAppView("studentAccounts"));
elements.coursesViewButton.addEventListener("click", () => setAppView("createCourse"));
elements.enrollmentViewButton.addEventListener("click", () => setAppView("enrollment"));
elements.studentCourseIndex.addEventListener("click", openStudentCourse);

elements.studentCoursesViewButton.addEventListener("click", () => {
  state.selectedStudentCourse = null;
  elements.studentCourseIndex.hidden = false;
  elements.studentCourseDetail.hidden = true;
  setAppView("studentPortal");
});
$("#student-course-back").addEventListener("click", () => {
  state.selectedStudentCourse = null;
  elements.studentCourseDetail.hidden = true;
  elements.studentCourseIndex.hidden = false;
});
elements.attendanceTab.addEventListener("click", () => setCourseView("attendance"));
elements.participationsTab.addEventListener("click", () => {
  setCourseView("participations");
  loadParticipationHistory();
});
elements.groupsTab.addEventListener("click", () => {
  setCourseView("groups");
  if (state.course && !state.groupPlans.length) loadGroupPlans();
});
elements.gradesViewButton.addEventListener("click", () => {
  state.gradeCycleId = state.course?.cycle_id || state.activeCycleId || null;
  state.gradeCourseId = null;
  renderGradeSelectors();
  setAppView("grades");
});
elements.gradeCycle.addEventListener("change", () => {
  state.gradeCycleId = Number(elements.gradeCycle.value) || null;
  state.gradeCourseId = null;
  renderGradeSelectors();
  loadGradeMatrix();
});
elements.gradeCourse.addEventListener("change", loadGradeMatrix);
elements.gradeMatrixBody.addEventListener("click", (event) => {
  const button = event.target.closest("[data-grade-student]");
  if (!button) return;
  loadGradeDetails(Number(button.dataset.gradeStudent), Number(button.dataset.gradeWeek));
});
$("#grade-detail-close").addEventListener("click", () => elements.gradeDetailDialog.close());
elements.gradeDetailDialog.addEventListener("click", (event) => {
  if (event.target === elements.gradeDetailDialog) elements.gradeDetailDialog.close();
});
elements.groupPlanSelect.addEventListener("change", () => {
  if (state.groupPlanEditing && !window.confirm("¿Descartar los cambios que todavía no guardaste?")) {
    elements.groupPlanSelect.value = String(state.activeGroupPlanId);
    return;
  }
  const plan = state.groupPlans.find((item) => item.id === Number(elements.groupPlanSelect.value));
  applyGroupPlan(plan || null);
});
$("#group-generation-form").addEventListener("submit", generateGroupPlan);
$("#create-auto-groups-button").addEventListener("click", () => {
  showGroupSetup("random");
  elements.groupMaxSize.focus();
});
elements.createManualGroupsButton.addEventListener("click", () => {
  showGroupSetup("manual");
  elements.manualGroupCount.value = String(Math.min(5, state.students.length || 1));
  updateManualGroupSizePreview();
  elements.manualGroupCount.focus();
});
document.querySelectorAll("[data-back-to-group-methods]").forEach((button) => {
  button.addEventListener("click", () => showGroupSetup());
});
elements.manualGroupCount.addEventListener("input", updateManualGroupSizePreview);
elements.prepareManualGroupsButton.addEventListener("click", () => createGroupPlan("manual"));
elements.groupMaxSize.addEventListener("change", () => {
  state.groupMaxSize = Number(elements.groupMaxSize.value);
  renderGroupEditor();
});
elements.groupPlanName.addEventListener("input", () => {
  elements.saveGroupPlanButton.disabled = !state.activeGroupPlanId || Boolean(groupPlanValidation());
});
elements.groupEditor.addEventListener("change", (event) => {
  if (!state.groupPlanEditing) return;
  const nameInput = event.target.closest("[data-group-name]");
  if (nameInput) {
    state.draftGroups[Number(nameInput.dataset.groupName)].name = nameInput.value.trim();
    renderGroupEditor();
    return;
  }
  const studentSelect = event.target.closest("[data-group-student]");
  if (!studentSelect) return;
  const studentId = Number(studentSelect.dataset.groupStudent);
  const toIndex = Number(studentSelect.value);
  if (!moveStudentToGroup(studentId, toIndex)) {
    notify("No se pudo mover al estudiante a ese grupo.", true);
    renderGroupEditor();
    return;
  }
  renderGroupEditor();
});
elements.groupEditor.addEventListener("dragstart", (event) => {
  if (!state.groupPlanEditing) return;
  const row = event.target.closest("[data-group-drag]");
  if (!row || !event.dataTransfer) return;
  state.draggedStudentId = Number(row.dataset.groupDrag);
  event.dataTransfer.setData("text/plain", String(state.draggedStudentId));
  event.dataTransfer.effectAllowed = "move";
  row.classList.add("is-dragging");
});
elements.groupEditor.addEventListener("dragend", (event) => {
  const row = event.target.closest("[data-group-drag]");
  if (row) row.classList.remove("is-dragging");
  state.draggedStudentId = null;
  elements.groupEditor.querySelectorAll(".is-drop-target").forEach((card) => {
    card.classList.remove("is-drop-target");
  });
});
elements.groupEditor.addEventListener("dragover", (event) => {
  if (!state.groupPlanEditing) return;
  const card = event.target.closest("[data-group-drop]");
  if (!card || !event.dataTransfer) return;
  const targetIndex = Number(card.dataset.groupDrop);
  const studentId = state.draggedStudentId;
  if (studentId === null) return;
  const sourceIndex = state.draftGroups.findIndex((group) => group.student_ids.includes(studentId));
  const isUnassigned = getUnassignedStudents().some((student) => Number(student.id) === studentId);
  if ((sourceIndex >= 0 || isUnassigned) && targetIndex >= -1 && targetIndex < state.draftGroups.length) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    card.classList.add("is-drop-target");
  }
});
elements.groupEditor.addEventListener("dragleave", (event) => {
  const card = event.target.closest("[data-group-drop]");
  if (card && !card.contains(event.relatedTarget)) card.classList.remove("is-drop-target");
});
elements.groupEditor.addEventListener("drop", (event) => {
  if (!state.groupPlanEditing) return;
  const card = event.target.closest("[data-group-drop]");
  if (!card || !event.dataTransfer) return;
  event.preventDefault();
  const studentId = state.draggedStudentId ?? Number(event.dataTransfer.getData("text/plain"));
  const targetIndex = Number(card.dataset.groupDrop);
  if (!moveStudentToGroup(studentId, targetIndex)) return;
  state.draggedStudentId = null;
  renderGroupEditor();
});
elements.groupEditor.addEventListener("click", (event) => {
  if (!state.groupPlanEditing) return;
  const removeButton = event.target.closest("[data-remove-group]");
  if (!removeButton) return;
  const index = Number(removeButton.dataset.removeGroup);
  if (state.draftGroups.length <= 1) {
    notify("La propuesta debe conservar al menos un grupo.", true);
    return;
  }
  const group = state.draftGroups[index];
  if (!group) return;
  const message = group.student_ids.length
    ? `¿Eliminar el grupo "${group.name}"? Sus ${group.student_ids.length} estudiantes pasarán a "Alumnos sin grupo".`
    : `¿Eliminar el grupo vacío "${group.name}"?`;
  if (!window.confirm(message)) return;
  state.draftGroups.splice(index, 1);
  state.draftGroups.forEach((group) => {
    group.student_ids = group.student_ids.map(Number);
  });
  renderGroupEditor();
});
elements.addGroupButton.addEventListener("click", () => {
  if (!state.groupPlanEditing) return;
  if (state.draftGroups.length >= 100) return;
  state.draftGroups.push({
    name: nextGroupName(),
    student_ids: [],
  });
  renderGroupEditor();
});
elements.saveGroupPlanButton.addEventListener("click", saveGroupPlan);
elements.deleteGroupPlanButton.addEventListener("click", deleteGroupPlan);
elements.editGroupPlanButton.addEventListener("click", startGroupPlanEditing);
elements.cancelGroupEditsButton.addEventListener("click", cancelGroupPlanEditing);
$("#refresh-participations").addEventListener("click", loadParticipationHistory);
elements.activeRole.addEventListener("change", () => {
  if (state.authenticatedUser?.role !== "administrador") return;
  state.viewAs = elements.activeRole.value;
  if (state.viewAs === "administrador" && ["daily", "grades"].includes(state.appView)) {
    state.appView = "cycles";
  }
  if (
    state.viewAs === "docente"
    && ["cycles", "teachers", "studentAccounts", "createCourse"].includes(state.appView)
  ) {
    state.appView = "enrollment";
  }
  setAppView(state.appView);
  setCourseView(state.courseView);
  notify(
    state.viewAs === "docente"
      ? "Vista Docente (previsualización). Tus permisos reales siguen siendo de administrador."
      : "Vista Administrador.",
  );
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

$("#temporary-password-close").addEventListener("click", () => {
  elements.temporaryPasswordDialog.close();
});
$("#temporary-password-done").addEventListener("click", () => {
  elements.temporaryPasswordDialog.close();
});
elements.temporaryPasswordDialog.addEventListener("close", clearTemporaryPassword);
$("#copy-temporary-password").addEventListener("click", async () => {
  const passwordField = $("#temporary-password-value");
  try {
    if (!navigator.clipboard?.writeText) throw new Error("El portapapeles no está disponible.");
    await navigator.clipboard.writeText(passwordField.value);
    notify("Contraseña temporal copiada.");
  } catch {
    passwordField.select();
    notify("No se pudo copiar automáticamente. La contraseña quedó seleccionada para copiarla.", true);
  }
});

$("#today-label").textContent = new Intl.DateTimeFormat("es", { dateStyle: "long" }).format(new Date());
setAppView("daily");
renderRecentCourses();
checkApi();
setInterval(checkApi, 30000);
initializeAuthentication();