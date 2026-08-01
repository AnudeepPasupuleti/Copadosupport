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
  let notifTimer = null;

  const dashboardView = document.getElementById("dashboard-view");
  const queueView = document.getElementById("queue-view");
  const taskDetailView = document.getElementById("task-detail-view");
  const taskDetailBody = document.getElementById("task-detail-body");
  const queueTbody = document.getElementById("queue-tbody");
  const queueEmpty = document.getElementById("queue-empty");
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
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Request failed");
    }
    if (res.status === 204) return null;
    return res.json();
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
      const mine = filter.value;
      filter.innerHTML =
        `<option value="">All assignees</option><option value="mine">Assigned to me</option>` + opts;
      filter.value = mine;
    }
    if (formAssignee) {
      formAssignee.innerHTML = `<option value="">Unassigned</option>` + opts;
    }
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
    dashboardView.hidden = false;
    const data = await api("/api/queue/dashboard");
    if (!data) return;

    const metrics = document.getElementById("dash-metrics");
    metrics.innerHTML = [
      ["Total Tasks", data.total],
      ["My Open", data.mine],
      ["Overdue", data.overdue],
      ["Due Today", data.due_today],
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
  }

  async function showQueue() {
    await ensureMeta();
    hideTeamViews();
    queueView.hidden = false;
    await loadQueue();
  }

  async function loadQueue() {
    const q = document.getElementById("queue-search")?.value.trim() || "";
    const status = document.getElementById("queue-filter-status")?.value || "";
    const priority = document.getElementById("queue-filter-priority")?.value || "";
    const assignee = document.getElementById("queue-filter-assignee")?.value || "";
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    if (assignee === "mine") params.set("mine", "true");
    else if (assignee) params.set("assignee_id", assignee);

    const tasks = await api(`/api/queue/tasks?${params}`);
    if (!tasks) return;
    queueTbody.innerHTML = "";
    queueEmpty.hidden = tasks.length > 0;
    tasks.forEach((t) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(t.case_number)}</td>
        <td><button type="button" class="queue-title-btn" data-id="${t.id}">${escapeHtml(t.title)}</button></td>
        <td><span class="badge ${statusClass(t.status)}">${escapeHtml(statusLabel(t.status))}</span></td>
        <td><span class="badge ${priorityClass(t.priority)}">${escapeHtml(t.priority)}</span></td>
        <td>${escapeHtml((t.assignee && t.assignee.name) || "—")}</td>
        <td>${escapeHtml(t.due_date || "—")}</td>`;
      tr.querySelector(".queue-title-btn").addEventListener("click", () => openTaskDetail(t.id));
      queueTbody.appendChild(tr);
    });
  }

  async function openTaskDetail(taskId) {
    await ensureMeta();
    hideTeamViews();
    if (window.ChecklistApp) {
      window.ChecklistApp.activateNav("queue");
      window.ChecklistApp.setPageTitle("Case detail");
    }
    taskDetailView.hidden = false;
    const task = await api(`/api/queue/tasks/${taskId}`);
    if (!task) return;
    renderTaskDetail(task);
  }

  function renderTaskDetail(task) {
    const comments = (task.comments || [])
      .map(
        (c) => `<li class="comment-item">
          <div class="comment-head">
            <strong>${escapeHtml((c.author && c.author.name) || "User")}</strong>
            <span>${escapeHtml(formatWhen(c.created_at))}</span>
          </div>
          <p>${escapeHtml(c.body)}</p>
        </li>`
      )
      .join("");

    taskDetailBody.innerHTML = `
      <div class="task-detail-main">
        <p class="task-case-id">${escapeHtml(task.case_number)}</p>
        <h2 class="task-detail-title">${escapeHtml(task.title)}</h2>
        <div class="task-detail-actions">
          <button type="button" class="btn btn-primary" id="task-edit-btn">Edit</button>
        </div>
        <section class="task-section">
          <h3>Description</h3>
          <p class="task-desc">${escapeHtml(task.description || "No description.")}</p>
        </section>
        <section class="task-section">
          <h3>Comments (${(task.comments || []).length})</h3>
          <ul class="comment-list">${comments || '<li class="upcoming-empty">No comments yet.</li>'}</ul>
          <form id="comment-form" class="comment-form">
            <textarea id="comment-body" class="diary-textarea" rows="3" placeholder="Add a comment…" required></textarea>
            <button type="submit" class="btn btn-primary">Comment</button>
          </form>
        </section>
      </div>
      <aside class="task-detail-meta">
        <dl>
          <dt>Status</dt><dd><span class="badge ${statusClass(task.status)}">${escapeHtml(statusLabel(task.status))}</span></dd>
          <dt>Priority</dt><dd><span class="badge ${priorityClass(task.priority)}">${escapeHtml(task.priority)}</span></dd>
          <dt>Assignee</dt><dd>${escapeHtml((task.assignee && task.assignee.name) || "Unassigned")}</dd>
          <dt>Reporter</dt><dd>${escapeHtml((task.reporter && task.reporter.name) || "—")}</dd>
          <dt>Due</dt><dd>${escapeHtml(task.due_date || "—")}</dd>
          <dt>Tags</dt><dd>${escapeHtml(task.tags || "—")}</dd>
        </dl>
      </aside>`;

    document.getElementById("task-edit-btn")?.addEventListener("click", () => openTaskModal(task));
    document.getElementById("comment-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = document.getElementById("comment-body").value.trim();
      if (!body) return;
      const updated = await api(`/api/queue/tasks/${task.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ body }),
      });
      if (updated) {
        renderTaskDetail(updated);
        refreshNotifications();
      }
    });
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
    document.getElementById("task-modal-title").textContent = task ? "Edit task" : "New task";
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
      alert(err.message || "Could not save task");
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
    notifTimer = setInterval(refreshNotifications, 30000);
  }

  window.TeamApp = {
    onAppView,
    hideTeamViews,
    openTaskDetail,
    refreshNotifications,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
