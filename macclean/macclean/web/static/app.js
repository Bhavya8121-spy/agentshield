/* macclean dashboard. Vanilla JS. All server data is rendered with
 * textContent / text nodes, never innerHTML, so odd file names can't inject markup. */
(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="macclean-token"]').content;
  const $ = (sel, root = document) => root.querySelector(sel);

  const COMMANDS = [
    ["macclean scan", "What is using space (changes nothing)"],
    ["macclean scan --deep", "Also find stale node_modules (slower)"],
    ["macclean clean", "Dry run: show exactly what would be removed"],
    ["macclean clean --execute", "Delete SAFE items after a confirmation prompt"],
    ["macclean clean --include-review --execute", "Also clean review items"],
    ["macclean clean -c xcode -c npm", "Limit to certain categories"],
    ["macclean largest ~ -n 20", "Biggest files (report only)"],
    ["macclean doctor", "Check tools and permissions"],
    ["macclean web", "Open this dashboard"],
  ];

  const RING_C = 2 * Math.PI * 94; // matches r="94" in index.html

  const state = {
    items: [],
    selected: new Set(),
    categories: [],
    activeCats: new Set(),
    busy: false,
  };

  // ---------------------------------------------------------------- helpers

  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (value == null || value === false) continue;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
      }
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  function fmt(bytes) {
    const units = ["B", "kB", "MB", "GB", "TB"];
    let size = bytes, i = 0;
    while (size >= 1000 && i < units.length - 1) { size /= 1000; i++; }
    return i === 0 ? `${Math.round(size)} B` : `${size.toFixed(2)} ${units[i]}`;
  }

  async function api(path, body) {
    const opts = { headers: { "X-Macclean-Token": TOKEN } };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (_) {
      throw new Error("Can't reach macclean. Is `macclean web` still running in Terminal?");
    }
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON error body */ }
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  function toast(message, kind) {
    const node = el("div", { class: "toast " + (kind || ""), text: message });
    $("#toasts").append(node);
    setTimeout(() => node.remove(), kind === "error" ? 9000 : 5000);
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied", "ok");
    } catch (_) {
      toast("Couldn't copy. Select the text and copy it manually.", "error");
    }
  }

  function badge(safety) {
    const map = { safe: ["✓ Safe", "safe"], review: ["! Review", "review"], dangerous: ["✗ Dangerous", "danger"] };
    const [text, cls] = map[safety] || [safety, ""];
    return el("span", { class: "badge " + cls, text });
  }

  // ------------------------------------------------------------------ modal

  const dlg = $("#modal");
  function openModal(...nodes) {
    $("#modal-body").replaceChildren(...nodes);
    if (!dlg.open) dlg.showModal();
  }
  function closeModal() { if (dlg.open) dlg.close(); }
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeModal(); });

  // ------------------------------------------------------------------- tabs

  const tabButtons = document.querySelectorAll(".tabs button");
  const loaded = { health: false };

  function showTab(name) {
    if (!$("#tab-" + name)) name = "overview";
    tabButtons.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    document.querySelectorAll("main > section").forEach((s) => { s.hidden = s.id !== "tab-" + name; });
    if (name === "overview") updateBar();
    else $("#actionbar").hidden = true;
    if (name === "health" && !loaded.health) loadHealth();
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  }
  tabButtons.forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  // ----------------------------------------------------------------- status

  async function loadStatus() {
    const s = await api("/api/status");
    $("#ver").textContent = "v" + s.version;
    if (s.disk) {
      $("#disk").hidden = false;
      const pct = Math.max(0, Math.min(100, s.disk.percent));
      $("#disk-used").textContent = s.disk.used_human;
      $("#disk-total").textContent = `of ${s.disk.total_human}`;
      $("#disk-free").textContent = s.disk.free_human;
      $("#disk-note").textContent = `${(100 - pct).toFixed(0)}% available`;
      $("#ring-pct").textContent = Math.round(pct) + "%";
      $("#ring").setAttribute("aria-label", `Disk ${Math.round(pct)}% used`);
      $("#ring").classList.toggle("high", pct >= 90);
      // Animate from empty so the gauge fills in once on load.
      const fill = $("#ring-fill");
      requestAnimationFrame(() => fill.setAttribute("stroke-dashoffset", String(RING_C * (1 - pct / 100))));
    }
    if (!s.is_mac) {
      $("#scan-hint").textContent = "Heads up: macclean is built for macOS, so most categories will be empty on this system. " + $("#scan-hint").textContent;
    }
    state.categories = s.categories;
    renderChips();
  }

  function renderChips() {
    $("#chips").replaceChildren(
      ...state.categories.map((name) =>
        el("button", {
          class: "chip", type: "button", text: name,
          "aria-pressed": String(state.activeCats.has(name)),
          onclick: (e) => {
            if (state.activeCats.has(name)) state.activeCats.delete(name);
            else state.activeCats.add(name);
            e.currentTarget.setAttribute("aria-pressed", String(state.activeCats.has(name)));
          },
        })
      )
    );
  }

  // ------------------------------------------------------------------- scan

  function setBusy(busy, label) {
    state.busy = busy;
    const btn = $("#scan-btn");
    btn.disabled = busy;
    btn.replaceChildren(...(busy ? [el("span", { class: "spin" }), label || "Working…"] : ["Scan"]));
    updateBar();
  }

  async function runScan() {
    setBusy(true, "Scanning…");
    try {
      const data = await api("/api/scan", {
        deep: $("#deep").checked,
        categories: [...state.activeCats],
      });
      state.items = data.items;
      state.selected = new Set(data.items.filter((i) => i.cleanable && i.safety === "safe").map((i) => i.id));
      renderResults(data);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function renderResults(data) {
    $("#results").hidden = false;
    $("#stats").replaceChildren(
      stat("Safe to reclaim", data.totals_human.safe, "safe", "✓", "Regenerates on its own. Preselected."),
      stat("Needs review", data.totals_human.review, "review", "!", "Look first. Never preselected."),
      stat("Report only", data.totals_human.report_only, "", "i", "Shown for information. Not deleted."),
    );
    const n = state.items.length;
    $("#scan-summary").textContent = n === 0
      ? "Scan finished. Nothing significant found."
      : `${data.totals_human.safe} ready to reclaim · ${n} item${n === 1 ? "" : "s"} found`;

    const rows = $("#rows");
    if (state.items.length === 0) {
      rows.replaceChildren(el("tr", null, el("td", { colspan: "4", class: "muted", text: "Nothing significant found. Your Mac is tidy." })));
    } else {
      rows.replaceChildren(...groupedRows());
    }

    const errs = Object.entries(data.errors || {});
    $("#scan-errors").replaceChildren(
      ...errs.map(([name, msg]) => el("div", { class: "err-box", text: `${name} scan failed: ${msg}` }))
    );
    updateBar();
  }

  function stat(label, value, cls, icon, caption) {
    return el("div", { class: "stat " + cls },
      el("div", { class: "stat-head" }, el("span", { class: "stat-icon", "aria-hidden": "true", text: icon }), label),
      el("div", { class: "value", text: value }),
      el("div", { class: "caption", text: caption }));
  }

  const GROUPS = [
    ["Safe to clean", (i) => i.cleanable && i.safety === "safe"],
    ["Review first", (i) => i.cleanable && i.safety !== "safe"],
    ["Report only", (i) => !i.cleanable],
  ];

  function groupedRows() {
    const out = [];
    for (const [title, test] of GROUPS) {
      const members = state.items.filter(test);
      if (members.length === 0) continue;
      const total = members.reduce((n, i) => n + i.size, 0);
      out.push(el("tr", { class: "group" },
        el("td", { colspan: "4" },
          el("div", { class: "group-row" },
            el("span", { text: title }),
            el("span", { class: "muted", text: `${members.length} item${members.length === 1 ? "" : "s"} · ${fmt(total)}` })))));
      out.push(...members.map(itemRow));
    }
    return out;
  }

  function statusText(item) {
    if (item.safety === "dangerous") return "Never cleaned";
    if (item.report_only) return "Report only";
    return item.safety === "review" ? "Review first" : "Cleanable";
  }

  function itemRow(item) {
    const cb = el("input", {
      type: "checkbox",
      "aria-label": `Select ${item.label}`,
      checked: state.selected.has(item.id),
      disabled: !item.cleanable,
      onchange: (e) => {
        if (e.target.checked) state.selected.add(item.id);
        else state.selected.delete(item.id);
        updateBar();
      },
    });
    cb.dataset.id = item.id;
    return el(
      "tr",
      { class: item.cleanable ? "" : "disabled" },
      el("td", { class: "c-check" }, cb),
      el(
        "td", null,
        el("div", { class: "item-main" },
          el("span", { class: "item-tile " + (item.safety === "dangerous" ? "danger" : item.safety === "review" ? "review" : ""), "aria-hidden": "true", text: (item.label || "?").trim().charAt(0) }),
          el("div", { class: "item-text" },
            el("div", { class: "item-label" }, badge(item.safety), item.label),
            item.note && el("div", { class: "item-note", text: item.note }),
            item.target && el("div", { class: "item-target", text: item.target }))),
      ),
      el("td", { class: "num", text: item.size_human }),
      el("td", { class: "c-status" }, el("span", { class: "status", text: statusText(item) })),
    );
  }

  function selectedItems() {
    return state.items.filter((i) => state.selected.has(i.id) && i.cleanable);
  }

  function setSelection(predicate) {
    state.selected = new Set(state.items.filter((i) => i.cleanable && predicate(i)).map((i) => i.id));
    document.querySelectorAll("#rows input[type=checkbox]").forEach((cb) => { cb.checked = state.selected.has(cb.dataset.id); });
    updateBar();
  }

  function updateBar() {
    const bar = $("#actionbar");
    const onOverview = !$("#tab-overview").hidden;
    const sel = selectedItems();
    const show = onOverview && state.items.some((i) => i.cleanable);
    bar.hidden = !show;
    if (!show) return;
    const total = sel.reduce((n, i) => n + i.size, 0);
    const hasReview = sel.some((i) => i.safety === "review");
    $("#bar-text").replaceChildren(
      sel.length === 0
        ? el("span", { class: "muted", text: "Nothing selected" })
        : el("span", null, `${sel.length} selected · `, el("strong", { text: fmt(total) }), hasReview ? el("span", { class: "muted", text: "  (includes review items)" }) : null)
    );
    $("#dry-btn").disabled = state.busy || sel.length === 0;
    $("#del-btn").disabled = state.busy || sel.length === 0;
  }

  // ------------------------------------------------------------ clean flow

  async function dryRun() {
    const ids = selectedItems().map((i) => i.id);
    try {
      const r = await api("/api/clean", { ids, dry_run: true });
      toast(`Dry run: would free ${r.freed_human}. Nothing was deleted.`, "ok");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function confirmDelete() {
    const sel = selectedItems();
    if (sel.length === 0) return;
    const total = sel.reduce((n, i) => n + i.size, 0);
    const warnings = [];
    if (sel.some((i) => i.category === "trash")) warnings.push("The Trash is emptied permanently. Those files can't be recovered.");
    if (sel.some((i) => i.category === "caches")) warnings.push("Quit the apps whose caches you're clearing first. They rebuild them on next launch.");
    if (sel.some((i) => i.safety === "review")) warnings.push("This includes review items. Skim the list below before continuing.");

    const list = el(
      "div", { class: "modal-list" },
      ...sel.map((i) =>
        el("div", { class: "m-row" },
          el("div", null,
            el("div", { class: "item-label" }, badge(i.safety), i.label),
            el("div", { class: "item-target", text: i.target })),
          el("div", { class: "num", text: i.size_human }))
      )
    );
    const cancel = el("button", { class: "btn", text: "Cancel", autofocus: true, onclick: closeModal });
    const go = el("button", { class: "btn danger", text: `Delete ${sel.length} item${sel.length === 1 ? "" : "s"}`, onclick: () => execute(sel, go, cancel) });
    openModal(
      el("h2", { text: `Delete ${fmt(total)}?` }),
      el("p", { class: "muted", text: "These will be removed from your Mac. Everything on the SAFE list regenerates on its own." }),
      ...warnings.map((w) => el("div", { class: "warn-box", text: w })),
      list,
      el("div", { class: "modal-actions" }, cancel, go),
    );
  }

  async function execute(items, goBtn, cancelBtn) {
    goBtn.disabled = true;
    cancelBtn.disabled = true;
    goBtn.replaceChildren(el("span", { class: "spin" }), "Deleting…");
    try {
      const r = await api("/api/clean", { ids: items.map((i) => i.id), dry_run: false, confirm: true });
      const done = el("button", { class: "btn primary", text: "Done", autofocus: true, onclick: closeModal });
      openModal(
        el("h2", { text: `Freed ${r.freed_human}` }),
        el("p", { class: "muted", text: `Cleaned ${r.cleaned.length} item${r.cleaned.length === 1 ? "" : "s"}.` }),
        ...r.errors.map((e) => el("div", { class: "err-box", text: e })),
        r.errors.length ? el("p", { class: "muted small", text: "Some things couldn't be removed. The Health check tab can tell you whether a permission is missing." }) : null,
        el("div", { class: "modal-actions" }, done),
      );
      dlg.addEventListener("close", () => { loadStatus().catch(() => {}); runScan(); }, { once: true });
    } catch (err) {
      closeModal();
      toast(err.message, "error");
      runScan(); // results may be stale now
    }
  }

  // ---------------------------------------------------------------- largest

  async function runLargest() {
    const btn = $("#lg-btn");
    btn.disabled = true;
    btn.replaceChildren(el("span", { class: "spin" }), "Searching…");
    try {
      const r = await api("/api/largest", {
        path: $("#lg-path").value.trim() || "~",
        number: Number($("#lg-n").value) || 20,
        min_mb: Number($("#lg-min").value),
      });
      $("#lg-card").hidden = false;
      $("#lg-rows").replaceChildren(
        ...(r.files.length
          ? r.files.map((f) =>
              el("tr", null,
                el("td", { class: "num", text: f.size_human }),
                el("td", null, el("span", { class: "mono", text: f.path })),
                el("td", { class: "num" }, el("button", { class: "btn small", text: "Copy path", onclick: () => copy(f.path) })),
              ))
          : [el("tr", null, el("td", { colspan: "3", class: "muted", text: "No files that large in " + r.root + "." }))])
      );
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Find large files";
    }
  }

  // ----------------------------------------------------------------- health

  async function loadHealth() {
    try {
      const r = await api("/api/doctor");
      loaded.health = true;
      const cls = { ok: "st-ok", warn: "st-warn", missing: "st-warn", denied: "st-bad" };
      $("#health-rows").replaceChildren(
        ...r.checks.map((c) =>
          el("tr", null,
            el("td", { text: c.name }),
            el("td", null, el("span", { class: cls[c.status] || "muted", text: c.status })),
            el("td", { class: "muted", text: c.note }))
        )
      );
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ------------------------------------------------------------------ theme

  const THEMES = ["auto", "light", "dark"];
  const THEME_LABEL = { auto: "Theme: Auto", light: "Theme: Light", dark: "Theme: Dark" };

  function applyTheme(name) {
    if (name === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", name);
    $("#theme-label").textContent = THEME_LABEL[name];
    try { localStorage.setItem("macclean-theme", name); } catch (_) { /* private mode */ }
  }

  function initTheme() {
    let saved = "auto";
    try { saved = localStorage.getItem("macclean-theme") || "auto"; } catch (_) { /* ignore */ }
    applyTheme(THEMES.includes(saved) ? saved : "auto");
    $("#theme-btn").addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "auto";
      applyTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
    });
  }

  // -------------------------------------------------------------------- init

  function renderCommands() {
    $("#commands").replaceChildren(
      ...COMMANDS.map(([cmd, desc]) =>
        el("button", { class: "cmd", type: "button", title: "Click to copy", onclick: () => copy(cmd) },
          el("code", { text: cmd }), el("span", { text: desc }))
      )
    );
  }

  $("#scan-btn").addEventListener("click", runScan);
  $("#sel-safe").addEventListener("click", () => setSelection((i) => i.safety === "safe"));
  $("#sel-none").addEventListener("click", () => setSelection(() => false));
  $("#dry-btn").addEventListener("click", dryRun);
  $("#del-btn").addEventListener("click", confirmDelete);
  $("#lg-btn").addEventListener("click", runLargest);
  $("#health-btn").addEventListener("click", loadHealth);

  initTheme();
  renderCommands();
  showTab(location.hash.slice(1) || "overview");
  loadStatus().catch((err) => toast(err.message, "error"));
})();
