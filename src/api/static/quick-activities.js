// Cacería en vivo — Sprint 7 (S12, 16–22 nov 2026).
//
// * Docente (pestaña "Cacería en vivo" del curso): prepara preguntas
//   cortas, publica la actividad con un código temporal y ve las respuestas
//   registradas (HU-Q3). La generación de preguntas con IA (HU-Q1) y la
//   imagen QR (HU-Q2) se conectan sobre esta misma pantalla: el QR solo
//   tiene que codificar el enlace que ya se muestra.
// * Estudiante (portal, "Unirse a actividad"): ingresa el código o abre el
//   enlace `/?actividad=CÓDIGO`; el servidor valida vigencia, pertenencia al
//   curso y envío único (HU-Q5) y registra sus respuestas en su cuenta.
//
// Se carga después de app.js y usa su estado (`state`), `api`, `notify`,
// `escapeHtml`, `setBusy`, `setCourseView` y `elements`.

const quickState = {
  mode: "live",
  activities: [],
  drafts: [],
  responsesFor: null,
  responses: null,
  // HU-Q4: el panel muestra "results" (resumen) o "responses" (detalle).
  panelView: "results",
  results: null,
  tickTimer: null,
  pollTimer: null,
  joined: null,
  joinCode: "",
};

const OPTION_LETTERS = "ABCDEF";
const JOIN_CODE_STORAGE = "aula-join-code";

// --------------------------------------------------------------------------
// Enlace del QR: /?actividad=CÓDIGO
// --------------------------------------------------------------------------

(function captureJoinCodeFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("actividad");
  if (code) {
    // Se guarda en la pestaña para que sobreviva al inicio de sesión y al
    // cambio obligatorio de contraseña.
    sessionStorage.setItem(JOIN_CODE_STORAGE, code.trim().toUpperCase());
    params.delete("actividad");
    const query = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }
})();

function pendingJoinCode() {
  return sessionStorage.getItem(JOIN_CODE_STORAGE) || "";
}

function clearPendingJoinCode() {
  sessionStorage.removeItem(JOIN_CODE_STORAGE);
}

function formatClock(value) {
  return new Date(value).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(value) {
  return new Date(value).toLocaleString("es", { dateStyle: "short", timeStyle: "short" });
}

function remainingLabel(expiresAt) {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "Vencida";
  const totalSeconds = Math.ceil(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function joinLink(activity) {
  return `${window.location.origin}${activity.join_url}`;
}

function qrUrl(activity) {
  // El código va en la URL para que el navegador no reutilice una imagen
  // anterior si el docente publica otra actividad.
  return `/courses/${activity.course_id}/quick-activities/${activity.id}/qr.svg?c=${activity.join_code}`;
}

// --------------------------------------------------------------------------
// Docente
// --------------------------------------------------------------------------

function newQuestionDraft() {
  return { prompt: "", type: "choice", options: "", correct: "" };
}

function resetQuickActivities(reloadIfVisible = false) {
  clearInterval(quickState.tickTimer);
  clearInterval(quickState.pollTimer);
  if (!state.authenticatedUser) {
    // Cierre de sesión: no debe quedar a la vista la actividad de otra cuenta.
    quickState.joined = null;
    quickState.joinCode = "";
    stopStudentTimer();
    if (typeof stopStudentLive === "function") stopStudentLive();
    if (typeof closeLiveStage === "function") closeLiveStage();
    if (typeof closeScanner === "function") closeScanner();
  }
  quickState.activities = [];
  quickState.responsesFor = null;
  quickState.responses = null;
  quickState.results = null;
  if (!quickState.drafts.length) quickState.drafts = [newQuestionDraft()];
  renderQuickActivities();
  if (reloadIfVisible && state.courseView === "quick" && state.course) loadQuickActivities();
}

function renderQuestionDrafts() {
  const list = $("#quick-question-list");
  if (!list) return;
  list.innerHTML = quickState.drafts.map((draft, index) => {
    const options = draft.options.split("\n").map((option) => option.trim()).filter(Boolean);
    return `
    <fieldset class="quick-question" data-draft-index="${index}">
      <legend>Pregunta ${index + 1}</legend>
      <label class="sr-only" for="quick-prompt-${index}">Enunciado de la pregunta ${index + 1}</label>
      <textarea class="field" id="quick-prompt-${index}" data-draft-field="prompt" rows="2" maxlength="1000"
        placeholder="Escribe la pregunta" required>${escapeHtml(draft.prompt)}</textarea>
      <div class="quick-question-row">
        <label class="form-label" for="quick-type-${index}">Tipo</label>
        <select class="field" id="quick-type-${index}" data-draft-field="type" ${quickState.mode === "live" ? "disabled" : ""}>
          <option value="open" ${draft.type === "open" ? "selected" : ""}>Respuesta abierta</option>
          <option value="choice" ${draft.type === "choice" ? "selected" : ""}>Opción múltiple</option>
        </select>
        <button class="button button-quiet button-danger" type="button" data-remove-draft="${index}"
          ${quickState.drafts.length === 1 ? "disabled" : ""}>Quitar</button>
      </div>
      ${draft.type === "choice" ? `
        <label class="form-label" for="quick-options-${index}">Alternativas (una por línea, de 2 a 6)</label>
        <textarea class="field" id="quick-options-${index}" data-draft-field="options" rows="3">${escapeHtml(draft.options)}</textarea>
        <label class="form-label" for="quick-correct-${index}">Alternativa correcta ${quickState.mode === "live" ? "" : '<span class="optional">OPCIONAL</span>'}</label>
        <select class="field" id="quick-correct-${index}" data-draft-field="correct">
          <option value="">${quickState.mode === "live" ? "Elige la correcta" : "Sin respuesta correcta"}</option>
          ${options.map((option, optionIndex) => `
            <option value="${optionIndex}" ${String(optionIndex) === String(draft.correct) ? "selected" : ""}>
              ${OPTION_LETTERS[optionIndex] || optionIndex + 1}. ${escapeHtml(option)}
            </option>`).join("")}
        </select>` : ""}
    </fieldset>`;
  }).join("");
  $("#quick-add-question").disabled = quickState.drafts.length >= 20;
}

function availabilityChip(activity) {
  const labels = {
    draft: ["Borrador", "is-draft"],
    open: [`Abierta · ${remainingLabel(activity.expires_at)}`, "is-open"],
    expired: ["Vencida", "is-expired"],
    closed: ["Cerrada", "is-closed"],
  };
  const [label, tone] = labels[activity.availability] || [activity.availability, ""];
  return `<span class="quick-chip ${tone}" data-quick-chip="${activity.id}">${escapeHtml(label)}</span>`;
}

function renderQuickActivities() {
  const list = $("#quick-activity-list");
  if (!list) return;
  if (!quickState.drafts.length) quickState.drafts = [newQuestionDraft()];
  renderQuestionDrafts();
  $("#quick-count").textContent = quickState.activities.length;
  $("#quick-empty").hidden = quickState.activities.length > 0;
  const courseDisabled = state.course?.enabled === false;
  $("#quick-create-submit").disabled = courseDisabled;
  list.innerHTML = quickState.activities.map((activity) => {
    const open = activity.availability === "open";
    const live = activity.mode === "live";
    const liveRunning = live && activity.status === "published";
    const canPublish = activity.status !== "closed" && !courseDisabled
      && !(live && activity.live_phase && activity.live_phase !== "lobby");
    return `
    <article class="quick-activity-row ${open || liveRunning ? "is-open" : ""}">
      <div class="quick-activity-main">
        <strong>${escapeHtml(activity.title)}</strong>
        <span class="quick-chip ${live ? "is-live" : "is-legacy"}">${live ? `En vivo · ${activity.question_seconds} s` : "Actividad anterior"}</span>
        ${availabilityChip(activity)}
        <span class="form-note">${activity.questions.length} pregunta${activity.questions.length === 1 ? "" : "s"}
          · ${activity.response_count} envío${activity.response_count === 1 ? "" : "s"}
          ${live ? "" : activity.allow_multiple_responses ? "· admite reenvíos" : "· un envío por estudiante"}
          ${activity.expires_at && activity.availability !== "draft" ? `· vence ${formatClock(activity.expires_at)}` : ""}</span>
      </div>
      ${open ? `
        <div class="quick-join-box">
          <img class="quick-join-qr" src="${qrUrl(activity)}" alt="Código QR para unirse a ${escapeHtml(activity.title)}" width="148" height="148" />
          <div class="quick-join-text">
            <span class="form-label">Código para tus estudiantes</span>
            <span class="quick-join-code" aria-label="Código ${escapeHtml(activity.join_code.split("").join(" "))}">${escapeHtml(activity.join_code)}</span>
            <span class="quick-join-link">${escapeHtml(joinLink(activity))}</span>
            <button class="button button-quiet" type="button" data-copy-join="${activity.id}">Copiar enlace</button>
          </div>
        </div>` : ""}
      <div class="quick-activity-actions">
        ${canPublish ? `
          <label class="sr-only" for="quick-minutes-${activity.id}">${live ? "Minutos para unirse" : "Minutos de vigencia"}</label>
          <input class="field quick-minutes" id="quick-minutes-${activity.id}" type="number" min="1" max="240" value="${live ? 60 : 10}"
            title="${live ? "Minutos en que el código acepta ingresos" : "Minutos de vigencia del código"}" />
          <button class="button ${live && activity.status !== "draft" ? "button-quiet" : "button-add"}" type="button" data-publish-quick="${activity.id}">
            ${activity.status === "draft" ? "Publicar" : "Extender vigencia"}
          </button>` : ""}
        ${liveRunning ? `
          <button class="button button-add" type="button" data-open-live="${activity.id}">Abrir pantalla en vivo</button>` : ""}
        ${activity.status === "published" ? `
          <button class="button button-quiet" type="button" data-close-quick="${activity.id}">Cerrar</button>` : ""}
        ${activity.status !== "draft" ? `
          <button class="button button-quiet" type="button" data-view-quick="${activity.id}">Resultados</button>` : ""}
      </div>
    </article>`;
  }).join("");
  renderQuickResponses();
  scheduleQuickTimers();
}

function percent(value) {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)} %`;
}

function rateTone(value) {
  if (value === null || value === undefined) return "";
  if (value >= 0.75) return "is-high";
  if (value >= 0.5) return "is-medium";
  return "is-low";
}

function panelHeading(activity, eyebrow, note) {
  const view = quickState.panelView;
  return `
    <div class="panel-heading">
      <div>
        <p class="eyebrow">${eyebrow}</p>
        <h3>${escapeHtml(activity.title)}</h3>
        <p class="form-note">${note}</p>
      </div>
      <div class="cycle-actions">
        <div class="quick-panel-switch" role="group" aria-label="Vista de resultados">
          <button class="button button-quiet ${view === "results" ? "is-active" : ""}" type="button" data-panel-view="results" aria-pressed="${view === "results"}">Resumen</button>
          <button class="button button-quiet ${view === "responses" ? "is-active" : ""}" type="button" data-panel-view="responses" aria-pressed="${view === "responses"}">Respuestas por estudiante</button>
        </div>
        <button class="button button-quiet" type="button" data-refresh-responses="${activity.id}">Actualizar</button>
        <button class="button button-quiet" type="button" data-hide-responses>Ocultar</button>
      </div>
    </div>`;
}

// HU-Q4: resumen para conocer el nivel de comprensión del grupo.
function renderResultsHtml(data) {
  const levels = { alto: "Comprensión alta", medio: "Comprensión media", bajo: "Comprensión baja" };
  const live = data.activity.mode === "live";
  const note = `${data.respondent_count} de ${data.enrolled_count} estudiante${data.enrolled_count === 1 ? "" : "s"} matriculado${data.enrolled_count === 1 ? "" : "s"} participaron. Los porcentajes se calculan sobre quienes participaron${live ? "; no responder a tiempo cuenta como no acertar" : ""}.`;
  const hardest = data.questions.find((question) => question.position === data.hardest_question_position);
  const cards = `
    <div class="quick-result-cards">
      <div class="quick-result-card">
        <span>Participación</span>
        <strong>${data.respondent_count} / ${data.enrolled_count}</strong>
        <small>${percent(data.participation_rate)} del curso</small>
      </div>
      <div class="quick-result-card ${rateTone(data.group_score)}">
        <span>Aciertos promedio del grupo</span>
        <strong>${percent(data.group_score)}</strong>
        <small>${data.comprehension_level ? levels[data.comprehension_level] : data.scored_question_count ? "Sin participantes todavía" : "Sin preguntas calificables"}</small>
      </div>
      <div class="quick-result-card">
        <span>Preguntas calificadas</span>
        <strong>${data.scored_question_count} de ${data.questions.length}</strong>
        <small>${data.open_question_count ? `${data.open_question_count} abierta${data.open_question_count === 1 ? "" : "s"}, sin calificar` : "Todas con respuesta correcta"}</small>
      </div>
      <div class="quick-result-card ${hardest ? rateTone(hardest.correct_rate) : ""}">
        <span>Pregunta con menos aciertos</span>
        <strong>${hardest ? `P${hardest.position}` : "—"}</strong>
        <small>${hardest ? `${percent(hardest.correct_rate)} de aciertos` : "Sin datos"}</small>
      </div>
    </div>`;
  const questionHtml = data.questions.map((question) => {
    const header = `
      <div class="quick-result-question-head">
        <strong>P${question.position}. ${escapeHtml(question.prompt)}</strong>
        ${question.correct_rate !== null && question.correct_rate !== undefined
          ? `<span class="quick-rate ${rateTone(question.correct_rate)}">${percent(question.correct_rate)} aciertos</span>`
          : `<span class="quick-rate">Sin calificar</span>`}
      </div>`;
    if (question.kind === "choice") {
      const base = data.respondent_count || 1;
      return `<li class="quick-result-question">${header}
        <div class="quick-result-options">
          ${question.options.map((option, index) => {
            const count = question.distribution?.[index] ?? 0;
            const correct = index === question.correct_option;
            return `
            <div class="quick-result-option ${correct ? "is-correct" : ""}">
              <span class="quick-result-option-label">${OPTION_LETTERS[index]}. ${escapeHtml(option)}${correct ? " ✓" : ""}</span>
              <span class="quick-result-bar" aria-hidden="true"><span style="width:${Math.round((count / base) * 100)}%"></span></span>
              <span class="quick-result-count">${count} · ${Math.round((count / base) * 100)} %</span>
            </div>`;
          }).join("")}
        </div>
        <p class="form-note">${question.answered_count} respondieron esta pregunta.</p>
      </li>`;
    }
    return `<li class="quick-result-question">${header}
      <details class="quick-open-answers" ${question.open_answers.length <= 5 ? "open" : ""}>
        <summary>${question.open_answers.length} respuesta${question.open_answers.length === 1 ? "" : "s"} abierta${question.open_answers.length === 1 ? "" : "s"} · se leen y califican aparte</summary>
        <ul>${question.open_answers.map((answer) => `
          <li><strong>${escapeHtml(answer.student_name)}</strong> <small>${escapeHtml(answer.student_code)}</small><p>${escapeHtml(answer.answer_text)}</p></li>`).join("")}
        </ul>
      </details>
    </li>`;
  }).join("");
  const studentRows = data.students.map((student) => `
    <tr>
      <th scope="row"><strong>${escapeHtml(student.student_name)}</strong><small>${escapeHtml(student.student_code)}</small></th>
      <td>${student.correct_count === null ? "—" : `${student.correct_count} / ${data.scored_question_count}`}</td>
      <td><span class="quick-rate ${rateTone(student.score_rate)}">${percent(student.score_rate)}</span></td>
      ${live ? `<td>${student.points ?? 0}</td>` : `<td>${student.attempt > 1 ? `#${student.attempt}` : "1"}</td>`}
    </tr>`).join("");
  return `
    ${panelHeading(data.activity, "RESULTADOS DE LA ACTIVIDAD", note)}
    ${cards}
    ${data.respondent_count ? `
      <h4 class="quick-result-subtitle">Por pregunta</h4>
      <ol class="quick-result-questions">${questionHtml}</ol>
      <h4 class="quick-result-subtitle">Por estudiante</h4>
      <div class="quick-table-wrap">
        <table class="quick-response-table">
          <thead><tr>
            <th scope="col">Estudiante</th><th scope="col">Aciertos</th><th scope="col">% aciertos</th>
            <th scope="col">${live ? "Puntos" : "Envío contado"}</th>
          </tr></thead>
          <tbody>${studentRows}</tbody>
        </table>
      </div>` : '<p class="history-none">Todavía no hay respuestas registradas.</p>'}`;
}

function renderQuickResponses() {
  const panel = $("#quick-responses");
  if (!panel) return;
  if (quickState.panelView === "results") {
    const results = quickState.results;
    if (!results || results.activity.id !== quickState.responsesFor) {
      panel.hidden = true;
      panel.innerHTML = "";
      return;
    }
    panel.hidden = false;
    panel.innerHTML = renderResultsHtml(results);
    return;
  }
  const data = quickState.responses;
  if (!data || data.activity.id !== quickState.responsesFor) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  const questions = data.activity.questions;
  const answerCell = (question, answer) => {
    if (!answer) return '<td class="quick-answer is-empty">—</td>';
    if (question.options) {
      const letter = OPTION_LETTERS[answer.selected_option] || answer.selected_option + 1;
      const text = `${letter}. ${question.options[answer.selected_option] ?? ""}`;
      const mark = answer.is_correct === true ? " ✓" : answer.is_correct === false ? " ✗" : "";
      const tone = answer.is_correct === true ? "is-correct" : answer.is_correct === false ? "is-wrong" : "";
      return `<td class="quick-answer ${tone}">${escapeHtml(text)}${mark}</td>`;
    }
    return `<td class="quick-answer">${escapeHtml(answer.answer_text || "")}</td>`;
  };
  panel.hidden = false;
  panel.innerHTML = `
    ${panelHeading(
      data.activity,
      "RESPUESTAS REGISTRADAS",
      `${data.respondent_count} de ${data.enrolled_count} estudiante${data.enrolled_count === 1 ? "" : "s"} matriculado${data.enrolled_count === 1 ? "" : "s"} ${data.respondent_count === 1 ? "respondió" : "respondieron"} · ${data.responses.length} envío${data.responses.length === 1 ? "" : "s"}.`,
    )}
    ${data.responses.length ? `
      <div class="quick-table-wrap">
        <table class="quick-response-table">
          <thead>
            <tr>
              <th scope="col">Estudiante</th>
              <th scope="col">Envío</th>
              ${questions.map((question) => `<th scope="col" title="${escapeHtml(question.prompt)}">P${question.position}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${data.responses.map((response) => {
              const byQuestion = new Map(response.answers.map((answer) => [answer.question_id, answer]));
              return `<tr>
                <th scope="row"><strong>${escapeHtml(response.student_name)}</strong><small>${escapeHtml(response.student_code)}</small></th>
                <td>${response.attempt > 1 ? `#${response.attempt} · ` : ""}${formatClock(response.submitted_at)}</td>
                ${questions.map((question) => answerCell(question, byQuestion.get(question.id))).join("")}
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
      <ol class="quick-question-legend">
        ${questions.map((question) => `<li><strong>P${question.position}.</strong> ${escapeHtml(question.prompt)}</li>`).join("")}
      </ol>` : '<p class="history-none">Todavía no se registran respuestas.</p>'}`;
}

function scheduleQuickTimers() {
  clearInterval(quickState.tickTimer);
  clearInterval(quickState.pollTimer);
  const hasOpen = quickState.activities.some((activity) => activity.availability === "open");
  if (!hasOpen) return;
  // Cuenta regresiva visible del código.
  quickState.tickTimer = setInterval(() => {
    let expiredNow = false;
    quickState.activities.forEach((activity) => {
      if (activity.availability !== "open") return;
      const chip = document.querySelector(`[data-quick-chip="${activity.id}"]`);
      const label = remainingLabel(activity.expires_at);
      if (label === "Vencida") expiredNow = true;
      if (chip) chip.textContent = `Abierta · ${label}`;
    });
    if (expiredNow) loadQuickActivities();
  }, 1000);
  // Mientras haya una actividad abierta, se refrescan los envíos.
  quickState.pollTimer = setInterval(() => {
    if (state.courseView !== "quick" || elements.workspace.hidden || document.hidden) return;
    loadQuickActivities({ quiet: true });
  }, 15000);
}

async function loadQuickActivities({ quiet = false } = {}) {
  if (!state.course) return;
  const courseId = state.course.id;
  try {
    const activities = await api(`/courses/${courseId}/quick-activities`);
    if (state.course?.id !== courseId) return;
    quickState.activities = activities;
    if (quickState.responsesFor) {
      const kind = quickState.panelView === "results" ? "results" : "responses";
      quickState[kind] = await api(
        `/courses/${courseId}/quick-activities/${quickState.responsesFor}/${kind}`,
      );
    }
    renderQuickActivities();
  } catch (error) {
    if (!quiet) notify(error.message, true);
  }
}

function collectQuestionPayload() {
  return quickState.drafts.map((draft, index) => {
    const prompt = draft.prompt.trim();
    if (!prompt) throw new Error(`La pregunta ${index + 1} está vacía.`);
    if (draft.type !== "choice") return { prompt };
    const options = draft.options.split("\n").map((option) => option.trim()).filter(Boolean);
    if (options.length < 2 || options.length > 6) {
      throw new Error(`La pregunta ${index + 1} debe tener entre 2 y 6 alternativas.`);
    }
    if (quickState.mode === "live" && draft.correct === "") {
      throw new Error(`Marca la alternativa correcta de la pregunta ${index + 1}: en vivo se puntúa al instante.`);
    }
    return {
      prompt,
      options,
      correct_option: draft.correct === "" ? null : Number(draft.correct),
    };
  });
}

$("#quick-question-list")?.addEventListener("input", (event) => {
  const field = event.target.dataset.draftField;
  const container = event.target.closest("[data-draft-index]");
  if (!field || !container) return;
  const draft = quickState.drafts[Number(container.dataset.draftIndex)];
  draft[field] = event.target.value;
  if (field === "options") {
    // Las alternativas cambian la lista de "correcta" sin perder el foco.
    const select = container.querySelector('[data-draft-field="correct"]');
    const options = draft.options.split("\n").map((option) => option.trim()).filter(Boolean);
    if (Number(draft.correct) >= options.length) draft.correct = "";
    if (select) {
      select.innerHTML = `<option value="">Sin respuesta correcta</option>${options.map((option, optionIndex) => `
        <option value="${optionIndex}" ${String(optionIndex) === String(draft.correct) ? "selected" : ""}>
          ${OPTION_LETTERS[optionIndex] || optionIndex + 1}. ${escapeHtml(option)}</option>`).join("")}`;
    }
  }
});

$("#quick-question-list")?.addEventListener("change", (event) => {
  const field = event.target.dataset.draftField;
  const container = event.target.closest("[data-draft-index]");
  if (!field || !container) return;
  quickState.drafts[Number(container.dataset.draftIndex)][field] = event.target.value;
  if (field === "type") renderQuestionDrafts();
});

$("#quick-question-list")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-draft]");
  if (!button) return;
  quickState.drafts.splice(Number(button.dataset.removeDraft), 1);
  renderQuestionDrafts();
});

$("#quick-add-question")?.addEventListener("click", () => {
  quickState.drafts.push(newQuestionDraft());
  renderQuestionDrafts();
  $(`#quick-prompt-${quickState.drafts.length - 1}`)?.focus();
});

$("#quick-create-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.course) return;
  const button = $("#quick-create-submit");
  let questions;
  try {
    questions = collectQuestionPayload();
  } catch (error) {
    notify(error.message, true);
    return;
  }
  setBusy(button, true, "Guardando...");
  try {
    const activity = await api(`/courses/${state.course.id}/quick-activities`, {
      method: "POST",
      body: JSON.stringify({
        title: $("#quick-title-input").value.trim(),
        mode: "live",
        question_seconds: Number($("#quick-question-seconds").value) || 30,
        allow_multiple_responses: false,
        class_session_id: state.session?.id || null,
        questions,
      }),
    });
    quickState.drafts = [newQuestionDraft()];
    $("#quick-title-input").value = "";
    await loadQuickActivities();
    notify(`Quiz en vivo “${activity.title}” guardado. Publícalo para generar el código y el QR.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#quick-activity-list")?.addEventListener("click", async (event) => {
  if (!state.course) return;
  const courseId = state.course.id;
  const publishButton = event.target.closest("[data-publish-quick]");
  const closeButton = event.target.closest("[data-close-quick]");
  const viewButton = event.target.closest("[data-view-quick]");
  const copyButton = event.target.closest("[data-copy-join]");
  const liveButton = event.target.closest("[data-open-live]");
  if (liveButton) {
    if (typeof openLiveStage === "function") openLiveStage(Number(liveButton.dataset.openLive));
    return;
  }
  if (publishButton) {
    const id = Number(publishButton.dataset.publishQuick);
    const minutes = Number($(`#quick-minutes-${id}`)?.value) || 10;
    setBusy(publishButton, true, "Publicando...");
    try {
      const activity = await api(`/courses/${courseId}/quick-activities/${id}/publish`, {
        method: "POST",
        body: JSON.stringify({ duration_minutes: minutes }),
      });
      await loadQuickActivities();
      notify(`Código ${activity.join_code} vigente hasta las ${formatClock(activity.expires_at)}.`);
      // Quiz en vivo: se abre directamente la sala de espera para proyectarla.
      if (activity.mode === "live" && activity.live_phase === "lobby" && typeof openLiveStage === "function") {
        openLiveStage(activity.id);
      }
    } catch (error) {
      notify(error.message, true);
      setBusy(publishButton, false);
    }
    return;
  }
  if (closeButton) {
    const id = Number(closeButton.dataset.closeQuick);
    const activity = quickState.activities.find((item) => item.id === id);
    if (!window.confirm(`¿Cerrar “${activity?.title || "la actividad"}”? El código dejará de aceptar respuestas.`)) return;
    setBusy(closeButton, true, "Cerrando...");
    try {
      await api(`/courses/${courseId}/quick-activities/${id}/close`, { method: "POST" });
      await loadQuickActivities();
      notify("Actividad cerrada.");
    } catch (error) {
      notify(error.message, true);
      setBusy(closeButton, false);
    }
    return;
  }
  if (viewButton) {
    quickState.responsesFor = Number(viewButton.dataset.viewQuick);
    quickState.panelView = "results";
    await loadQuickActivities();
    $("#quick-responses")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (copyButton) {
    const activity = quickState.activities.find((item) => item.id === Number(copyButton.dataset.copyJoin));
    if (!activity) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error();
      await navigator.clipboard.writeText(joinLink(activity));
      notify("Enlace copiado.");
    } catch {
      notify(`Comparte este enlace: ${joinLink(activity)}`);
    }
  }
});

$("#quick-responses")?.addEventListener("click", (event) => {
  if (event.target.closest("[data-hide-responses]")) {
    quickState.responsesFor = null;
    quickState.responses = null;
    quickState.results = null;
    renderQuickResponses();
    return;
  }
  const switchButton = event.target.closest("[data-panel-view]");
  if (switchButton) {
    quickState.panelView = switchButton.dataset.panelView;
    loadQuickActivities();
    return;
  }
  if (event.target.closest("[data-refresh-responses]")) loadQuickActivities();
});

$("#refresh-quick")?.addEventListener("click", () => loadQuickActivities());

elements.quickTab?.addEventListener("click", () => {
  setCourseView("quick");
  loadQuickActivities();
});

// --------------------------------------------------------------------------
// Estudiante — HU-Q5 (unirse) y HU-Q3 (enviar)
// --------------------------------------------------------------------------

function setJoinStatus(message, isError = false) {
  const status = $("#student-join-status");
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}

function stopStudentTimer() {
  clearInterval(quickState.studentTimer);
  quickState.studentTimer = null;
}

function renderStudentActivity() {
  const form = $("#student-activity-form");
  const activity = quickState.joined;
  form.hidden = !activity;
  if (!activity) {
    stopStudentTimer();
    return;
  }
  $("#student-join-form").hidden = true;
  $("#student-activity-done").hidden = true;
  $("#student-activity-course").textContent = activity.course_name.toUpperCase();
  $("#student-activity-name").textContent = activity.title;
  $("#student-activity-questions").innerHTML = activity.questions.map((question) => `
    <li class="student-question" data-question-id="${question.id}">
      <p class="student-question-prompt">${escapeHtml(question.prompt)}</p>
      ${question.options
        ? `<div class="student-question-options" role="radiogroup" aria-label="Alternativas de la pregunta ${question.position}">
            ${question.options.map((option, index) => `
              <label class="student-option">
                <input type="radio" name="question-${question.id}" value="${index}" required />
                <span><b>${OPTION_LETTERS[index]}.</b> ${escapeHtml(option)}</span>
              </label>`).join("")}
          </div>`
        : `<label class="sr-only" for="answer-${question.id}">Tu respuesta</label>
           <textarea class="field" id="answer-${question.id}" name="question-${question.id}" rows="3" maxlength="2000" required></textarea>`}
    </li>`).join("");
  const timer = $("#student-activity-timer");
  const tick = () => {
    const label = remainingLabel(activity.expires_at);
    timer.textContent = label === "Vencida" ? "Código vencido" : `Vence en ${label}`;
    timer.classList.toggle("is-expired", label === "Vencida");
  };
  stopStudentTimer();
  tick();
  quickState.studentTimer = setInterval(tick, 1000);
}

async function loadStudentSubmissions() {
  try {
    const submissions = await api("/student/quick-activities/responses");
    $("#student-submission-list").innerHTML = submissions.map((item) => `
      <article class="student-history-item">
        <strong>${escapeHtml(item.activity_title)}</strong>
        <span>${escapeHtml(item.course_name)} · ${formatDateTime(item.submitted_at)}${item.attempt > 1 ? ` · envío #${item.attempt}` : ""}</span>
      </article>`).join("");
    $("#student-submission-empty").hidden = submissions.length > 0;
  } catch (error) {
    $("#student-submission-empty").hidden = false;
    $("#student-submission-empty").textContent = error.message;
  }
}

async function joinActivity(code) {
  const button = $("#student-join-submit");
  setBusy(button, true, "Validando...");
  setJoinStatus("");
  try {
    quickState.joined = await api("/student/quick-activities/join", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    quickState.joinCode = code;
    if (quickState.joined.mode === "live") {
      const activity = quickState.joined;
      quickState.joined = null;
      $("#student-join-form").hidden = true;
      if (typeof startStudentLive === "function") startStudentLive(activity);
      return;
    }
    if (quickState.joined.previous_attempts) {
      const attempts = quickState.joined.previous_attempts;
      setJoinStatus(`Ya enviaste ${attempts} ${attempts === 1 ? "vez" : "veces"}; el docente permite responder de nuevo.`);
    }
    renderStudentActivity();
  } catch (error) {
    quickState.joined = null;
    renderStudentActivity();
    setJoinStatus(error.message, true);
  } finally {
    setBusy(button, false);
    clearPendingJoinCode();
  }
}

function resetStudentJoin() {
  if (typeof stopStudentLive === "function") stopStudentLive();
  quickState.joined = null;
  quickState.joinCode = "";
  renderStudentActivity();
  $("#student-join-form").hidden = false;
  $("#student-join-code").value = "";
}

function openStudentActivityView() {
  loadStudentSubmissions();
  const code = pendingJoinCode();
  if (code && !quickState.joined) {
    $("#student-join-code").value = code;
    joinActivity(code);
  } else if (!quickState.joined) {
    $("#student-join-form").hidden = false;
    $("#student-join-code").focus();
  }
}

$("#student-join-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  const code = $("#student-join-code").value.trim();
  if (code) joinActivity(code);
});

$("#student-activity-cancel")?.addEventListener("click", () => {
  if (!window.confirm("¿Salir sin enviar tus respuestas?")) return;
  resetStudentJoin();
  setJoinStatus("");
});

$("#student-activity-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const activity = quickState.joined;
  if (!activity) return;
  const form = event.currentTarget;
  const answers = activity.questions.map((question) => {
    if (question.options) {
      const checked = form.querySelector(`input[name="question-${question.id}"]:checked`);
      return { question_id: question.id, selected_option: checked ? Number(checked.value) : null };
    }
    return {
      question_id: question.id,
      answer_text: form.querySelector(`[name="question-${question.id}"]`).value.trim(),
    };
  });
  const button = $("#student-activity-submit");
  setBusy(button, true, "Enviando...");
  try {
    const result = await api(`/student/quick-activities/${activity.id}/responses`, {
      method: "POST",
      body: JSON.stringify({ code: quickState.joinCode, answers }),
    });
    quickState.joined = null;
    renderStudentActivity();
    const done = $("#student-activity-done");
    done.hidden = false;
    done.innerHTML = `
      <p class="eyebrow">RESPUESTAS REGISTRADAS</p>
      <h3>¡Listo! Tu envío de “${escapeHtml(result.activity_title)}” quedó registrado.</h3>
      <p class="form-note">Se registraron ${result.answered_count} respuesta${result.answered_count === 1 ? "" : "s"} a las ${formatClock(result.submitted_at)} con tu cuenta.</p>
      <div class="cycle-actions">
        ${result.can_submit_again ? '<button class="button button-quiet" type="button" data-answer-again>Responder otra vez</button>' : ""}
        <button class="button button-add" type="button" data-join-another>Unirme a otra actividad</button>
      </div>`;
    setJoinStatus("");
    loadStudentSubmissions();
  } catch (error) {
    setJoinStatus(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#student-activity-done")?.addEventListener("click", (event) => {
  if (event.target.closest("[data-answer-again]")) {
    const code = quickState.joinCode;
    $("#student-activity-done").hidden = true;
    joinActivity(code);
    return;
  }
  if (event.target.closest("[data-join-another]")) {
    $("#student-activity-done").hidden = true;
    resetStudentJoin();
    $("#student-join-code").focus();
  }
});
