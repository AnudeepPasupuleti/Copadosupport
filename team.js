/**
 * Team Queue, Dashboard, and Notifications for Copado Support.
 * Relies on app.js exporting setView / closeSidebar via window.ChecklistApp hooks.
 */
(function () {
  const STATUS_LABELS = {
    new: "New",
    investigating: "Investigating",
    waiting_customer: "Waiting on Customer",
    waiting_engineering: "Waiting on Engineering",
    resolved: "Resolved",
    closed: "Closed",
  };

  let meta = null;
  let teammates = [];
  let editingTaskId = null;
  let editingTaskVersion = null;
  let openTaskId = null;
  let notifTimer = null;
  let queueScope = "all";

  const dashboardView = document.getElementById("dashboard-view");
  const queueView = document.getElementById("queue-view");
  const taskDetailView = document.getElementById("task-detail-view");
  const taskDetailBody = document.getElementById("task-detail-body");
  const queueTbody = document.getElementById("queue-tbody");
  const tasksToolbar = document.getElementById("tasks-toolbar");

  async function api(path, options = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (res.status === 401) {
      location.href = "/login";
      return null;
    }
    const data = await res.json().catch(() => ({}));
    if (res.status === 409) {
      const err = new Error(data.message || data.detail || "Conflict");
      err.code = data.code;
      err.task = data.task;
      err.status = 409;
      throw err;
    }
    if (!res.ok) {
      const detail = data.detail;
      const msg =
        typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : null;
      throw new Error(msg || data.message || "Request failed");
    }
    if (res.status === 204) return null;
    return data;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  }

  function statusLabel(s) {
    return (meta && meta.status_labels && meta.status_labels[s]) || STATUS_LABELS[s] || s;
  }

  function hideTeamViews() {
    if (dashboardView) dashboardView.hidden = true;
    if (queueView) queueView.hidden = true;
    if (taskDetailView) taskDetailView.hidden = true;
    closeTaskModal();
  }

  async function ensureMeta() {
    if (meta) return;
    meta = await api("/api/queue/meta");
    teammates = (await api("/api/queue/users")) || [];
    fillStatusSelects();
    fillAssigneeSelects();
  }

  function fillStatusSelects() {
    const statuses = (meta && meta.statuses) || Object.keys(STATUS_LABELS);
    const filter = document.getElementById("queue-filter-status");
    const formStatus = document.getElementById("task-status");
    if (filter) {
      const current = filter.value;
      filter.innerHTML = `<option value="">All statuses</option>`;
      statuses.forEach((s) => {
        filter.insertAdjacentHTML(
          "beforeend",
          `<option value="${s}">${escapeHtml(statusLabel(s))}</option>`
        );
      });
      filter.value = current;
    }
    if (formStatus) {
      formStatus.innerHTML = statuses
        .map((s) => `<option value="${s}">${escapeHtml(statusLabel(s))}</option>`)
        .join("");
    }
  }

  function fillAssigneeSelects() {
    const filter = document.getElementById("queue-filter-assignee");
    const formAssignee = document.getElementById("task-assignee");
    const opts = teammates
      .map((u) => `<option value="${u.id}">${escapeHtml(u.name || u.email)}</option>`)
      .join("");
    if (filter) {
      const current = filter.value;
      filter.innerHTML = `<option value="">Any assignee</option>` + opts;
      filter.value = current;
      // Assignee person filter only applies within "All team tickets"
      filter.disabled = queueScope !== "all";
    }
    if (formAssignee) {
      formAssignee.innerHTML = `<option value="">Unassigned</option>` + opts;
    }
  }

  function setQueueScope(scope) {
    queueScope = scope || "all";
    document.querySelectorAll(".queue-scope-btn").forEach((btn) => {
      const active = btn.dataset.scope === queueScope;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    fillAssigneeSelects();
    loadQueue();
  }

  function priorityClass(p) {
    return `prio-${p || "medium"}`;
  }

  function statusClass(s) {
    return `status-${s || "new"}`;
  }

  async function showDashboard() {
    await ensureMeta();
    hideTeamViews();
    if (window.OrgApp) window.OrgApp.hideOrgView();
    const todayView = document.getElementById("today-view");
    const profileView = document.getElementById("profile-view");
    if (todayView) todayView.hidden = true;
    if (profileView) profileView.hidden = true;
    dashboardView.hidden = false;
    const data = await api("/api/queue/dashboard");
    if (!data) return;

    const myTasks = window.ChecklistApp?.getMyTasks?.() || {
      open: [],
      done: [],
      openCount: 0,
      doneCount: 0,
      total: 0,
    };

    const metrics = document.getElementById("dash-metrics");
    metrics.innerHTML = [
      ["Total Tickets", data.total],
      ["My Open Tickets", data.mine],
      ["Overdue Tickets", data.overdue],
      ["Tickets Due Today", data.due_today],
      ["My Tasks Open", myTasks.openCount],
      ["My Tasks Done", myTasks.doneCount],
    ]
      .map(
        ([label, value]) =>
          `<div class="metric-card"><p class="metric-label">${label}</p><p class="metric-value">${value}</p></div>`
      )
      .join("");

    const bars = document.getElementById("dash-status-bars");
    const max = Math.max(1, ...Object.values(data.by_status || {}));
    bars.innerHTML = Object.entries(data.by_status || {})
      .map(([status, count]) => {
        const pct = Math.round((count / max) * 100);
        return `<li class="status-bar-row">
          <span class="status-bar-label">${escapeHtml(statusLabel(status))}</span>
          <span class="status-bar-track"><span class="status-bar-fill" style="width:${pct}%"></span></span>
          <span class="status-bar-count">${count}</span>
        </li>`;
      })
      .join("");

    const upcoming = document.getElementById("dash-upcoming");
    if (!data.upcoming || !data.upcoming.length) {
      upcoming.innerHTML = `<li class="upcoming-empty">No upcoming due dates.</li>`;
    } else {
      upcoming.innerHTML = data.upcoming
        .map(
          (t) => `<li>
            <button type="button" class="upcoming-link" data-task-id="${t.id}">
              <span class="upcoming-id">${escapeHtml(t.case_number)}</span>
              <span class="upcoming-title">${escapeHtml(t.title)}</span>
              <span class="badge ${priorityClass(t.priority)}">${escapeHtml(t.priority)}</span>
              <span class="upcoming-due">${escapeHtml(t.due_date || "")}</span>
            </button>
          </li>`
        )
        .join("");
      upcoming.querySelectorAll("[data-task-id]").forEach((btn) => {
        btn.addEventListener("click", () => openTaskDetail(Number(btn.dataset.taskId)));
      });
    }

    renderMyTasksCard(myTasks);
    renderMyTicketsCard(data.my_tickets || []);

    const gotoTasks = document.getElementById("dash-goto-tasks");
    if (gotoTasks) {
      gotoTasks.onclick = () => window.ChecklistApp?.setView?.("today");
    }
    const gotoTickets = document.getElementById("dash-goto-tickets");
    if (gotoTickets) {
      gotoTickets.onclick = () => {
        queueScope = "assigned";
        window.ChecklistApp?.setView?.("queue");
        // Ensure scope UI matches after navigation
        setTimeout(() => setQueueScope("assigned"), 0);
      };
    }
  }

  function renderMyTasksCard(myTasks) {
    const list = document.getElementById("dash-my-tasks");
    if (!list) return;
    const items = (myTasks.open || []).slice(0, 12);
    if (!items.length) {
      list.innerHTML = `<li class="upcoming-empty">No open personal tasks. Add some under My Tasks.</li>`;
      return;
    }
    list.innerHTML = items
      .map((item) => {
        const due = item.dueDate ? `<span class="dash-task-due">${escapeHtml(item.dueDate)}</span>` : "";
        return `<li class="dash-task-row">
          <span class="dash-task-check" aria-hidden="true">○</span>
          <span class="dash-task-text">${escapeHtml(item.text || "Untitled")}</span>
          ${due}
        </li>`;
      })
      .join("");
  }

  function renderMyTicketsCard(tickets) {
    const list = document.getElementById("dash-my-tickets");
    if (!list) return;
    if (!tickets.length) {
      list.innerHTML = `<li class="upcoming-empty">No open tickets assigned to you.</li>`;
      return;
    }
    list.innerHTML = tickets
      .map(
        (t) => `<li>
          <button type="button" class="upcoming-link" data-task-id="${t.id}">
            <span class="upcoming-id">${escapeHtml(t.case_number)}</span>
            <span class="upcoming-title">${escapeHtml(t.title)}</span>
            <span class="badge ${statusClass(t.status)}">${escapeHtml(statusLabel(t.status))}</span>
          </button>
        </li>`
      )
      .join("");
    list.querySelectorAll("[data-task-id]").forEach((btn) => {
      btn.addEventListener("click", () => openTaskDetail(Number(btn.dataset.taskId)));
    });
  }

  async function showQueue() {
    await ensureMeta();
    hideTeamViews();
    if (window.OrgApp) window.OrgApp.hideOrgView();
    const todayView = document.getElementById("today-view");
    const profileView = document.getElementById("profile-view");
    if (todayView) todayView.hidden = true;
    if (profileView) profileView.hidden = true;
    queueView.hidden = false;
    await loadQueue();
  }

  async function loadQueue() {
    const q = document.getElementById("queue-search")?.value.trim() || "";
    const status = document.getElementById("queue-filter-status")?.value || "";
    const priority = document.getElementById("queue-filter-priority")?.value || "";
    const assignee = document.getElementById("queue-filter-assignee")?.value || "";
    const params = new URLSearchParams();
    params.set("scope", queueScope || "all");
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    if (queueScope === "all" && assignee) params.set("assignee_id", assignee);

    const data = await api(`/api/queue/tasks?${params}`);
    if (!data) return;
    const tasks = Array.isArray(data) ? data : data.items || [];
    queueTbody.innerHTML = "";
    const empty = document.getElementById("queue-empty");
    if (empty) {
      empty.hidden = tasks.length > 0;
      const title = empty.querySelector(".empty-title");
      const hint = empty.querySelector(".empty-hint");
      if (tasks.length === 0) {
        if (queueScope === "assigned") {
          if (title) title.textContent = "Nothing assigned to you";
          if (hint) hint.textContent = "Tickets assigned to you will show up here.";
        } else if (queueScope === "created") {
          if (title) title.textContent = "You haven’t created any tickets";
          if (hint) hint.textContent = "Use + New Ticket to report a ticket for the team.";
        } else {
          if (title) title.textContent = "No tickets yet";
          if (hint) hint.textContent = "Create a team ticket to start collaborating.";
        }
      }
    }
    tasks.forEach((t) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(t.case_number)}</td>
        <td><button type="button" class="queue-title-btn" data-id="${t.id}">${escapeHtml(t.title)}</button></td>
        <td><span class="badge ${statusClass(t.status)}">${escapeHtml(statusLabel(t.status))}</span></td>
        <td><span class="badge ${priorityClass(t.priority)}">${escapeHtml(t.priority)}</span></td>
        <td>${escapeHtml((t.assignee && t.assignee.name) || "—")}</td>
        <td>${escapeHtml((t.reporter && t.reporter.name) || "—")}</td>
        <td>${escapeHtml(t.due_date || "—")}</td>`;
      tr.querySelector(".queue-title-btn").addEventListener("click", () => openTaskDetail(t.id));
      tr.style.cursor = "pointer";
      tr.addEventListener("click", (e) => {
        if (e.target.closest("button, a, select, input")) return;
        openTaskDetail(t.id);
      });
      queueTbody.appendChild(tr);
    });
  }

  async function openTaskDetail(taskId) {
    await ensureMeta();
    hideTeamViews();
    const todayView = document.getElementById("today-view");
    const diaryView = document.getElementById("diary-view");
    const historyView = document.getElementById("history-view");
    const comingSoon = document.getElementById("coming-soon-view");
    const toolbar = document.getElementById("tasks-toolbar");
    if (todayView) todayView.hidden = true;
    if (diaryView) diaryView.hidden = true;
    if (historyView) historyView.hidden = true;
    if (comingSoon) comingSoon.hidden = true;
    if (toolbar) toolbar.hidden = true;
    const profileView = document.getElementById("profile-view");
    if (profileView) profileView.hidden = true;

    if (window.ChecklistApp) {
      window.ChecklistApp.activateNav("queue");
      window.ChecklistApp.setPageTitle("Ticket detail");
    }
    taskDetailView.hidden = false;
    try {
      const task = await api(`/api/queue/tasks/${taskId}`);
      if (!task) return;
      renderTaskDetail(task);
    } catch (err) {
      taskDetailBody.innerHTML = `<p class="login-error">${escapeHtml(err.message || "Could not open ticket")}</p>`;
    }
  }

  function currentUserId() {
    return window.ChecklistApp?.getCurrentUser?.()?.id ?? null;
  }

  function mentionableTeammates() {
    const me = currentUserId();
    return (teammates || []).filter((u) => u && u.id !== me);
  }

  function mentionHandle(user) {
    const emailLocal = (user.email || "").split("@")[0];
    if (emailLocal) return emailLocal;
    return (user.name || `user${user.id}`).replace(/\s+/g, "");
  }

  function mentionAliases(user) {
    const aliases = new Set();
    const handle = mentionHandle(user);
    if (handle) aliases.add(handle);
    if (user.name) {
      aliases.add(user.name);
      aliases.add(user.name.replace(/\s+/g, ""));
      user.name.split(/\s+/).filter(Boolean).forEach((part) => aliases.add(part));
    }
    return [...aliases];
  }

  function formatCommentBody(body, mentionIds) {
    const raw = body || "";
    const people = (teammates || []).filter((u) => (mentionIds || []).includes(u.id));
    const tokens = people
      .flatMap((u) => mentionAliases(u).map((alias) => ({ alias, user: u })))
      .sort((a, b) => b.alias.length - a.alias.length);
    if (!tokens.length) return escapeHtml(raw);

    let i = 0;
    let out = "";
    while (i < raw.length) {
      if (raw[i] === "@") {
        const rest = raw.slice(i + 1);
        const hit = tokens.find((t) => rest.toLowerCase().startsWith(t.alias.toLowerCase()));
        if (hit) {
          const label = hit.user.name || hit.alias;
          out += `<span class="comment-mention">@${escapeHtml(label)}</span>`;
          i += 1 + hit.alias.length;
          continue;
        }
      }
      out += escapeHtml(raw[i]);
      i += 1;
    }
    return out;
  }

  function extractMentionIds(text) {
    const ids = new Set();
    const people = mentionableTeammates();
    const tokens = people
      .flatMap((u) => mentionAliases(u).map((alias) => ({ alias, id: u.id })))
      .sort((a, b) => b.alias.length - a.alias.length);
    for (let i = 0; i < text.length; i += 1) {
      if (text[i] !== "@") continue;
      const rest = text.slice(i + 1);
      const hit = tokens.find((t) => rest.toLowerCase().startsWith(t.alias.toLowerCase()));
      if (hit) {
        ids.add(hit.id);
        i += hit.alias.length;
      }
    }
    return [...ids];
  }

  function bindMentionAutocomplete(textarea, menu) {
    let activeIndex = 0;
    let matches = [];
    let queryStart = -1;

    function hideMenu() {
      menu.hidden = true;
      menu.innerHTML = "";
      matches = [];
      queryStart = -1;
    }

    function mentionQueryAtCursor() {
      const value = textarea.value;
      const caret = textarea.selectionStart ?? 0;
      const before = value.slice(0, caret);
      const at = before.lastIndexOf("@");
      if (at < 0) return null;
      if (at > 0 && !/\s/.test(before[at - 1])) return null;
      const query = before.slice(at + 1);
      if (/\n/.test(query) || query.length > 40) return null;
      if (query.includes("  ")) return null;
      return { at, query };
    }

    function filteredPeople(query) {
      const q = (query || "").trim().toLowerCase();
      return mentionableTeammates().filter((u) => {
        if (!q) return true;
        const hay = `${u.name || ""} ${u.email || ""} ${mentionHandle(u)}`.toLowerCase();
        return hay.includes(q) || mentionAliases(u).some((a) => a.toLowerCase().startsWith(q));
      });
    }

    function renderMenu() {
      if (!matches.length) {
        hideMenu();
        return;
      }
      activeIndex = Math.max(0, Math.min(activeIndex, matches.length - 1));
      menu.innerHTML = matches
        .map(
          (u, idx) => `<button type="button" class="mention-suggest-item${
            idx === activeIndex ? " is-active" : ""
          }" data-idx="${idx}" role="option">
            <strong>${escapeHtml(u.name || mentionHandle(u))}</strong>
            <span>${escapeHtml(u.email || "")}</span>
          </button>`
        )
        .join("");
      menu.hidden = false;
      menu.querySelectorAll(".mention-suggest-item").forEach((btn) => {
        btn.addEventListener("mousedown", (e) => {
          e.preventDefault();
          insertMention(matches[Number(btn.dataset.idx)]);
        });
      });
    }

    function insertMention(user) {
      if (!user || queryStart < 0) return;
      const caret = textarea.selectionStart ?? 0;
      const before = textarea.value.slice(0, queryStart);
      const after = textarea.value.slice(caret);
      const label = (user.name || "").trim().split(/\s+/)[0] || mentionHandle(user);
      const token = `@${label}`;
      textarea.value = `${before}${token} ${after}`;
      const next = before.length + token.length + 1;
      textarea.focus();
      textarea.setSelectionRange(next, next);
      hideMenu();
    }

    function refreshFromCaret() {
      const found = mentionQueryAtCursor();
      if (!found) {
        hideMenu();
        return;
      }
      queryStart = found.at;
      matches = filteredPeople(found.query).slice(0, 8);
      activeIndex = 0;
      renderMenu();
    }

    textarea.addEventListener("input", refreshFromCaret);
    textarea.addEventListener("click", refreshFromCaret);
    textarea.addEventListener("blur", () => setTimeout(hideMenu, 120));
    textarea.addEventListener("keydown", (e) => {
      if (menu.hidden || !matches.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIndex = (activeIndex + 1) % matches.length;
        renderMenu();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = (activeIndex - 1 + matches.length) % matches.length;
        renderMenu();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insertMention(matches[activeIndex]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        hideMenu();
      }
    });
  }

  function renderTaskDetail(task) {
    openTaskId = task.id;
    const comments = (task.comments || [])
      .map(
        (c) => `<li class="comment-item">
          <div class="comment-head">
            <strong>${escapeHtml((c.author && c.author.name) || "User")}</strong>
            <span>${escapeHtml(formatWhen(c.created_at))}</span>
          </div>
          <p class="comment-body">${formatCommentBody(c.body, c.mention_ids)}</p>
        </li>`
      )
      .join("");

    taskDetailBody.innerHTML = `
      <div class="task-detail-main">
        <p class="task-case-id">${escapeHtml(task.case_number)}</p>
        <h2 class="task-detail-title">${escapeHtml(task.title)}</h2>
        <div class="task-detail-actions">
          <button type="button" class="btn btn-primary" id="task-edit-btn">Edit ticket</button>
        </div>
        <section class="task-section">
          <h3>Description</h3>
          <p class="task-desc">${escapeHtml(task.description || "No description.")}</p>
        </section>
        <section class="task-section">
          <h3>Comments (${(task.comments || []).length})</h3>
          <ul class="comment-list">${comments || '<li class="upcoming-empty">No comments yet.</li>'}</ul>
          <form id="comment-form" class="comment-form">
            <div class="comment-compose">
              <textarea id="comment-body" class="diary-textarea" rows="3" placeholder="Add a comment… Type @ to mention someone" required></textarea>
              <div id="mention-suggest" class="mention-suggest" hidden role="listbox"></div>
            </div>
            <button type="submit" class="btn btn-primary">Comment</button>
          </form>
        </section>
        <section class="task-section">
          <h3>Activity</h3>
          <ul class="activity-list" id="task-activity-list"><li class="upcoming-empty">Loading…</li></ul>
        </section>
      </div>
      <aside class="task-detail-meta">
        <dl>
          <dt>Status</dt><dd><span class="badge ${statusClass(task.status)}">${escapeHtml(statusLabel(task.status))}</span></dd>
          <dt>Priority</dt><dd><span class="badge ${priorityClass(task.priority)}">${escapeHtml(task.priority)}</span></dd>
          <dt>Assignee</dt><dd>${escapeHtml((task.assignee && task.assignee.name) || "Unassigned")}</dd>
          <dt>Reporter</dt><dd>${escapeHtml((task.reporter && task.reporter.name) || "—")}</dd>
          <dt>Due</dt><dd>${escapeHtml(task.due_date || "—")}</dd>
          <dt>Version</dt><dd>${escapeHtml(String(task.version || 1))}</dd>
          <dt>Tags</dt><dd>${escapeHtml(task.tags || "—")}</dd>
        </dl>
      </aside>`;

    document.getElementById("task-edit-btn")?.addEventListener("click", () => openTaskModal(task));
    const commentBody = document.getElementById("comment-body");
    const mentionMenu = document.getElementById("mention-suggest");
    if (commentBody && mentionMenu) bindMentionAutocomplete(commentBody, mentionMenu);

    document.getElementById("comment-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = document.getElementById("comment-body").value.trim();
      if (!body) return;
      const mention_ids = extractMentionIds(body);
      const updated = await api(`/api/queue/tasks/${task.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ body, mention_ids }),
      });
      if (updated) {
        renderTaskDetail(updated);
        refreshNotifications();
      }
    });
    loadActivities(task.id);
  }

  async function loadActivities(taskId) {
    const list = document.getElementById("task-activity-list");
    if (!list) return;
    try {
      const data = await api(`/api/queue/tasks/${taskId}/activities`);
      const items = data?.items || [];
      if (!items.length) {
        list.innerHTML = `<li class="upcoming-empty">No activity yet.</li>`;
        return;
      }
      list.innerHTML = items
        .map(
          (a) => `<li class="activity-item">
            <strong>${escapeHtml(a.type)}</strong>
            <span>${escapeHtml(formatWhen(a.occurred_at))}</span>
          </li>`
        )
        .join("");
    } catch {
      list.innerHTML = `<li class="upcoming-empty">Could not load activity.</li>`;
    }
  }

  function formatWhen(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function openTaskModal(task = null) {
    editingTaskId = task ? task.id : null;
    editingTaskVersion = task ? task.version || 1 : null;
    document.getElementById("task-modal-title").textContent = task ? "Edit ticket" : "New ticket";
    document.getElementById("task-title").value = task?.title || "";
    document.getElementById("task-description").value = task?.description || "";
    document.getElementById("task-status").value = task?.status || "new";
    document.getElementById("task-priority").value = task?.priority || "medium";
    document.getElementById("task-assignee").value = task?.assignee_id || "";
    document.getElementById("task-due").value = task?.due_date || "";
    document.getElementById("task-tags").value = task?.tags || "";
    document.getElementById("task-modal").hidden = false;
  }

  function closeTaskModal() {
    const modal = document.getElementById("task-modal");
    if (modal) modal.hidden = true;
    editingTaskId = null;
    editingTaskVersion = null;
  }

  async function saveTask(e) {
    e.preventDefault();
    const payload = {
      title: document.getElementById("task-title").value.trim(),
      description: document.getElementById("task-description").value.trim(),
      status: document.getElementById("task-status").value,
      priority: document.getElementById("task-priority").value,
      due_date: document.getElementById("task-due").value || null,
      tags: document.getElementById("task-tags").value.trim(),
      assignee_id: document.getElementById("task-assignee").value
        ? Number(document.getElementById("task-assignee").value)
        : null,
    };
    try {
      let task;
      if (editingTaskId) {
        payload.version = editingTaskVersion;
        task = await api(`/api/queue/tasks/${editingTaskId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        task = await api("/api/queue/tasks", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      closeTaskModal();
      refreshNotifications();
      if (task) openTaskDetail(task.id);
    } catch (err) {
      if (err.status === 409 && err.task) {
        alert(err.message || "This ticket was updated by someone else. Reloading…");
        closeTaskModal();
        openTaskDetail(err.task.id);
        return;
      }
      alert(err.message || "Could not save ticket");
    }
  }

  /* ——— Notifications ——— */

  async function refreshNotifications() {
    const data = await api("/api/queue/notifications");
    if (!data) return;
    const badge = document.getElementById("notif-badge");
    const list = document.getElementById("notif-list");
    const empty = document.getElementById("notif-empty");
    if (badge) {
      badge.hidden = data.unread < 1;
      badge.textContent = data.unread > 9 ? "9+" : String(data.unread);
    }
    if (!list) return;
    list.innerHTML = "";
    empty.hidden = data.items.length > 0;
    data.items.forEach((n) => {
      const li = document.createElement("li");
      li.className = `notif-item${n.read ? "" : " unread"}`;
      li.innerHTML = `<button type="button" class="notif-item-btn">
        <strong>${escapeHtml(n.title)}</strong>
        <span>${escapeHtml(n.body)}</span>
        <time>${escapeHtml(formatWhen(n.created_at))}</time>
      </button>`;
      li.querySelector("button").addEventListener("click", async () => {
        await api("/api/queue/notifications/read", {
          method: "POST",
          body: JSON.stringify({ ids: [n.id] }),
        });
        closeNotifPanel();
        if (n.task_id) openTaskDetail(n.task_id);
        else refreshNotifications();
      });
      list.appendChild(li);
    });
  }

  function toggleNotifPanel() {
    const panel = document.getElementById("notif-panel");
    const btn = document.getElementById("notif-btn");
    if (!panel || !btn) return;
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) refreshNotifications();
  }

  function closeNotifPanel() {
    const panel = document.getElementById("notif-panel");
    const btn = document.getElementById("notif-btn");
    if (panel) panel.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function onAppView(view) {
    hideTeamViews();
    if (view === "dashboard") {
      if (tasksToolbar) tasksToolbar.hidden = true;
      showDashboard();
      return true;
    }
    if (view === "queue") {
      if (tasksToolbar) tasksToolbar.hidden = true;
      showQueue();
      return true;
    }
    return false;
  }

  function wire() {
    document.getElementById("queue-new-btn")?.addEventListener("click", () => openTaskModal());
    document.getElementById("task-modal-cancel")?.addEventListener("click", closeTaskModal);
    document.getElementById("task-modal-backdrop")?.addEventListener("click", closeTaskModal);
    document.getElementById("task-form")?.addEventListener("submit", saveTask);
    document.getElementById("task-back-btn")?.addEventListener("click", () => {
      if (window.ChecklistApp) window.ChecklistApp.setView("queue");
      else showQueue();
    });
    document.querySelectorAll(".queue-scope-btn").forEach((btn) => {
      btn.addEventListener("click", () => setQueueScope(btn.dataset.scope));
    });
    ["queue-search", "queue-filter-status", "queue-filter-priority", "queue-filter-assignee"].forEach(
      (id) => {
        document.getElementById(id)?.addEventListener("change", loadQueue);
        document.getElementById(id)?.addEventListener("input", () => {
          if (id === "queue-search") {
            clearTimeout(loadQueue._t);
            loadQueue._t = setTimeout(loadQueue, 250);
          }
        });
      }
    );

    document.getElementById("notif-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleNotifPanel();
    });
    document.getElementById("notif-mark-all")?.addEventListener("click", async () => {
      await api("/api/queue/notifications/read", { method: "POST", body: JSON.stringify({}) });
      refreshNotifications();
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".notif-wrap")) closeNotifPanel();
    });

    refreshNotifications();
    notifTimer = setInterval(() => {
      if (!window.RealtimeApp || !window.RealtimeApp.isConnected()) {
        refreshNotifications();
      }
    }, 30000);
  }

  function onRealtimeEvent(envelope) {
    const type = envelope?.event_type || "";
    if (queueView && !queueView.hidden) loadQueue();
    if (dashboardView && !dashboardView.hidden) showDashboard();
    if (
      openTaskId &&
      taskDetailView &&
      !taskDetailView.hidden &&
      (type.startsWith("case.") || type.startsWith("comment.") || type.startsWith("mention."))
    ) {
      const agg = envelope.aggregate_id;
      if (!agg || Number(agg) === Number(openTaskId)) {
        openTaskDetail(openTaskId);
      }
    }
  }

  window.TeamApp = {
    onAppView,
    hideTeamViews,
    openTaskDetail,
    refreshNotifications,
    onRealtimeEvent,
    loadQueue,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
