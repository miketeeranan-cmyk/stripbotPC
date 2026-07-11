(() => {
  let lang = "en";
  const DEMO = window.__DEMO__;
  let threshold = window.__THRESHOLD__;
  let sheetName = "";
  let monitoring = false;
  let startTime = null; // epoch seconds, or null
  let statusState = "idle";
  let readyKind = "ready_login";
  let lastLogId = 0;
  let activePromptKey = null; // dedupes re-showing the same pending prompt every poll
  let pollTimer = null;

  const $ = (id) => document.getElementById(id);

  // ---------------- screen / modal plumbing ----------------
  function showScreen(id) {
    document.querySelectorAll(".screen").forEach((el) => el.classList.add("hidden"));
    $(id).classList.remove("hidden");
  }

  function showModal(id) {
    $("overlay").classList.remove("hidden");
    $(id).classList.remove("hidden");
  }

  function hideModal(id) {
    $(id).classList.add("hidden");
    if (!document.querySelector(".modal:not(.hidden)")) {
      $("overlay").classList.add("hidden");
    }
  }

  // ---------------- language screen ----------------
  document.querySelectorAll("#lang-list .option").forEach((btn) => {
    btn.addEventListener("click", () => {
      lang = btn.dataset.lang;
      applyI18n(lang);
      showScreen("screen-connect");
      connect();
    });
  });

  // ---------------- connect screen ----------------
  async function connect() {
    $("connect-subtitle").textContent = DEMO ? t(lang, "demo_mode") : t(lang, "connecting");
    $("connect-spinner").classList.remove("hidden");
    $("connect-error").classList.add("hidden");
    $("sheet-list").classList.add("hidden");
    $("retry-btn").classList.add("hidden");
    try {
      const res = await fetch("/api/connect", { method: "POST" });
      const data = await res.json();
      $("connect-spinner").classList.add("hidden");
      if (data.ok) {
        $("connect-subtitle").textContent = t(lang, "select_sheet");
        renderSheetOptions($("sheet-list"), data.sheets, selectSheet);
      } else {
        $("connect-subtitle").textContent = t(lang, "connect_failed");
        $("connect-error").textContent = data.error || "";
        $("connect-error").classList.remove("hidden");
        $("retry-btn").classList.remove("hidden");
      }
    } catch (e) {
      $("connect-spinner").classList.add("hidden");
      $("connect-subtitle").textContent = t(lang, "connect_failed");
      $("connect-error").textContent = String(e);
      $("connect-error").classList.remove("hidden");
      $("retry-btn").classList.remove("hidden");
    }
  }
  $("retry-btn").addEventListener("click", connect);

  function renderSheetOptions(container, names, onPick) {
    container.innerHTML = "";
    (names || []).forEach((name) => {
      const btn = document.createElement("button");
      btn.className = "option";
      btn.textContent = name;
      btn.addEventListener("click", () => onPick(name));
      container.appendChild(btn);
    });
    container.classList.remove("hidden");
  }

  async function selectSheet(name) {
    await fetch("/api/select-sheet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sheet_name: name }),
    });
    sheetName = name;
    $("sheet-badge").textContent = sheetName;
    $("stat-threshold").textContent = `Lv ${threshold}+`;
    $("stat-poll").textContent = `${window.__POLL_INTERVAL__}s`;
    showScreen("screen-dashboard");
    startPolling();
  }

  // ---------------- dashboard: polling ----------------
  function startPolling() {
    if (pollTimer) return;
    pollOnce();
    pollTimer = setInterval(pollOnce, 1200);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollOnce() {
    try {
      const res = await fetch(`/api/poll?since=${lastLogId}`);
      const data = await res.json();
      applyPoll(data);
    } catch (e) {
      // transient network hiccup -- next tick will retry
    }
  }

  function applyPoll(data) {
    sheetName = data.sheet_name;
    threshold = data.threshold;
    monitoring = data.monitoring;
    startTime = data.start_time;
    lastLogId = data.next_since;
    $("sheet-badge").textContent = sheetName;
    $("stat-threshold").textContent = `Lv ${threshold}+`;
    $("stat-logged").textContent = String(data.logged_count);
    setStatus(data.state);
    setControlsEnabled(monitoring);
    (data.log || []).forEach((entry) => appendLogEntry(entry));
    handlePrompt(data.prompt);
  }

  function setControlsEnabled(isMonitoring) {
    $("start-btn").disabled = isMonitoring;
    $("stop-btn").disabled = !isMonitoring;
    $("switch-btn").disabled = isMonitoring;
  }

  // ---------------- dashboard: status pill + uptime ----------------
  function setStatus(newState) {
    statusState = newState;
    const pill = $("status-pill");
    pill.classList.remove("status-idle", "status-live", "status-busy");
    pill.classList.add(`status-${newState}`);
    pill.textContent = t(lang, `status_${newState}`);
    if (newState !== "live") {
      $("stat-uptime").textContent = "00:00";
    }
  }

  setInterval(() => {
    if (statusState !== "live" || !startTime) return;
    const elapsed = Math.floor(Date.now() / 1000 - startTime);
    const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const ss = String(elapsed % 60).padStart(2, "0");
    $("stat-uptime").textContent = `${mm}:${ss}`;
  }, 1000);

  // ---------------- dashboard: activity log table (Username / Level / Link / Time) ----------------
  function td(node) {
    const cell = document.createElement("td");
    cell.appendChild(typeof node === "string" ? document.createTextNode(node) : node);
    return cell;
  }

  function appendLogEntry(entry) {
    const tbody = $("log-output");
    const tr = document.createElement("tr");

    tr.appendChild(td(entry.username));
    tr.appendChild(td(String(entry.level)));

    let linkNode;
    if (entry.link && /^https?:\/\//i.test(entry.link)) {
      linkNode = document.createElement("a");
      linkNode.className = "log-link";
      linkNode.href = entry.link;
      linkNode.target = "_blank";
      linkNode.rel = "noopener";
      linkNode.textContent = t(lang, "link_label");
    } else {
      linkNode = document.createElement("span");
      linkNode.className = "log-link dim";
      linkNode.textContent = "—";
    }
    tr.appendChild(td(linkNode));
    tr.appendChild(td(entry.timestamp));

    tbody.appendChild(tr);
    const wrap = document.querySelector(".log-table-wrap");
    wrap.scrollTop = wrap.scrollHeight;
  }

  // ---------------- dashboard: start / stop ----------------
  $("start-btn").addEventListener("click", async () => {
    $("start-btn").disabled = true;
    $("switch-btn").disabled = true;
    setStatus("busy");
    await fetch("/api/start", { method: "POST" });
  });

  $("stop-btn").addEventListener("click", async () => {
    $("stop-btn").disabled = true;
    setStatus("busy");
    await fetch("/api/stop", { method: "POST" });
  });

  // ---------------- switch sheet modal ----------------
  $("switch-btn").addEventListener("click", async () => {
    if (monitoring) return;
    const res = await fetch("/api/sheets");
    const data = await res.json();
    renderSheetOptions($("switch-list"), data.sheets, async (name) => {
      hideModal("modal-switch-sheet");
      const r = await fetch("/api/switch-sheet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sheet_name: name }),
      });
      const d = await r.json();
      if (d.ok) {
        sheetName = name;
        $("sheet-badge").textContent = sheetName;
      }
    });
    showModal("modal-switch-sheet");
  });
  $("switch-cancel-btn").addEventListener("click", () => hideModal("modal-switch-sheet"));

  // ---------------- threshold modal ----------------
  $("threshold-btn").addEventListener("click", () => {
    $("threshold-input").value = threshold;
    $("threshold-error").classList.add("hidden");
    showModal("modal-threshold");
    $("threshold-input").focus();
  });

  async function applyThreshold() {
    const raw = $("threshold-input").value.trim();
    const res = await fetch("/api/threshold", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: raw }),
    });
    const data = await res.json();
    if (!data.ok) {
      $("threshold-error").textContent = t(lang, "invalid_threshold");
      $("threshold-error").classList.remove("hidden");
      return;
    }
    threshold = data.threshold;
    $("stat-threshold").textContent = `Lv ${threshold}+`;
    hideModal("modal-threshold");
  }
  $("threshold-apply-btn").addEventListener("click", applyThreshold);
  $("threshold-cancel-btn").addEventListener("click", () => hideModal("modal-threshold"));
  $("threshold-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") applyThreshold();
  });

  // ---------------- pending-prompt handling (ready modals / browser errors) ----------------
  function promptKey(prompt) {
    return prompt ? JSON.stringify(prompt) : null;
  }

  async function ackPrompt(kind, confirm) {
    await fetch("/api/ready", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, confirm }),
    });
  }

  function handlePrompt(prompt) {
    const key = promptKey(prompt);
    if (key === activePromptKey) return; // already showing this one (or already absent)
    activePromptKey = key;
    if (!prompt) {
      hideModal("modal-ready");
      return;
    }
    if (prompt.type === "browser_error") {
      hideModal("modal-ready");
      alert(t(lang, "browser_start_failed", { error: prompt.message }));
      ackPrompt("browser_error", false);
      return;
    }
    showReadyModal(prompt.type, prompt.sheet_name);
  }

  function showReadyModal(kind, sheet) {
    readyKind = kind;
    if (kind === "ready_login") {
      $("ready-title").textContent = t(lang, "login_title");
      $("ready-body").textContent = t(lang, "login_body");
    } else {
      $("ready-title").textContent = t(lang, "switch_navigate_title", { sheet });
      $("ready-body").textContent = t(lang, "switch_navigate_body", { sheet });
    }
    showModal("modal-ready");
  }

  async function respondReady(confirm) {
    hideModal("modal-ready");
    activePromptKey = null;
    await ackPrompt(readyKind, confirm);
    if (!confirm) setControlsEnabled(false);
  }
  $("ready-confirm-btn").addEventListener("click", () => respondReady(true));
  $("ready-cancel-btn").addEventListener("click", () => respondReady(false));

  // ---------------- generic confirm modal (quit while monitoring) ----------------
  function showConfirmModal(message, onYes) {
    $("confirm-message").textContent = message;
    showModal("modal-confirm");
    const yesBtn = $("confirm-yes-btn");
    const noBtn = $("confirm-no-btn");
    function cleanup() {
      yesBtn.removeEventListener("click", yesHandler);
      noBtn.removeEventListener("click", noHandler);
    }
    function yesHandler() {
      hideModal("modal-confirm");
      cleanup();
      onYes();
    }
    function noHandler() {
      hideModal("modal-confirm");
      cleanup();
    }
    yesBtn.addEventListener("click", yesHandler);
    noBtn.addEventListener("click", noHandler);
  }

  // ---------------- language toggle + quit ----------------
  $("lang-btn").addEventListener("click", () => {
    lang = lang === "en" ? "zh" : "en";
    applyI18n(lang);
    setStatus(statusState);
    $("stat-threshold").textContent = `Lv ${threshold}+`;
  });

  $("quit-btn").addEventListener("click", () => {
    if (monitoring) {
      showConfirmModal(t(lang, "quit_confirm"), () => {
        stopPolling();
        fetch("/api/quit", { method: "POST" });
      });
    } else {
      stopPolling();
      fetch("/api/quit", { method: "POST" });
    }
  });

  // ---------------- init ----------------
  applyI18n(lang);
})();
