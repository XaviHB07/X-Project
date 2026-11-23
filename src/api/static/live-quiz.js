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
const LIVE_COLORS = ["live-red", "live-blue", "live-yellow", "live-green"];
const LIVE_COLOR_NAMES = ["Rojo", "Azul", "Amarillo", "Verde"];

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
  return LIVE_COLOR_NAMES[index] || "Color";
}

function liveRanking(rows, limit = 5) {
  if (!rows?.length) return '<p class="form-note">Todavía no hay puntajes.</p>';
  return `<ol class="live-ranking">${rows.slice(0, limit).map((row) => `
    <li><span class="live-rank">${row.rank}</span><strong>${escapeHtml(row.student_name)}</strong>
      <span>${row.points} pts · ${row.correct} acierto${row.correct === 1 ? "" : "s"}</span></li>`).join("")}</ol>`;
}

function liveFinishElapsed(data, fetchedAt) {
  const finishedAt = Date.parse(data?.finished_at || "");
  const serverTime = Date.parse(data?.server_time || "");
  if (!Number.isFinite(finishedAt) || !Number.isFinite(serverTime)) return 0;
  return Math.max(0, serverTime - finishedAt + Date.now() - fetchedAt);
}

function wolfRunnerMarkup() {
  return `
    <svg class="wolf-runner-art" viewBox="0 0 820 430" role="presentation">
      <defs>
        <linearGradient id="wolf-fur" x1=".2" x2=".8" y1="0" y2="1">
          <stop stop-color="#535575" />
          <stop offset=".35" stop-color="#20233f" />
          <stop offset=".72" stop-color="#10142a" />
          <stop offset="1" stop-color="#070a16" />
        </linearGradient>
        <linearGradient id="wolf-mane" x1="0" x2="1" y1="0" y2="1">
          <stop stop-color="#68658f" />
          <stop offset=".24" stop-color="#343654" />
          <stop offset=".64" stop-color="#1b1e39" />
          <stop offset="1" stop-color="#0b1021" />
        </linearGradient>
        <linearGradient id="wolf-violet" x1="0" x2="1" y1="0" y2="1">
          <stop stop-color="#e4b6ff" />
          <stop offset=".36" stop-color="#a94dff" />
          <stop offset="1" stop-color="#5335e9" />
        </linearGradient>
        <linearGradient id="wolf-fur-light" x1="0" x2="0" y1="0" y2="1">
          <stop stop-color="#aaa6c7" />
          <stop offset="1" stop-color="#4a4e70" />
        </linearGradient>
        <filter id="wolf-eye-glow" x="-300%" y="-300%" width="700%" height="700%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id="wolf-neon-glow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <g class="wolf-speed-trails">
        <path d="M253 225 Q157 198 42 211 M231 245 Q143 245 62 272 M258 196 Q164 160 85 174" />
        <path d="M205 261 Q127 281 55 306 M217 179 Q150 132 96 143" />
      </g>
      <ellipse class="wolf-runner-shadow" cx="397" cy="366" rx="254" ry="18" />
      <g class="wolf-runner-bob">
        <path class="wolf-tail" d="M246 196 Q205 160 158 160 L126 139 140 175 101 163 127 199 83 198 119 224 Q166 240 213 214 L250 230Z" />
        <path class="wolf-tail-mark" d="M220 199 Q177 178 140 178 M198 216 Q157 205 128 210 M177 188 Q146 181 121 184" />
        <g transform="translate(270 219)"><g class="wolf-leg-swing wolf-leg-rear-a">
          <path class="wolf-leg-base" d="M0 0 Q-30 7 -43 34 L-59 55 -98 65 Q-111 70 -102 81 L-78 82 -43 72 Q-19 68 -8 47 L18 17Z" />
          <path class="wolf-leg-detail" d="M-9 13 Q-27 31 -40 54 L-79 70" />
          <path class="wolf-leg-paw" d="M-101 70 Q-125 68 -136 82 Q-124 92 -99 84 L-78 81Z" />
        </g></g>
        <g transform="translate(312 216)"><g class="wolf-leg-swing wolf-leg-rear-b">
          <path class="wolf-leg-base" d="M0 0 Q-22 14 -14 40 L2 57 -22 76 Q-28 88 -11 91 L14 81 39 56 Q51 37 25 12Z" />
          <path class="wolf-leg-detail" d="M8 13 Q-1 35 14 53 L-9 77" />
          <path class="wolf-leg-paw" d="M-19 81 Q-40 89 -41 103 Q-24 111 0 94 L14 84Z" />
        </g></g>
        <path class="wolf-torso" d="M205 188 C216 163 237 150 264 149 C282 132 303 131 324 143 C356 122 389 124 418 139 C445 128 472 140 492 159 C518 161 540 178 551 198 L532 216 Q525 235 498 258 L477 244 457 267 437 247 416 264 394 245 372 262 349 243 326 258 306 237 280 251 261 228 236 232 214 211Z" />
        <path class="wolf-shoulder" d="M425 146 Q462 126 491 153 L511 184 Q493 205 479 239 L456 262 437 241 420 224Z" />
        <path class="wolf-haunch" d="M233 164 Q258 140 287 148 Q304 165 291 199 L272 231 250 222 229 226 210 207Z" />
        <path class="wolf-belly" d="M293 211 Q365 235 433 209 L413 244 394 242 371 260 349 239 324 254 305 232 280 246 259 223Z" />
        <g class="wolf-mane">
          <path d="M436 147 Q465 112 502 117 L530 132 557 152 543 171 559 181 536 191 548 203 524 204 535 219 511 217 517 237 495 226 495 251 474 237 457 260 439 239 420 248 414 224 394 209Z" />
          <path class="wolf-mane-strand" d="M462 151 Q483 130 509 133 M454 164 Q477 148 500 148 M450 180 Q473 166 491 163 M445 196 Q466 185 481 181 M438 210 Q457 204 470 198" />
        </g>
        <g transform="translate(466 217)"><g class="wolf-leg-swing wolf-leg-front-a">
          <path class="wolf-leg-base" d="M0 0 Q-19 12 -14 39 L-1 59 20 78 52 75 66 66 44 58 27 38 34 8Z" />
          <path class="wolf-leg-detail" d="M1 12 Q-8 33 8 52 L33 68" />
          <path class="wolf-leg-paw" d="M48 70 Q71 64 84 78 Q75 92 48 82 L27 79Z" />
        </g></g>
        <g transform="translate(506 206)"><g class="wolf-leg-swing wolf-leg-front-b">
          <path class="wolf-leg-base" d="M0 0 Q13 16 31 26 L38 49 58 68 Q63 80 48 85 L26 75 8 55 -11 34 -27 13Z" />
          <path class="wolf-leg-detail" d="M3 11 27 37 31 57 47 72" />
          <path class="wolf-leg-paw" d="M48 77 Q65 78 78 91 Q68 103 47 91 L29 82Z" />
        </g></g>
        <path class="wolf-back-ridge" d="M225 172 Q257 133 293 143 Q337 117 380 130 Q419 120 451 142" />
        <g class="wolf-head-bob">
          <path class="wolf-neck-fur" d="M459 166 Q475 126 516 110 L548 112 572 133 558 162 538 177 551 190 528 196 532 215 509 208 513 229 490 216 490 238 470 220 450 236 439 216 420 222 418 201Z" />
          <path class="wolf-head" d="M512 143 Q527 111 557 99 L590 96 608 59 627 91 Q655 85 681 98 L715 119 752 133 786 149 Q771 163 744 159 L725 174 Q700 182 676 168 L658 185 631 174 608 190 585 174 563 190 545 169Z" />
          <path class="wolf-ear-back" d="M574 105 590 68 609 101Z" />
          <path class="wolf-ear" d="M603 103 624 59 646 99 Q630 107 603 112Z" />
          <path class="wolf-ear-inner" d="M615 96 625 75 636 97Z" />
          <path class="wolf-cheek-plate" d="M613 125 Q642 110 670 122 L691 145 669 167 645 176 626 162 604 170 588 157Z" />
          <path class="wolf-face-mark" d="M625 110 Q650 95 677 108 L661 119 641 121Z" />
          <path class="wolf-muzzle" d="M702 128 Q743 125 780 147 Q773 159 746 160 L713 151 690 143Z" />
          <path class="wolf-mouth" d="M699 153 Q731 163 765 153 Q753 174 724 172 L703 164Z" />
          <path class="wolf-jaw" d="M704 162 Q735 174 761 157 Q748 184 721 181 L706 170Z" />
          <path class="wolf-nose" d="M777 143 Q792 141 799 149 Q794 159 779 156 L770 151Z" />
          <path class="wolf-eye-socket" d="M670 115 Q689 103 706 115 L694 128 673 124Z" />
          <path class="wolf-eye" d="M676 117 Q689 110 699 117 L691 123 678 122Z" />
          <path class="wolf-eye-light" d="M680 118 694 117 687 122Z" />
          <path class="wolf-brow" d="M669 111 Q688 101 707 110" />
          <path class="wolf-nostril" d="M785 147 791 149" />
          <path class="wolf-fang" d="M725 163 731 175 737 162Z" />
          <path class="wolf-whisker" d="M746 162 770 168 M742 166 763 175" />
          <path class="wolf-face-glow" d="M531 142 Q548 111 582 102 M631 101 Q663 91 687 105 M714 121 754 137" />
        </g>
        <path class="wolf-fur-detail" d="M237 180 Q261 159 284 157 M248 192 Q274 173 293 169 M264 207 Q284 191 303 184 M316 155 Q350 136 379 141 M334 169 Q366 149 398 150 M353 184 Q386 163 416 164 M380 198 Q407 180 435 177 M285 187 Q305 169 323 166 M302 201 Q323 181 343 178 M365 218 Q392 195 420 190 M431 170 Q449 155 465 157 M448 185 Q466 169 481 167" />
        <path class="wolf-violet-edge" d="M134 167 Q179 173 211 198 M224 165 Q247 138 279 143 L293 131 Q318 145 339 126 Q378 114 408 130 L426 143 Q454 132 478 150 M460 159 Q478 127 513 115 M531 142 Q548 107 580 101 M630 100 Q658 89 682 101" />
        <path class="wolf-leg-rim" d="M235 226 Q210 251 183 261 M279 227 Q264 251 242 270 M461 238 Q475 257 507 275 M506 236 Q523 253 552 264" />
      </g>
    </svg>`;
}

function renderWolfFinale(rows, elapsed, personalResult = null) {
  const placements = [2, 1, 3].map((rank) => {
    const winner = rows?.find((row) => row.rank === rank);
    const delay = rank === 3 ? 3200 : rank === 2 ? 3900 : 4600;
    const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : "🥉";
    return winner ? `
      <article class="wolf-winner-card place-${rank}" style="--reveal-at:${delay}ms">
        <span class="wolf-medal" aria-hidden="true">${medal}</span>
        <span class="wolf-place">${rank}° PUESTO</span>
        <strong>${escapeHtml(winner.student_name)}</strong>
        <span class="wolf-points">${winner.points.toLocaleString("es")} pts</span>
      </article>` : "";
  }).join("");
  const particles = Array.from({ length: 28 }, (_, index) => `
    <i style="--particle-x:${(index * 37) % 100}%;--particle-start:${2600 + (index % 8) * 150}ms;--particle-delay:${(index % 7) * 90}ms"></i>
  `).join("");
  const stars = Array.from({ length: 34 }, (_, index) => `
    <i style="--star-x:${(index * 47) % 100}%;--star-y:${(index * 29) % 61}%;--star-delay:${(index % 9) * 220}ms"></i>
  `).join("");
  const personal = personalResult ? `
    <p class="wolf-personal-result">
      ${personalResult.rank === 1 ? "¡Eres el líder de la manada!" : "Tu lugar en la manada"}
      <strong>#${personalResult.rank ?? "—"} · ${(personalResult.points ?? 0).toLocaleString("es")} pts</strong>
    </p>` : "";
  return `
    <section class="wolf-finale" style="--elapsed:${Math.max(0, elapsed)}ms" aria-label="Resultados finales del quiz">
      <div class="wolf-finale-sky" aria-hidden="true">
        <div class="wolf-stars">${stars}</div>
        <div class="wolf-moon"></div>
        <svg class="wolf-landscape" viewBox="0 0 1200 650" preserveAspectRatio="xMidYMax slice">
          <defs>
            <linearGradient id="wolf-ground" x1="0" x2="0" y1="0" y2="1">
              <stop stop-color="#473765" />
              <stop offset="1" stop-color="#101629" />
            </linearGradient>
          </defs>
          <path class="wolf-mountain-back" d="M0 404 117 291 192 357 330 210 451 356 563 250 691 378 813 205 965 367 1071 260 1200 390V650H0Z" />
          <path class="wolf-mountain-snow" d="m330 210 38 71-38-16-29 36-26 12Zm483-5 48 78-49-25-37 33-24 4Zm258 55 38 48-40-18-27 21-20-2Z" />
          <path class="wolf-mountain-front" d="M0 457 143 337 252 437 371 320 493 447 630 340 763 450 899 325 1044 451 1134 372 1200 426V650H0Z" />
          <path class="wolf-forest" d="M0 478 20 430 37 478 53 445 70 486 90 438 109 486 128 451 145 493 166 443 188 492 207 455 226 494 249 438 271 495 292 449 315 496 340 451 360 500 386 449 406 503 430 455 454 501 480 447 502 499 529 455 552 505 580 444 603 502 628 453 650 500 676 446 700 498 723 455 746 500 770 439 796 502 823 449 847 502 871 451 894 504 917 441 941 502 964 455 987 499 1012 447 1037 498 1060 452 1084 494 1108 441 1132 490 1156 450 1178 492 1200 454V650H0Z" />
          <path class="wolf-ground" d="M0 503 Q255 466 500 505 T1000 496 Q1111 487 1200 508V650H0Z" />
          <path class="wolf-ground-light" d="M0 521 Q300 490 580 527 T1200 518" />
        </svg>
        <div class="wolf-light"></div>
        <div class="wolf-claws"><i></i><i></i><i></i></div>
        <div class="wolf-particles">${particles}</div>
        <div class="wolf-runner">${wolfRunnerMarkup()}</div>
      </div>
      <div class="wolf-finale-content">
        <p class="wolf-finale-eyebrow">CACERÍA CONCLUIDA</p>
        <h3 class="wolf-finale-title">¡La manada ya tiene líderes!</h3>
        <button class="wolf-howler" type="button" data-wolf-howl>♪ Escuchar aullido</button>
        <div class="wolf-winners">${placements || '<p class="form-note">No hubo participantes en esta cacería.</p>'}</div>
        ${personal}
        <p class="wolf-finale-signoff">FUERZA <span>·</span> INSTINTO <span>·</span> MANADA</p>
      </div>
    </section>`;
}

function playWolfHowl(button) {
  const AudioContext = window.AudioContext;
  if (!AudioContext) {
    notify("Este navegador no permite reproducir el aullido.", true);
    return;
  }
  const context = new AudioContext();
  const now = context.currentTime;
  const gain = context.createGain();
  const filter = context.createBiquadFilter();
  const howl = context.createOscillator();
  const undertone = context.createOscillator();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(1150, now);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.12, now + 0.25);
  gain.gain.setValueAtTime(0.12, now + 1.65);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 2.8);
  howl.type = "triangle";
  howl.frequency.setValueAtTime(330, now);
  howl.frequency.exponentialRampToValueAtTime(620, now + 0.8);
  howl.frequency.exponentialRampToValueAtTime(280, now + 2.8);
  undertone.type = "sine";
  undertone.frequency.setValueAtTime(165, now);
  undertone.frequency.exponentialRampToValueAtTime(140, now + 2.8);
  howl.connect(filter);
  undertone.connect(filter);
  filter.connect(gain);
  gain.connect(context.destination);
  button.disabled = true;
  howl.onended = () => context.close();
  howl.start(now);
  undertone.start(now);
  howl.stop(now + 2.8);
  undertone.stop(now + 2.8);
  setTimeout(() => { button.disabled = false; }, 3000);
  context.resume().catch(() => notify("El navegador no permitió reproducir el aullido.", true));
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-wolf-howl]");
  if (button) playWolfHowl(button);
});

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

  body.innerHTML = renderWolfFinale(data.leaderboard, liveFinishElapsed(data, live.fetchedAt));
  advance.textContent = "Cerrar pantalla";
  advance.disabled = false;
  const mailStatus = {
    disabled: "Correo de resultados desactivado; configura SMTP para habilitarlo.",
    already_sent: "Los correos de resultados ya fueron enviados.",
    sent: `Resultados enviados a ${data.result_emails_sent} participante${data.result_emails_sent === 1 ? "" : "s"}${data.result_emails_skipped ? `; ${data.result_emails_skipped} sin correo válido` : ""}.`,
    partial_failure: `Se enviaron ${data.result_emails_sent} correos; ${data.result_emails_failed} fallaron${data.result_emails_skipped ? ` y ${data.result_emails_skipped} no tienen correo válido` : ""}.`,
    failed: "No se pudieron entregar los correos de resultados. Revisa el registro del servidor.",
    no_recipients: "No hay correos registrados para los participantes de esta cacería.",
  };
  status.textContent = `${data.participant_count} participante${data.participant_count === 1 ? "" : "s"}. ${mailStatus[data.result_email_status] || 'Resultados disponibles en "Resultados".'}`;
}

async function fetchLiveTeacher() {
  const live = liveState.teacher;
  if (!live) return;
  try {
    const data = await api(`/courses/${live.courseId}/quick-activities/${live.activityId}/live`);
    if (liveState.teacher !== live) return;
    const changed = !live.data || live.data.phase !== data.phase || live.data.position !== data.position
      || live.data.answered_count !== data.answered_count
      || live.data.participant_count !== data.participant_count
      || live.data.result_email_status !== data.result_email_status;
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
        <p class="student-live-instruction">Observa la pantalla del aula y elige el color de la alternativa correcta.</p>
      </div>
      <div class="student-live-options">
        ${LIVE_COLOR_NAMES.slice(0, data.option_count || 0).map((color, index) => `
          <button class="live-answer ${LIVE_COLORS[index]}" type="button" data-live-answer="${index}"
            aria-label="${color}" title="${color}" ${live.sending ? "disabled" : ""}></button>`).join("")}
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
        : `<div class="student-live-result is-wrong"><strong>Incorrecto</strong><p>La respuesta era ${liveOptionLabel(data.correct_option)}.</p></div>`;
    panel.innerHTML = `${header}${result}
      <p class="student-live-score">Total: <strong>${data.total_points ?? 0} pts</strong> · Puesto ${data.rank ?? "—"} de ${data.participant_count}</p>`;
    return;
  }
  panel.innerHTML = `${header}${renderWolfFinale(data.podium, liveFinishElapsed(data, live.fetchedAt), {
    rank: data.rank,
    points: data.total_points,
  })}
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
