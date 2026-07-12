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
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const $ = (id) => document.getElementById(id);

  // ---------------- screen / modal plumbing ----------------
  function showScreen(id) {
    document.querySelectorAll(".screen").forEach((el) => el.classList.add("hidden"));
    $(id).classList.remove("hidden");
  }

  function showModal(id) {
    $("overlay").classList.add("visible");
    $(id).classList.add("visible");
  }

  function hideModal(id) {
    $(id).classList.remove("visible");
    if (!document.querySelector(".modal.visible")) {
      $("overlay").classList.remove("visible");
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

  function bumpElement(el) {
    if (reduceMotion) return;
    el.classList.remove("stat-bump");
    void el.offsetWidth;
    el.classList.add("stat-bump");
  }

  function applyPoll(data) {
    sheetName = data.sheet_name;
    threshold = data.threshold;
    monitoring = data.monitoring;
    startTime = data.start_time;
    lastLogId = data.next_since;
    $("sheet-badge").textContent = sheetName;
    $("stat-threshold").textContent = `Lv ${threshold}+`;
    const loggedEl = $("stat-logged");
    if (String(data.logged_count) !== loggedEl.textContent) {
      loggedEl.textContent = String(data.logged_count);
      bumpElement(loggedEl);
    }
    setStatus(data.state);
    setControlsEnabled(monitoring);
    (data.log || []).forEach((entry) => addLogEntry(entry));
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
  // Paginated 200 rows/page: the tbody only ever holds the page being viewed
  // (everything else stays in `allLogRows`), so a long-running session never
  // stretches the page -- the log box itself scrolls, and paging is
  // "smart-follow": if you're watching the newest page live, new pages
  // appear and the view follows onto them; if you've paged back to review
  // older entries, your view is left alone and the new page just becomes
  // reachable via Next.
  const LOG_PAGE_SIZE = 200;
  const allLogRows = [];
  let currentLogPage = 0;

  function td(node) {
    const cell = document.createElement("td");
    cell.appendChild(typeof node === "string" ? document.createTextNode(node) : node);
    return cell;
  }

  function buildLogRow(entry) {
    const tr = document.createElement("tr");

    tr.appendChild(td(entry.username));

    const levelChip = document.createElement("span");
    levelChip.className = "level-chip " + (entry.level >= threshold * 2 ? "high" : "mid");
    levelChip.textContent = String(entry.level);
    tr.appendChild(td(levelChip));

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
    return tr;
  }

  function totalLogPages() {
    return Math.max(1, Math.ceil(allLogRows.length / LOG_PAGE_SIZE));
  }

  function updateLogPagerUI() {
    const pages = totalLogPages();
    $("log-pager").classList.toggle("hidden", pages <= 1);
    $("log-pager-label").textContent = t(lang, "page_of", { x: currentLogPage + 1, y: pages });
    $("log-prev-btn").disabled = currentLogPage <= 0;
    $("log-next-btn").disabled = currentLogPage >= pages - 1;
  }

  function renderLogPage(pageIndex) {
    // Flip the page state + pager label immediately so a fast run of
    // addLogEntry calls always sees the real current page -- only the
    // visual row swap below is what's faded/delayed.
    currentLogPage = pageIndex;
    updateLogPagerUI();

    const wrap = document.querySelector(".log-table-wrap");
    const tbody = $("log-output");

    function paint() {
      tbody.innerHTML = "";
      const start = pageIndex * LOG_PAGE_SIZE;
      allLogRows.slice(start, start + LOG_PAGE_SIZE).forEach((tr) => tbody.appendChild(tr));
      wrap.classList.remove("fading");
    }

    if (reduceMotion) {
      paint();
    } else {
      wrap.classList.add("fading");
      setTimeout(paint, 140);
    }
  }

  function flashNewRow(tr) {
    if (reduceMotion) return;
    tr.classList.add("row-enter");
    setTimeout(() => tr.classList.remove("row-enter"), 1650);
  }

  function addLogEntry(entry) {
    const wasOnLastPage = currentLogPage === totalLogPages() - 1;
    const tr = buildLogRow(entry);
    allLogRows.push(tr);
    const rowPageIndex = Math.floor((allLogRows.length - 1) / LOG_PAGE_SIZE);

    if (rowPageIndex === currentLogPage) {
      const tbody = $("log-output");
      tbody.appendChild(tr);
      const wrap = document.querySelector(".log-table-wrap");
      wrap.scrollTop = wrap.scrollHeight;
      flashNewRow(tr);
      updateLogPagerUI();
    } else if (wasOnLastPage) {
      renderLogPage(rowPageIndex);
      setTimeout(() => flashNewRow(tr), 180);
    } else {
      updateLogPagerUI();
    }
  }

  $("log-prev-btn").addEventListener("click", () => {
    if (currentLogPage > 0) renderLogPage(currentLogPage - 1);
  });
  $("log-next-btn").addEventListener("click", () => {
    if (currentLogPage < totalLogPages() - 1) renderLogPage(currentLogPage + 1);
  });
  updateLogPagerUI();

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
  function switchLanguage(newLang) {
    const shell = document.querySelector(".shell");
    function apply() {
      lang = newLang;
      applyI18n(lang);
      setStatus(statusState);
      $("stat-threshold").textContent = `Lv ${threshold}+`;
      updateLogPagerUI();
    }
    if (reduceMotion) {
      apply();
      return;
    }
    shell.classList.add("fading");
    setTimeout(() => {
      apply();
      shell.classList.remove("fading");
    }, 140);
  }

  $("lang-btn").addEventListener("click", () => {
    switchLanguage(lang === "en" ? "zh" : "en");
  });

  // ---------------- theme toggle (manual override on top of prefers-color-scheme) ----------------
  function effectiveThemeIsDark() {
    const current = document.documentElement.getAttribute("data-theme");
    if (current) return current === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function updateThemeIcon() {
    $("theme-toggle").textContent = effectiveThemeIsDark() ? "☀️" : "🌙";
  }

  const storedTheme = localStorage.getItem("theme");
  if (storedTheme === "light" || storedTheme === "dark") {
    document.documentElement.setAttribute("data-theme", storedTheme);
  }
  updateThemeIcon();

  $("theme-toggle").addEventListener("click", () => {
    const next = effectiveThemeIsDark() ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    updateThemeIcon();
  });

  $("quit-btn").addEventListener("click", () => {
    const message = monitoring ? t(lang, "quit_confirm") : t(lang, "quit_confirm_idle");
    showConfirmModal(message, () => {
      stopPolling();
      fetch("/api/quit", { method: "POST" });
      window.close();
    });
  });

  // ---------------- init ----------------
  applyI18n(lang);
})();
