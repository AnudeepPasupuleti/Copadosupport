/**
 * Org Chart — reporting tree + teams.
 * Relies on ChecklistApp / TeamApp view hooks.
 */
(function () {
  const orgView = document.getElementById("org-view");
  let chart = null;
  let canEdit = false;

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (res.status === 401) {
      location.href = "/login";
      throw new Error("Unauthorized");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg =
        typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : null;
      throw new Error(msg || "Request failed");
    }
    return data;
  }

  function hideOrgView() {
    if (orgView) orgView.hidden = true;
    closeAllModals();
  }

  function closeAllModals() {
    ["org-team-modal", "org-member-modal", "org-manager-modal"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.hidden = true;
    });
  }

  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/);
    return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
  }

  function personCard(p, depth) {
    const avatar = p.picture
      ? `<img class="org-person-avatar" src="${escapeHtml(p.picture)}" alt="" />`
      : `<span class="org-person-avatar-fallback">${escapeHtml(initials(p.name || p.email))}</span>`;
    const editBtn = canEdit
      ? `<button type="button" class="text-action org-set-manager" data-user-id="${p.id}">Set manager</button>`
      : "";
    const kids = (p.reports || []).map((c) => personCard(c, depth + 1)).join("");
    return `<li class="org-node" style="--org-depth:${depth}">
      <div class="org-person">
        ${avatar}
        <div class="org-person-copy">
          <strong>${escapeHtml(p.name || p.email)}</strong>
          <span>${escapeHtml(p.role_label || p.role || "Member")}</span>
        </div>
        ${editBtn}
      </div>
      ${kids ? `<ul class="org-children">${kids}</ul>` : ""}
    </li>`;
  }

  function renderTree() {
    const treeEl = document.getElementById("org-tree");
    if (!treeEl || !chart) return;
    const tree = chart.tree || [];
    if (!tree.length) {
      treeEl.innerHTML = `<p class="org-empty">No reporting lines yet.${
        canEdit ? " Use Set manager on a person to build the tree." : ""
      }</p>`;
      return;
    }
    treeEl.innerHTML = `<ul class="org-root">${tree.map((n) => personCard(n, 0)).join("")}</ul>`;
    treeEl.querySelectorAll(".org-set-manager").forEach((btn) => {
      btn.addEventListener("click", () => openManagerModal(Number(btn.dataset.userId)));
    });
  }

  function renderTeams() {
    const teamsEl = document.getElementById("org-teams");
    if (!teamsEl || !chart) return;
    const teams = chart.teams || [];
    if (!teams.length) {
      teamsEl.innerHTML = `<p class="org-empty">No teams yet.${
        canEdit ? " Create a team to group people." : ""
      }</p>`;
      return;
    }
    teamsEl.innerHTML = teams
      .map((t) => {
        const members = (t.members || [])
          .map(
            (m) => `<li class="org-chip">
              <span>${escapeHtml(m.name || m.email)}${
              m.title ? ` · ${escapeHtml(m.title)}` : ""
            }</span>
              ${
                canEdit
                  ? `<button type="button" class="org-chip-remove" data-team-id="${t.id}" data-user-id="${m.id}" title="Remove">×</button>`
                  : ""
              }
            </li>`
          )
          .join("");
        return `<article class="org-team-card" data-team-id="${t.id}">
          <div class="org-team-head">
            <div>
              <h3>${escapeHtml(t.name)}</h3>
              <p>${escapeHtml(t.description || "No description")}</p>
            </div>
            ${
              canEdit
                ? `<div class="org-team-actions">
              <button type="button" class="btn btn-outline org-add-member" data-team-id="${t.id}">Add</button>
              <button type="button" class="btn btn-outline org-edit-team" data-team-id="${t.id}">Edit</button>
              <button type="button" class="btn btn-danger-outline org-delete-team" data-team-id="${t.id}">Delete</button>
            </div>`
                : ""
            }
          </div>
          <ul class="org-chip-list">${members || '<li class="org-empty-inline">No members</li>'}</ul>
        </article>`;
      })
      .join("");

    teamsEl.querySelectorAll(".org-add-member").forEach((btn) => {
      btn.addEventListener("click", () => openMemberModal(Number(btn.dataset.teamId)));
    });
    teamsEl.querySelectorAll(".org-edit-team").forEach((btn) => {
      btn.addEventListener("click", () => openTeamModal(Number(btn.dataset.teamId)));
    });
    teamsEl.querySelectorAll(".org-delete-team").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this team?")) return;
        try {
          await api(`/api/org/teams/${btn.dataset.teamId}`, { method: "DELETE" });
          await loadChart();
        } catch (err) {
          alert(err.message || "Could not delete team");
        }
      });
    });
    teamsEl.querySelectorAll(".org-chip-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/org/teams/${btn.dataset.teamId}/members/${btn.dataset.userId}`, {
            method: "DELETE",
          });
          await loadChart();
        } catch (err) {
          alert(err.message || "Could not remove member");
        }
      });
    });
  }

  async function loadChart() {
    chart = await api("/api/org/chart");
    canEdit = !!chart.can_edit;
    const toolbar = document.getElementById("org-edit-toolbar");
    if (toolbar) toolbar.hidden = !canEdit;
    renderTree();
    renderTeams();
  }

  async function showOrg() {
    hideOrgView();
    const todayView = document.getElementById("today-view");
    const profileView = document.getElementById("profile-view");
    const dashboardView = document.getElementById("dashboard-view");
    const queueView = document.getElementById("queue-view");
    if (todayView) todayView.hidden = true;
    if (profileView) profileView.hidden = true;
    if (dashboardView) dashboardView.hidden = true;
    if (queueView) queueView.hidden = true;
    if (window.TeamApp) window.TeamApp.hideTeamViews();
    orgView.hidden = false;
    await loadChart();
  }

  function openTeamModal(teamId) {
    const modal = document.getElementById("org-team-modal");
    const title = document.getElementById("org-team-modal-title");
    const idEl = document.getElementById("org-team-edit-id");
    const nameEl = document.getElementById("org-team-name");
    const descEl = document.getElementById("org-team-description");
    const team = (chart?.teams || []).find((t) => t.id === teamId);
    idEl.value = team ? String(team.id) : "";
    nameEl.value = team?.name || "";
    descEl.value = team?.description || "";
    title.textContent = team ? "Edit team" : "New team";
    modal.hidden = false;
  }

  function openMemberModal(teamId) {
    const modal = document.getElementById("org-member-modal");
    document.getElementById("org-member-team-id").value = String(teamId);
    const select = document.getElementById("org-member-user");
    const team = (chart?.teams || []).find((t) => t.id === teamId);
    const memberIds = new Set((team?.members || []).map((m) => m.id));
    select.innerHTML = (chart?.people || [])
      .filter((p) => !memberIds.has(p.id))
      .map((p) => `<option value="${p.id}">${escapeHtml(p.name || p.email)}</option>`)
      .join("");
    document.getElementById("org-member-title").value = "";
    if (!select.options.length) {
      alert("Everyone is already on this team.");
      return;
    }
    modal.hidden = false;
  }

  function openManagerModal(userId) {
    const person = (chart?.people || []).find((p) => p.id === userId);
    if (!person) return;
    document.getElementById("org-manager-user-id").value = String(userId);
    document.getElementById("org-manager-person-label").textContent =
      `Set manager for ${person.name || person.email}`;
    const select = document.getElementById("org-manager-select");
    select.innerHTML =
      `<option value="">No manager (top level)</option>` +
      (chart?.people || [])
        .filter((p) => p.id !== userId)
        .map(
          (p) =>
            `<option value="${p.id}" ${
              person.reports_to_id === p.id ? "selected" : ""
            }>${escapeHtml(p.name || p.email)}</option>`
        )
        .join("");
    document.getElementById("org-manager-modal").hidden = false;
  }

  function wire() {
    document.getElementById("org-add-team-btn")?.addEventListener("click", () => openTeamModal(null));
    document.getElementById("org-team-modal-cancel")?.addEventListener("click", closeAllModals);
    document.getElementById("org-team-modal-backdrop")?.addEventListener("click", closeAllModals);
    document.getElementById("org-member-modal-cancel")?.addEventListener("click", closeAllModals);
    document.getElementById("org-member-modal-backdrop")?.addEventListener("click", closeAllModals);
    document.getElementById("org-manager-modal-cancel")?.addEventListener("click", closeAllModals);
    document.getElementById("org-manager-modal-backdrop")?.addEventListener("click", closeAllModals);

    document.getElementById("org-team-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = document.getElementById("org-team-edit-id").value;
      const body = {
        name: document.getElementById("org-team-name").value.trim(),
        description: document.getElementById("org-team-description").value.trim(),
      };
      try {
        if (id) {
          await api(`/api/org/teams/${id}`, { method: "PATCH", body: JSON.stringify(body) });
        } else {
          await api("/api/org/teams", { method: "POST", body: JSON.stringify(body) });
        }
        closeAllModals();
        await loadChart();
      } catch (err) {
        alert(err.message || "Could not save team");
      }
    });

    document.getElementById("org-member-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const teamId = document.getElementById("org-member-team-id").value;
      const body = {
        user_id: Number(document.getElementById("org-member-user").value),
        title: document.getElementById("org-member-title").value.trim(),
      };
      try {
        await api(`/api/org/teams/${teamId}/members`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        closeAllModals();
        await loadChart();
      } catch (err) {
        alert(err.message || "Could not add member");
      }
    });

    document.getElementById("org-manager-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const userId = document.getElementById("org-manager-user-id").value;
      const raw = document.getElementById("org-manager-select").value;
      const body = { manager_id: raw ? Number(raw) : null };
      try {
        await api(`/api/org/users/${userId}/manager`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        closeAllModals();
        await loadChart();
      } catch (err) {
        alert(err.message || "Could not set manager");
      }
    });
  }

  function onAppView(view) {
    if (view === "org") {
      showOrg();
      return true;
    }
    hideOrgView();
    return false;
  }

  wire();
  window.OrgApp = { onAppView, hideOrgView, showOrg };
})();
