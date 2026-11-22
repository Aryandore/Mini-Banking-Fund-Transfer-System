let currentAccount = null;

// ==========================================
// HELPERS & ALERTS
// ==========================================
function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(value || 0));
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showAlert(message, type = "success") {
  const box = document.getElementById("alert-box");
  const msgEl = document.getElementById("alert-message");
  box.className = `alert ${type}`;
  msgEl.textContent = message;
  box.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function hideAlert() {
  document.getElementById("alert-box").classList.add("hidden");
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && currentAccount !== null) {
      switchToLoggedOutView();
    }
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

// ==========================================
// VIEW STATE MANAGEMENT (AUTH GATE VS PORTAL)
// ==========================================
function switchToLoggedOutView() {
  currentAccount = null;
  document.getElementById("user-nav").classList.add("hidden");
  document.getElementById("portal-view").classList.add("hidden");
  document.getElementById("auth-view").classList.remove("hidden");
}

async function switchToLoggedInView(account) {
  currentAccount = account;

  // Update Header & Hero Summary
  document.getElementById("nav-acc-num").textContent = account.account_number;
  document.getElementById("nav-owner").textContent = account.owner_name;

  document.getElementById("hero-balance").textContent = formatCurrency(account.balance);
  document.getElementById("hero-acc-num").textContent = account.account_number;
  document.getElementById("hero-owner").textContent = account.owner_name;
  document.getElementById("hero-email").textContent = account.email;

  document.getElementById("auth-view").classList.add("hidden");
  document.getElementById("user-nav").classList.remove("hidden");
  document.getElementById("portal-view").classList.remove("hidden");

  await Promise.all([loadRecipients(), loadStatement()]);
}

async function checkSessionOnLoad() {
  try {
    const res = await apiRequest("/api/auth/me");
    if (res.authenticated && res.account) {
      await switchToLoggedInView(res.account);
    } else {
      switchToLoggedOutView();
    }
  } catch {
    switchToLoggedOutView();
  }
}

// ==========================================
// AUTH TABS, LOGIN, REGISTER & LOGOUT
// ==========================================
const tabLogin = document.getElementById("tab-login");
const tabRegister = document.getElementById("tab-register");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");

tabLogin.addEventListener("click", () => {
  hideAlert();
  tabLogin.classList.add("active");
  tabRegister.classList.remove("active");
  loginForm.classList.remove("hidden");
  registerForm.classList.add("hidden");
});

tabRegister.addEventListener("click", () => {
  hideAlert();
  tabRegister.classList.add("active");
  tabLogin.classList.remove("active");
  registerForm.classList.remove("hidden");
  loginForm.classList.add("hidden");
});

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await apiRequest("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        identifier: document.getElementById("login-identifier").value,
        password: document.getElementById("login-password").value,
      }),
    });
    loginForm.reset();
    showAlert(res.message, "success");
    await switchToLoggedInView(res.account);
  } catch (err) {
    showAlert(err.message, "error");
  }
});

registerForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await apiRequest("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        account_number: document.getElementById("reg-acc-num").value,
        owner_name: document.getElementById("reg-owner").value,
        email: document.getElementById("reg-email").value,
        password: document.getElementById("reg-password").value,
        initial_balance: parseFloat(document.getElementById("reg-balance").value || "0"),
      }),
    });
    registerForm.reset();
    document.getElementById("reg-balance").value = "500.00";
    showAlert(res.message, "success");
    await switchToLoggedInView(res.account);
  } catch (err) {
    showAlert(err.message, "error");
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    const res = await apiRequest("/api/auth/logout", { method: "POST" });
    switchToLoggedOutView();
    showAlert(res.message, "success");
  } catch (err) {
    showAlert(err.message, "error");
  }
});

// ==========================================
// BANKING PORTAL DATA & TRANSACTIONS
// ==========================================
async function loadRecipients() {
  const data = await apiRequest("/api/recipients");
  const select = document.getElementById("tx-to");
  const prev = select.value;

  if (!data.recipients.length) {
    select.innerHTML = `<option value="">-- No other accounts registered yet --</option>`;
    return;
  }

  select.innerHTML =
    `<option value="">-- Select Recipient Account --</option>` +
    data.recipients
      .map(
        (r) =>
          `<option value="${r.id}">${escapeHtml(r.account_number)} — ${escapeHtml(r.owner_name)}</option>`
      )
      .join("");

  if (prev) select.value = prev;
}

async function loadStatement() {
  const data = await apiRequest("/api/transactions");
  const tbody = document.getElementById("transactions-tbody");

  if (!data.transactions.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No transactions on your account yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.transactions
    .map((tx) => {
      const isIncoming = tx.to_account_id === currentAccount.id;
      const badgeClass = isIncoming ? "badge-credit" : "badge-debit";
      const amountClass = isIncoming ? "amount-credit" : "amount-debit";
      const sign = isIncoming ? "+" : "-";

      let typeLabel = tx.transaction_type;
      let details = "";

      if (tx.transaction_type === "DEPOSIT") {
        details = "External Cash / Electronic Deposit";
      } else if (tx.transaction_type === "WITHDRAWAL") {
        details = "External Cash / ATM Withdrawal";
      } else if (tx.transaction_type === "TRANSFER") {
        if (isIncoming) {
          typeLabel = "TRANSFER IN";
          details = `From ${escapeHtml(tx.from_owner_name)} (${escapeHtml(tx.from_account_number)})`;
        } else {
          typeLabel = "TRANSFER OUT";
          details = `To ${escapeHtml(tx.to_owner_name)} (${escapeHtml(tx.to_account_number)})`;
        }
      }

      return `
        <tr>
          <td>#${tx.id}</td>
          <td><span class="badge ${badgeClass}">${escapeHtml(typeLabel)}</span></td>
          <td>${details}</td>
          <td>${escapeHtml(tx.description)}</td>
          <td class="text-right ${amountClass}">${sign}${formatCurrency(tx.amount)}</td>
          <td>${escapeHtml(tx.created_at)}</td>
        </tr>
      `;
    })
    .join("");
}

// Deposit Handler
document.getElementById("deposit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await apiRequest("/api/deposit", {
      method: "POST",
      body: JSON.stringify({
        amount: parseFloat(document.getElementById("dep-amount").value),
        description: document.getElementById("dep-desc").value || "Deposit",
      }),
    });
    e.target.reset();
    showAlert(res.message, "success");
    await switchToLoggedInView(res.account);
  } catch (err) {
    showAlert(err.message, "error");
  }
});

// Withdraw Handler
document.getElementById("withdraw-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await apiRequest("/api/withdraw", {
      method: "POST",
      body: JSON.stringify({
        amount: parseFloat(document.getElementById("wit-amount").value),
        description: document.getElementById("wit-desc").value || "Withdrawal",
      }),
    });
    e.target.reset();
    showAlert(res.message, "success");
    await switchToLoggedInView(res.account);
  } catch (err) {
    showAlert(err.message, "error");
  }
});

// Transfer Handler
document.getElementById("transfer-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await apiRequest("/api/transfer", {
      method: "POST",
      body: JSON.stringify({
        to_account_id: parseInt(document.getElementById("tx-to").value, 10),
        amount: parseFloat(document.getElementById("tx-amount").value),
        description: document.getElementById("tx-desc").value || "Fund Transfer",
      }),
    });
    document.getElementById("tx-amount").value = "";
    document.getElementById("tx-desc").value = "";
    showAlert(res.message, "success");
    await switchToLoggedInView(res.from_account);
  } catch (err) {
    showAlert(`Transfer Rolled Back: ${err.message}`, "error");
  }
});

// ==========================================
// PROFILE MODAL & ACCOUNT CLOSURE
// ==========================================
document.getElementById("open-profile-btn").addEventListener("click", () => {
  if (!currentAccount) return;
  document.getElementById("prof-acc-num").value = currentAccount.account_number;
  document.getElementById("prof-owner").value = currentAccount.owner_name;
  document.getElementById("prof-email").value = currentAccount.email;
  document.getElementById("profile-modal").classList.remove("hidden");
});

document.getElementById("modal-close").addEventListener("click", () => {
  document.getElementById("profile-modal").classList.add("hidden");
});

document.getElementById("profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const res = await apiRequest("/api/profile", {
      method: "PUT",
      body: JSON.stringify({
        owner_name: document.getElementById("prof-owner").value,
        email: document.getElementById("prof-email").value,
      }),
    });
    document.getElementById("profile-modal").classList.add("hidden");
    showAlert(res.message, "success");
    await switchToLoggedInView(res.account);
  } catch (err) {
    showAlert(err.message, "error");
  }
});

document.getElementById("close-account-btn").addEventListener("click", async () => {
  if (!confirm("Close your account? Balance must be $0.00 and have no restricted audit ledger entries.")) {
    return;
  }
  try {
    const res = await apiRequest("/api/profile", { method: "DELETE" });
    document.getElementById("profile-modal").classList.add("hidden");
    switchToLoggedOutView();
    showAlert(res.message, "success");
  } catch (err) {
    document.getElementById("profile-modal").classList.add("hidden");
    showAlert(err.message, "error");
  }
});

document.getElementById("alert-close").addEventListener("click", hideAlert);
document.getElementById("refresh-btn").addEventListener("click", async () => {
  if (currentAccount) {
    await checkSessionOnLoad();
  }
});

document.addEventListener("DOMContentLoaded", checkSessionOnLoad);