/**
 * Salesforce Bridge — sync Case / User Story data from the Data Bridge API
 * into the website DB and show a simple dashboard with search/delete.
 */
(function () {
  const bridgeView = document.getElementById("bridge-view");
  const statusEl = document.getElementById("bridge-status");
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

  function metricCard(label, value) {
    return (
      `<div class="dash-card" style="padding:12px">` +
      `<p class="hint" style="margin:0">${escapeHtml(label)}</p>` +
      `<strong style="font-size:1.4rem">${escapeHtml(String(value))}</strong>` +
      `</div>`
    );
  }

  function renderMetrics(dash) {
    if (!metricsEl) return;
    const cases = dash.cases || {};
    const stories = dash.userStories || {};
    const parts = [
      metricCard("Cases synced", cases.total ?? 0),
      metricCard("Open cases", cases.open ?? 0),
      metricCard("User stories", stories.total ?? 0),
      metricCard(
        "Last sync",
        dash.lastSyncedAt
          ? new Date(dash.lastSyncedAt).toLocaleString()
          : "Never"
      ),
    ];
    const byStatus = cases.byStatus || {};
    const topStatuses = Object.entries(byStatus).slice(0, 4);
    for (const [k, v] of topStatuses) {
      parts.push(metricCard(`Cases · ${k}`, v));
    }
    metricsEl.innerHTML = parts.join("");
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
    if (casesCount) casesCount.textContent = `${cases.length} row(s)`;
    if (!cases.length) {
      casesBody.innerHTML =
        '<tr><td colspan="6" class="hint">No cases synced yet. Export from the extension, then Sync now.</td></tr>';
      updateDeleteButtons();
      return;
    }
    for (const c of cases) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td><input type="checkbox" data-id="${escapeHtml(String(c.id))}" aria-label="Select case ${escapeHtml(c.caseNumber || c.sfId || "")}" /></td>` +
        `<td>${escapeHtml(c.caseNumber || "—")}</td>` +
        `<td>${escapeHtml(c.subject || "—")}</td>` +
        `<td>${escapeHtml(c.status || "—")}</td>` +
        `<td>${escapeHtml(c.priority || "—")}</td>` +
        `<td>${escapeHtml(c.caseOwner || "—")}</td>`;
      casesBody.appendChild(tr);
    }
    updateDeleteButtons();
  }

  function renderUserStories(stories) {
    if (!usBody) return;
    usBody.innerHTML = "";
    if (usCount) usCount.textContent = `${stories.length} row(s)`;
    if (!stories.length) {
      usBody.innerHTML =
        '<tr><td colspan="5" class="hint">No user stories synced yet.</td></tr>';
      updateDeleteButtons();
      return;
    }
    for (const s of stories) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td><input type="checkbox" data-id="${escapeHtml(String(s.id))}" aria-label="Select story ${escapeHtml(s.name || s.sfId || "")}" /></td>` +
        `<td>${escapeHtml(s.name || "—")}</td>` +
        `<td>${escapeHtml(s.title || "—")}</td>` +
        `<td>${escapeHtml(s.status || "—")}</td>` +
        `<td>${escapeHtml(s.priority || "—")}</td>`;
      usBody.appendChild(tr);
    }
    updateDeleteButtons();
  }

  async function loadCases() {
    const q = (casesQ?.value || "").trim();
    const qs = new URLSearchParams({ limit: "200" });
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
    if (statusEl) statusEl.textContent = "Loading…";
    try {
      const [status, dash] = await Promise.all([
        api("/api/bridge/status"),
        api("/api/bridge/dashboard"),
      ]);
      if (statusEl) {
        statusEl.textContent = status.reachable
          ? `Connected to ${status.url || "bridge"}`
          : `Bridge unreachable: ${status.message || "unknown"}`;
        statusEl.className = status.reachable ? "hint ok" : "hint login-error";
      }
      renderMetrics(dash);
      await Promise.all([loadCases(), loadUserStories()]);
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = err instanceof Error ? err.message : "Failed to load";
        statusEl.className = "hint login-error";
      }
    }
  }

  async function syncNow() {
    if (syncMsg) syncMsg.textContent = "Syncing from Data Bridge…";
    if (syncBtn) syncBtn.disabled = true;
    try {
      const result = await api("/api/bridge/sync", { method: "POST" });
      if (syncMsg) {
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
        syncMsg.textContent = parts.join(" · ");
      }
      await refresh();
    } catch (err) {
      if (syncMsg) {
        syncMsg.textContent =
          err instanceof Error ? err.message : "Sync failed";
      }
    } finally {
      if (syncBtn) syncBtn.disabled = false;
    }
  }

  async function deleteCases(opts) {
    if (casesMsg) casesMsg.textContent = "Deleting…";
    try {
      const result = await api("/api/bridge/cases/delete", {
        method: "POST",
        body: JSON.stringify(opts),
      });
      if (casesMsg) {
        casesMsg.textContent = `Deleted ${result.deleted || 0} case row(s).`;
      }
      await refresh();
    } catch (err) {
      if (casesMsg) {
        casesMsg.textContent =
          err instanceof Error ? err.message : "Delete failed";
      }
    }
  }

  async function deleteUserStories(opts) {
    if (usMsg) usMsg.textContent = "Deleting…";
    try {
      const result = await api("/api/bridge/user-stories/delete", {
        method: "POST",
        body: JSON.stringify(opts),
      });
      if (usMsg) {
        usMsg.textContent = `Deleted ${result.deleted || 0} user story row(s).`;
      }
      await refresh();
    } catch (err) {
      if (usMsg) {
        usMsg.textContent =
          err instanceof Error ? err.message : "Delete failed";
      }
    }
  }

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
        if (casesMsg) {
          casesMsg.textContent =
            err instanceof Error ? err.message : "Search failed";
        }
      });
    }, 250);
  });

  usQ?.addEventListener("input", () => {
    clearTimeout(usSearchTimer);
    usSearchTimer = setTimeout(() => {
      void loadUserStories().catch((err) => {
        if (usMsg) {
          usMsg.textContent =
            err instanceof Error ? err.message : "Search failed";
        }
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
    void refresh();
    return true;
  }

  window.BridgeApp = {
    onAppView,
    hideBridgeView,
    refresh,
  };
})();
