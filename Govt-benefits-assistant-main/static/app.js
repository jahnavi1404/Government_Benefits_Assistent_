/* Government Benefits Assistant — frontend */

const T = window.T;
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let lastResults = [];
let lastNear = [];
let activeFilter = "all";
let sessionId = null;

/* ------------------------------------------------------------ language */

$("#langSelect").addEventListener("change", (e) => {
  location.href = "/?lang=" + encodeURIComponent(e.target.value);
});

/* ---------------------------------------------------------------- tabs */

document.querySelectorAll(".door").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".door").forEach((b) => {
      const on = b === btn;
      b.classList.toggle("is-open", on);
      b.setAttribute("aria-selected", on);
    });
    $("#pane-form").hidden = btn.dataset.mode !== "form";
    $("#pane-chat").hidden = btn.dataset.mode !== "chat";
    if (btn.dataset.mode === "chat" && !$("#transcript").children.length) {
      addBubble(T.chat_intro, "bot");
    }
  });
});

/* ------------------------------------------------------- profile form */

$("#profileForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = {};
  fd.forEach((v, k) => { if (v !== "") body[k] = v; });

  setBusy(true);
  try {
    const res = await fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    lastResults = data.results;
    lastNear = data.near_misses || [];
    render();
  } catch (err) {
    $("#resultList").innerHTML =
      `<div class="empty">Could not reach the server. Make sure it is running, then try again.</div>`;
  } finally {
    setBusy(false);
  }
});

$("#profileForm").addEventListener("reset", () => {
  lastResults = []; lastNear = []; render();
});

function setBusy(on) {
  const btn = $("#profileForm .btn-primary");
  btn.disabled = on;
  btn.textContent = on ? T.loading : T.btn_find;
}

/* ---------------------------------------------------------------- chat */

function addBubble(text, who) {
  const div = document.createElement("div");
  div.className = "bubble " + who;
  div.textContent = text;
  const tr = $("#transcript");
  tr.appendChild(div);
  tr.scrollTop = tr.scrollHeight;
  return div;
}

const QUICK = {
  gender: [[T.opt_female, "female"], [T.opt_male, "male"], [T.opt_transgender, "transgender"]],
  area: [[T.opt_rural, "rural"], [T.opt_urban, "urban"]],
  disability: [[T.opt_yes, "yes"], [T.opt_no, "no"]],
  social_category: [["General", "general"], ["OBC / BC", "obc"], ["SC", "sc"], ["ST", "st"], ["EWS", "ews"], ["Minority", "minority"]],
};

function showQuick(field) {
  const box = $("#chatSlots");
  box.innerHTML = "";
  (QUICK[field] || []).forEach(([label, value]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "slot";
    b.textContent = label;
    b.addEventListener("click", () => { box.innerHTML = ""; sendChat(value, label); });
    box.appendChild(b);
  });
}

$("#chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#chatInput").value.trim();
  if (text) { $("#chatInput").value = ""; sendChat(text); }
});

async function sendChat(text, displayAs) {
  addBubble(displayAs || text, "me");
  $("#chatSlots").innerHTML = "";
  const typing = addBubble("…", "bot");
  typing.classList.add("typing");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    const data = await res.json();
    sessionId = data.session_id;
    typing.remove();
    addBubble(data.reply, "bot");
    if (data.field) showQuick(data.field);
    if (data.done) { lastResults = data.results; lastNear = []; render(); }
  } catch (err) {
    typing.remove();
    addBubble("The server is not responding. Check that it is running and send your message again.", "bot");
  }
}

$("#chatReset").addEventListener("click", async () => {
  if (sessionId) {
    await fetch("/api/chat/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  }
  sessionId = null;
  $("#transcript").innerHTML = "";
  $("#chatSlots").innerHTML = "";
  lastResults = []; lastNear = [];
  addBubble(T.chat_intro, "bot");
  render();
});

/* ------------------------------------------------------------ results */

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    activeFilter = chip.dataset.filter;
    document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("is-on", c === chip));
    render();
  });
});

function list(items, tag) {
  if (!items || !items.length) return "";
  return `<${tag}>` + items.map((i) => `<li>${esc(i)}</li>`).join("") + `</${tag}>`;
}

const BADGE = {
  eligible: () => T.badge_eligible,
  likely: () => T.badge_likely,
  unverified: () => T.badge_unverified,
};

function card(r, i, missed) {
  const badge = missed ? T.near_heading : BADGE[r.status]();
  const cls = missed ? "missed" : r.status;
  const points = missed ? r.blockers : r.reasons;
  const rankMark = missed ? "!" : (r.status === "unverified" ? "?" : i + 1);

  return `
  <article class="card${r.verified ? "" : " corpus"}" data-level="${esc(r.level)}">
    <div class="card-top">
      <div class="rank">${rankMark}</div>
      <div>
        <div class="tags">
          <span class="tag ${esc(r.level)}">${r.level === "central" ? T.badge_central : esc(r.state || T.badge_state)}</span>
          ${r.categories.slice(0, 3).map((c) => `<span class="tag">${esc(c)}</span>`).join("")}
        </div>
        <h3>${esc(r.name)}</h3>
        <p class="org">${esc(r.ministry)}</p>
        <p class="blurb">${esc(r.summary)}</p>
      </div>
    </div>

    ${points && points.length ? `
    <div class="verdict ${cls}">
      <div class="verdict-head">${esc(badge)}</div>
      ${list(points, "ul")}
    </div>` : ""}

    <button class="more" type="button" aria-expanded="false">${esc(T.sec_benefits)} · ${esc(T.sec_docs)} · ${esc(T.sec_process)}</button>
    <div class="detail" hidden>
      <h4>${esc(T.sec_benefits)}</h4>
      <p>${esc(r.benefits)}</p>
      ${r.other_criteria.length ? `<h4>${esc(T.sec_criteria)}</h4>${list(r.other_criteria, "ul")}` : ""}
      ${r.documents.length ? `<h4>${esc(T.sec_docs)}</h4>${list(r.documents, "ul")}` : ""}
      ${r.process.length ? `<h4>${esc(T.sec_process)}</h4>${list(r.process, "ol")}` : ""}
      <h4>${esc(T.sec_deadline)}</h4>
      <p class="deadline">${esc(r.deadline)}</p>
      ${r.link
        ? `<a class="apply" href="${esc(r.link)}" target="_blank" rel="noopener">${esc(T.btn_apply)}</a>`
        : (r.source_link ? `<a class="apply" href="${esc(r.source_link)}" target="_blank" rel="noopener">${esc(T.btn_apply)}</a>` : "")}
    </div>
  </article>`;
}

function passesFilter(r) {
  if (activeFilter === "all") return true;
  if (activeFilter === "verified") return r.verified;
  return r.level === activeFilter;
}

function render() {
  const shown = lastResults.filter(passesFilter);
  // Checked matches and corpus entries are different kinds of answer, so
  // they get different sections rather than one blended list.
  const checked = shown.filter((r) => r.status !== "unverified");
  const corpus = shown.filter((r) => r.status === "unverified");
  const listEl = $("#resultList");
  const nearEl = $("#nearList");

  $("#filters").hidden = lastResults.length === 0;
  $("#resultsCount").textContent = lastResults.length
    ? `${shown.length} ${T.results_count}` : "";

  if (!shown.length) {
    listEl.innerHTML = `<div class="empty">${esc(T.results_none)}</div>`;
    nearEl.innerHTML = "";
    return;
  }

  listEl.innerHTML = checked.map((r, i) => card(r, i, false)).join("");

  nearEl.innerHTML =
    (lastNear.length
      ? `<h3 class="near-head">${esc(T.near_heading)}</h3>
         <p class="near-note">${esc(T.near_note)}</p>` +
        lastNear.map((r) => card(r, 0, true)).join("")
      : "") +
    (corpus.length
      ? `<h3 class="corpus-head">${esc(T.corpus_heading)}</h3>
         <p class="corpus-note">${esc(T.corpus_note)}</p>` +
        corpus.map((r) => card(r, 0, false)).join("")
      : "");

  document.querySelectorAll(".more").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.nextElementSibling;
      const open = !panel.hidden;
      panel.hidden = open;
      btn.setAttribute("aria-expanded", String(!open));
    });
  });
}

render();
