import { setupExperience } from "/static/interview.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let mode = localStorage.getItem("scout-mode") === "demo" ? "demo" : "live";
let state,
  view = "dashboard",
  filter = "new",
  busy = false;
let token = sessionStorage.getItem("scout-token") || "";
const experience = setupExperience({ api, action, notify, esc });

async function api(path, { method = "GET", body, file } = {}) {
  const headers = { "X-Scout-Client": "job-scout" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(
    `/api/${path}${path.includes("?") ? "&" : "?"}mode=${mode}`,
    {
      method,
      headers,
      body: file || (body ? JSON.stringify(body) : undefined),
    },
  );
  if (response.status === 401) {
    if (!$("#auth-dialog").open) $("#auth-dialog").showModal();
    throw new Error("Enter your access token to continue.");
  }
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the form fields and try again.",
    );
  return data;
}

function notify(message, error = false) {
  const box = $("#notice");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = false;
}

async function action(fn) {
  try {
    await fn();
  } catch (error) {
    notify(error.message, true);
  }
}

function date(value) {
  return value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not checked yet";
}

function age(value) {
  const days = Math.floor((Date.now() - new Date(value)) / 86400000);
  return days < 1
    ? "Found today"
    : `Found ${days} day${days === 1 ? "" : "s"} ago`;
}

function setView(next) {
  view = next === "saved" ? "dashboard" : next;
  if (next === "saved") filter = "saved";
  else if (next === "dashboard") filter = "new";
  $$(".view").forEach((el) => {
    el.hidden = el.id !== `${view}-view`;
  });
  $$(".nav-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === next),
  );
  $("#breadcrumb").textContent =
    `Workspace / ${{ dashboard: "Discover", saved: "Saved jobs", profile: "Your profile", sources: "Search sources" }[next]}`;
  if (state) renderJobs();
  if (next === "profile") action(() => experience.loadInterview());
  window.scrollTo({ top: 0, behavior: "instant" });
}

function fillProfile(profile) {
  experience.setProfile(profile);
  const form = $("#profile-form");
  Object.entries(profile).forEach(([key, value]) => {
    if (form.elements[key])
      form.elements[key].value = Array.isArray(value)
        ? value.join(", ")
        : value;
  });
}

async function load({ profile = false } = {}) {
  state = await api("state");
  $("#demo-banner").hidden = mode !== "demo";
  $("#mode-toggle").textContent =
    mode === "demo" ? "Go to my workspace ↗" : "Explore the demo ↗";
  $("#daily-toggle").checked = state.daily;
  $("#daily-toggle").disabled = mode === "demo";
  $("#sources-daily").checked = state.daily;
  $("#sources-daily").disabled = mode === "demo";
  $("#header-mode").textContent =
    mode === "demo" ? "My workspace" : "Explore demo";
  $("#schedule-copy").textContent =
    mode === "demo"
      ? "Try daily updates in your live workspace."
      : state.daily
        ? `Next: ${date(state.next_run) === "Not checked yet" ? "within 30 seconds" : date(state.next_run)}. Keep Job Scout running.`
        : "Updates run while Job Scout is running.";
  $("#profile-name").textContent = state.profile.name || "Your workspace";
  $("#sources-schedule").textContent = $("#schedule-copy").textContent;
  $("#avatar").textContent = (state.profile.name || "Y")[0].toUpperCase();
  $("#dashboard-title").textContent = state.profile.name
    ? `Your next chapter, ${state.profile.name}.`
    : "Your next chapter.";
  $("#search-summary-title").textContent = state.profile.roles.length
    ? `Looking for ${state.profile.roles.slice(0, 2).join(" or ")}`
    : "A search that starts with you";
  const preferences = [
    ...state.profile.locations,
    ...(state.profile.remote === "remote" ? ["Remote only"] : []),
    ...state.profile.interests,
  ];
  $("#search-summary-text").textContent = preferences.length
    ? preferences.join(" · ")
    : "Tell us what you want to do next. We’ll look for the overlap.";
  $("#stat-new").textContent = state.jobs.filter(
    (j) =>
      j.active &&
      j.enabled &&
      j.status === "new" &&
      j.match.eligible &&
      Date.now() - new Date(j.first_seen) < 86400000,
  ).length;
  $("#stat-matches").textContent = state.jobs.filter(
    (j) =>
      j.active && j.enabled && j.match.eligible && j.status !== "dismissed",
  ).length;
  $("#stat-saved").textContent = state.jobs.filter(
    (j) => j.status === "saved",
  ).length;
  $("#nav-count").textContent = $("#stat-matches").textContent;
  $("#last-checked").textContent = state.runs[0]
    ? `Last attempt ${date(state.runs[0].started)}`
    : mode === "demo"
      ? "Sample data · Explore freely"
      : "Ready when you are";
  $("#discovery-status").textContent = state.discovery_available
    ? "Web discovery is configured. Only target roles and locations are sent to the search provider."
    : "Connect Brigade using the included extension, or set TAVILY_API_KEY to enable this button.";
  $("#discover-sources").disabled =
    !state.discovery_available || mode === "demo";
  $("#starter-sources").disabled = mode === "demo";
  if (profile) {
    fillProfile(state.profile);
    await experience.loadInterview();
  }
  renderJobs();
  renderSources();
  renderActivity();
}

function renderJobs() {
  const query = $("#job-search").value.toLowerCase().trim();
  const eligibility = $("#eligibility").value;
  const jobs = state.jobs.filter((j) => {
    if (j.status !== filter) return false;
    if (eligibility === "closed") {
      if (j.active) return false;
    } else if (filter === "new" && (!j.active || !j.enabled)) return false;
    if (eligibility === "eligible" && filter === "new" && !j.match.eligible)
      return false;
    return (
      !query ||
      `${j.title} ${j.company} ${j.location} ${j.description}`
        .toLowerCase()
        .includes(query)
    );
  });
  $$(".tab").forEach((el) =>
    el.classList.toggle("active", el.dataset.filter === filter),
  );
  $("#result-count").textContent = jobs.length;
  $("#results-title").firstChild.textContent =
    filter === "saved"
      ? "Worth a closer look "
      : filter === "dismissed"
        ? "Dismissed opportunities "
        : "Your opportunities ";
  $("#jobs").innerHTML = jobs
    .slice(0, 120)
    .map((job) => {
      const fit = job.review
        ? `${job.review.fit[0].toUpperCase()}${job.review.fit.slice(1)} fit · Brigade review`
        : !job.match.eligible
          ? "Outside your filters"
          : job.match.score >= 55
            ? "Strong matching signals"
            : job.match.score >= 25
              ? "Some matching signals"
              : "Worth exploring";
      return `<article class="job-card"><div class="card-top"><span class="company-logo" aria-hidden="true">${esc(job.company.slice(0, 2).toUpperCase())}</span><div><div class="company-name">${esc(job.company)}</div><div class="job-age">${esc(age(job.first_seen))}${!job.active ? " · Closed" : ""}</div></div><button class="save-button ${job.status === "saved" ? "saved" : ""}" data-save="${job.id}" aria-label="${job.status === "saved" ? "Unsave" : "Save"} ${esc(job.title)} at ${esc(job.company)}" aria-pressed="${job.status === "saved"}">${job.status === "saved" ? "♥" : "♡"}</button></div><h3>${esc(job.title)}</h3><div class="job-meta"><span>⌖ ${esc(job.location)}</span><span>◷ ${esc(job.workplace === "unknown" ? "Arrangement not listed" : job.workplace)}</span></div><p class="job-salary">${esc(job.salary || "Salary not listed")}</p><div class="match-box ${!job.match.eligible ? "caution" : ""}"><div class="match-label">✧ ${esc(fit)}</div><p>${esc(job.review?.summary || (job.match.blocked.length ? job.match.blocked.join(" · ") : job.match.reasons.slice(0, 2).join(" · ")))}</p></div><div class="tags">${
        job.match.skills
          .slice(0, 5)
          .map((s) => `<span class="tag">${esc(s)}</span>`)
          .join("") || '<span class="tag">Explore the full description</span>'
      }</div><div class="card-bottom"><span>${job.source_error ? "⚠ Last check failed" : `${esc(job.provider)} · ${mode === "demo" ? "Fictional listing" : "Employer board"}`}</span><button class="text-button" data-detail="${job.id}">View opportunity ↗</button></div></article>`;
    })
    .join("");
  $("#empty-state").hidden = jobs.length > 0;
  $("#empty-state h2").textContent = state.jobs.length
    ? "Nothing here just yet."
    : "Make room for your next move.";
  $("#empty-state p").textContent = state.jobs.length
    ? "Try another filter, save a role from Discover, or expand your employer sources."
    : "Start with a few preferences, connect employer job boards, and let your shortlist take shape.";
  if (jobs.length > 120)
    $("#jobs").insertAdjacentHTML(
      "beforeend",
      '<p class="muted">Showing the first 120 roles. Use search to narrow the list.</p>',
    );
}

function renderSources() {
  $("#source-list").innerHTML = state.sources.length
    ? state.sources
        .map(
          (s) =>
            `<div class="source-row"><div><strong>${esc(s.company)}</strong><small>${esc(s.provider)} / ${esc(s.board)} · ${date(s.checked)}</small>${s.error ? `<small class="source-error">${esc(s.error)}. Existing jobs retained.</small>` : ""}</div><label><input type="checkbox" data-source="${s.id}" ${s.enabled ? "checked" : ""} aria-label="Enable ${esc(s.company)}" /> Active</label></div>`,
        )
        .join("")
    : '<p class="muted">No employers added yet. Add a board, or try the starter employers below.</p>';
}

function renderActivity() {
  $("#activity-list").innerHTML = state.runs.length
    ? state.runs
        .slice(0, 5)
        .map(
          (run) =>
            `<div class="activity-row"><span>${run.status === "complete" ? "✓" : "◷"}</span><div><strong>${esc(run.status[0].toUpperCase() + run.status.slice(1))}</strong> · ${date(run.started)}<small>${run.result?.found ?? 0} listings checked · ${run.result?.added ?? 0} new · ${run.result?.changed ?? 0} changed</small>${(run.result?.errors || []).map((e) => `<small class="activity-error">${esc(e)}</small>`).join("")}</div></div>`,
        )
        .join("")
    : `<p class="muted">${mode === "demo" ? "This is a sample workspace. Live refresh history will appear in your own workspace." : "Your first search starts with a profile and an employer board."}</p>`;
}

function details(id) {
  const job = state.jobs.find((j) => j.id === id);
  const list = (items) =>
    `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  $("#job-detail").innerHTML =
    `<div class="detail-company">${esc(job.company)} · ${esc(job.provider)}</div><h2>${esc(job.title)}</h2><p class="muted">${esc(job.location)} · ${esc(job.salary || "Salary not listed")}</p>${!job.active ? '<p class="detail-warning">This role was absent from the last successful feed. It may be closed.</p>' : ""}${job.source_error ? '<p class="detail-warning">The last source check failed. Availability has not been reverified.</p>' : ""}<h3>Why it appeared</h3>${list(job.match.reasons)}${job.match.blocked.length ? `<h3>Outside your preferences</h3>${list(job.match.blocked)}` : ""}<h3>What to check</h3>${list(job.match.gaps.length ? job.match.gaps : ["Confirm responsibilities, compensation, and work eligibility with the employer."])}${job.review ? `<h3>Brigade’s assessment · ${esc(job.review.fit)} fit</h3><p class="description">${esc(job.review.summary)}</p>${job.review.evidence.map((e) => `<p class="muted">${esc(e.claim)}</p><blockquote class="evidence-quote">${esc(e.quote)}</blockquote>`).join("")}${list(job.review.gaps)}` : '<p class="muted">This listing currently uses transparent rule-based matching. Connect Brigade for a deeper review with supporting quotes.</p>'}<h3>From the employer</h3><div class="description">${esc(job.description)}</div><p class="muted">First found ${date(job.first_seen)} · Last seen ${date(job.last_seen)}${job.published ? ` · Published ${esc(job.published)}` : ""}</p><label class="muted" for="dismiss-reason">Optional feedback for future Brigade reviews</label><input id="dismiss-reason" maxlength="300" placeholder="e.g. Too senior, wrong industry…" value="${esc(job.reason)}" /><div class="detail-actions">${mode === "live" ? `<a class="button primary" href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">Open employer listing ↗</a>` : '<span class="button secondary">Fictional demo listing</span>'}<button class="button secondary" data-save="${job.id}">${job.status === "saved" ? "Unsave" : "Save role"}</button><button class="text-button" data-dismiss="${job.id}">${job.status === "dismissed" ? "Restore to Discover" : "Dismiss role"}</button></div>`;
  if (!$("#job-dialog").open) $("#job-dialog").showModal();
}

async function refresh(discover = false) {
  if (busy) return;
  busy = true;
  $("#refresh").disabled = true;
  $("#refresh").textContent = "Checking employer boards…";
  try {
    const result = await api(`refresh?discover=${discover}`, {
      method: "POST",
    });
    await load();
    notify(
      mode === "demo"
        ? "Demo refreshed. Switch to your workspace to search real employer boards."
        : `${result.found} listings checked. ${result.added} new, ${result.changed} changed.${result.errors.length ? " Some sources need attention; see Search activity." : ""}`,
      result.status === "failed",
    );
  } finally {
    busy = false;
    $("#refresh").disabled = false;
    $("#refresh").textContent = "↻ Refresh search";
  }
}

async function switchMode(next) {
  if (experience.isBusy())
    throw new Error(
      "Wait for the current interview request before switching workspaces.",
    );
  experience.reset();
  mode = next;
  localStorage.setItem("scout-mode", mode);
  $("#notice").hidden = true;
  await load({ profile: true });
  setView("dashboard");
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("button, a");
  if (!target) return;
  if (target.dataset.view) setView(target.dataset.view);
  if (target.dataset.filter) {
    filter = target.dataset.filter;
    renderJobs();
  }
  if (target.dataset.detail) details(target.dataset.detail);
  if (target.dataset.save)
    action(async () => {
      const job = state.jobs.find((j) => j.id === target.dataset.save);
      await api(`jobs/${job.id}`, {
        method: "PATCH",
        body: {
          status: job.status === "saved" ? "new" : "saved",
          reason: job.reason,
        },
      });
      await load();
      if ($("#job-dialog").open) details(job.id);
    });
  if (target.dataset.dismiss)
    action(async () => {
      const job = state.jobs.find((j) => j.id === target.dataset.dismiss);
      await api(`jobs/${job.id}`, {
        method: "PATCH",
        body: {
          status: job.status === "dismissed" ? "new" : "dismissed",
          reason: $("#dismiss-reason").value,
        },
      });
      $("#job-dialog").close();
      await load();
    });
});
$("#close-dialog").addEventListener("click", () => $("#job-dialog").close());
$("#job-search").addEventListener("input", renderJobs);
$("#eligibility").addEventListener("change", renderJobs);
$("#refresh").addEventListener("click", () => action(() => refresh()));
$("#discover-sources").addEventListener("click", () =>
  action(() => refresh(true)),
);
$("#try-demo").addEventListener("click", () =>
  action(() => switchMode("demo")),
);
$("#exit-demo").addEventListener("click", () =>
  action(() => switchMode("live")),
);
$("#mode-toggle").addEventListener("click", () =>
  action(() => switchMode(mode === "demo" ? "live" : "demo")),
);
$("#header-mode").addEventListener("click", () =>
  action(() => switchMode(mode === "demo" ? "live" : "demo")),
);
$("#sources-daily").addEventListener("change", () =>
  action(async () => {
    await api("schedule", {
      method: "PUT",
      body: { enabled: $("#sources-daily").checked },
    });
    await load();
  }),
);
$("#daily-toggle").addEventListener("change", () =>
  action(async () => {
    await api("schedule", {
      method: "PUT",
      body: { enabled: $("#daily-toggle").checked },
    });
    await load();
  }),
);
$("#source-list").addEventListener("change", (event) => {
  if (event.target.dataset.source)
    action(async () => {
      await api(`sources/${event.target.dataset.source}`, {
        method: "PATCH",
        body: { enabled: event.target.checked },
      });
      await load();
    });
});
$("#profile-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(new FormData(event.target));
    fields.background = experience.profileBackground();
    ["roles", "skills", "locations", "interests", "excluded"].forEach((key) => {
      fields[key] = fields[key]
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    });
    await api("profile", { method: "PUT", body: fields });
    await load();
    experience.setProfile(state.profile);
    $("#profile-save-status").textContent = "Profile saved";
    notify(
      "Profile saved. Your existing jobs have been ranked again. Add employer boards in Search sources to find more.",
    );
  });
});
$("#resume-file").addEventListener("change", (event) =>
  action(async () => {
    const file = event.target.files[0];
    if (!file || experience.isBusy()) return;
    experience.setBusy(true);
    $("#upload-status").textContent = "Reading your resume…";
    try {
      const form = new FormData();
      form.append("file", file);
      const remember = $("#remember-resume").checked;
      const result = await api(
        `resume?remember=${remember}&revision=${experience.revision()}`,
        { method: "POST", file: form },
      );
      for (const key of ["roles", "skills"]) {
        const input = $("#profile-form").elements[key];
        const existing = input.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        input.value = [...new Set([...existing, ...result.profile[key]])].join(
          ", ",
        );
      }
      $("#upload-status").textContent = result.message;
      if (remember) await experience.loadInterview();
    } catch (error) {
      $("#upload-status").textContent = error.message;
      throw error;
    } finally {
      event.target.value = "";
      experience.setBusy(false);
    }
  }),
);
$("#source-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    await api("sources", {
      method: "POST",
      body: Object.fromEntries(new FormData(event.target)),
    });
    event.target.reset();
    await load();
    notify(
      "Employer added. Refresh your search to retrieve its current openings.",
    );
  });
});
$("#starter-sources").addEventListener("click", () =>
  action(async () => {
    for (const source of [
      { provider: "ashby", board: "openai", company: "OpenAI" },
      { provider: "greenhouse", board: "databricks", company: "Databricks" },
      { provider: "lever", board: "spotify", company: "Spotify" },
    ]) {
      await api("sources", { method: "POST", body: source });
    }
    await load();
    notify(
      "Three example employers added. These are starting points, not personalized recommendations. Refresh to retrieve their openings.",
    );
  }),
);
$("#auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  token = $("#access-token").value;
  sessionStorage.setItem("scout-token", token);
  $("#auth-dialog").close();
  action(() => load({ profile: true }));
});
action(() => load({ profile: true }));
setInterval(() => {
  if (
    !document.hidden &&
    !busy &&
    view === "dashboard" &&
    !$("#job-dialog").open &&
    !$("#auth-dialog").open
  )
    action(() => load());
}, 60000);
