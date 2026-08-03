/**
 * Salesforce Bridge — sync Case / User Story data from the Data Bridge API
 * into the website DB and show a simple dashboard.
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
  const syncBtn = document.getElementById("bridge-sync-btn");

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

  function renderCases(cases) {
    if (!casesBody) return;
    casesBody.innerHTML = "";
    if (casesCount) casesCount.textContent = `${cases.length} row(s)`;
    if (!cases.length) {
      casesBody.innerHTML =
        '<tr><td colspan="5" class="hint">No cases synced yet. Export from the extension, then Sync now.</td></tr>';
      return;
    }
    for (const c of cases) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${escapeHtml(c.caseNumber || "—")}</td>` +
        `<td>${escapeHtml(c.subject || "—")}</td>` +
        `<td>${escapeHtml(c.status || "—")}</td>` +
        `<td>${escapeHtml(c.priority || "—")}</td>` +
        `<td>${escapeHtml(c.caseOwner || "—")}</td>`;
      casesBody.appendChild(tr);
    }
  }

  function renderUserStories(stories) {
    if (!usBody) return;
    usBody.innerHTML = "";
    if (usCount) usCount.textContent = `${stories.length} row(s)`;
    if (!stories.length) {
      usBody.innerHTML =
        '<tr><td colspan="4" class="hint">No user stories synced yet.</td></tr>';
      return;
    }
    for (const s of stories) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${escapeHtml(s.name || "—")}</td>` +
        `<td>${escapeHtml(s.title || "—")}</td>` +
        `<td>${escapeHtml(s.status || "—")}</td>` +
        `<td>${escapeHtml(s.priority || "—")}</td>`;
      usBody.appendChild(tr);
    }
  }

  async function refresh() {
    if (statusEl) statusEl.textContent = "Loading…";
    try {
      const [status, dash, casesPayload, usPayload] = await Promise.all([
        api("/api/bridge/status"),
        api("/api/bridge/dashboard"),
        api("/api/bridge/cases?limit=200"),
        api("/api/bridge/user-stories?limit=200"),
      ]);
      if (statusEl) {
        statusEl.textContent = status.reachable
          ? `Connected to ${status.url || "bridge"}`
          : `Bridge unreachable: ${status.message || "unknown"}`;
        statusEl.className = status.reachable ? "hint ok" : "hint login-error";
      }
      renderMetrics(dash);
      renderCases(casesPayload.cases || []);
      renderUserStories(usPayload.userStories || []);
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

  syncBtn?.addEventListener("click", () => {
    void syncNow();
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
