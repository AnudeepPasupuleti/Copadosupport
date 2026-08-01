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
  if (res.status === 403) {
    alert("Admin only");
    location.href = "/";
    throw new Error("Forbidden");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : null;
    throw new Error(msg || "Request failed");
  }
  return data;
}

const googleEnabled = document.getElementById("google-enabled");
const githubEnabled = document.getElementById("github-enabled");
const googleMeta = document.getElementById("google-meta");
const githubMeta = document.getElementById("github-meta");
const googleBadge = document.getElementById("google-badge");
const githubBadge = document.getElementById("github-badge");
const userTableBody = document.getElementById("user-table-body");
const usersTable = document.getElementById("users-table");
const usersEmpty = document.getElementById("users-empty");
const navUserCount = document.getElementById("nav-user-count");
const addForm = document.getElementById("add-user-form");
const adminError = document.getElementById("admin-error");
const pageTitle = document.getElementById("page-title");
const pageDesc = document.getElementById("page-desc");

const PANELS = {
  users: {
    title: "Users",
    desc: "Assign roles, log in as users, or reset passwords.",
  },
  auth: {
    title: "Authentication",
    desc: "Enable or disable login providers shown on the sign-in page.",
  },
};

function setPanel(name) {
  const key = PANELS[name] ? name : "users";
  document.querySelectorAll(".admin-nav-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.nav === key);
  });
  document.querySelectorAll(".admin-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.panel === key);
  });
  pageTitle.textContent = PANELS[key].title;
  pageDesc.textContent = PANELS[key].desc;
  if (location.hash !== `#${key}`) {
    history.replaceState(null, "", `#${key}`);
  }
}

function setConfiguredBadge(el, configured) {
  el.textContent = configured ? "Configured" : "Not configured";
  el.className = `badge ${configured ? "badge-ok" : "badge-warn"}`;
}

function showUsersError(message) {
  adminError.textContent = message;
  adminError.hidden = false;
}

async function loadSettings() {
  const s = await api("/api/admin/settings");
  googleEnabled.checked = s.google_login_enabled;
  githubEnabled.checked = s.github_login_enabled;
  googleMeta.textContent = s.google_configured
    ? "Credentials in .env — toggle to show on login page"
    : "Not configured (set GOOGLE_CLIENT_ID / SECRET in .env)";
  githubMeta.textContent = s.github_configured
    ? "Credentials in .env — toggle to show on login page"
    : "Not configured (set GITHUB_CLIENT_ID / SECRET in .env)";
  googleEnabled.disabled = !s.google_configured;
  githubEnabled.disabled = !s.github_configured;
  setConfiguredBadge(googleBadge, s.google_configured);
  setConfiguredBadge(githubBadge, s.github_configured);
}

async function loadUsers() {
  const statusEl = document.getElementById("users-db-status");
  let status = null;
  try {
    status = await api("/api/admin/status");
    if (statusEl) {
      statusEl.textContent = `Database: ${status.dialect} · ${status.db_host || "local"}/${status.db_name || "—"} · ${status.user_count} users (${status.roles?.admin || 0} admin, ${status.roles?.manager || 0} manager, ${status.roles?.member || 0} member) · ${status.ticket_count} tickets`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = "Could not read database status.";
  }

  const users = await api("/api/admin/users");
  if (!Array.isArray(users)) {
    throw new Error("Could not load users");
  }

  if (status && status.user_count !== users.length && statusEl) {
    statusEl.textContent += ` — warning: status count ${status.user_count} ≠ list ${users.length}`;
  }

  userTableBody.innerHTML = "";
  const empty = users.length === 0;
  usersEmpty.hidden = !empty;
  usersEmpty.textContent = empty ? "No users found." : "";
  if (usersTable) usersTable.hidden = empty;

  if (navUserCount) {
    navUserCount.textContent = String(users.length);
    navUserCount.hidden = false;
  }

  users.forEach((u) => {
    const tr = document.createElement("tr");

    const nameTd = document.createElement("td");
    nameTd.textContent = u.name || "—";

    const emailTd = document.createElement("td");
    emailTd.className = "cell-muted";
    emailTd.textContent = u.email || "";

    const typeTd = document.createElement("td");
    typeTd.className = "cell-muted";
    typeTd.textContent = u.auth_type || "";

    const roleTd = document.createElement("td");
    const roleSelect = document.createElement("select");
    roleSelect.className = "field-input role-select";
    roleSelect.dataset.roleUser = String(u.id);
    roleSelect.dataset.email = u.email || "";
    [
      ["admin", "Admin"],
      ["manager", "Manager"],
      ["member", "Member"],
    ].forEach(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      if ((u.role || "member") === value) opt.selected = true;
      roleSelect.appendChild(opt);
    });
    roleTd.appendChild(roleSelect);

    const actionTd = document.createElement("td");
    actionTd.className = "cell-actions";
    if (u.is_admin || u.role === "admin") {
      const note = document.createElement("span");
      note.className = "cell-muted";
      note.textContent = "Admin";
      actionTd.appendChild(note);
    } else {
      const loginAs = document.createElement("button");
      loginAs.type = "button";
      loginAs.className = "btn btn-outline";
      loginAs.textContent = "Login as";
      loginAs.dataset.impersonate = String(u.id);
      loginAs.dataset.email = u.email || "";
      actionTd.appendChild(loginAs);

      const resetPw = document.createElement("button");
      resetPw.type = "button";
      resetPw.className = "btn btn-outline";
      resetPw.textContent = u.has_password ? "Reset password" : "Set password";
      resetPw.dataset.resetPw = String(u.id);
      resetPw.dataset.email = u.email || "";
      resetPw.dataset.username = u.username || "";
      resetPw.dataset.hasPassword = u.has_password ? "1" : "0";
      actionTd.appendChild(resetPw);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-danger-outline";
      btn.textContent = "Remove";
      btn.dataset.remove = String(u.id);
      btn.dataset.email = u.email || "";
      actionTd.appendChild(btn);
    }

    tr.append(nameTd, emailTd, typeTd, roleTd, actionTd);
    userTableBody.appendChild(tr);
  });
}

document.querySelectorAll(".admin-nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => setPanel(btn.dataset.nav));
});

window.addEventListener("hashchange", () => {
  const hash = (location.hash || "#users").replace("#", "");
  setPanel(hash);
});

googleEnabled.addEventListener("change", async () => {
  await api("/api/admin/settings", {
    method: "PUT",
    body: JSON.stringify({ google_login_enabled: googleEnabled.checked }),
  });
});

githubEnabled.addEventListener("change", async () => {
  await api("/api/admin/settings", {
    method: "PUT",
    body: JSON.stringify({ github_login_enabled: githubEnabled.checked }),
  });
});

const changePasswordForm = document.getElementById("change-password-form");
const passwordError = document.getElementById("password-error");
const passwordSuccess = document.getElementById("password-success");

changePasswordForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  passwordError.hidden = true;
  passwordSuccess.hidden = true;
  try {
    await api("/api/admin/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: document.getElementById("current-password").value,
        new_password: document.getElementById("new-password").value,
      }),
    });
    changePasswordForm.reset();
    passwordSuccess.hidden = false;
  } catch (err) {
    passwordError.textContent = err.message || "Could not update password";
    passwordError.hidden = false;
  }
});

userTableBody.addEventListener("change", async (e) => {
  const select = e.target.closest("[data-role-user]");
  if (!select) return;
  const userId = select.dataset.roleUser;
  const email = select.dataset.email || "user";
  const role = select.value;
  try {
    await api(`/api/admin/users/${userId}/role`, {
      method: "POST",
      body: JSON.stringify({ role }),
    });
    await loadUsers();
  } catch (err) {
    showUsersError(err.message || `Could not update role for ${email}`);
    await loadUsers();
  }
});

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  adminError.hidden = true;
  try {
    await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("new-email").value.trim(),
        name: document.getElementById("new-name").value.trim(),
        auth_type: "oauth",
        role: document.getElementById("new-role")?.value || "member",
        copy_from_admin: document.getElementById("copy-admin").checked,
      }),
    });
    addForm.reset();
    const roleEl = document.getElementById("new-role");
    if (roleEl) roleEl.value = "member";
    await loadUsers();
  } catch (err) {
    showUsersError(err.message || "Could not add user");
    setPanel("users");
  }
});

userTableBody.addEventListener("click", async (e) => {
  const impersonateBtn = e.target.closest("[data-impersonate]");
  if (impersonateBtn) {
    const email = impersonateBtn.dataset.email || "this user";
    if (!confirm(`Log in as ${email}? You can return to Admin from the yellow banner.`)) return;
    try {
      await api(`/api/admin/users/${impersonateBtn.dataset.impersonate}/impersonate`, {
        method: "POST",
        body: "{}",
      });
      location.href = "/";
    } catch (err) {
      showUsersError(err.message || "Could not log in as user");
    }
    return;
  }

  const resetBtn = e.target.closest("[data-reset-pw]");
  if (resetBtn) {
    const email = resetBtn.dataset.email || "this user";
    let username = resetBtn.dataset.username || "";
    if (!username) {
      username = (prompt(`Username for ${email} (needed for password login):`) || "").trim();
      if (!username) return;
    }
    const newPassword = (prompt(`New password for ${email} (min 8 characters):`) || "").trim();
    if (!newPassword) return;
    if (newPassword.length < 8) {
      showUsersError("Password must be at least 8 characters");
      return;
    }
    try {
      const result = await api(`/api/admin/users/${resetBtn.dataset.resetPw}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ new_password: newPassword, username }),
      });
      alert(`Password set for ${result.username}. Share it securely with the user.`);
      await loadUsers();
    } catch (err) {
      showUsersError(err.message || "Could not reset password");
    }
    return;
  }

  const btn = e.target.closest("[data-remove]");
  if (!btn) return;
  const email = btn.dataset.email || "this user";
  if (!confirm(`Remove ${email}?`)) return;
  try {
    await api(`/api/admin/users/${btn.dataset.remove}`, { method: "DELETE" });
    await loadUsers();
  } catch (err) {
    showUsersError(err.message || "Could not remove user");
  }
});

(async () => {
  try {
    const me = await api("/api/me");
    if (!me.is_admin) {
      location.href = "/";
      return;
    }
    const hash = (location.hash || "#users").replace("#", "");
    setPanel(hash);
    await loadSettings();
    await loadUsers();
  } catch (err) {
    showUsersError(err.message || "Could not load admin data");
  }
})();
