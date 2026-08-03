/**
 * Salesforce Bridge — sync Case / User Story data from the Data Bridge API
 * into the website DB and show an ops workspace with search/delete.
 */
(function () {
  const bridgeView = document.getElementById("bridge-view");
  const statusEl = document.getElementById("bridge-status");
  const statusPill = document.getElementById("bridge-status-pill");
  const statusUrl = document.getElementById("bridge-status-url");
  const syncMsg = document.getElementById("bridge-sync-msg");
  const metricsEl = document.getElementById("bridge-metrics");
  const casesBody = document.querySelector("#bridge-cases-table tbody");
  const usBody = document.querySelector("#bridge-us-table tbody");
  const casesCount = document.getElementById("bridge-cases-count");
  const usCount = document.getElementById("bridge-us-count");
  const casesMsg = document.getElementById("bridge-cases-msg");
  const usMsg = document.getElementById("bridge-us-msg");
  const syncBtn = document.getElementById("bridge-sync-btn");
  const casesQ = document.getElementById("bridge-cases-q");
  const usQ = document.getElementById("bridge-us-q");
  const casesDeleteBtn = document.getElementById("bridge-cases-delete");
  const usDeleteBtn = document.getElementById("bridge-us-delete");

  let casesSearchTimer = null;
  let usSearchTimer = null;
  let activeTab = "cases";

  function escapeHtml(str) {
    return String(str ?? "")
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
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail[0]?.msg
            : null;
      throw new Error(msg || "Request failed");
    }
    return data;
  }

  function hideBridgeView() {
    if (bridgeView) bridgeView.hidden = true;
  }

  function setActiveTab(tab) {
    activeTab = tab === "stories" ? "stories" : "cases";
    document.querySelectorAll("[data-bridge-tab]").forEach((btn) => {
      const isActive = btn.getAttribute("data-bridge-tab") === activeTab;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    document.querySelectorAll("[data-bridge-panel]").forEach((panel) => {
      const show = panel.getAttribute("data-bridge-panel") === activeTab;
      panel.hidden = !show;
    });
  }

  function setConnectionStatus(state, urlText, liveText) {
    if (statusPill) {
      statusPill.dataset.state = state;
      statusPill.textContent =
        state === "connected"
          ? "Connected"
          : state === "unreachable"
            ? "Unreachable"
            : "Checking";
    }
    if (statusUrl) {
      statusUrl.textContent = urlText || "";
    }
    if (statusEl) {
      statusEl.textContent = liveText || "";
    }
  }

  function setSyncMessage(text, kind) {
    if (!syncMsg) return;
    if (!text) {
      syncMsg.hidden = true;
      syncMsg.textContent = "";
      syncMsg.classList.remove("is-ok", "is-error");
      return;
    }
    syncMsg.hidden = false;
    syncMsg.textContent = text;
    syncMsg.classList.toggle("is-ok", kind === "ok");
    syncMsg.classList.toggle("is-error", kind === "error");
  }

  function setPanelMessage(el, text, isError) {
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      el.classList.remove("is-error");
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle("is-error", !!isError);
  }

  function metricCard(label, value) {
    return (
      `<div class="metric-card">` +
      `<p class="metric-label">${escapeHtml(label)}</p>` +
      `<p class="metric-value">${escapeHtml(String(value))}</p>` +
      `</div>`
    );
  }

  function renderMetrics(dash) {
    if (!metricsEl) return;
    const cases = dash.cases || {};
    metricsEl.innerHTML = [
      metricCard("New", cases.open ?? 0),
      metricCard("In progress", cases.inProgress ?? 0),
      metricCard("On hold", cases.onHold ?? 0),
      metricCard("Aged over 30 days", cases.agedOver30Days ?? 0),
    ].join("");
  }

  function badgeClassForStatus(status) {
    const raw = String(status || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "_");
    if (!raw) return "badge";
    const map = {
      new: "status-new",
      open: "status-new",
      investigating: "status-investigating",
      in_progress: "status-investigating",
      "in-progress": "status-investigating",
      waiting_customer: "status-waiting_customer",
      waiting_engineering: "status-waiting_engineering",
      resolved: "status-resolved",
      closed: "status-closed",
      done: "status-resolved",
      completed: "status-resolved",
    };
    return `badge ${map[raw] || ""}`.trim();
  }

  function badgeClassForPriority(priority) {
    const raw = String(priority || "")
      .trim()
      .toLowerCase();
    if (!raw) return "badge";
    if (raw.includes("high") || raw === "p1" || raw === "1") {
      return "badge prio-high";
    }
    if (raw.includes("low") || raw === "p3" || raw === "3") {
      return "badge prio-low";
    }
    return "badge prio-medium";
  }

  function badgeCell(value, kind) {
    const label = value || "—";
    if (!value) return `<td>${escapeHtml(label)}</td>`;
    const cls =
      kind === "priority"
        ? badgeClassForPriority(value)
        : badgeClassForStatus(value);
    return `<td><span class="${cls}">${escapeHtml(label)}</span></td>`;
  }

  function emptyStateRow(colspan, title, copy) {
    return (
      `<tr><td colspan="${colspan}">` +
      `<div class="bridge-empty">` +
      `<p class="bridge-empty-title">${escapeHtml(title)}</p>` +
      `<p class="bridge-empty-copy">${escapeHtml(copy)}</p>` +
      `</div>` +
      `</td></tr>`
    );
  }

  function selectedIds(tbody) {
    if (!tbody) return [];
    return Array.from(
      tbody.querySelectorAll('input[type="checkbox"][data-id]:checked')
    ).map((el) => Number(el.getAttribute("data-id")));
  }

  function updateDeleteButtons() {
    const caseIds = selectedIds(casesBody);
    const usIds = selectedIds(usBody);
    if (casesDeleteBtn) {
      casesDeleteBtn.hidden = caseIds.length === 0;
      casesDeleteBtn.textContent =
        caseIds.length > 0
          ? `Delete selected (${caseIds.length})`
          : "Delete selected";
    }
    if (usDeleteBtn) {
      usDeleteBtn.hidden = usIds.length === 0;
      usDeleteBtn.textContent =
        usIds.length > 0
          ? `Delete selected (${usIds.length})`
          : "Delete selected";
    }
  }

  function renderCases(cases) {
    if (!casesBody) return;
    casesBody.innerHTML = "";
    if (casesCount) casesCount.textContent = String(cases.length);
    if (!cases.length) {
      casesBody.innerHTML = emptyStateRow(
        6,
        "No cases synced yet",
        "Export from the Data Bridge extension, then use Sync now."
      );
      updateDeleteButtons();
      return;
    }
    for (const c of cases) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td><input type="checkbox" data-id="${escapeHtml(String(c.id))}" aria-label="Select case ${escapeHtml(c.caseNumber || c.sfId || "")}" /></td>` +
        `<td>${escapeHtml(c.caseNumber || "—")}</td>` +
        `<td>${escapeHtml(c.subject || "—")}</td>` +
        badgeCell(c.status, "status") +
        badgeCell(c.priority, "priority") +
        `<td>${escapeHtml(c.caseOwner || "—")}</td>`;
      casesBody.appendChild(tr);
    }
    updateDeleteButtons();
  }

  function renderUserStories(stories) {
    if (!usBody) return;
    usBody.innerHTML = "";
    if (usCount) usCount.textContent = String(stories.length);
    if (!stories.length) {
      usBody.innerHTML = emptyStateRow(
        5,
        "No user stories synced yet",
        "Export from the Data Bridge extension, then use Sync now."
      );
      updateDeleteButtons();
      return;
    }
    for (const s of stories) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td><input type="checkbox" data-id="${escapeHtml(String(s.id))}" aria-label="Select story ${escapeHtml(s.name || s.sfId || "")}" /></td>` +
        `<td>${escapeHtml(s.name || "—")}</td>` +
        `<td>${escapeHtml(s.title || "—")}</td>` +
        badgeCell(s.status, "status") +
        badgeCell(s.priority, "priority");
      usBody.appendChild(tr);
    }
    updateDeleteButtons();
  }

  async function loadCases() {
    const q = (casesQ?.value || "").trim();
    const qs = new URLSearchParams({ limit: "500" });
    if (q) qs.set("q", q);
    const payload = await api(`/api/bridge/cases?${qs.toString()}`);
    renderCases(payload.cases || []);
  }

  async function loadUserStories() {
    const q = (usQ?.value || "").trim();
    const qs = new URLSearchParams({ limit: "200" });
    if (q) qs.set("q", q);
    const payload = await api(`/api/bridge/user-stories?${qs.toString()}`);
    renderUserStories(payload.userStories || []);
  }

  async function refresh() {
    setConnectionStatus("checking", "", "Loading…");
    try {
      const [status, dash] = await Promise.all([
        api("/api/bridge/status"),
        api("/api/bridge/dashboard"),
      ]);
      if (status.reachable) {
        setConnectionStatus(
          "connected",
          status.url || "",
          `Connected to ${status.url || "bridge"}`
        );
      } else {
        setConnectionStatus(
          "unreachable",
          status.url || "",
          `Bridge unreachable: ${status.message || "unknown"}`
        );
      }
      renderMetrics(dash);
      await Promise.all([loadCases(), loadUserStories()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      setConnectionStatus("unreachable", "", msg);
    }
  }

  async function syncNow() {
    setSyncMessage("Syncing from Data Bridge…");
    if (syncBtn) syncBtn.disabled = true;
    try {
      const result = await api("/api/bridge/sync", { method: "POST" });
      const parts = [
        `Synced: ${result.casesUpserted || 0} case row(s), ` +
          `${result.userStoriesUpserted || 0} user story row(s)`,
        `jobs ${result.jobsProcessed || 0}/${result.jobsFound || 0}`,
        `records ${result.recordsSeen || 0}`,
      ];
      if (result.recordsSkipped) {
        parts.push(`${result.recordsSkipped} skipped (no Id/CaseNumber)`);
      }
      if (result.errors?.length) {
        parts.push(`${result.errors.length} error(s)`);
      }
      setSyncMessage(
        parts.join(" · "),
        result.errors?.length ? "error" : "ok"
      );
      await refresh();
    } catch (err) {
      setSyncMessage(
        err instanceof Error ? err.message : "Sync failed",
        "error"
      );
    } finally {
      if (syncBtn) syncBtn.disabled = false;
    }
  }

  async function deleteCases(opts) {
    setPanelMessage(casesMsg, "Deleting…");
    try {
      const result = await api("/api/bridge/cases/delete", {
        method: "POST",
        body: JSON.stringify(opts),
      });
      setPanelMessage(casesMsg, `Deleted ${result.deleted || 0} case row(s).`);
      await refresh();
    } catch (err) {
      setPanelMessage(
        casesMsg,
        err instanceof Error ? err.message : "Delete failed",
        true
      );
    }
  }

  async function deleteUserStories(opts) {
    setPanelMessage(usMsg, "Deleting…");
    try {
      const result = await api("/api/bridge/user-stories/delete", {
        method: "POST",
        body: JSON.stringify(opts),
      });
      setPanelMessage(
        usMsg,
        `Deleted ${result.deleted || 0} user story row(s).`
      );
      await refresh();
    } catch (err) {
      setPanelMessage(
        usMsg,
        err instanceof Error ? err.message : "Delete failed",
        true
      );
    }
  }

  document.querySelectorAll("[data-bridge-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveTab(btn.getAttribute("data-bridge-tab"));
    });
  });

  syncBtn?.addEventListener("click", () => {
    void syncNow();
  });

  casesBody?.addEventListener("change", (e) => {
    if (e.target instanceof HTMLInputElement && e.target.type === "checkbox") {
      updateDeleteButtons();
    }
  });
  usBody?.addEventListener("change", (e) => {
    if (e.target instanceof HTMLInputElement && e.target.type === "checkbox") {
      updateDeleteButtons();
    }
  });

  document
    .getElementById("bridge-cases-select-all")
    ?.addEventListener("click", () => {
      casesBody
        ?.querySelectorAll('input[type="checkbox"][data-id]')
        .forEach((el) => {
          el.checked = true;
        });
      updateDeleteButtons();
    });

  document.getElementById("bridge-us-select-all")?.addEventListener("click", () => {
    usBody
      ?.querySelectorAll('input[type="checkbox"][data-id]')
      .forEach((el) => {
        el.checked = true;
      });
    updateDeleteButtons();
  });

  casesDeleteBtn?.addEventListener("click", () => {
    const ids = selectedIds(casesBody);
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} selected case row(s) from the website DB?`)) {
      return;
    }
    void deleteCases({ ids, clearAll: false });
  });

  usDeleteBtn?.addEventListener("click", () => {
    const ids = selectedIds(usBody);
    if (!ids.length) return;
    if (
      !confirm(
        `Delete ${ids.length} selected user story row(s) from the website DB?`
      )
    ) {
      return;
    }
    void deleteUserStories({ ids, clearAll: false });
  });

  document.getElementById("bridge-cases-clear")?.addEventListener("click", () => {
    if (
      !confirm(
        "Clear ALL synced cases from the website DB? This cannot be undone."
      )
    ) {
      return;
    }
    void deleteCases({ ids: [], clearAll: true });
  });

  document.getElementById("bridge-us-clear")?.addEventListener("click", () => {
    if (
      !confirm(
        "Clear ALL synced user stories from the website DB? This cannot be undone."
      )
    ) {
      return;
    }
    void deleteUserStories({ ids: [], clearAll: true });
  });

  casesQ?.addEventListener("input", () => {
    clearTimeout(casesSearchTimer);
    casesSearchTimer = setTimeout(() => {
      void loadCases().catch((err) => {
        setPanelMessage(
          casesMsg,
          err instanceof Error ? err.message : "Search failed",
          true
        );
      });
    }, 250);
  });

  usQ?.addEventListener("input", () => {
    clearTimeout(usSearchTimer);
    usSearchTimer = setTimeout(() => {
      void loadUserStories().catch((err) => {
        setPanelMessage(
          usMsg,
          err instanceof Error ? err.message : "Search failed",
          true
        );
      });
    }, 250);
  });

  function onAppView(view) {
    if (view !== "bridge") {
      hideBridgeView();
      return false;
    }
    if (!bridgeView) return false;
    bridgeView.hidden = false;
    setActiveTab(activeTab);
    void refresh();
    return true;
  }

  window.BridgeApp = {
    onAppView,
    hideBridgeView,
    refresh,
  };
})();
