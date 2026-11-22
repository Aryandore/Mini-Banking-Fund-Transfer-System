let cachedAccounts = [];
let selectedFilterAccountId = null;

// ==========================================
// UTILITY & ALERT HELPERS
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
    throw new Error(data.error || `Request failed with status ${response.status}`);
  }
  return data;
}

// ==========================================
// DATA LOADING & DOM RENDERING
// ==========================================
async function loadDashboard() {
  try {
    const accountsData = await apiRequest("/api/accounts");
    cachedAccounts = accountsData.accounts;

    document.getElementById("stat-count").textContent = accountsData.count;
    document.getElementById("stat-liquidity").textContent = formatCurrency(accountsData.total_liquidity);

    renderAccountsTable(cachedAccounts);
    populateAccountSelects(cachedAccounts);

    await loadTransactions(selectedFilterAccountId);
  } catch (err) {
    showAlert(err.message, "error");
  }
}

function renderAccountsTable(accounts) {
  const tbody = document.getElementById("accounts-tbody");
  if (!accounts.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No accounts yet. Open one above to get started.</td></tr>`;
    return;
  }

  tbody.innerHTML = accounts
    .map(
      (acc) => `
      <tr>
        <td>#${acc.id}</td>
        <td><strong>${escapeHtml(acc.account_number)}</strong></td>
        <td>${escapeHtml(acc.owner_name)}</td>
        <td>${escapeHtml(acc.email)}</td>
        <td class="text-right"><strong>${formatCurrency(acc.balance)}</strong></td>
        <td class="actions-cell">
          <button type="button" class="btn btn-outline btn-sm" onclick="filterByAccount(${acc.id}, '${escapeHtml(acc.account_number)}')">History</button>
          <button type="button" class="btn btn-outline btn-sm" onclick="openEditModal(${acc.id})">Edit</button>
          <button type="button" class="btn btn-danger-outline" onclick="handleDeleteAccount(${acc.id}, '${escapeHtml(acc.account_number)}')">Delete</button>
        </td>
      </tr>
    `
    )
    .join("");
}

function populateAccountSelects(accounts) {
  const selectIds = ["tx-from", "tx-to", "cash-account"];
  selectIds.forEach((id) => {
    const select = document.getElementById(id);
    const currentValue = select.value;
    const placeholder = id === "tx-from"
      ? "-- Select Source Account --"
      : id === "tx-to"
      ? "-- Select Destination Account --"
      : "-- Select Account --";

    select.innerHTML =
      `<option value="">${placeholder}</option>` +
      accounts
        .map(
          (acc) =>
            `<option value="${acc.id}">${escapeHtml(acc.account_number)} — ${escapeHtml(acc.owner_name)} (${formatCurrency(acc.balance)})</option>`
        )
        .join("");

    if (currentValue) {
      select.value = currentValue;
    }
  });
}

async function loadTransactions(accountId = null) {
  const url = accountId ? `/api/transactions?account_id=${accountId}` : "/api/transactions";
  const data = await apiRequest(url);
  const tbody = document.getElementById("transactions-tbody");

  if (!data.transactions.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No transactions recorded yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.transactions
    .map((tx) => {
      const badgeClass =
        tx.transaction_type === "TRANSFER"
          ? "badge-transfer"
          : tx.transaction_type === "DEPOSIT"
          ? "badge-deposit"
          : "badge-withdrawal";

      const fromLabel = tx.from_account_number
        ? `${escapeHtml(tx.from_account_number)} (${escapeHtml(tx.from_owner_name)})`
        : "— External —";

      const toLabel = tx.to_account_number
        ? `${escapeHtml(tx.to_account_number)} (${escapeHtml(tx.to_owner_name)})`
        : "— External —";

      return `
        <tr>
          <td>#${tx.id}</td>
          <td><span class="badge ${badgeClass}">${escapeHtml(tx.transaction_type)}</span></td>
          <td>${fromLabel}</td>
          <td>${toLabel}</td>
          <td class="text-right"><strong>${formatCurrency(tx.amount)}</strong></td>
          <td>${escapeHtml(tx.description)}</td>
          <td>${escapeHtml(tx.created_at)}</td>
        </tr>
      `;
    })
    .join("");
}

function filterByAccount(accountId, accountNumber) {
  selectedFilterAccountId = accountId;
  document.getElementById("ledger-filter-label").textContent = `Filtered by account: ${accountNumber}`;
  document.getElementById("clear-filter-btn").classList.remove("hidden");
  loadTransactions(accountId).catch((err) => showAlert(err.message, "error"));
}

// ==========================================
// FORM & CRUD EVENT HANDLERS
// ==========================================
document.getElementById("create-account-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = {
      account_number: document.getElementById("acc-number").value,
      owner_name: document.getElementById("acc-owner").value,
      email: document.getElementById("acc-email").value,
      initial_balance: parseFloat(document.getElementById("acc-balance").value || "0"),
    };
    const res = await apiRequest("/api/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    e.target.reset();
    document.getElementById("acc-balance").value = "0.00";
    showAlert(res.message, "success");
    await loadDashboard();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

document.getElementById("transfer-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = {
      from_account_id: parseInt(document.getElementById("tx-from").value, 10),
      to_account_id: parseInt(document.getElementById("tx-to").value, 10),
      amount: parseFloat(document.getElementById("tx-amount").value),
      description: document.getElementById("tx-desc").value || "Fund Transfer",
    };
    const res = await apiRequest("/api/transfer", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    document.getElementById("tx-amount").value = "";
    document.getElementById("tx-desc").value = "";
    showAlert(res.message, "success");
    await loadDashboard();
  } catch (err) {
    showAlert(`Transfer Rolled Back: ${err.message}`, "error");
  }
});

document.getElementById("cash-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const accountId = parseInt(document.getElementById("cash-account").value, 10);
    const opType = document.getElementById("cash-type").value;
    const payload = {
      amount: parseFloat(document.getElementById("cash-amount").value),
      description: document.getElementById("cash-desc").value || (opType === "deposit" ? "Deposit" : "Withdrawal"),
    };
    const res = await apiRequest(`/api/accounts/${accountId}/${opType}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    document.getElementById("cash-amount").value = "";
    document.getElementById("cash-desc").value = "";
    showAlert(res.message, "success");
    await loadDashboard();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

async function handleDeleteAccount(accountId, accountNumber) {
  if (!confirm(`Delete account ${accountNumber}? Only $0.00 accounts without ledger history can be deleted.`)) {
    return;
  }
  try {
    const res = await apiRequest(`/api/accounts/${accountId}`, { method: "DELETE" });
    if (selectedFilterAccountId === accountId) {
      selectedFilterAccountId = null;
      document.getElementById("ledger-filter-label").textContent = "Showing all system-wide transactions";
      document.getElementById("clear-filter-btn").classList.add("hidden");
    }
    showAlert(res.message, "success");
    await loadDashboard();
  } catch (err) {
    showAlert(err.message, "error");
  }
}

// ==========================================
// EDIT MODAL HANDLERS
// ==========================================
function openEditModal(accountId) {
  const acc = cachedAccounts.find((a) => a.id === accountId);
  if (!acc) return;
  document.getElementById("edit-id").value = acc.id;
  document.getElementById("edit-acc-num").value = acc.account_number;
  document.getElementById("edit-owner").value = acc.owner_name;
  document.getElementById("edit-email").value = acc.email;
  document.getElementById("edit-modal").classList.remove("hidden");
}

function closeEditModal() {
  document.getElementById("edit-modal").classList.add("hidden");
}

document.getElementById("edit-account-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = parseInt(document.getElementById("edit-id").value, 10);
  try {
    const payload = {
      owner_name: document.getElementById("edit-owner").value,
      email: document.getElementById("edit-email").value,
    };
    const res = await apiRequest(`/api/accounts/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    closeEditModal();
    showAlert(res.message, "success");
    await loadDashboard();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

document.getElementById("modal-close").addEventListener("click", closeEditModal);
document.getElementById("modal-cancel").addEventListener("click", closeEditModal);
document.getElementById("alert-close").addEventListener("click", hideAlert);
document.getElementById("refresh-btn").addEventListener("click", () => loadDashboard());
document.getElementById("clear-filter-btn").addEventListener("click", () => {
  selectedFilterAccountId = null;
  document.getElementById("ledger-filter-label").textContent = "Showing all system-wide transactions";
  document.getElementById("clear-filter-btn").classList.add("hidden");
  loadTransactions(null);
});

// Initial load
document.addEventListener("DOMContentLoaded", loadDashboard);