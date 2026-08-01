const STORAGE_KEY = "personal-checklist-v2";
const APP_URL = "http://localhost:8080";
const THEME_KEY = "checklist-theme";
const REMIND_KEY = "checklist-reminders-enabled";
const REMIND_SENT_KEY = "checklist-reminders-sent";

let state = freshState();
let hideChecked = false;
let editingId = null;
let lastCelebrated = false;
let activeView = "today";
let serverSync = false;
let pollTimer = null;
let saveQueue = Promise.resolve();
let activeTagFilter = "";
let searchQuery = "";
let remindTimer = null;
const form = document.getElementById("add-form");
const input = document.getElementById("item-input");
const list = document.getElementById("checklist");
const emptyState = document.getElementById("empty-state");
const progressCard = document.getElementById("progress-card");
const progressBarFill = document.getElementById("progress-bar-fill");
const progressPercent = document.getElementById("progress-percent");
const progressLabel = document.getElementById("progress-label");
const progressHint = document.getElementById("progress-hint");
const completionBanner = document.getElementById("completion-banner");
const panelActions = document.getElementById("panel-actions");
const checkAllBtn = document.getElementById("check-all");
const toggleCompletedBtn = document.getElementById("toggle-completed");
const toggleCompletedLabel = document.getElementById("toggle-completed-label");
const clearCheckedBtn = document.getElementById("clear-checked");
const resetAllBtn = document.getElementById("reset-all");
const dateLabel = document.getElementById("date-label");
const syncStatus = document.getElementById("sync-status");
const storageWarning = document.getElementById("storage-warning");
const exportBtn = document.getElementById("export-btn");
const importBtn = document.getElementById("import-btn");
const importFile = document.getElementById("import-file");
const confettiEl = document.getElementById("confetti");
const rolloverBanner = document.getElementById("rollover-banner");
const rolloverText = document.getElementById("rollover-text");
const todayView = document.getElementById("today-view");
const historyView = document.getElementById("history-view");
const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");
const diaryForm = document.getElementById("diary-form");
const diaryInput = document.getElementById("diary-input");
const diaryEntriesToday = document.getElementById("diary-entries-today");
const diaryEmptyToday = document.getElementById("diary-empty-today");
const diaryView = document.getElementById("diary-view");
const diaryArchiveList = document.getElementById("diary-archive-list");
const diaryArchiveEmpty = document.getElementById("diary-archive-empty");
const userChip = document.getElementById("user-chip");
const userName = document.getElementById("user-name");
const userAvatar = document.getElementById("user-avatar");
const logoutBtn = document.getElementById("logout-btn");
const themeBtn = document.getElementById("theme-btn");
const remindBtn = document.getElementById("remind-btn");
const searchInput = document.getElementById("search-input");
const addPriority = document.getElementById("add-priority");
const addTag = document.getElementById("add-tag");
const addDue = document.getElementById("add-due");
const menuBtn = document.getElementById("menu-btn");
const appMenu = document.getElementById("app-menu");
const detailsToggle = document.getElementById("details-toggle");
const addDetails = document.getElementById("add-details");
const menuAdminSlot = document.getElementById("menu-admin-slot");
const sidebarAdminSlot = document.getElementById("sidebar-admin-slot");
const pageTitle = document.getElementById("page-title");
const comingSoonView = document.getElementById("coming-soon-view");
const comingSoonTitle = document.getElementById("coming-soon-title");
const comingSoonText = document.getElementById("coming-soon-text");
const tasksToolbar = document.getElementById("tasks-toolbar");
const profileView = document.getElementById("profile-view");
const profileMenuBtn = document.getElementById("profile-menu-btn");
const appShell = document.querySelector(".app-shell");
const sidebarOpen = document.getElementById("sidebar-open");
const sidebarClose = document.getElementById("sidebar-close");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");

const STUB_COPY = {
  calendar: {
    title: "Calendar",
    text: "Due-date calendar views are on the roadmap. Due dates already work on checklist items and team cases.",
  },
  reports: {
    title: "Reports",
    text: "SLA and completion reports will appear here later. Use Dashboard for live queue health today.",
  },
  settings: {
    title: "Settings",
    text: "Workspace settings are planned for a later phase. Theme, reminders, and export live in the account menu (⋯).",
  },
};

let currentUser = null;

init();

async function init() {
  const authed = await requireAuth();
  if (!authed) return;

  await bootstrapState();

  processDayRollover();
  updateDateLabel();
  checkStorageOrigin();
  updateSyncStatus();

  form.addEventListener("submit", onAdd);
  checkAllBtn.addEventListener("click", checkAll);
  toggleCompletedBtn.addEventListener("click", () => {
    hideChecked = !hideChecked;
    render();
  });
  clearCheckedBtn.addEventListener("click", clearChecked);
  resetAllBtn.addEventListener("click", uncheckAll);
  diaryForm.addEventListener("submit", onDiarySave);
  diaryInput.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      onDiarySave(e);
    }
  });
  exportBtn.addEventListener("click", () => {
    exportData();
    closeAppMenu();
  });
  importBtn.addEventListener("click", () => {
    importFile.click();
    closeAppMenu();
  });
  importFile.addEventListener("change", onImportFile);
  logoutBtn?.addEventListener("click", onLogout);
  themeBtn?.addEventListener("click", () => {
    toggleTheme();
    closeAppMenu();
  });
  remindBtn?.addEventListener("click", async () => {
    await enableReminders();
    closeAppMenu();
  });
  menuBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAppMenu();
  });
  document.addEventListener("click", (e) => {
    if (!appMenu || appMenu.hidden) return;
    if (!e.target.closest(".menu-wrap")) closeAppMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAppMenu();
  });
  detailsToggle?.addEventListener("click", () => {
    const open = addDetails.hidden;
    addDetails.hidden = !open;
    detailsToggle.setAttribute("aria-expanded", String(open));
  });
  searchInput?.addEventListener("input", () => {
    searchQuery = (searchInput.value || "").trim().toLowerCase();
    render();
  });
  document.querySelectorAll(".tag-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTagFilter = btn.dataset.tag || "";
      document.querySelectorAll(".tag-filter").forEach((b) => {
        b.classList.toggle("is-active", (b.dataset.tag || "") === activeTagFilter);
      });
      render();
    });
  });

  document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });
  document.querySelectorAll(".nav-item[data-stub]").forEach((btn) => {
    btn.addEventListener("click", () => showComingSoon(btn.dataset.nav));
  });
  profileMenuBtn?.addEventListener("click", () => {
    closeAppMenu();
    setView("profile");
  });
  userChip?.addEventListener("click", () => setView("profile"));
  document.getElementById("profile-form")?.addEventListener("submit", onSaveProfile);
  document.getElementById("profile-password-form")?.addEventListener("submit", onSavePassword);
  sidebarOpen?.addEventListener("click", openSidebar);
  sidebarClose?.addEventListener("click", closeSidebar);
  sidebarBackdrop?.addEventListener("click", closeSidebar);

  updateThemeButton();
  updateRemindButton();
  startReminderChecks();

  window.addEventListener("storage", (e) => {
    if (!serverSync && (e.key === STORAGE_KEY || e.key === `${STORAGE_KEY}:updated`)) {
      reloadFromStorage();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      reloadRemoteState();
      if (serverSync) startPolling();
    } else if (serverSync) {
      startPolling(true);
    }
  });
  window.addEventListener("focus", reloadRemoteState);
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) reloadRemoteState();
  });

  if (serverSync) startPolling();

  render();
}

async function requireAuth() {
  try {
    const res = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
    if (res.status === 401) {
      location.href = "/login";
      return false;
    }
    if (!res.ok) throw new Error("auth failed");
    currentUser = await res.json();
    showUser(currentUser);
    return true;
  } catch {
    location.href = "/login";
    return false;
  }
}

function showUser(user) {
  if (!userChip) return;
  userChip.hidden = false;
  userChip.style.cursor = "pointer";
  userChip.title = "Open profile";
  userName.textContent = user.name || user.email || user.username || "User";
  if (user.picture && userAvatar) {
    userAvatar.src = user.picture;
    userAvatar.hidden = false;
  } else if (userAvatar) {
    userAvatar.hidden = true;
  }

  const banner = document.getElementById("impersonation-banner");
  const bannerText = document.getElementById("impersonation-text");
  if (banner) {
    if (user.impersonating) {
      banner.hidden = false;
      if (bannerText) {
        bannerText.textContent = `Logged in as ${user.name || user.email || "user"} (Admin impersonation)`;
      }
      document.body.classList.add("is-impersonating");
    } else {
      banner.hidden = true;
      document.body.classList.remove("is-impersonating");
    }
  }

  // Admin control must not exist in the DOM for non-admins
  document.getElementById("admin-link")?.remove();
  document.getElementById("admin-nav")?.remove();
  if (user.is_admin && !user.impersonating) {
    if (menuAdminSlot) {
      const adminLink = document.createElement("a");
      adminLink.id = "admin-link";
      adminLink.className = "menu-item";
      adminLink.href = "/admin";
      adminLink.setAttribute("role", "menuitem");
      adminLink.textContent = "Admin console";
      menuAdminSlot.appendChild(adminLink);
    }
    if (sidebarAdminSlot) {
      const adminNav = document.createElement("a");
      adminNav.id = "admin-nav";
      adminNav.className = "nav-item";
      adminNav.href = "/admin";
      adminNav.innerHTML =
        '<span class="nav-icon" aria-hidden="true">◎</span> Admin';
      sidebarAdminSlot.appendChild(adminNav);
    }
  }
}

function toggleAppMenu() {
  if (!appMenu || !menuBtn) return;
  const open = appMenu.hidden;
  appMenu.hidden = !open;
  menuBtn.setAttribute("aria-expanded", String(open));
}

function closeAppMenu() {
  if (!appMenu || !menuBtn) return;
  appMenu.hidden = true;
  menuBtn.setAttribute("aria-expanded", "false");
}

async function onLogout() {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  location.href = "/login";
}

document.getElementById("stop-impersonating-btn")?.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/admin/stop-impersonating", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!res.ok) throw new Error("Could not return to Admin");
    location.href = "/admin#users";
  } catch (err) {
    alert(err.message || "Could not return to Admin");
  }
});

async function bootstrapState() {
  if (location.protocol === "file:") {
    location.href = "/login";
    return;
  }

  try {
    const health = await fetch("/api/health", { credentials: "same-origin" });
    if (!health.ok) throw new Error("no api");
    serverSync = true;
  } catch {
    state = freshState();
    return;
  }

  const remote = await fetchRemoteState();
  if (remote) {
    state = normalizeState(remote);
    saveStateToLocal(state);
  } else {
    state = freshState();
  }
}

function normalizeState(s) {
  return {
    activeDate: s.activeDate || todayKey(),
    items: (s.items || []).map(normalizeItem),
    history: (s.history || []).map((day) => ({
      ...day,
      items: (day.items || []).map(normalizeItem),
    })),
    diary: s.diary || [],
    updatedAt: s.updatedAt,
  };
}

function normalizeItem(item) {
  return {
    id: item.id,
    text: item.text || "",
    checked: !!item.checked,
    checkedAt: item.checkedAt ?? null,
    createdAt: item.createdAt ?? Date.now(),
    addedOn: item.addedOn || null,
    carriedFrom: item.carriedFrom ?? null,
    rolledOver: item.rolledOver,
    priority: ["low", "medium", "high"].includes(item.priority) ? item.priority : "",
    tag: ["work", "personal"].includes(item.tag) ? item.tag : "",
    dueDate: item.dueDate || null,
  };
}

function hasStateContent(s) {
  return (
    (s.items && s.items.length > 0) ||
    (s.history && s.history.length > 0) ||
    (s.diary && s.diary.length > 0)
  );
}

async function fetchRemoteState() {
  try {
    const res = await fetch("/api/state", { cache: "no-store", credentials: "same-origin" });
    if (res.status === 401) {
      location.href = "/login";
      return null;
    }
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function persistToServer(data) {
  const payload = { ...data, updatedAt: Date.now() };
  saveQueue = saveQueue
    .then(async () => {
      const res = await fetch("/api/state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      if (!res.ok) throw new Error("save failed");
      state.updatedAt = payload.updatedAt;
    })
    .catch(() => {});
  return saveQueue;
}

const POLL_MS_ACTIVE = 3000;
const POLL_MS_HIDDEN = 30000;

function startPolling(hidden = document.visibilityState === "hidden") {
  if (pollTimer) clearInterval(pollTimer);
  const ms = hidden ? POLL_MS_HIDDEN : POLL_MS_ACTIVE;
  pollTimer = setInterval(reloadRemoteState, ms);
}

function showSyncToast(message) {
  let el = document.getElementById("sync-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "sync-toast";
    el.className = "sync-toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.hidden = false;
  clearTimeout(showSyncToast._timer);
  showSyncToast._timer = setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

async function reloadRemoteState() {
  if (serverSync) {
    const remote = await fetchRemoteState();
    if (!remote) return;
    const remoteTime = remote.updatedAt || 0;
    const localTime = state.updatedAt || 0;
    if (JSON.stringify(remote) !== JSON.stringify(state) && remoteTime > localTime) {
      applyRemoteState(remote);
      showSyncToast("Updated from another session");
    }
    return;
  }
  reloadFromStorage();
}

function applyRemoteState(remote) {
  state = normalizeState(remote);
  editingId = null;
  processDayRollover();
  updateDateLabel();
  render();
}

function updateSyncStatus() {
  if (location.protocol === "file:") return;
  syncStatus.hidden = false;
  if (serverSync && currentUser) {
    syncStatus.textContent = `● Signed in as ${currentUser.email || currentUser.name} — synced`;
    syncStatus.classList.remove("local-only");
  } else if (serverSync) {
    syncStatus.textContent = "● Shared storage — synced";
    syncStatus.classList.remove("local-only");
  } else {
    syncStatus.textContent = "● Offline — run uvicorn backend.main:app --port 8080";
    syncStatus.classList.add("local-only");
  }
}

function exportData() {
  const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `checklist-${todayKey()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function onImportFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const imported = JSON.parse(reader.result);
      if (!imported.items || !imported.history) throw new Error("invalid");
      if (!confirm("Replace your current checklist with this backup?")) return;
      state = normalizeState({
        activeDate: imported.activeDate || todayKey(),
        items: imported.items,
        history: imported.history,
        diary: imported.diary || [],
        updatedAt: Date.now(),
      });
      saveState();
      processDayRollover();
      updateDateLabel();
      render();
    } catch {
      alert("Could not import — please choose a valid checklist backup file.");
    }
    importFile.value = "";
  };
  reader.readAsText(file);
}

function checkStorageOrigin() {
  if (location.protocol === "file:") {
    storageWarning.hidden = false;
    storageWarning.innerHTML =
      `Opened as a file — use <a href="${APP_URL}">${APP_URL}</a> and run <code>python3 server.py</code> for cross-browser sync.`;
    return;
  }

  if (location.hostname === "127.0.0.1") {
    storageWarning.hidden = false;
    storageWarning.innerHTML =
      `Use <a href="${APP_URL}">localhost:8080</a> (not 127.0.0.1) so all browsers share the same data.`;
    return;
  }

  storageWarning.hidden = true;
}

function reloadFromStorage() {
  const saved = loadLocalState();
  if (!saved) return;

  const prev = JSON.stringify(state);
  const next = JSON.stringify(saved);
  if (prev === next) return;

  state = normalizeState(saved);
  editingId = null;
  processDayRollover();
  updateDateLabel();
  render();
}

function todayKey() {
  return formatDateKey(new Date());
}

function formatDateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseDateKey(key) {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatDisplayDate(key, style = "long") {
  const date = parseDateKey(key);
  if (style === "short") {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function updateDateLabel() {
  dateLabel.textContent = formatDisplayDate(state.activeDate);
}

function createItem(text, { carriedFrom = null, addedOn = null, priority = "", tag = "", dueDate = null } = {}) {
  return {
    id: crypto.randomUUID(),
    text,
    checked: false,
    checkedAt: null,
    createdAt: Date.now(),
    addedOn: addedOn || state.activeDate,
    carriedFrom,
    priority: priority || "",
    tag: tag || "",
    dueDate: dueDate || null,
  };
}

function cloneItemForRollover(item) {
  return {
    id: crypto.randomUUID(),
    text: item.text,
    checked: false,
    checkedAt: null,
    createdAt: Date.now(),
    addedOn: item.addedOn,
    carriedFrom: item.carriedFrom || state.activeDate,
    priority: item.priority || "",
    tag: item.tag || "",
    dueDate: item.dueDate || null,
  };
}

function snapshotItem(item, { rolledOver = false } = {}) {
  return {
    id: item.id,
    text: item.text,
    checked: item.checked,
    checkedAt: item.checkedAt,
    addedOn: item.addedOn,
    carriedFrom: item.carriedFrom,
    rolledOver,
    priority: item.priority || "",
    tag: item.tag || "",
    dueDate: item.dueDate || null,
  };
}

function buildDaySummary(items) {
  const total = items.length;
  const completed = items.filter((i) => i.checked).length;
  const incomplete = total - completed;
  const rolledOver = items.filter((i) => !i.checked).length;
  return { total, completed, incomplete, rolledOver };
}

function archiveDay(dateKey, items) {
  const snapshot = items.map((item) =>
    snapshotItem(item, { rolledOver: !item.checked })
  );
  const summary = buildDaySummary(snapshot);

  const existing = state.history.findIndex((h) => h.date === dateKey);
  const record = { date: dateKey, items: snapshot, summary };

  if (existing >= 0) state.history[existing] = record;
  else state.history.unshift(record);

  state.history.sort((a, b) => b.date.localeCompare(a.date));
}

function processDayRollover() {
  const today = todayKey();

  if (!state.activeDate) {
    state.activeDate = today;
    state.items = state.items || [];
    saveState();
    return;
  }

  if (state.activeDate === today) return;

  const previousItems = state.items || [];
  archiveDay(state.activeDate, previousItems);

  const rolled = previousItems
    .filter((i) => !i.checked)
    .map(cloneItemForRollover);

  state.activeDate = today;
  state.items = rolled;
  lastCelebrated = false;
  saveState();
}

function storageKey() {
  return currentUser ? `${STORAGE_KEY}:u${currentUser.id}` : STORAGE_KEY;
}

function loadLocalState() {
  try {
    const saved = localStorage.getItem(storageKey());
    if (saved) return JSON.parse(saved);
    return migrateLegacyData();
  } catch {
    return null;
  }
}

function freshState() {
  return {
    activeDate: todayKey(),
    items: [],
    history: [],
    diary: [],
  };
}

function migrateLegacyData() {
  const today = todayKey();
  const legacyV1 = localStorage.getItem("personal-checklist");
  const legacyTodos = localStorage.getItem("personal-todos");

  let items = [];
  if (legacyV1) {
    items = JSON.parse(legacyV1).map((t) => ({
      id: t.id,
      text: t.text,
      checked: t.checked ?? t.completed ?? false,
      checkedAt: t.checkedAt ?? null,
      createdAt: t.createdAt ?? Date.now(),
      addedOn: t.addedOn ?? today,
      carriedFrom: t.carriedFrom ?? null,
    }));
  } else if (legacyTodos) {
    items = JSON.parse(legacyTodos).map((t) => ({
      id: t.id,
      text: t.text,
      checked: t.completed ?? false,
      checkedAt: null,
      createdAt: t.createdAt ?? Date.now(),
      addedOn: today,
      carriedFrom: null,
    }));
  }

  const migrated = { activeDate: today, items, history: [], diary: [] };
  saveStateToLocal(migrated);
  return migrated;
}

function saveState() {
  state.updatedAt = Date.now();
  saveStateToLocal(state);
  if (serverSync) persistToServer(state);
}

function saveStateToLocal(data) {
  localStorage.setItem(storageKey(), JSON.stringify(data));
  localStorage.setItem(`${storageKey()}:updated`, String(data.updatedAt || Date.now()));
}

function onAdd(e) {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  state.items.push(
    createItem(text, {
      priority: addPriority?.value || "",
      tag: addTag?.value || "",
      dueDate: addDue?.value || null,
    })
  );
  input.value = "";
  if (addPriority) addPriority.value = "";
  if (addTag) addTag.value = "";
  if (addDue) addDue.value = "";
  saveState();
  render();
  input.focus();
}

function toggleItem(id, row) {
  const item = state.items.find((i) => i.id === id);
  if (!item || editingId === id) return;

  item.checked = !item.checked;
  item.checkedAt = item.checked ? Date.now() : null;
  saveState();

  if (item.checked && row) {
    row.classList.add("just-checked");
    setTimeout(() => row.classList.remove("just-checked"), 400);
  }

  render();
}

function deleteItem(id, e) {
  e.stopPropagation();
  state.items = state.items.filter((i) => i.id !== id);
  saveState();
  render();
}

function checkAll() {
  const now = Date.now();
  state.items.forEach((i) => {
    i.checked = true;
    i.checkedAt = i.checkedAt || now;
  });
  saveState();
  render();
}

function uncheckAll() {
  state.items.forEach((i) => {
    i.checked = false;
    i.checkedAt = null;
  });
  lastCelebrated = false;
  saveState();
  render();
}

function clearChecked() {
  state.items = state.items.filter((i) => !i.checked);
  lastCelebrated = false;
  saveState();
  render();
}

function startEditing(id, el, e) {
  e.stopPropagation();
  editingId = id;
  el.closest(".check-item")?.classList.add("editing-row");
  el.contentEditable = "true";
  el.classList.add("editing");
  el.style.pointerEvents = "auto";
  el.focus();

  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function finishEditing(id, el) {
  const text = el.textContent.trim();
  editingId = null;
  el.closest(".check-item")?.classList.remove("editing-row");
  el.contentEditable = "false";
  el.classList.remove("editing");
  el.style.pointerEvents = "";

  if (!text) {
    state.items = state.items.filter((i) => i.id !== id);
    saveState();
    render();
    return;
  }

  const item = state.items.find((i) => i.id === id);
  if (item && item.text !== text) {
    item.text = text;
    saveState();
  }
  render();
}

function getVisibleItems() {
  let items = hideChecked ? state.items.filter((i) => !i.checked) : state.items.slice();
  if (activeTagFilter) {
    items = items.filter((i) => (i.tag || "") === activeTagFilter);
  }
  if (searchQuery) {
    items = items.filter((i) => (i.text || "").toLowerCase().includes(searchQuery));
  }
  return items.sort((a, b) => {
    const pr = { high: 0, medium: 1, low: 2, "": 3 };
    const pa = pr[a.priority || ""] ?? 3;
    const pb = pr[b.priority || ""] ?? 3;
    if (pa !== pb) return pa - pb;
    if (a.dueDate && b.dueDate) return a.dueDate.localeCompare(b.dueDate);
    if (a.dueDate) return -1;
    if (b.dueDate) return 1;
    return (a.createdAt || 0) - (b.createdAt || 0);
  });
}

function getCarriedCount() {
  return state.items.filter((i) => i.carriedFrom).length;
}

function carriedLabel(item) {
  if (!item.carriedFrom) return null;
  return `Incomplete on ${formatDisplayDate(item.carriedFrom, "short")}`;
}

function updateRolloverBanner() {
  const carried = state.items.filter((i) => i.carriedFrom);
  const uncheckedCarried = carried.filter((i) => !i.checked);

  if (uncheckedCarried.length === 0) {
    rolloverBanner.hidden = true;
    return;
  }

  const dates = [...new Set(uncheckedCarried.map((i) => i.carriedFrom))];
  const datePhrase =
    dates.length === 1
      ? formatDisplayDate(dates[0], "short")
      : "previous days";

  rolloverBanner.hidden = false;
  rolloverText.textContent =
    uncheckedCarried.length === 1
      ? `1 item carried over from ${datePhrase}`
      : `${uncheckedCarried.length} items carried over from ${datePhrase}`;
}

function updateProgress() {
  const items = state.items;
  const total = items.length;
  const checked = items.filter((i) => i.checked).length;
  const percent = total === 0 ? 0 : Math.round((checked / total) * 100);
  const allDone = total > 0 && checked === total;
  const visible = getVisibleItems();

  progressCard.hidden = total === 0;
  panelActions.hidden = total === 0;
  emptyState.hidden = visible.length > 0;
  if (total > 0 && visible.length === 0) {
    emptyState.querySelector(".empty-title").textContent = "No matching items";
    emptyState.querySelector(".empty-hint").textContent =
      "Try clearing search or switching list filter (All / Work / Personal).";
  } else if (total === 0) {
    emptyState.querySelector(".empty-title").textContent = "Nothing for today";
    emptyState.querySelector(".empty-hint").textContent =
      "Add an item below. History fills in after the day rolls over.";
  }
  clearCheckedBtn.hidden = checked === 0;
  completionBanner.hidden = !allDone;

  progressCard.classList.toggle("complete", allDone);
  progressPercent.textContent = `${percent}%`;
  progressLabel.textContent =
    total === 0 ? "No items yet" : `${checked} of ${total} done`;
  if (progressHint) {
    progressHint.textContent = allDone
      ? "Everything is checked off for today!"
      : `${total - checked} remaining — unchecked items roll over tonight`;
  }
  if (progressBarFill) {
    progressBarFill.style.width = `${percent}%`;
  }

  updateRolloverBanner();

  if (allDone && !lastCelebrated) {
    lastCelebrated = true;
    fireConfetti();
  }
  if (!allDone) lastCelebrated = false;
}

function fireConfetti() {
  const colors = ["#2563eb", "#60a5fa", "#059669", "#94a3b8", "#0f172a"];
  confettiEl.innerHTML = "";

  for (let i = 0; i < 24; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = colors[Math.floor(Math.random() * colors.length)];
    piece.style.animationDuration = `${1.5 + Math.random() * 2}s`;
    piece.style.animationDelay = `${Math.random() * 0.5}s`;
    confettiEl.appendChild(piece);
  }

  setTimeout(() => (confettiEl.innerHTML = ""), 3500);
}

function setView(view) {
  activeView = view;
  if (comingSoonView) comingSoonView.hidden = true;
  todayView.hidden = view !== "today";
  diaryView.hidden = view !== "diary";
  historyView.hidden = view !== "history";
  if (profileView) profileView.hidden = view !== "profile";
  if (tasksToolbar) tasksToolbar.hidden = view !== "today";
  if (dateLabel) dateLabel.hidden = view === "profile";

  if (window.TeamApp) {
    window.TeamApp.hideTeamViews();
    if (window.TeamApp.onAppView(view)) {
      const titles = { dashboard: "Dashboard", queue: "Team Queue" };
      if (pageTitle) pageTitle.textContent = titles[view] || view;
      document.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.view === view || item.dataset.nav === view);
      });
      closeSidebar();
      return;
    }
  }

  const titles = {
    today: "My Tasks",
    diary: "Diary",
    history: "History",
    dashboard: "Dashboard",
    queue: "Team Queue",
    profile: "Profile",
  };
  if (pageTitle) pageTitle.textContent = titles[view] || "My Tasks";

  document.querySelectorAll(".nav-item").forEach((item) => {
    const active = item.dataset.view === view;
    item.classList.toggle("is-active", active);
  });

  closeSidebar();
  if (view === "profile") {
    fillProfileForm(currentUser);
    return;
  }
  render();
}

function fillProfileForm(user) {
  if (!user) return;
  const name = user.name || "";
  const email = user.email || "";
  const roleLabel = user.role_label || user.role || "Member";
  document.getElementById("profile-display-name").textContent = name || email || "User";
  document.getElementById("profile-display-email").textContent = email || "—";
  const roleBadge = document.getElementById("profile-role-badge");
  if (roleBadge) {
    roleBadge.textContent = roleLabel;
    roleBadge.className = `badge ${user.is_admin ? "badge-admin" : user.role === "manager" ? "badge-manager" : "badge-muted"}`;
  }
  document.getElementById("profile-name").value = name;
  document.getElementById("profile-email").value = email;
  document.getElementById("profile-username").value = user.username || "—";
  setProfileAvatar(user.picture, name || email);

  const hasPassword = !!user.has_password;
  document.getElementById("profile-password-title").textContent = hasPassword
    ? "Change password"
    : "Set password";
  document.getElementById("profile-password-submit").textContent = hasPassword
    ? "Update password"
    : "Set password";
  document.getElementById("profile-current-password-wrap").hidden = !hasPassword;
  document.getElementById("profile-username-set-wrap").hidden = hasPassword || !!user.username;
  document.getElementById("profile-current-password").value = "";
  document.getElementById("profile-new-password").value = "";
  document.getElementById("profile-set-username").value = user.username || "";
  document.getElementById("profile-error").hidden = true;
  document.getElementById("profile-success").hidden = true;
  document.getElementById("profile-password-error").hidden = true;
  document.getElementById("profile-password-success").hidden = true;
}

function setProfileAvatar(url, label) {
  const img = document.getElementById("profile-avatar");
  const fallback = document.getElementById("profile-avatar-fallback");
  if (!img || !fallback) return;
  if (url) {
    img.src = url;
    img.hidden = false;
    fallback.hidden = true;
  } else {
    img.hidden = true;
    fallback.hidden = false;
    fallback.textContent = (label || "?").trim().charAt(0).toUpperCase() || "?";
  }
}

async function onSaveProfile(e) {
  e.preventDefault();
  const err = document.getElementById("profile-error");
  const ok = document.getElementById("profile-success");
  err.hidden = true;
  ok.hidden = true;
  try {
    const res = await fetch("/api/me/profile", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.getElementById("profile-name").value.trim(),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Could not save profile");
    }
    currentUser = data;
    showUser(currentUser);
    fillProfileForm(currentUser);
    ok.hidden = false;
  } catch (ex) {
    err.textContent = ex.message || "Could not save profile";
    err.hidden = false;
  }
}

async function onSavePassword(e) {
  e.preventDefault();
  const err = document.getElementById("profile-password-error");
  const ok = document.getElementById("profile-password-success");
  err.hidden = true;
  ok.hidden = true;
  const payload = {
    new_password: document.getElementById("profile-new-password").value,
  };
  if (currentUser?.has_password) {
    payload.current_password = document.getElementById("profile-current-password").value;
  } else if (!currentUser?.username) {
    payload.username = document.getElementById("profile-set-username").value.trim();
  }
  try {
    const res = await fetch("/api/me/password", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Could not update password");
    }
    if (data.user) {
      currentUser = data.user;
      showUser(currentUser);
      fillProfileForm(currentUser);
    }
    ok.hidden = false;
  } catch (ex) {
    err.textContent = ex.message || "Could not update password";
    err.hidden = false;
  }
}

function showComingSoon(navKey) {
  activeView = "stub";
  todayView.hidden = true;
  diaryView.hidden = true;
  historyView.hidden = true;
  if (profileView) profileView.hidden = true;
  if (tasksToolbar) tasksToolbar.hidden = true;
  if (dateLabel) dateLabel.hidden = false;
  if (window.TeamApp) window.TeamApp.hideTeamViews();
  if (comingSoonView) comingSoonView.hidden = false;

  const copy = STUB_COPY[navKey] || {
    title: "Coming soon",
    text: "This area is on the Copado Support roadmap.",
  };
  if (pageTitle) pageTitle.textContent = copy.title;
  if (comingSoonTitle) comingSoonTitle.textContent = copy.title;
  if (comingSoonText) comingSoonText.textContent = copy.text;

  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.nav === navKey);
  });
  closeSidebar();
}

function openSidebar() {
  appShell?.classList.add("sidebar-open");
  if (sidebarBackdrop) sidebarBackdrop.hidden = false;
}

function closeSidebar() {
  appShell?.classList.remove("sidebar-open");
  if (sidebarBackdrop) sidebarBackdrop.hidden = true;
}

function formatTimestamp(ts) {
  const date = new Date(ts);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function getDiaryEntries() {
  if (!state.diary) state.diary = [];
  return [...state.diary].sort((a, b) => b.createdAt - a.createdAt);
}

function getTodayDiaryEntries() {
  const today = todayKey();
  return getDiaryEntries().filter((e) => e.date === today);
}

function onDiarySave(e) {
  e.preventDefault();
  const text = diaryInput.value.trim();
  if (!text) return;

  const now = Date.now();
  if (!state.diary) state.diary = [];
  state.diary.unshift({
    id: crypto.randomUUID(),
    text,
    createdAt: now,
    date: todayKey(),
  });

  diaryInput.value = "";
  saveState();
  renderDiaryToday();
  diaryInput.focus();
}

function deleteDiaryEntry(id) {
  state.diary = (state.diary || []).filter((e) => e.id !== id);
  saveState();
  render();
}

function renderDiaryEntry(entry, { showDate = false } = {}) {
  const li = document.createElement("li");
  li.className = "diary-entry";

  const timeLabel = showDate
    ? `${formatDisplayDate(entry.date)} · ${new Date(entry.createdAt).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
    : formatTimestamp(entry.createdAt);

  li.innerHTML = `
    <div class="diary-entry-header">
      <time class="diary-entry-time" datetime="${new Date(entry.createdAt).toISOString()}">${timeLabel}</time>
      <button type="button" class="icon-btn delete diary-delete" aria-label="Delete diary entry">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    </div>
    <p class="diary-entry-text"></p>
  `;

  li.querySelector(".diary-entry-text").textContent = entry.text;
  li.querySelector(".diary-delete").addEventListener("click", () => {
    if (confirm("Delete this diary entry?")) deleteDiaryEntry(entry.id);
  });

  return li;
}

function renderDiaryToday() {
  let entries = getTodayDiaryEntries();
  if (searchQuery) {
    entries = entries.filter((e) => (e.text || "").toLowerCase().includes(searchQuery));
  }
  diaryEntriesToday.innerHTML = "";
  diaryEmptyToday.hidden = entries.length > 0;
  if (searchQuery && entries.length === 0) {
    diaryEmptyToday.querySelector(".empty-hint").textContent = "No diary matches for this search.";
  } else if (!searchQuery) {
    diaryEmptyToday.querySelector(".empty-hint").textContent = "No diary entries yet today.";
  }

  entries.forEach((entry) => {
    diaryEntriesToday.appendChild(renderDiaryEntry(entry));
  });
}

function renderDiaryArchive() {
  diaryArchiveList.innerHTML = "";
  let entries = getDiaryEntries();
  if (searchQuery) {
    entries = entries.filter((e) => (e.text || "").toLowerCase().includes(searchQuery));
  }
  diaryArchiveEmpty.hidden = entries.length > 0;
  diaryArchiveList.hidden = entries.length === 0;
  if (searchQuery && entries.length === 0) {
    diaryArchiveEmpty.querySelector(".empty-title").textContent = "No matching diary entries";
    diaryArchiveEmpty.querySelector(".empty-hint").textContent = "Try a different search.";
  } else if (!searchQuery) {
    diaryArchiveEmpty.querySelector(".empty-title").textContent = "No diary entries yet";
    diaryArchiveEmpty.querySelector(".empty-hint").textContent = "Write your first note on the Today tab.";
  }

  const byDate = {};
  entries.forEach((entry) => {
    if (!byDate[entry.date]) byDate[entry.date] = [];
    byDate[entry.date].push(entry);
  });

  const dates = Object.keys(byDate).sort((a, b) => b.localeCompare(a));

  dates.forEach((dateKey) => {
    const dayEntries = byDate[dateKey];
    const li = document.createElement("li");
    li.className = "diary-day";
    if (searchQuery) li.classList.add("open");

    li.innerHTML = `
      <button type="button" class="diary-day-header" aria-expanded="${searchQuery ? "true" : "false"}">
        <span class="diary-day-date">${formatDisplayDate(dateKey)}</span>
        <span class="diary-day-count">${dayEntries.length} ${dayEntries.length === 1 ? "entry" : "entries"}</span>
        <svg class="history-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </button>
      <ul class="diary-day-items" ${searchQuery ? "" : "hidden"}></ul>
    `;

    const header = li.querySelector(".diary-day-header");
    const itemsEl = li.querySelector(".diary-day-items");

    dayEntries.forEach((entry) => {
      itemsEl.appendChild(renderDiaryEntry(entry, { showDate: false }));
    });

    header.addEventListener("click", () => {
      const open = header.getAttribute("aria-expanded") === "true";
      header.setAttribute("aria-expanded", String(!open));
      itemsEl.hidden = open;
      li.classList.toggle("open", !open);
    });

    diaryArchiveList.appendChild(li);
  });
}

function renderHistoryItemStatus(item) {
  if (item.rolledOver && !item.checked) {
    const from = item.carriedFrom
      ? ` (from ${formatDisplayDate(item.carriedFrom, "short")})`
      : "";
    return { icon: "→", label: `Rolled to next day${from}`, className: "rolled" };
  }
  if (item.checked && item.carriedFrom) {
    return {
      icon: "✓",
      label: `Done — was incomplete ${formatDisplayDate(item.carriedFrom, "short")}`,
      className: "done-carried",
    };
  }
  if (item.checked) {
    return { icon: "✓", label: "Done", className: "done" };
  }
  return { icon: "○", label: "Incomplete", className: "incomplete" };
}

function renderHistory() {
  historyList.innerHTML = "";
  let days = state.history.filter((h) => h.date !== state.activeDate);
  if (searchQuery) {
    days = days
      .map((day) => ({
        ...day,
        items: (day.items || []).filter((i) => (i.text || "").toLowerCase().includes(searchQuery)),
      }))
      .filter((day) => day.items.length > 0);
  }

  historyEmpty.hidden = days.length > 0;
  historyList.hidden = days.length === 0;
  if (searchQuery && days.length === 0) {
    historyEmpty.hidden = false;
    historyEmpty.querySelector(".empty-title").textContent = "No matching history";
    historyEmpty.querySelector(".empty-hint").textContent = "Try a different search.";
  } else if (!searchQuery) {
    const title = historyEmpty.querySelector(".empty-title");
    const hint = historyEmpty.querySelector(".empty-hint");
    if (title) title.textContent = "No history yet";
    if (hint) hint.textContent = "Completed days will appear here after midnight.";
  }

  days.forEach((day) => {
    const li = document.createElement("li");
    li.className = "history-day";
    if (searchQuery) li.classList.add("open");

    const { total, completed, rolledOver } = day.summary || buildDaySummary(day.items || []);
    const summaryText =
      total === 0
        ? "No items"
        : `${completed}/${total} done` +
          (rolledOver > 0 ? ` · ${rolledOver} rolled forward` : "");

    li.innerHTML = `
      <button type="button" class="history-day-header" aria-expanded="${searchQuery ? "true" : "false"}">
        <span class="history-day-date">${formatDisplayDate(day.date)}</span>
        <span class="history-day-summary">${summaryText}</span>
        <svg class="history-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </button>
      <ul class="history-day-items" ${searchQuery ? "" : "hidden"}></ul>
    `;

    const header = li.querySelector(".history-day-header");
    const itemsEl = li.querySelector(".history-day-items");

    day.items.forEach((item) => {
      const status = renderHistoryItemStatus(item);
      const row = document.createElement("li");
      row.className = `history-item ${status.className}`;
      const extras = [item.tag, item.priority, item.dueDate ? `due ${item.dueDate}` : ""]
        .filter(Boolean)
        .join(" · ");
      row.innerHTML = `
        <span class="history-item-icon" aria-hidden="true">${status.icon}</span>
        <div class="history-item-body">
          <span class="history-item-text">${escapeHtml(item.text)}</span>
          <span class="history-item-meta">${status.label}${extras ? ` · ${escapeHtml(extras)}` : ""}</span>
        </div>
      `;
      itemsEl.appendChild(row);
    });

    header.addEventListener("click", () => {
      const open = header.getAttribute("aria-expanded") === "true";
      header.setAttribute("aria-expanded", String(!open));
      itemsEl.hidden = open;
      li.classList.toggle("open", !open);
    });

    historyList.appendChild(li);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderTodayList() {
  toggleCompletedLabel.textContent = hideChecked ? "Show checked" : "Hide checked";

  const visible = getVisibleItems();
  list.innerHTML = "";

  visible.forEach((item) => {
    const overdue = isOverdue(item);
    const li = document.createElement("li");
    li.className = `check-item${item.checked ? " checked" : ""}${item.carriedFrom && !item.checked ? " carried" : ""}${overdue ? " overdue" : ""}${item.priority ? ` priority-${item.priority}` : ""}`;
    li.dataset.id = item.id;
    li.setAttribute("role", "checkbox");
    li.setAttribute("aria-checked", String(item.checked));
    li.tabIndex = 0;

    li.addEventListener("click", (e) => {
      if (e.target.closest(".icon-btn") || e.target.closest(".item-meta-line") || editingId === item.id)
        return;
      toggleItem(item.id, li);
    });

    li.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        if (editingId !== item.id) toggleItem(item.id, li);
      }
    });

    const box = document.createElement("div");
    box.className = "check-box";
    box.innerHTML = `<svg class="check-mark" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;

    const content = document.createElement("div");
    content.className = "item-content";

    const label = document.createElement("span");
    label.className = "item-label";
    label.textContent = item.text;
    label.addEventListener("dblclick", (e) => startEditing(item.id, label, e));
    label.addEventListener("blur", () => {
      if (editingId === item.id) finishEditing(item.id, label);
    });
    label.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") {
        e.preventDefault();
        label.blur();
      }
      if (e.key === "Escape") {
        label.textContent = item.text;
        label.blur();
      }
    });

    content.appendChild(label);

    const metaParts = [];
    if (item.dueDate) {
      metaParts.push(
        overdue
          ? `Overdue ${formatDisplayDate(item.dueDate, "short")}`
          : `Due ${formatDisplayDate(item.dueDate, "short")}`
      );
    }
    if (item.tag) {
      metaParts.push(item.tag === "work" ? "Work" : "Personal");
    }
    if (item.priority) {
      metaParts.push(item.priority.charAt(0).toUpperCase() + item.priority.slice(1));
    }
    const carried = carriedLabel(item);
    if (carried) {
      metaParts.push(
        item.checked ? `Was incomplete · ${formatDisplayDate(item.carriedFrom, "short")}` : carried
      );
    }

    if (metaParts.length) {
      const metaLine = document.createElement("span");
      metaLine.className = `item-meta-line${overdue ? " overdue" : ""}`;
      metaParts.forEach((part, idx) => {
        if (idx > 0) metaLine.appendChild(document.createTextNode(" · "));
        if (item.tag && part === (item.tag === "work" ? "Work" : "Personal")) {
          const tagBtn = document.createElement("button");
          tagBtn.type = "button";
          tagBtn.textContent = part;
          tagBtn.title = "Filter by this list";
          tagBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            activeTagFilter = item.tag;
            document.querySelectorAll(".tag-filter").forEach((b) => {
              b.classList.toggle("is-active", (b.dataset.tag || "") === activeTagFilter);
            });
            render();
          });
          metaLine.appendChild(tagBtn);
        } else {
          metaLine.appendChild(document.createTextNode(part));
        }
      });
      content.appendChild(metaLine);
    }

    const actions = document.createElement("div");
    actions.className = "item-actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "icon-btn";
    editBtn.setAttribute("aria-label", `Edit "${item.text}"`);
    editBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`;
    editBtn.addEventListener("click", (e) => startEditing(item.id, label, e));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "icon-btn delete";
    deleteBtn.setAttribute("aria-label", `Remove "${item.text}"`);
    deleteBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
    deleteBtn.addEventListener("click", (e) => deleteItem(item.id, e));

    actions.append(editBtn, deleteBtn);
    li.append(box, content, actions);
    list.appendChild(li);
  });
}

function isOverdue(item) {
  if (!item || item.checked || !item.dueDate) return false;
  return item.dueDate < todayKey();
}

function toggleTheme() {
  const dark = document.documentElement.getAttribute("data-theme") !== "dark";
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
  updateThemeButton();
}

function updateThemeButton() {
  if (!themeBtn) return;
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  themeBtn.textContent = dark ? "Theme: Light" : "Theme: Dark";
}

function remindersSupported() {
  return typeof Notification !== "undefined";
}

function remindersEnabled() {
  return localStorage.getItem(REMIND_KEY) === "1" && Notification.permission === "granted";
}

function updateRemindButton() {
  if (!remindBtn) return;
  if (!remindersSupported()) {
    remindBtn.hidden = true;
    return;
  }
  remindBtn.hidden = false;
  if (remindersEnabled()) {
    remindBtn.textContent = "Reminders: On";
    remindBtn.classList.add("is-on");
  } else {
    remindBtn.textContent = "Reminders: Off";
    remindBtn.classList.remove("is-on");
  }
}

async function enableReminders() {
  if (!remindersSupported()) return;
  if (remindersEnabled()) {
    localStorage.setItem(REMIND_KEY, "0");
    updateRemindButton();
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission === "granted") {
    localStorage.setItem(REMIND_KEY, "1");
    updateRemindButton();
    checkDueReminders(true);
  } else {
    alert("Notifications were blocked. Enable them in your browser settings to get due-date reminders.");
  }
}

function startReminderChecks() {
  if (remindTimer) clearInterval(remindTimer);
  checkDueReminders();
  remindTimer = setInterval(() => checkDueReminders(), 60000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkDueReminders();
  });
}

function checkDueReminders(force = false) {
  if (!remindersEnabled()) return;
  const today = todayKey();
  let sent = {};
  try {
    sent = JSON.parse(localStorage.getItem(REMIND_SENT_KEY) || "{}");
  } catch {
    sent = {};
  }
  const dueItems = (state.items || []).filter(
    (i) => !i.checked && i.dueDate && i.dueDate <= today
  );
  dueItems.forEach((item) => {
    const key = `${item.id}:${item.dueDate}`;
    if (!force && sent[key] === today) return;
    try {
      new Notification(item.dueDate < today ? "Overdue checklist item" : "Due today", {
        body: item.text,
        tag: key,
      });
      sent[key] = today;
    } catch {
      /* ignore */
    }
  });
  localStorage.setItem(REMIND_SENT_KEY, JSON.stringify(sent));
}

function render() {
  if (activeView === "stub" || activeView === "dashboard" || activeView === "queue" || activeView === "profile") return;
  if (activeView === "history") {
    renderHistory();
    return;
  }
  if (activeView === "diary") {
    renderDiaryArchive();
    return;
  }
  updateProgress();
  renderTodayList();
  renderDiaryToday();
}

window.ChecklistApp = {
  setView,
  closeSidebar,
  setPageTitle(title) {
    if (pageTitle) pageTitle.textContent = title;
  },
  activateNav(navKey) {
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle(
        "is-active",
        item.dataset.view === navKey || item.dataset.nav === navKey
      );
    });
  },
  getMyTasks() {
    const items = state.items || [];
    const open = items.filter((i) => !i.checked);
    const done = items.filter((i) => i.checked);
    return {
      activeDate: state.activeDate,
      open,
      done,
      total: items.length,
      openCount: open.length,
      doneCount: done.length,
    };
  },
};
