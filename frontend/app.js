"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
const icon = (name) => `<i class="ph ph-${name}" aria-hidden="true"></i>`;
const chips = (items, cls = "") => items.map((s) => `<span class="chip ${cls}">${esc(s)}</span>`).join("");
const skeleton = (n = 4, cls = "") => `<div class="skel ${cls}">${"<i></i>".repeat(n)}</div>`;
const errorBox = (msg) => `<div class="error-box" role="alert">${esc(msg)}</div>`;

const state = { file: null, data: null, jd: "", jdCompany: "", health: {}, recipient: null, purpose: "research", hrJob: null };

async function api(path, opts) {
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("Network error. Check your connection and try again.");
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? "Some input was invalid." : `Request failed (${res.status}).`);
  }
  return body;
}
const post = (path, payload) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

/* ---------- theme toggle ---------- */

const darkQuery = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => (document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light")) === "dark";
function syncThemeBtn() {
  const btn = $("#themeBtn");
  btn.innerHTML = icon(isDark() ? "sun" : "moon");
  btn.setAttribute("aria-label", isDark() ? "Switch to light mode" : "Switch to dark mode");
}
$("#themeBtn").addEventListener("click", () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch { /* private mode: choice lasts this visit only */ }
  syncThemeBtn();
});
darkQuery.addEventListener("change", syncThemeBtn);
syncThemeBtn();

api("/api/health").then((h) => (state.health = h)).catch(() => {});

/* ---------- upload form ---------- */

const form = $("#form");
const fileInput = $("#resume");
const drop = $("#drop");

function setFile(file) {
  $("#formError").textContent = "";
  if (!file) return;
  if (!/\.(pdf|docx)$/i.test(file.name)) {
    $("#formError").textContent = "Use a PDF or DOCX file.";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    $("#formError").textContent = "That file is over 5 MB.";
    return;
  }
  state.file = file;
  drop.classList.add("has-file");
  drop.querySelector(".ph").className = "ph ph-file-text";
  $("#dropTitle").textContent = file.name;
  $("#dropHint").textContent = `${Math.max(1, Math.round(file.size / 1024))} KB. Click to replace.`;
}

fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("drag")));
drop.addEventListener("drop", (e) => { e.preventDefault(); setFile(e.dataTransfer.files[0]); });

$("#urlToggle").addEventListener("click", () => {
  const row = $("#urlRow");
  row.hidden = !row.hidden;
  if (!row.hidden) $("#jobUrl").focus();
});

$("#fetchJd").addEventListener("click", async () => {
  const url = $("#jobUrl").value.trim();
  const msg = $("#jdMsg");
  msg.className = "field-msg";
  if (!url) return;
  const btn = $("#fetchJd");
  btn.disabled = true;
  msg.textContent = "Reading the posting...";
  try {
    const job = await post("/api/job-from-url", { url });
    $("#jd").value = job.description;
    state.jdCompany = job.company || "";
    msg.textContent = `Loaded${job.title ? `: ${job.title}` : ""}${job.company ? ` at ${job.company}` : ""}`;
  } catch (e) {
    msg.className = "field-msg err";
    msg.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

$("#jdFile").addEventListener("change", async () => {
  const f = $("#jdFile").files[0];
  const msg = $("#jdMsg");
  msg.className = "field-msg";
  if (!f) return;
  if (!/\.(pdf|docx)$/i.test(f.name)) {
    msg.className = "field-msg err";
    msg.textContent = "Use a PDF or DOCX file for the job description.";
    return;
  }
  msg.textContent = `Reading ${f.name}...`;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const r = await api("/api/jd-from-file", { method: "POST", body: fd });
    $("#jd").value = r.description;
    state.jdCompany = "";
    msg.textContent = `Loaded from ${f.name}. Check the text below, then analyze.`;
  } catch (e) {
    msg.className = "field-msg err";
    msg.textContent = e.message;
  } finally {
    $("#jdFile").value = "";
  }
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  analyze();
});

async function analyze() {
  const err = $("#formError");
  err.textContent = "";
  if (!state.file) {
    err.textContent = "Add your resume first.";
    return;
  }
  const btn = $("#analyzeBtn");
  const label = btn.querySelector("span");
  btn.disabled = true;
  btn.querySelector(".ph").className = "ph ph-circle-notch spin";
  label.textContent = "Analyzing";
  const slow = setTimeout(() => (label.textContent = "Waking up the server, this can take a minute"), 8000);

  const fd = new FormData();
  fd.append("resume", state.file);
  fd.append("job_description", $("#jd").value.trim());
  try {
    state.data = await api("/api/analyze", { method: "POST", body: fd });
    state.jd = $("#jd").value.trim();
    renderResults();
  } catch (e2) {
    err.textContent = e2.message;
  } finally {
    clearTimeout(slow);
    btn.disabled = false;
    btn.querySelector(".ph").className = "ph ph-arrow-right";
    label.textContent = "Analyze resume";
  }
}

/* ---------- results shell ---------- */

function renderResults() {
  const d = state.data;
  const p = d.profile;
  const top = d.roles[0];
  const el = $("#results");
  el.hidden = false;
  el.innerHTML = `
    <div class="summary reveal">
      <div>
        <div class="who-name">${esc(p.name || "Your resume")}</div>
        <div class="who-meta">${esc(p.email || "No email found")}</div>
        <div class="who-meta">${d.skills.length} skills detected</div>
      </div>
      <div>
        <div class="stat-label">Job match</div>
        ${d.match ? `<div class="stat-value">${d.match.score}<small>/100</small></div>`
                  : `<div class="stat-text" style="color:var(--muted);font-weight:500">Add a job description</div>`}
      </div>
      <div>
        <div class="stat-label">ATS readiness</div>
        <div class="stat-value">${d.ats.score}<small>/100</small></div>
      </div>
      <div>
        <div class="stat-label">Best-fit role</div>
        <div class="stat-text">${esc(top.role)}</div>
      </div>
    </div>

    <nav class="tabs" role="tablist" aria-label="Results">
      <button class="tab" role="tab" data-tab="overview" aria-selected="true">${icon("chart-bar")}Overview</button>
      <button class="tab" role="tab" data-tab="jobs" aria-selected="false">${icon("briefcase")}Jobs <span class="count" id="jobsCount"></span></button>
      <button class="tab" role="tab" data-tab="outreach" aria-selected="false">${icon("envelope-simple")}Cold email</button>
    </nav>

    <div id="tab-overview" role="tabpanel">${overview(d)}</div>
    <div id="tab-jobs" role="tabpanel" hidden>${jobsShell(d)}</div>
    <div id="tab-outreach" role="tabpanel" hidden>${outreachShell()}</div>`;

  el.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  bindJobs();
  bindComposer();
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });

  loadReview();
  loadJobs();
  loadFaculty();
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  ["overview", "jobs", "outreach"].forEach((n) => ($(`#tab-${n}`).hidden = n !== name));
}

/* ---------- overview ---------- */

function overview(d) {
  const m = d.match;
  const failed = d.ats.checks.filter((c) => c.points < c.max);
  const passed = d.ats.checks.filter((c) => c.points >= c.max);
  const checkRow = (c) => `
    <li class="check ${c.points >= c.max ? "ok" : ""}">
      ${icon(c.points >= c.max ? "check-circle" : "circle-dashed")}
      <div><div class="check-label">${esc(c.label)}</div>${c.tip ? `<div class="check-tip">${esc(c.tip)}</div>` : ""}</div>
      <span class="check-pts">${c.points}/${c.max}</span>
    </li>`;

  const matchBlock = m ? `
    <section class="panel block reveal" style="--i:1">
      <h2>Match with this job</h2>
      <p class="sub">60% exact skill coverage, 40% semantic similarity of the full text.</p>
      <div class="match">
        <div class="ring-wrap"><div class="ring" style="--v:${m.score}"></div><div class="ring-num">${m.score}</div></div>
        <div>
          <dl class="kv">
            <dt>Skill coverage</dt><dd>${m.coverage === null ? "no skills recognised in the JD" : m.coverage + "%"}</dd>
            <dt>Semantic fit</dt><dd>${m.semantic}%</dd>
          </dl>
          ${m.matched.length ? `<div class="chip-label">You have</div><div class="chips">${chips(m.matched, "have")}</div>` : ""}
          ${m.missing.length ? `<div class="chip-label">Missing from your resume</div><div class="chips">${chips(m.missing, "miss")}</div>` : ""}
        </div>
      </div>
    </section>` : "";

  const roles = d.roles.map((r) => `
    <li>
      <div class="role-top"><span>${esc(r.role)}</span><span>${r.fit}</span></div>
      <div class="bar" style="width:${r.fit}%"></div>
      ${r.missing.length ? `<div class="role-miss">To add: ${esc(r.missing.slice(0, 4).join(", "))}</div>` : ""}
    </li>`).join("");

  const evidence = Object.entries(d.evidence).slice(0, 8).map(([skill, lines]) => `
    <details><summary>${esc(skill)}</summary>${lines.map((l) => `<p>${esc(l)}</p>`).join("")}</details>`).join("");

  return `
    <div class="grid-main">
      <div class="stack">
        ${matchBlock}
        <section class="panel block reveal" style="--i:2" id="review">
          <h2>Recruiter review</h2>
          <p class="sub">Written feedback on this specific resume.</p>
          ${skeleton(5)}
        </section>
        <section class="panel block reveal" style="--i:3">
          <h2>ATS readiness</h2>
          <p class="sub">Deterministic checks. Fix the items below to raise the score.</p>
          <ul class="checks">${failed.map(checkRow).join("") || `<li class="check ok">${icon("check-circle")}<div class="check-label">Everything passes.</div><span></span></li>`}</ul>
          ${passed.length ? `<details class="passed"><summary>${passed.length} checks passed</summary><ul class="checks">${passed.map(checkRow).join("")}</ul></details>` : ""}
        </section>
      </div>
      <aside class="side stack">
        <section class="block reveal" style="--i:2">
          <h2>Best-fit roles</h2>
          <p class="sub">Skill coverage plus similarity to each role.</p>
          <ul class="roles">${roles}</ul>
        </section>
        <section class="block reveal" style="--i:3">
          <h2>Skills found</h2>
          <p class="sub">Exact matches against 180+ tools and fields.</p>
          <div class="chips">${chips(d.skills) || "<span class='sub'>None recognised.</span>"}</div>
        </section>
        ${evidence ? `<section class="block reveal" style="--i:4"><h2>Where each skill shows up</h2><p class="sub">Recruiters look for skills used in projects, not just listed.</p><div class="evidence">${evidence}</div></section>` : ""}
      </aside>
    </div>`;
}

async function loadReview() {
  const box = $("#review");
  const d = state.data;
  const head = `<h2>Recruiter review</h2><p class="sub">Written feedback on this specific resume.</p>`;
  try {
    const r = await post("/api/review", {
      resume_text: d.resume_text,
      job_description: state.jd,
      top_role: d.roles[0].role,
      missing: d.match ? d.match.missing : d.roles[0].missing,
      ats: d.ats.score,
    });
    if (!r.configured) {
      box.innerHTML = head + `<p class="note">${icon("info")}Written reviews are off on this server. Set GROQ_API_KEY to turn them on.</p>`;
      return;
    }
    const list = (xs) => (xs || []).map((x) => `<li>${esc(x)}</li>`).join("");
    box.innerHTML = head + `
      <p class="review-summary">${esc(r.summary)}</p>
      <div class="cols">
        <div><h3>Working well</h3><ul>${list(r.strengths)}</ul></div>
        <div><h3>Fix next</h3><ul>${list(r.improvements)}</ul></div>
      </div>
      ${(r.rewrites || []).length ? `<div class="rewrites"><h3>Bullet rewrites</h3>${r.rewrites.map((w) => `
        <div class="rewrite"><span class="before">${esc(w.before)}</span><span class="after">${esc(w.after)}</span></div>`).join("")}</div>` : ""}`;
  } catch (e) {
    box.innerHTML = head + errorBox(e.message);
  }
}

/* ---------- jobs ---------- */

const COUNTRIES = { in: "India", us: "United States", gb: "United Kingdom", ca: "Canada", de: "Germany", sg: "Singapore", ae: "UAE", au: "Australia" };

function jobsShell(d) {
  return `
    <form class="controls" id="jobsForm">
      <label>Role
        <input type="text" id="jobRole" list="roleList" value="${esc(d.roles[0].role)}" required maxlength="80">
        <datalist id="roleList">${d.roles.map((r) => `<option value="${esc(r.role)}">`).join("")}</datalist>
      </label>
      <label>Country
        <select id="jobCountry">${Object.entries(COUNTRIES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
      </label>
      <label>City <input type="text" id="jobCity" placeholder="Any city" maxlength="60"></label>
      <label>Posted
        <select id="jobPosted"><option value="month">Past month</option><option value="week">Past week</option><option value="3days">Past 3 days</option><option value="all">Any time</option></select>
      </label>
      <button class="btn btn-primary" type="submit">${icon("magnifying-glass")}Search</button>
    </form>
    <div id="jobsOut">${skeleton(3, "tall")}</div>`;
}

function bindJobs() {
  $("#jobsForm").addEventListener("submit", (e) => {
    e.preventDefault();
    loadJobs();
  });
}

async function loadJobs() {
  const out = $("#jobsOut");
  const role = $("#jobRole").value.trim() || state.data.roles[0].role;
  const others = state.data.roles.map((r) => r.role).filter((r) => r !== role);
  out.innerHTML = skeleton(3, "tall");
  try {
    const r = await post("/api/jobs", {
      resume_text: state.data.resume_text,
      roles: [role, ...others].slice(0, 3),
      country: $("#jobCountry").value,
      city: $("#jobCity").value.trim(),
      date_posted: $("#jobPosted").value,
    });
    state.jobs = r.jobs;
    $("#jobsCount").textContent = r.jobs.length || "";
    out.innerHTML = renderJobs(r);
    out.querySelectorAll("[data-target]").forEach((b) => b.addEventListener("click", () => useAsTarget(+b.dataset.target)));
    out.querySelectorAll("[data-email]").forEach((b) => b.addEventListener("click", () => emailForJob(+b.dataset.email)));
  } catch (e) {
    out.innerHTML = errorBox(e.message);
  }
}

function renderJobs(r) {
  const linkedin = `<div class="linkedin">${icon("linkedin-logo")}<span>Also search LinkedIn:</span>${r.linkedin
    .map((l) => `<a class="btn btn-ghost btn-sm" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener">${esc(l.role)}${icon("arrow-square-out")}</a>`).join("")}</div>`;
  if (!r.configured) {
    return `<div class="empty" style="margin-top:20px">${icon("plug")}<strong>Live listings aren't connected on this server</strong>Set OPENWEBNINJA_API_KEY (JSearch) to pull ranked openings. LinkedIn searches still work below.</div>${linkedin}`;
  }
  if (!r.jobs.length) {
    return `<div class="empty" style="margin-top:20px">${icon("magnifying-glass")}<strong>No openings found</strong>Try a broader role, another city, or "Any time".</div>${linkedin}`;
  }
  const trends = `
    <div class="block trend">
      <h2>What these employers ask for</h2>
      <p class="sub">Most requested skills across ${r.sample} live listings. Highlighted ones are on your resume.</p>
      <div class="chips">${r.trends.map((t) => `<span class="chip ${t.have ? "have" : "miss"}">${esc(t.skill)} <span class="n">${t.count}</span></span>`).join("")}</div>
    </div>`;
  const rows = r.jobs.map((j, i) => {
    const initial = `<div class="logo fallback" ${j.logo ? "hidden" : ""}>${esc((j.company || "?")[0])}</div>`;
    const logo = j.logo
      ? `<div><img class="logo" src="${esc(safeUrl(j.logo))}" alt="" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false">${initial}</div>`
      : initial;
    const meta = [j.company, j.location, j.type].filter(Boolean).map(esc).join(", ");
    const posted = j.posted ? new Date(j.posted).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
    return `
      <li class="job reveal" style="--i:${Math.min(i, 8)}">
        ${logo}
        <div>
          <div class="job-title">${esc(j.title)}</div>
          <div class="job-meta">${meta}${j.source ? `. Via ${esc(j.source)}` : ""}${posted ? `, ${esc(posted)}` : ""}</div>
          <div class="chips">${chips(j.matched.slice(0, 6), "have")}${chips(j.missing.slice(0, 4), "miss")}</div>
        </div>
        <div class="job-side">
          <div class="fit">${j.fit}<small>fit</small></div>
          <div class="actions">
            <button class="btn btn-ghost btn-sm" data-target="${i}" type="button">Score against it</button>
            <button class="btn btn-ghost btn-sm" data-email="${i}" type="button">${icon("envelope-simple")}Email</button>
            <a class="btn btn-primary btn-sm" href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener">Apply${icon("arrow-up-right")}</a>
          </div>
        </div>
      </li>`;
  }).join("");
  return trends + `<ul class="joblist">${rows}</ul>` + linkedin;
}

function useAsTarget(i) {
  const j = state.jobs[i];
  $("#jd").value = `${j.title} at ${j.company}\n\n${j.description}`;
  $("#jdMsg").className = "field-msg";
  $("#jdMsg").textContent = `Scoring against: ${j.title} at ${j.company}`;
  analyze();
}

function emailForJob(i) {
  const j = state.jobs[i];
  showTab("outreach");
  setMode("hr");
  state.hrJob = j;
  $("#hrCompany").value = j.company || "";
  $("#hrDomain").value = "";
  loadContacts();
}

/* ---------- outreach ---------- */

function outreachShell() {
  return `
    <div class="outreach">
      <section class="block">
        <div class="seg" role="tablist" aria-label="Who to email">
          <button type="button" role="tab" data-mode="hr" aria-selected="true">${icon("buildings")}Company HR</button>
          <button type="button" role="tab" data-mode="faculty" aria-selected="false">${icon("graduation-cap")}Faculty</button>
        </div>

        <div id="mode-hr">
          <h2>Recruiters at the company</h2>
          <p class="sub">Names and emails from your job post, the company's public HR emails, and its careers page.</p>
          <form class="hr-form" id="hrForm">
            <label>Company <input type="text" id="hrCompany" maxlength="120" placeholder="e.g. Cvent" value="${esc(state.jdCompany)}"></label>
            <label><span>Website <span class="optional">optional</span></span><input type="text" id="hrDomain" maxlength="200" placeholder="cvent.com"></label>
            <button class="btn btn-primary" type="submit">${icon("magnifying-glass")}Find</button>
          </form>
          <div id="hrOut"><div class="empty">${icon("buildings")}<strong>Find who's hiring</strong>${state.jd
            ? "Enter the company (or leave it empty and we'll read it from your job description) and press Find."
            : "Enter a company name and press Find, or use Email on any listing in the Jobs tab."}</div></div>
        </div>

        <div id="mode-faculty" hidden>
          <h2>Faculty who work on what you've built</h2>
          <p class="sub">IIT and IIM professors ranked by how closely their research matches your resume. Pick one to draft an email.</p>
          <div class="fac-filter"><select id="facFilter" aria-label="Filter by institute"><option value="">All institutes</option><option value="IIT">All IITs</option><option value="IIM">All IIMs</option></select></div>
          <div id="facOut">${skeleton(4, "tall")}</div>
        </div>
      </section>
      <section class="panel block composer" id="composer">
        <h2>Draft</h2>
        <p class="to" id="composeTo">Choose a recruiter or a professor to start a draft.</p>
        <div class="field"><label class="field-label" for="mailSubject">Subject</label><input type="text" id="mailSubject"></div>
        <div class="field"><label class="field-label" for="mailBody">Message</label><textarea id="mailBody"></textarea></div>
        <div class="composer-actions">
          <a class="btn btn-primary" id="gmailBtn" target="_blank" rel="noopener" href="#">${icon("paper-plane-tilt")}Open in Gmail</a>
          <button class="btn btn-ghost" id="copyBtn" type="button">${icon("copy")}Copy</button>
          <a class="btn btn-ghost" id="mailtoBtn" href="#">${icon("envelope-simple")}Mail app</a>
          <button class="btn btn-ghost" id="redraftBtn" type="button" hidden>${icon("arrow-clockwise")}Redraft</button>
        </div>
        <p class="hint" id="draftHint">Attach your resume in Gmail before sending, and read every line first.</p>
      </section>
    </div>`;
}

function setMode(mode) {
  document.querySelectorAll(".seg [data-mode]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
  $("#mode-hr").hidden = mode !== "hr";
  $("#mode-faculty").hidden = mode !== "faculty";
}

async function loadContacts() {
  const out = $("#hrOut");
  const company = $("#hrCompany").value.trim();
  const jd = state.hrJob ? `${state.hrJob.title} at ${state.hrJob.company}\n\n${state.hrJob.description}` : state.jd;
  if (!company && !jd) {
    out.innerHTML = errorBox("Enter the company name.");
    return;
  }
  out.innerHTML = skeleton(3, "tall");
  try {
    const r = await post("/api/contacts", { company, domain: $("#hrDomain").value.trim(), job_description: jd });
    if (r.company && !company) $("#hrCompany").value = r.company;
    if (r.domain && !$("#hrDomain").value.trim()) $("#hrDomain").value = r.domain;
    state.contacts = r.contacts;
    const title = state.hrJob ? state.hrJob.title : "";
    const team = { company: r.company || company, title, description: jd };
    const rows = r.contacts.map((c, i) => `
      <li><button class="fac" type="button" data-contact="${i}" aria-pressed="false">
        <span class="fac-name">${esc(c.name || c.email)}</span>
        ${c.confidence ? `<span class="fit" title="Hunter.io confidence">${c.confidence}%</span>` : "<span></span>"}
        <span class="fac-org">${esc([c.position, c.name ? c.email : ""].filter(Boolean).join(". "))}</span>
        <span class="fac-int">From ${esc(c.source)}</span>
      </button>${c.linkedin ? `<a class="row-link" href="${esc(safeUrl(c.linkedin))}" target="_blank" rel="noopener">${icon("linkedin-logo")}LinkedIn profile</a>` : ""}</li>`).join("");
    const links = r.links.length ? `<div class="linkedin">${icon("linkedin-logo")}<span>Search more:</span>${r.links
      .map((l) => `<a class="btn btn-ghost btn-sm" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener">${esc(l.label)}${icon("arrow-square-out")}</a>`).join("")}</div>` : "";
    const none = `<div class="empty">${icon("user-circle")}<strong>No contacts found${r.company ? ` for ${esc(r.company)}` : ""}</strong>${r.hunter
      ? "Try the company's website domain, or search LinkedIn below."
      : "Only the job post and company website were checked. Set HUNTER_API_KEY on the server to search public HR emails."}</div>`;
    out.innerHTML = `${rows ? `<ul class="faclist">${rows}</ul>` : none}
      <button class="btn btn-ghost btn-sm" type="button" id="teamDraft" style="margin-top:12px">${icon("envelope-simple")}Write to the hiring team instead</button>
      ${links}
      ${rows ? `<p class="hint">Emails come from public sources and can be out of date. "Guessed" addresses follow the company's usual format and may bounce.</p>` : ""}`;
    out.querySelectorAll("[data-contact]").forEach((b) => b.addEventListener("click", () => {
      out.querySelectorAll("[data-contact]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const c = state.contacts[+b.dataset.contact];
      draft({ ...team, name: c.name, position: c.position, email: c.email }, "job", c.name ? `${c.name} <${c.email}>` : c.email);
    }));
    $("#teamDraft").addEventListener("click", () => draft(team, "job", `Hiring team, ${team.company || "the company"}`));
  } catch (e) {
    out.innerHTML = errorBox(e.message);
  }
}

function bindComposer() {
  $("#facFilter").addEventListener("change", loadFaculty);
  document.querySelectorAll(".seg [data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("#hrForm").addEventListener("submit", (e) => {
    e.preventDefault();
    state.hrJob = null;
    loadContacts();
  });
  ["mailSubject", "mailBody"].forEach((id) => $(`#${id}`).addEventListener("input", syncLinks));
  $("#copyBtn").addEventListener("click", async () => {
    const btn = $("#copyBtn");
    try {
      await navigator.clipboard.writeText(`Subject: ${$("#mailSubject").value}\n\n${$("#mailBody").value}`);
      btn.innerHTML = `${icon("check")}Copied`;
    } catch {
      btn.innerHTML = `${icon("x")}Copy blocked`;
    }
    setTimeout(() => (btn.innerHTML = `${icon("copy")}Copy`), 1600);
  });
  $("#redraftBtn").addEventListener("click", () => state.recipient && draft(state.recipient, state.purpose, state.toLabel));
  syncLinks();
}

function syncLinks() {
  const to = (state.recipient && state.recipient.email) || "";
  const su = $("#mailSubject").value;
  const body = $("#mailBody").value;
  const q = (o) => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  $("#gmailBtn").href = `https://mail.google.com/mail/?${q({ view: "cm", fs: 1, to, su, body })}`;
  $("#mailtoBtn").href = `mailto:${encodeURIComponent(to)}?${q({ subject: su, body })}`;
}

async function loadFaculty() {
  const out = $("#facOut");
  out.innerHTML = skeleton(4, "tall");
  try {
    const r = await post("/api/faculty", { resume_text: state.data.resume_text, institute: $("#facFilter").value });
    const filter = $("#facFilter");
    if (filter.options.length <= 3) {
      r.institutes.forEach((n) => filter.insertAdjacentHTML("beforeend", `<option value="${esc(n)}">${esc(n)}</option>`));
    }
    if (!r.available) {
      out.innerHTML = `<div class="empty">${icon("graduation-cap")}<strong>Faculty directory isn't loaded</strong>Add professors.csv as a Render secret file to enable matching. You can still draft emails from the Jobs tab.</div>`;
      return;
    }
    state.faculty = r.matches;
    out.innerHTML = `<ul class="faclist">${r.matches.map((f, i) => `
      <li><button class="fac" type="button" data-fac="${i}" aria-pressed="false">
        <span class="fac-name">${esc(f.name)}</span>
        <span class="fit">${f.fit}</span>
        <span class="fac-org">${esc(f.department)}, ${esc(f.institute)}</span>
        <span class="fac-int">${esc(f.interests || "Research interests not listed")}</span>
      </button></li>`).join("")}</ul>`;
    out.querySelectorAll("[data-fac]").forEach((b) => b.addEventListener("click", () => {
      out.querySelectorAll("[data-fac]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const f = state.faculty[+b.dataset.fac];
      draft(f, "research", `${f.name} <${f.email}>`);
    }));
  } catch (e) {
    out.innerHTML = errorBox(e.message);
  }
}

async function draft(recipient, purpose, toLabel) {
  Object.assign(state, { recipient, purpose, toLabel });
  $("#composeTo").innerHTML = `To <strong>${esc(toLabel)}</strong>`;
  const body = $("#mailBody");
  const hint = $("#draftHint");
  $("#mailSubject").value = "";
  body.value = "";
  body.placeholder = "Writing a draft from your resume...";
  $("#redraftBtn").hidden = true;
  if (matchMedia("(max-width: 960px)").matches) $("#composer").scrollIntoView({ behavior: "smooth" });
  try {
    const r = await post("/api/email", { resume_text: state.data.resume_text, purpose, recipient });
    $("#mailSubject").value = r.subject;
    body.value = r.body;
    hint.textContent = r.ai
      ? "Drafted from your resume. Attach your resume in Gmail and read every line before sending."
      : "Template draft: fill in the [brackets]. Set GROQ_API_KEY on the server for personalised drafts.";
    $("#redraftBtn").hidden = !r.ai;
  } catch (e) {
    hint.textContent = e.message;
  } finally {
    body.placeholder = "";
    syncLinks();
  }
}
