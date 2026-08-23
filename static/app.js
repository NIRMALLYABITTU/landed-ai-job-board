(() => {
  "use strict";

  const state = {
    page: 1,
    per_page: 20,
    filters: { search: "", source: "all", role_category: "all", experience_level: "all" },
    lastJobs: [],
  };

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html !== undefined) n.innerHTML = html;
    return n;
  };
  const escapeHtml = (s) =>
    (s ?? "").toString().replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function readApiResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    }
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  // ---------- STATS ----------
  function animateCounter(selector, target, duration = 1500) {
    const node = $(selector);
    if (!node) return;

    const end = Math.max(0, Number(target) || 0);
    const start = 0;
    const startTime = performance.now();
    const easeOut = (t) => 1 - Math.pow(1 - t, 3);

    node.textContent = start.toLocaleString();
    node.classList.remove("counting");
    void node.offsetWidth;
    node.classList.add("counting");

    if (end === 0) {
      node.textContent = "0";
      setTimeout(() => node.classList.remove("counting"), 350);
      return;
    }

    function tick(now) {
      const progress = Math.min(1, (now - startTime) / duration);
      const value = Math.floor(start + (end - start) * easeOut(progress));
      node.textContent = value.toLocaleString();
      if (progress < 1) {
        requestAnimationFrame(tick);
      } else {
        node.textContent = end.toLocaleString();
        setTimeout(() => node.classList.remove("counting"), 350);
      }
    }

    requestAnimationFrame(tick);
  }

  async function loadStats() {
    try {
      const r = await fetch("/api/stats");
      const d = await readApiResponse(r);

      animateCounter("#stat-total", d.total_jobs ?? 0, 1800);
      animateCounter("#stat-companies", d.companies ?? 0, 1400);
      animateCounter("#stat-sources", d.sources ?? 0, 900);
      animateCounter("#stat-updated", d.jobs_added_today ?? 0, 1200);
      animateCounter("#hero-eyebrow-count", d.total_jobs ?? 0, 1800);

      const todayNote = $("#stat-today-note");
      if (todayNote) {
        const count = Number(d.jobs_added_today || 0);
        todayNote.textContent = count === 0
          ? `No new jobs on ${d.today || "today"}`
          : `Updated for ${d.today || "today"}`;
      }
    } catch (e) {
      console.error("stats failed", e);
    }
  }

  // ---------- FILTER OPTIONS ----------
  async function loadFilterOptions() {
    try {
      const r = await fetch("/api/sources");
      const d = await readApiResponse(r);
      fillSelect($("#f-source"), d.sources, "All platforms");
      fillSelect($("#f-role"), d.role_categories, "All categories");
      fillSelect($("#f-exp"), d.experience_levels, "Any experience");
    } catch (e) {
      console.error("filter options failed", e);
    }
  }

  function fillSelect(selectEl, values, allLabel) {
    if (!selectEl) return;

    selectEl.innerHTML = "";

    const allOption = document.createElement("option");
    allOption.value = "all";
    allOption.textContent = allLabel;
    selectEl.appendChild(allOption);

    (values || []).forEach((value) => {
        if (!value) return;

        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;

        selectEl.appendChild(option);
    });
  }

  // ---------- JOB LIST ----------
  async function loadJobs() {
    const list = $("#job-list");
    list.innerHTML = `<div class="job-card-empty">Loading jobs…</div>`;

    const params = new URLSearchParams({
      page: state.page,
      per_page: state.per_page,
      search: state.filters.search,
      source: state.filters.source,
      role_category: state.filters.role_category,
      experience_level: state.filters.experience_level,
    });

    try {
      const r = await fetch(`/api/jobs?${params.toString()}`);
      const d = await readApiResponse(r);
      state.lastJobs = d.jobs || [];
      renderJobs(d);
    } catch (e) {
      console.error(e);
      list.innerHTML = `<div class="job-card-error"><strong>Couldn't load jobs.</strong><br>${escapeHtml(e.message || "Check that the backend is running.")}</div>`;
    }
  }

  function renderJobs(d) {
    const list = $("#job-list");
    list.innerHTML = "";

    $("#results-count").textContent = d.total
      ? `${d.total.toLocaleString()} role${d.total === 1 ? "" : "s"} found · page ${d.page} of ${d.total_pages}`
      : "No roles match those filters";

    if (!d.jobs || d.jobs.length === 0) {
      list.appendChild(el("div", "job-card-empty", "No jobs match these filters yet. Try broadening your search."));
      renderPagination(d);
      return;
    }

    d.jobs.forEach((job, index) => {
      const card = buildJobCard(job);
      card.style.animationDelay = `${Math.min(index * 45, 500)}ms`;
      requestAnimationFrame(() => card.classList.add("loaded"));
      list.appendChild(card);
    });
    renderPagination(d);
  }

  function buildJobCard(job) {
    const card = el("div", "job-card");
    card.tabIndex = 0;
    card.setAttribute("role", "button");

    const skills = (job.skills || []).slice(0, 4);
    const extra = (job.skills || []).length - skills.length;

    card.innerHTML = `
      <div>
        <p class="job-card-title">${escapeHtml(job.title || "Untitled role")}</p>
        <p class="job-card-meta">
          ${escapeHtml(job.company || "Unknown company")}
          <span class="sep">·</span>${escapeHtml(job.location || "Location N/A")}
          <span class="sep">·</span>${escapeHtml(job.experience_level || job.experience || "Experience N/A")}
        </p>
        <div class="chip-row">
          ${skills.map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("")}
          ${extra > 0 ? `<span class="chip chip-more">+${extra} more</span>` : ""}
        </div>
      </div>
      <span class="job-card-source">${escapeHtml(job.source || "—")}</span>
    `;
    card.addEventListener("click", () => openDrawer(job));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(job); }
    });
    return card;
  }

  function renderPagination(d) {
    const wrap = $("#pagination");
    wrap.innerHTML = "";
    if (!d.total_pages || d.total_pages <= 1) return;

    const prev = el("button", null, "← Prev");
    prev.disabled = d.page <= 1;
    prev.addEventListener("click", () => { state.page--; loadJobs(); scrollToBrowse(); });

    const info = el("span", null, `Page ${d.page} / ${d.total_pages}`);

    const next = el("button", null, "Next →");
    next.disabled = d.page >= d.total_pages;
    next.addEventListener("click", () => { state.page++; loadJobs(); scrollToBrowse(); });

    wrap.append(prev, info, next);
  }

  function scrollToBrowse() {
    $("#browse").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- FILTER WIRING ----------
  let searchDebounce;
  function bindFilters() {
    $("#f-search").addEventListener("input", (e) => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        state.filters.search = e.target.value.trim();
        state.page = 1;
        loadJobs();
      }, 350);
    });
    $("#f-source").addEventListener("change", (e) => { state.filters.source = e.target.value; state.page = 1; loadJobs(); });
    $("#f-role").addEventListener("change", (e) => { state.filters.role_category = e.target.value; state.page = 1; loadJobs(); });
    $("#f-exp").addEventListener("change", (e) => { state.filters.experience_level = e.target.value; state.page = 1; loadJobs(); });
    $("#f-reset").addEventListener("click", () => {
      state.filters = { search: "", source: "all", role_category: "all", experience_level: "all" };
      state.page = 1;
      $("#f-search").value = "";
      $("#f-source").value = "all";
      $("#f-role").value = "all";
      $("#f-exp").value = "all";
      loadJobs();
    });

    $("#hero-search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const val = $("#hero-search-input").value.trim();
      $("#f-search").value = val;
      state.filters.search = val;
      state.page = 1;
      loadJobs();
      scrollToBrowse();
    });

    $("#hero-match-btn").addEventListener("click", () => {
      $("#match").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $("#nav-cta").addEventListener("click", () => {
      $("#match").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  // ---------- DRAWER ----------
  function openDrawer(job) {
    const content = $("#drawer-content");
    const alsoPosted = job.also_posted_on && job.also_posted_on.length
      ? `<p class="also-posted">Also posted on ${job.also_posted_on.map(escapeHtml).join(", ")}</p>`
      : "";

    content.innerHTML = `
      <p class="mono-label">${escapeHtml(job.source || "")}</p>
      <h3 class="drawer-title">${escapeHtml(job.title || "Untitled role")}</h3>
      <p class="drawer-company">${escapeHtml(job.company || "Unknown company")} · ${escapeHtml(job.location || "")}</p>
      <div class="drawer-meta-row">
        <span class="drawer-tag">${escapeHtml(job.experience_level || job.experience || "Experience N/A")}</span>
        <span class="drawer-tag">${escapeHtml(job.role_category || "Uncategorized")}</span>
        <span class="drawer-tag">Posted ${escapeHtml(job.posted_date || "—")}</span>
      </div>
      ${alsoPosted}
      <p class="drawer-section-label">// Skills</p>
      <div class="chip-row">${(job.skills || []).map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("") || '<span class="mono-label">None tagged</span>'}</div>
      <p class="drawer-section-label">// Description</p>
      <p class="drawer-desc">${escapeHtml(job.description || "No description provided.")}</p>
      <div class="drawer-actions">
        ${job.url ? `<a class="btn btn-primary" href="${escapeHtml(job.url)}" target="_blank" rel="noopener">Apply ↗</a>` : ""}
        <button class="btn btn-outline" id="drawer-ask-ai">Ask AI about this job</button>
      </div>
    `;

    $("#drawer-ask-ai").addEventListener("click", () => {
      currentJobHash = job.content_hash;
      openAssistant();
      pushAssistantMsg(`Analyze "${job.title}" at ${job.company}.`, "user");
      sendAssistantQuestion(
        `Analyze the selected job "${job.title}" at ${job.company}. Tell me what the role requires, whether my uploaded resume is a good fit, which skills I already have, which skills are missing, and what I should prepare before applying.`,
        job.content_hash
      );
    });

    $("#job-drawer").classList.add("open");
    $("#drawer-overlay").classList.add("open");
  }

  function closeDrawer() {
    $("#job-drawer").classList.remove("open");
    $("#drawer-overlay").classList.remove("open");
  }

  // ---------- RESUME UPLOAD ----------
  function bindUpload() {
    const drop = $("#upload-drop");
    const input = $("#resume-file");

    ["dragover", "dragenter"].forEach((evt) =>
      drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach((evt) =>
      drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.remove("dragover"); })
    );
    drop.addEventListener("drop", (e) => {
      const file = e.dataTransfer.files[0];
      if (file) uploadResume(file);
    });
    input.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) uploadResume(file);
    });
  }

  async function uploadResume(file) {
    const allowed = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"];
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!['pdf','docx','txt'].includes(ext)) {
      $("#upload-text").textContent = "Use a PDF, DOCX or TXT resume.";
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      $("#upload-text").textContent = "Resume is larger than 5MB.";
      return;
    }
    $("#upload-text").textContent = `Parsing ${file.name}…`;
    const form = new FormData();
    form.append("resume", file);

    try {
      const r = await fetch("/api/resume/upload", { method: "POST", body: form });
      const d = await readApiResponse(r);

      $("#upload-text").textContent = `${file.name} — parsed ✓`;
      $("#upload-skills").hidden = false;
      $("#upload-skills-chips").innerHTML = (d.skills || [])
        .map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("") || '<span class="mono-label">No skills detected</span>';

      await loadRecommendations();
    } catch (e) {
      $("#upload-text").textContent = e.message || "Resume upload failed.";
      $("#upload-skills").hidden = true;
      console.error("Resume upload failed:", e);
    }
  }

  async function loadRecommendations() {
    const wrap = $("#match-results");
    wrap.innerHTML = `<p class="match-placeholder">Scoring the board against your resume…</p>`;
    try {
      const r = await fetch("/api/recommendations");
      const d = await readApiResponse(r);

      if (!d.recommendations || d.recommendations.length === 0) {
        wrap.innerHTML = `<p class="match-placeholder">No strong matches yet — try a resume with more detail on skills and tools.</p>`;
        return;
      }

      wrap.innerHTML = "";
      d.recommendations.forEach((job) => {
        const score = job.match_score != null ? Math.round(job.match_score) : null;
        const item = el("div", "match-item");
        item.innerHTML = `
          <div class="match-item-top">
            <span class="match-item-title">${escapeHtml(job.title || "Untitled role")}</span>
            ${score != null ? `<span class="match-score">${score}% match</span>` : ""}
          </div>
          <p class="match-item-meta">${escapeHtml(job.company || "")} · ${escapeHtml(job.location || "")}</p>
          ${job.matched_skills && job.matched_skills.length ? `<p class="match-item-why">Shares: ${escapeHtml(job.matched_skills.join(", "))}</p>` : ""}
        `;
        item.addEventListener("click", () => openDrawer(job));
        wrap.appendChild(item);
      });
    } catch (e) {
      wrap.innerHTML = `<p class="match-placeholder">Couldn't score matches right now — try re-uploading your resume.</p>`;
      console.error(e);
    }
  }

  // ---------- AI ASSISTANT ----------
  let currentJobHash = null;

  function openAssistant() {
    $("#assistant-panel").classList.add("open");
    $("#assistant-panel").setAttribute("aria-hidden", "false");
    setTimeout(() => $("#assistant-input")?.focus(), 120);
  }
  function closeAssistant() {
    $("#assistant-panel").classList.remove("open");
    $("#assistant-panel").setAttribute("aria-hidden", "true");
  }

  function pushAssistantMsg(text, who) {
    const body = $("#assistant-body");
    const msg = el("div", `assistant-msg ${who}`, escapeHtml(text));
    body.appendChild(msg);
    body.scrollTop = body.scrollHeight;
  }

  async function sendAssistantQuestion(question, jobHash) {
    const body = $("#assistant-body");
    const thinking = el("div", "assistant-msg bot", "…");
    body.appendChild(thinking);
    body.scrollTop = body.scrollHeight;

    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, job_hash: jobHash || currentJobHash || null }),
      });
      const d = await readApiResponse(r);
      thinking.textContent = d.answer || "I couldn't find a grounded answer for that — try rephrasing, or open a specific job first.";
    } catch (e) {
      thinking.textContent = e.message || "The assistant could not respond.";
      console.error(e);
    }
  }

  function bindAssistant() {
    $("#assistant-fab").addEventListener("click", () => {
      $("#assistant-panel").classList.contains("open") ? closeAssistant() : openAssistant();
    });
    $("#assistant-close").addEventListener("click", closeAssistant);
    $("#nav-assistant")?.addEventListener("click", (e) => {
      e.preventDefault();
      openAssistant();
    });

    $("#assistant-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("#assistant-input");
      const q = input.value.trim();
      if (!q) return;
      pushAssistantMsg(q, "user");
      sendAssistantQuestion(q);
      input.value = "";
    });
  }

  // ---------- AUTH ----------
  const authState = { mode: "login", user: null };

  function openAuthModal(mode) {
    setAuthMode(mode || "login");
    $("#auth-error").hidden = true;
    $("#auth-form").reset();
    $("#auth-overlay").classList.add("open");
    $("#auth-modal").classList.add("open");
    $("#auth-modal").setAttribute("aria-hidden", "false");
    setTimeout(() => $("#auth-email")?.focus(), 50);
  }

  function closeAuthModal() {
    $("#auth-overlay").classList.remove("open");
    $("#auth-modal").classList.remove("open");
    $("#auth-modal").setAttribute("aria-hidden", "true");
  }

  function setAuthMode(mode) {
    authState.mode = mode;
    const isSignup = mode === "signup";
    $("#auth-tab-login").classList.toggle("active", !isSignup);
    $("#auth-tab-signup").classList.toggle("active", isSignup);
    $("#auth-name-field").hidden = !isSignup;
    $("#auth-modal-title").textContent = isSignup ? "Create your account" : "Welcome back";
    $("#auth-sub").textContent = isSignup
      ? "Save your matches and pick up where you left off next time."
      : "Log in to save your matches and pick up where you left off.";
    $("#auth-submit").textContent = isSignup ? "Create account" : "Log in";
    $("#auth-password").setAttribute("autocomplete", isSignup ? "new-password" : "current-password");
    $("#auth-switch-text").textContent = isSignup ? "Already have an account?" : "Don't have an account?";
    $("#auth-switch-link").textContent = isSignup ? "Log in" : "Create one";
    $("#auth-error").hidden = true;
  }

  function renderAuthNav() {
    const slot = $("#nav-auth-slot");
    if (!slot) return;
    if (authState.user) {
      const label = authState.user.name || authState.user.email;
      slot.innerHTML = `
        <div class="nav-account">
          <span class="nav-account-email" title="${escapeHtml(authState.user.email)}">${escapeHtml(label)}</span>
          <button class="nav-logout-btn" id="nav-logout-btn" type="button">Log out</button>
        </div>`;
      $("#nav-logout-btn").addEventListener("click", handleLogout);
    } else {
      slot.innerHTML = `<a href="#" id="nav-login-link" class="nav-login-link">Log in</a>`;
      $("#nav-login-link").addEventListener("click", (e) => { e.preventDefault(); openAuthModal("login"); });
    }
  }

  async function refreshAuthState() {
    try {
      const data = await fetch("/api/auth/me").then(readApiResponse);
      authState.user = data.user || null;
    } catch (e) {
      authState.user = null;
    }
    renderAuthNav();
  }

  async function handleLogout() {
    try {
      await fetch("/api/auth/logout", { method: "POST" }).then(readApiResponse);
    } catch (e) {
      console.error("Logout failed:", e);
    }
    authState.user = null;
    renderAuthNav();
  }

  function bindAuth() {
    $("#nav-login-link")?.addEventListener("click", (e) => { e.preventDefault(); openAuthModal("login"); });
    $("#auth-close").addEventListener("click", closeAuthModal);
    $("#auth-overlay").addEventListener("click", closeAuthModal);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAuthModal(); });

    $("#auth-tab-login").addEventListener("click", () => setAuthMode("login"));
    $("#auth-tab-signup").addEventListener("click", () => setAuthMode("signup"));
    $("#auth-switch-link").addEventListener("click", (e) => {
      e.preventDefault();
      setAuthMode(authState.mode === "signup" ? "login" : "signup");
    });

    $("#auth-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = $("#auth-email").value.trim();
      const password = $("#auth-password").value;
      const name = $("#auth-name").value.trim();
      const errorEl = $("#auth-error");
      const submitBtn = $("#auth-submit");
      errorEl.hidden = true;
      submitBtn.disabled = true;
      const originalLabel = submitBtn.textContent;
      submitBtn.textContent = authState.mode === "signup" ? "Creating account…" : "Logging in…";

      try {
        const endpoint = authState.mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
        const body = authState.mode === "signup" ? { email, password, name } : { email, password };
        const data = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }).then(readApiResponse);
        authState.user = data.user;
        renderAuthNav();
        closeAuthModal();
      } catch (err) {
        errorEl.textContent = err.message || "Something went wrong. Please try again.";
        errorEl.hidden = false;
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalLabel;
      }
    });
  }

  // ---------- INIT ----------
  function bindDrawer() {
    $("#drawer-close").addEventListener("click", closeDrawer);
    $("#drawer-overlay").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add("motion-ready");
    bindFilters();
    bindDrawer();
    bindUpload();
    bindAssistant();
    bindAuth();
    refreshAuthState();
    loadStats();
    fetch("/api/health").then(readApiResponse).then(d => { const status = $("#connection-status"); if (status) status.textContent = `Backend connected · ${Number(d.database_jobs || 0).toLocaleString()} jobs indexed`; }).catch(e => { const status = $("#connection-status"); if (status) status.textContent = "Backend connection failed · check the Flask terminal"; console.error("API health check failed:", e); });
    loadFilterOptions();
    loadJobs();
  });
})();
