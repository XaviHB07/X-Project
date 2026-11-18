// Quiz en vivo (tipo Kahoot / Quizizz) — Sprint 7.
//
// * Docente: pantalla para proyectar. Muestra la sala de espera (código, QR y
//   participantes), una pregunta a la vez con su cuenta regresiva, los
//   resultados de cada pregunta (respuesta correcta, distribución y ranking)
//   y el podio final. El botón principal avanza el quiz.
// * Estudiante: en su celular ve la pregunta y toca una alternativa; al
//   cerrarse la pregunta ve si acertó, sus puntos y su puesto.
//
// La sincronización es por consultas cortas (cada segundo) al servidor, que
// guarda la fase actual y es el reloj de referencia. Así funciona igual con
// varios procesos del servidor y sin WebSockets.
//
// Se carga después de app.js y quick-activities.js.

const LIVE_POLL_MS = 1000;
// Los celulares consultan un poco menos seguido: con 40 estudiantes son unas
// 27 consultas por segundo en vez de 40.
const LIVE_STUDENT_POLL_MS = 1500;
const LIVE_COLORS = ["live-red", "live-blue", "live-yellow", "live-green", "live-purple", "live-teal"];
const LIVE_SHAPES = ["▲", "◆", "●", "■", "★", "⬢"];

const liveState = {
  teacher: null, // { courseId, activityId, data, fetchedAt, timer }
  student: null, // { activityId, title, data, fetchedAt, timer, sending }
  tick: null,
};

function liveRemainingSeconds(data, fetchedAt) {
  if (!data || data.phase !== "question") return 0;
  const left = data.remaining_ms - (Date.now() - fetchedAt);
  return Math.max(0, Math.ceil(left / 1000));
}

function liveOptionLabel(index) {
  return `${LIVE_SHAPES[index] || ""} ${OPTION_LETTERS[index] || index + 1}`;
}

function liveRanking(rows, limit = 5) {
  if (!rows?.length) return '<p class="form-note">Todavía no hay puntajes.</p>';
  return `<ol class="live-ranking">${rows.slice(0, limit).map((row) => `
    <li><span class="live-rank">${row.rank}</span><strong>${escapeHtml(row.student_name)}</strong>
      <span>${row.points} pts · ${row.correct} acierto${row.correct === 1 ? "" : "s"}</span></li>`).join("")}</ol>`;
}

// --------------------------------------------------------------------------
// Docente — pantalla para proyectar
// --------------------------------------------------------------------------

function renderLiveStage() {
  const live = liveState.teacher;
  if (!live?.data) return;
  const data = live.data;
  const activity = data.activity;
  $("#live-stage-title").textContent = activity.title;
  const body = $("#live-stage-body");
  const advance = $("#live-advance");
  const status = $("#live-stage-status");
  const question = data.question;

  if (data.phase === "lobby") {
    body.innerHTML = `
      <div class="live-lobby">
        <img class="live-qr" src="${qrUrl(activity)}" alt="Código QR para unirse" />
        <div class="live-lobby-info">
          <p class="live-lobby-hint">Escanea el QR o entra al portal → <strong>Unirse a actividad</strong> y escribe:</p>
          <p class="live-big-code">${escapeHtml(activity.join_code || "")}</p>
          <p class="live-lobby-link">${escapeHtml(joinLink(activity))}</p>
          <p class="live-count"><strong>${data.participant_count}</strong> participante${data.participant_count === 1 ? "" : "s"} conectado${data.participant_count === 1 ? "" : "s"}</p>
          <div class="live-participants">${data.participants.map((item) =>
            `<span>${escapeHtml(item.student_name)}</span>`).join("")}</div>
        </div>
      </div>`;
    advance.textContent = "Comenzar";
    advance.disabled = data.participant_count === 0;
    status.textContent = data.participant_count === 0 ? "Esperando a que se una al menos un estudiante." : "";
    return;
  }

  if (data.phase === "question" || data.phase === "reveal") {
    const reveal = data.phase === "reveal";
    const total = data.distribution ? data.distribution.reduce((a, b) => a + b, 0) : 0;
    body.innerHTML = `
      <div class="live-question-head">
        <span class="live-progress">Pregunta ${data.position} de ${data.question_count}</span>
        ${reveal ? '<span class="live-timer is-done">Tiempo</span>'
          : `<span class="live-timer" id="live-teacher-timer">${liveRemainingSeconds(data, live.fetchedAt)}</span>`}
        <span class="live-answered">${data.answered_count} / ${data.participant_count} respondieron</span>
      </div>
      <h3 class="live-prompt">${escapeHtml(question.prompt)}</h3>
      <div class="live-options ${reveal ? "is-reveal" : ""}">
        ${question.options.map((option, index) => {
          const correct = reveal && index === question.correct_option;
          const count = data.distribution?.[index] ?? 0;
          const width = total ? Math.round((count / total) * 100) : 0;
          return `
          <div class="live-option ${LIVE_COLORS[index]} ${reveal && !correct ? "is-dim" : ""} ${correct ? "is-correct" : ""}">
            <span class="live-option-label">${liveOptionLabel(index)}</span>
            <span class="live-option-text">${escapeHtml(option)}</span>
            ${reveal ? `<span class="live-option-count">${count}${correct ? " ✓" : ""}</span>
              <span class="live-option-bar" style="width:${width}%"></span>` : ""}
          </div>`;
        }).join("")}
      </div>
      ${reveal ? `<div class="live-board"><h4>Ranking</h4>${liveRanking(data.leaderboard)}</div>` : ""}`;
    const last = data.position >= data.question_count;
    advance.textContent = reveal ? (last ? "Ver podio final" : "Siguiente pregunta") : "Cerrar pregunta";
    advance.disabled = false;
    status.textContent = reveal ? "" : "La pregunta se cierra sola al terminar el tiempo.";
    return;
  }

  // Podio final
  const [first, second, third] = data.leaderboard;
  const step = (row, place) => row ? `
    <div class="live-podium-step place-${place}">
      <strong>${escapeHtml(row.student_name)}</strong>
      <span>${row.points} pts</span>
      <div class="live-podium-block">${place}</div>
    </div>` : `<div class="live-podium-step place-${place} is-empty"><div class="live-podium-block">${place}</div></div>`;
  body.innerHTML = `
    <div class="live-final">
      <h3>¡Quiz terminado!</h3>
      <div class="live-podium">${step(second, 2)}${step(first, 1)}${step(third, 3)}</div>
      <div class="live-board">${liveRanking(data.leaderboard, 10)}</div>
    </div>`;
  advance.textContent = "Cerrar pantalla";
  advance.disabled = false;
  status.textContent = `${data.participant_count} participante${data.participant_count === 1 ? "" : "s"}. Las respuestas quedan en "Ver respuestas".`;
}

async function fetchLiveTeacher() {
  const live = liveState.teacher;
  if (!live) return;
  try {
    const data = await api(`/courses/${live.courseId}/quick-activities/${live.activityId}/live`);
    if (liveState.teacher !== live) return;
    const changed = !live.data || live.data.phase !== data.phase || live.data.position !== data.position
      || live.data.answered_count !== data.answered_count
      || live.data.participant_count !== data.participant_count;
    live.data = data;
    live.fetchedAt = Date.now();
    if (changed) renderLiveStage();
  } catch (error) {
    $("#live-stage-status").textContent = `Sin conexión con el servidor: ${error.message}`;
  }
}

function tickLiveTimers() {
  const teacher = liveState.teacher;
  const timer = document.querySelector("#live-teacher-timer");
  if (teacher?.data && timer) timer.textContent = liveRemainingSeconds(teacher.data, teacher.fetchedAt);
  const student = liveState.student;
  const studentTimer = document.querySelector("#live-student-timer");
  if (student?.data && studentTimer) {
    studentTimer.textContent = liveRemainingSeconds(student.data, student.fetchedAt);
  }
}

function ensureLiveTick() {
  if (!liveState.tick) liveState.tick = setInterval(tickLiveTimers, 250);
}

async function openLiveStage(activityId) {
  if (!state.course) return;
  closeLiveStage();
  liveState.teacher = { courseId: state.course.id, activityId, data: null, fetchedAt: 0 };
  const dialog = $("#live-stage");
  $("#live-stage-body").innerHTML = '<p class="form-note">Cargando…</p>';
  if (!dialog.open) dialog.showModal();
  await fetchLiveTeacher();
  renderLiveStage();
  liveState.teacher.timer = setInterval(fetchLiveTeacher, LIVE_POLL_MS);
  ensureLiveTick();
}

function closeLiveStage() {
  if (liveState.teacher?.timer) clearInterval(liveState.teacher.timer);
  liveState.teacher = null;
  const dialog = $("#live-stage");
  if (dialog?.open) dialog.close();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

$("#live-advance")?.addEventListener("click", async () => {
  const live = liveState.teacher;
  if (!live?.data) return;
  if (live.data.phase === "finished") {
    closeLiveStage();
    if (typeof loadQuickActivities === "function") loadQuickActivities();
    return;
  }
  const button = $("#live-advance");
  setBusy(button, true, "Un momento...");
  try {
    live.data = await api(
      `/courses/${live.courseId}/quick-activities/${live.activityId}/live/advance`,
      { method: "POST" },
    );
    live.fetchedAt = Date.now();
    renderLiveStage();
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
    renderLiveStage();
  }
});

$("#live-stage-close")?.addEventListener("click", () => {
  closeLiveStage();
  if (typeof loadQuickActivities === "function") loadQuickActivities();
});
$("#live-stage")?.addEventListener("cancel", () => {
  if (liveState.teacher?.timer) clearInterval(liveState.teacher.timer);
  liveState.teacher = null;
});
$("#live-fullscreen")?.addEventListener("click", () => {
  const dialog = $("#live-stage");
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else dialog.requestFullscreen?.().catch(() => notify("El navegador no permitió la pantalla completa.", true));
});

// --------------------------------------------------------------------------
// Estudiante — responde desde su celular
// --------------------------------------------------------------------------

function renderStudentLive() {
  const live = liveState.student;
  const panel = $("#student-live");
  if (!live) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  panel.hidden = false;
  const data = live.data;
  const header = `
    <div class="student-live-head">
      <div><p class="eyebrow">QUIZ EN VIVO</p><h3>${escapeHtml(live.title)}</h3></div>
      ${data?.position ? `<span class="live-progress">Pregunta ${data.position} de ${data.question_count}</span>` : ""}
    </div>`;
  if (!data) {
    panel.innerHTML = `${header}<p class="form-note">Conectando…</p>`;
    return;
  }
  if (data.phase === "lobby") {
    panel.innerHTML = `${header}
      <div class="student-live-wait">
        <span class="live-pulse" aria-hidden="true"></span>
        <strong>¡Ya estás dentro!</strong>
        <p>Mira la pantalla del aula. El quiz empieza cuando tu docente lo indique.</p>
        <p class="form-note">${data.participant_count} participante${data.participant_count === 1 ? "" : "s"} conectado${data.participant_count === 1 ? "" : "s"}.</p>
      </div>`;
    return;
  }
  if (data.phase === "question" && !data.answered) {
    panel.innerHTML = `${header}
      <div class="student-live-question">
        <span class="live-timer" id="live-student-timer">${liveRemainingSeconds(data, live.fetchedAt)}</span>
        <p class="student-live-prompt">${escapeHtml(data.question.prompt)}</p>
      </div>
      <div class="student-live-options">
        ${data.question.options.map((option, index) => `
          <button class="live-answer ${LIVE_COLORS[index]}" type="button" data-live-answer="${index}" ${live.sending ? "disabled" : ""}>
            <span class="live-option-label">${liveOptionLabel(index)}</span>
            <span>${escapeHtml(option)}</span>
          </button>`).join("")}
      </div>`;
    return;
  }
  if (data.phase === "question") {
    panel.innerHTML = `${header}
      <div class="student-live-wait">
        <strong>Respuesta enviada</strong>
        <p>Elegiste <b>${liveOptionLabel(data.selected_option)}</b>. Espera a que se cierre la pregunta.</p>
        <span class="live-timer" id="live-student-timer">${liveRemainingSeconds(data, live.fetchedAt)}</span>
      </div>`;
    return;
  }
  if (data.phase === "reveal") {
    const result = !data.answered
      ? '<div class="student-live-result is-missed"><strong>Sin respuesta</strong><p>Se acabó el tiempo.</p></div>'
      : data.is_correct
        ? `<div class="student-live-result is-right"><strong>¡Correcto!</strong><p>+${data.points} puntos</p></div>`
        : `<div class="student-live-result is-wrong"><strong>Incorrecto</strong><p>La respuesta era ${liveOptionLabel(data.correct_option)}: ${escapeHtml(data.question.options[data.correct_option])}</p></div>`;
    panel.innerHTML = `${header}${result}
      <p class="student-live-score">Total: <strong>${data.total_points ?? 0} pts</strong> · Puesto ${data.rank ?? "—"} de ${data.participant_count}</p>`;
    return;
  }
  panel.innerHTML = `${header}
    <div class="student-live-result is-final">
      <strong>¡Quiz terminado!</strong>
      <p>Quedaste en el puesto <b>${data.rank ?? "—"}</b> de ${data.participant_count} con <b>${data.total_points ?? 0}</b> puntos.</p>
    </div>
    <div class="live-board">${liveRanking(data.podium, 3)}</div>
    <button class="button button-add" type="button" data-live-exit>Unirme a otra actividad</button>`;
}

async function fetchLiveStudent() {
  const live = liveState.student;
  if (!live || live.sending) return;
  try {
    const data = await api(`/student/quick-activities/${live.activityId}/live`);
    if (liveState.student !== live) return;
    const changed = !live.data || live.data.phase !== data.phase || live.data.position !== data.position
      || live.data.answered !== data.answered || live.data.participant_count !== data.participant_count;
    const phaseChanged = !live.data || live.data.phase !== data.phase || live.data.position !== data.position;
    live.data = data;
    live.fetchedAt = Date.now();
    if (changed) renderStudentLive();
    // En el celular, cada pregunta nueva o resultado queda a la vista.
    if (phaseChanged) $("#student-live")?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (data.phase === "finished") {
      clearInterval(live.timer);
      if (typeof loadStudentSubmissions === "function") loadStudentSubmissions();
    }
  } catch (error) {
    setJoinStatus(`Sin conexión con el quiz: ${error.message}`, true);
  }
}

function startStudentLive(activity) {
  stopStudentLive();
  setJoinStatus("");
  liveState.student = { activityId: activity.id, title: activity.title, data: null, fetchedAt: 0 };
  renderStudentLive();
  fetchLiveStudent();
  liveState.student.timer = setInterval(fetchLiveStudent, LIVE_STUDENT_POLL_MS);
  ensureLiveTick();
}

function stopStudentLive() {
  if (liveState.student?.timer) clearInterval(liveState.student.timer);
  liveState.student = null;
  const panel = $("#student-live");
  if (panel) { panel.hidden = true; panel.innerHTML = ""; }
}

$("#student-live")?.addEventListener("click", async (event) => {
  const live = liveState.student;
  if (event.target.closest("[data-live-exit]")) {
    stopStudentLive();
    $("#student-join-form").hidden = false;
    $("#student-join-code").value = "";
    return;
  }
  const button = event.target.closest("[data-live-answer]");
  if (!button || !live?.data?.question || live.sending) return;
  const selected = Number(button.dataset.liveAnswer);
  live.sending = true;
  renderStudentLive();
  try {
    await api(`/student/quick-activities/${live.activityId}/live/answers`, {
      method: "POST",
      body: JSON.stringify({ question_id: live.data.question.id, selected_option: selected }),
    });
    live.data = { ...live.data, answered: true, selected_option: selected };
  } catch (error) {
    setJoinStatus(error.message, true);
  } finally {
    live.sending = false;
    renderStudentLive();
    fetchLiveStudent();
  }
});
