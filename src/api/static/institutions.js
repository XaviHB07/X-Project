// Estructura institucional (Sprint 6 pendiente, avanzado el 17-nov-2026).
//
// * HU-A5 / HU-A6 / HU-A7: el Administrador registra, renombra, deshabilita y
//   elimina universidades, facultades y especialidades.
// * HU-C2: selección encadenada universidad → facultad → especialidad para
//   registrar ciclos (solo se ofrecen elementos habilitados).
//
// Se carga después de app.js y usa su estado (`state`), `api`, `notify`,
// `escapeHtml`, `setBusy` y `renderCycles`.

const institutionUi = {
  editing: null, // { level: "university" | "faculty" | "specialty", id }
};

const INSTITUTION_LEVELS = {
  university: { label: "Universidad", path: "universities" },
  faculty: { label: "Facultad", path: "faculties" },
  specialty: { label: "Especialidad", path: "specialties" },
};

function isAdminAccount() {
  return state.authenticatedUser?.role === "administrador";
}

function findInstitutionNode(level, id) {
  for (const university of state.institutions) {
    if (level === "university" && university.id === id) return university;
    for (const faculty of university.faculties) {
      if (level === "faculty" && faculty.id === id) return faculty;
      for (const specialty of faculty.specialties) {
        if (level === "specialty" && specialty.id === id) return specialty;
      }
    }
  }
  return null;
}

function findSpecialtyPath(specialtyId) {
  for (const university of state.institutions) {
    for (const faculty of university.faculties) {
      const specialty = faculty.specialties.find((item) => item.id === specialtyId);
      if (specialty) return { university, faculty, specialty };
    }
  }
  return null;
}

// --------------------------------------------------------------------------
// HU-C2 — selección encadenada
// --------------------------------------------------------------------------

function institutionOptions(items, selectedId, placeholder, keepId) {
  // Solo se ofrecen elementos habilitados; al editar un ciclo se conserva el
  // valor actual aunque luego se haya deshabilitado (se marca como tal).
  const visible = items.filter((item) => item.enabled !== false || item.id === keepId);
  return `<option value="">${placeholder}</option>${visible.map((item) => `
    <option value="${item.id}" ${item.id === selectedId ? "selected" : ""}>${escapeHtml(item.name)}${
      item.enabled === false ? " (deshabilitada)" : ""
    }</option>`).join("")}`;
}

function initInstitutionPicker(container, selectedSpecialtyId = null, { keepCurrent = false } = {}) {
  if (!container) return;
  const universitySelect = container.querySelector('[data-level="university"]');
  const facultySelect = container.querySelector('[data-level="faculty"]');
  const specialtySelect = container.querySelector('[data-level="specialty"]');
  const path = selectedSpecialtyId ? findSpecialtyPath(selectedSpecialtyId) : null;
  const keep = keepCurrent && path ? path : null;

  const fillUniversities = (selectedId) => {
    universitySelect.innerHTML = institutionOptions(
      state.institutions, selectedId, "Selecciona una universidad", keep?.university.id,
    );
  };
  const fillFaculties = (selectedId) => {
    const university = state.institutions.find((item) => item.id === Number(universitySelect.value));
    facultySelect.innerHTML = institutionOptions(
      university?.faculties || [], selectedId, "Selecciona una facultad", keep?.faculty.id,
    );
    facultySelect.disabled = !university;
  };
  const fillSpecialties = (selectedId) => {
    const university = state.institutions.find((item) => item.id === Number(universitySelect.value));
    const faculty = university?.faculties.find((item) => item.id === Number(facultySelect.value));
    specialtySelect.innerHTML = institutionOptions(
      faculty?.specialties || [], selectedId, "Selecciona una especialidad", keep?.specialty.id,
    );
    specialtySelect.disabled = !faculty;
  };

  fillUniversities(path?.university.id ?? null);
  fillFaculties(path?.faculty.id ?? null);
  fillSpecialties(path?.specialty.id ?? null);

  universitySelect.onchange = () => {
    fillFaculties(null);
    fillSpecialties(null);
  };
  facultySelect.onchange = () => fillSpecialties(null);
  specialtySelect.onchange = () => {
    if (container.id === "cycle-institution-picker" && specialtySelect.value) {
      localStorage.setItem("aula-active-specialty", specialtySelect.value);
    }
  };
}

function hasSelectableSpecialty() {
  return state.institutions.some((university) => university.enabled !== false
    && university.faculties.some((faculty) => faculty.enabled !== false
      && faculty.specialties.some((specialty) => specialty.enabled !== false)));
}

function renderCycleInstitutionPicker() {
  const picker = $("#cycle-institution-picker");
  if (!picker) return;
  // Se propone la última especialidad elegida o, si no hay, la del ciclo
  // más reciente: el docente suele trabajar siempre en la misma.
  const lastCycleSpecialty = [...state.cycles].reverse()
    .map((cycle) => cycle.specialty_id).find(Boolean) || null;
  const usable = [
    Number($("#cycle-specialty").value),
    Number(localStorage.getItem("aula-active-specialty")),
    lastCycleSpecialty,
  ].find((id) => {
    const path = id ? findSpecialtyPath(id) : null;
    return path && path.university.enabled !== false && path.faculty.enabled !== false
      && path.specialty.enabled !== false;
  }) || null;
  initInstitutionPicker(picker, usable);
  const available = hasSelectableSpecialty();
  $("#cycle-institution-hint").hidden = available;
  $("#cycle-institution-hint").textContent = isAdminAccount()
    ? "Primero registra al menos una universidad, una facultad y una especialidad en Estructura institucional."
    : "El administrador todavía no registró universidades habilitadas. Pídele que complete la estructura institucional.";
  $("#create-cycle-form button[type=submit]").disabled = !available;
}

// --------------------------------------------------------------------------
// HU-A5 / HU-A6 / HU-A7 — página del Administrador
// --------------------------------------------------------------------------

function institutionStatus(enabled) {
  return enabled
    ? '<em class="teacher-status">Habilitada</em>'
    : '<em class="teacher-status is-inactive">Deshabilitada</em>';
}

function institutionHead(level, node, childCount, childLabel) {
  const editing = institutionUi.editing?.level === level && institutionUi.editing?.id === node.id;
  if (editing) {
    return `
      <form class="institution-edit-form" data-institution-edit="${level}:${node.id}">
        <span class="institution-kind">${INSTITUTION_LEVELS[level].label}</span>
        <label class="sr-only" for="institution-edit-${level}-${node.id}">Nuevo nombre</label>
        <input class="field" id="institution-edit-${level}-${node.id}" name="name" maxlength="255" value="${escapeHtml(node.name)}" required />
        <button class="button button-add" type="submit">Guardar</button>
        <button class="button button-quiet" type="button" data-institution-cancel>Cancelar</button>
      </form>`;
  }
  const blocked = childCount > 0;
  const deleteTitle = blocked
    ? `Tiene ${childCount} ${childLabel}: deshabilítala para conservar su histórico.`
    : "Eliminar definitivamente";
  return `
    <div class="institution-head">
      <div>
        <span class="institution-kind">${INSTITUTION_LEVELS[level].label}</span>
        <strong>${escapeHtml(node.name)} ${institutionStatus(node.enabled !== false)}</strong>
      </div>
      <div class="cycle-actions">
        <button class="button button-quiet" type="button" data-institution-action="edit" data-level="${level}" data-id="${node.id}">Editar</button>
        <button class="button button-quiet" type="button" data-institution-action="toggle" data-level="${level}" data-id="${node.id}">${node.enabled !== false ? "Deshabilitar" : "Habilitar"}</button>
        <button class="button button-quiet button-danger" type="button" data-institution-action="delete" data-level="${level}" data-id="${node.id}" ${blocked ? "disabled" : ""} title="${escapeHtml(deleteTitle)}">Eliminar</button>
      </div>
    </div>`;
}

function renderInstitutionTree() {
  const tree = $("#institution-tree");
  if (!tree) return;
  $("#university-count").textContent = state.institutions.length;
  $("#institution-empty").hidden = state.institutions.length > 0;
  tree.innerHTML = state.institutions.map((university) => `
    <article class="institution-node institution-university ${university.enabled === false ? "is-disabled" : ""}">
      ${institutionHead("university", university, university.faculties.length, "facultad(es)")}
      <div class="institution-children">
        ${university.faculties.map((faculty) => `
          <article class="institution-node institution-faculty ${faculty.enabled === false ? "is-disabled" : ""}">
            ${institutionHead("faculty", faculty, faculty.specialties.length, "especialidad(es)")}
            <div class="institution-children">
              ${faculty.specialties.map((specialty) => `
                <article class="institution-node institution-specialty ${specialty.enabled === false ? "is-disabled" : ""}">
                  ${institutionHead("specialty", specialty, specialty.cycle_count, "ciclo(s) académico(s)")}
                  <span class="form-note">${specialty.cycle_count} ciclo${specialty.cycle_count === 1 ? "" : "s"} académico${specialty.cycle_count === 1 ? "" : "s"}</span>
                </article>`).join("")}
              ${faculty.enabled === false ? "" : `
              <form class="institution-add-form" data-institution-add="faculty:${faculty.id}">
                <label class="sr-only" for="new-specialty-${faculty.id}">Nueva especialidad</label>
                <input class="field" id="new-specialty-${faculty.id}" name="name" maxlength="255" placeholder="Nueva especialidad" required />
                <button class="button button-quiet" type="submit">＋ Especialidad</button>
              </form>`}
            </div>
          </article>`).join("")}
        ${university.enabled === false ? "" : `
        <form class="institution-add-form" data-institution-add="university:${university.id}">
          <label class="sr-only" for="new-faculty-${university.id}">Nueva facultad</label>
          <input class="field" id="new-faculty-${university.id}" name="name" maxlength="255" placeholder="Nueva facultad" required />
          <button class="button button-quiet" type="submit">＋ Facultad</button>
        </form>`}
      </div>
    </article>`).join("");
}

function renderInstitutionViews() {
  renderCycleInstitutionPicker();
  if (isAdminAccount()) renderInstitutionTree();
}

async function reloadInstitutions({ cycles = false } = {}) {
  state.institutions = await api("/institutions");
  if (cycles) {
    // Los ciclos muestran el nombre de su universidad/facultad/especialidad.
    state.cycles = await api("/cycles");
    renderCycles(state.activeCycleId);
  }
  renderInstitutionViews();
  if (state.appView === "institutions") setAppView("institutions");
}

$("#create-university-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const name = $("#university-name").value.trim();
  if (!name) return;
  setBusy(button, true, "Registrando...");
  try {
    await api("/institutions/universities", { method: "POST", body: JSON.stringify({ name }) });
    form.reset();
    await reloadInstitutions();
    notify(`Universidad “${name}” registrada.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#institution-tree")?.addEventListener("submit", async (event) => {
  const addForm = event.target.closest("[data-institution-add]");
  const editForm = event.target.closest("[data-institution-edit]");
  if (!addForm && !editForm) return;
  event.preventDefault();
  const form = addForm || editForm;
  const button = form.querySelector("button[type=submit]");
  const name = form.elements.name.value.trim();
  if (!name) return;
  setBusy(button, true, "Guardando...");
  try {
    if (addForm) {
      const [parentLevel, parentId] = addForm.dataset.institutionAdd.split(":");
      const url = parentLevel === "university"
        ? `/institutions/universities/${parentId}/faculties`
        : `/institutions/faculties/${parentId}/specialties`;
      await api(url, { method: "POST", body: JSON.stringify({ name }) });
      await reloadInstitutions();
      notify(`${parentLevel === "university" ? "Facultad" : "Especialidad"} “${name}” registrada.`);
    } else {
      const [level, id] = editForm.dataset.institutionEdit.split(":");
      await api(`/institutions/${INSTITUTION_LEVELS[level].path}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      institutionUi.editing = null;
      await reloadInstitutions({ cycles: true });
      notify(`${INSTITUTION_LEVELS[level].label} renombrada.`);
    }
  } catch (error) {
    notify(error.message, true);
    setBusy(button, false);
  }
});

$("#institution-tree")?.addEventListener("click", async (event) => {
  if (event.target.closest("[data-institution-cancel]")) {
    institutionUi.editing = null;
    renderInstitutionTree();
    return;
  }
  const button = event.target.closest("[data-institution-action]");
  if (!button) return;
  const level = button.dataset.level;
  const id = Number(button.dataset.id);
  const node = findInstitutionNode(level, id);
  if (!node) return;
  const label = INSTITUTION_LEVELS[level].label;
  const action = button.dataset.institutionAction;
  if (action === "edit") {
    institutionUi.editing = { level, id };
    renderInstitutionTree();
    document.querySelector(`#institution-edit-${level}-${id}`)?.focus();
    return;
  }
  if (action === "toggle") {
    const enable = node.enabled === false;
    if (!enable && !window.confirm(
      `¿Deshabilitar ${label.toLowerCase()} “${node.name}”? Se conserva su histórico, pero ya no se ofrecerá en registros nuevos.`,
    )) return;
    setBusy(button, true, enable ? "Habilitando..." : "Deshabilitando...");
    try {
      await api(`/institutions/${INSTITUTION_LEVELS[level].path}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: enable }),
      });
      await reloadInstitutions();
      notify(`${label} “${node.name}” ${enable ? "habilitada" : "deshabilitada"}.`);
    } catch (error) {
      notify(error.message, true);
      setBusy(button, false);
    }
    return;
  }
  if (action === "delete") {
    if (!window.confirm(`¿Eliminar definitivamente ${label.toLowerCase()} “${node.name}”?`)) return;
    setBusy(button, true, "Eliminando...");
    try {
      await api(`/institutions/${INSTITUTION_LEVELS[level].path}/${id}`, { method: "DELETE" });
      await reloadInstitutions();
      notify(`${label} “${node.name}” eliminada.`);
    } catch (error) {
      notify(error.message, true);
      setBusy(button, false);
    }
  }
});
