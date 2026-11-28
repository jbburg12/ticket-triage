// ticket-triage UI: plain JS, no build step. Ticket text is untrusted, so everything
// user- or model-provided goes through esc() before it touches innerHTML.

const $ = (sel) => document.querySelector(sel);

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const pct = (x) => (x == null ? "–" : `${(x * 100).toFixed(1)}%`);
const usd = (x) => (x == null ? "–" : x < 0.01 ? `$${x.toFixed(5)}` : `$${x.toFixed(2)}`);
const secs = (x) => (x == null ? "–" : `${x.toFixed(1)}s`);
const label = (s) => esc(String(s ?? "").replaceAll("_", " "));

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map((d) => d.msg).join("; ")
      : body.detail || res.statusText;
    throw new Error(detail);
  }
  return body;
}

// ---------- Tabs ----------

const views = { playground: null, results: null };

function showView(name) {
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.view === name));
  });
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  if (name === "results" && !views.results) views.results = initResults();
  history.replaceState(null, "", `#${name}`);
}

document.querySelectorAll(".tabs button").forEach((b) => {
  b.addEventListener("click", () => showView(b.dataset.view));
});

// ---------- Playground ----------

let examples = [];

async function initPlayground() {
  const [opts, exs] = await Promise.all([api("/api/options"), api("/api/examples")]);
  examples = exs;

  $("#model").innerHTML = opts.models
    .map((m) => `<option ${m === opts.default_model ? "selected" : ""}>${esc(m)}</option>`)
    .join("");
  $("#prompt").innerHTML = opts.prompt_versions
    .map((v) => `<option ${v === opts.default_prompt_version ? "selected" : ""}>${esc(v)}</option>`)
    .join("");
  $("#ticket").maxLength = opts.max_ticket_chars;
  $("#example").innerHTML +=
    exs.map((e) => `<option value="${esc(e.id)}">${esc(e.id)} · ${esc(e.tags.join(", "))} · ${esc(e.text.slice(0, 60))}</option>`).join("");
}

$("#example").addEventListener("change", (e) => {
  const ex = examples.find((x) => x.id === e.target.value);
  $("#ticket").value = ex ? ex.text : "";
  $("#expected").innerHTML = ex
    ? `Expected: <span class="chip">${label(ex.expected.category)}</span> <span class="chip ${esc(ex.expected.priority)}">${esc(ex.expected.priority)}</span>`
    : "";
});

$("#ticket").addEventListener("input", () => {
  // Once edited, the example's expected labels no longer apply.
  if ($("#example").value) {
    $("#example").value = "";
    $("#expected").innerHTML = "";
  }
});

$("#ticket").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#triage-form").requestSubmit();
});

$("#triage-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#ticket").value.trim();
  if (!text) return;
  const button = $("#submit");
  const out = $("#outcome");
  button.disabled = true;
  button.textContent = "Triaging…";
  out.className = "panel outcome empty";
  out.innerHTML = `<p class="muted">Calling ${esc($("#model").value)}…</p>`;
  try {
    const res = await api("/api/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, model: $("#model").value, prompt_version: $("#prompt").value }),
    });
    out.className = "panel outcome";
    out.innerHTML = res.ok ? renderResult(res) : renderFailure(res);
    // Judge exactly what was triaged, even if the textarea is edited afterwards.
    if (res.ok) wireJudge(text, res.result);
  } catch (err) {
    out.className = "panel outcome";
    out.innerHTML = `<div class="failure"><strong>Request failed</strong><pre>${esc(err.message)}</pre></div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Triage";
  }
});

function renderStats(stats, extra = "") {
  if (!stats) return "";
  return `<div class="stats">
    <span>${esc(stats.model)}</span>
    ${extra}
    <span>${secs(stats.latency_s)}</span>
    <span>${esc(stats.input_tokens)} in / ${esc(stats.output_tokens)} out tokens</span>
    <span>${usd(stats.cost_usd)}</span>
  </div>`;
}

function renderResult({ result, stats, prompt_version }) {
  return `
    <h3>Labels</h3>
    <div class="labels">
      <span class="chip">${label(result.category)}</span>
      <span class="chip ${esc(result.priority)}">${esc(result.priority)} priority</span>
    </div>
    <h3>Summary</h3>
    <p>${esc(result.summary)}</p>
    <h3>Suggested reply</h3>
    <p class="reply">${esc(result.suggested_reply)}</p>
    ${renderStats(stats, `<span>${esc(prompt_version)}</span>`)}
    <div id="judge" class="judge-box">
      <button type="button" id="judge-btn" class="secondary">Judge this reply</button>
      <span class="muted">Sonnet grades the summary and reply on the 4-criterion rubric. About 1¢.</span>
    </div>`;
}

function wireJudge(text, result) {
  const btn = $("#judge-btn");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Judging…";
    const box = $("#judge");
    try {
      const res = await api("/api/judge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, output: result }),
      });
      box.innerHTML = res.ok ? renderVerdicts(res) : renderFailure(res);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Judge this reply";
      box.insertAdjacentHTML("beforeend", `<div class="failure">${esc(err.message)}</div>`);
    }
  });
}

function renderVerdicts({ verdicts, stats, judge_prompt }) {
  const items = Object.entries(verdicts)
    .map(([c, v]) => `<li><span class="chip ${v.passed ? "pass" : "fail"}">${v.passed ? "pass" : "fail"}</span> <strong>${label(c)}</strong><br><span class="muted">${esc(v.reason)}</span></li>`)
    .join("");
  return `<h3>Judge</h3><ul class="judge-list">${items}</ul>
    ${renderStats(stats, `<span>${esc(judge_prompt)}</span>`)}`;
}

function renderFailure({ failure, stats }) {
  return `
    <div class="failure">
      <strong>Triage failed: ${label(failure.error)}</strong>
      <pre>${esc(failure.detail)}</pre>
      ${failure.raw ? `<pre class="mono">${esc(failure.raw)}</pre>` : ""}
    </div>
    ${renderStats(stats)}`;
}

// ---------- Results ----------

async function initResults() {
  const runs = await api("/api/runs");
  const select = $("#run");
  if (!runs.length) {
    $("#run-body").innerHTML = `<div class="notice">No eval runs yet. Run <span class="mono">uv run triage eval</span> to create one.</div>`;
    return true;
  }
  select.innerHTML = runs
    .map((r) => {
      const when = r.timestamp ? new Date(r.timestamp).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : r.run_id;
      const parts = [when, r.model, `triage/${r.prompt_version}`, r.dataset, `×${r.repeats}`];
      if (r.judged) parts.push("judged");
      return `<option value="${esc(r.run_id)}">${esc(parts.join(" · "))}</option>`;
    })
    .join("");
  select.addEventListener("change", () => loadRun(select.value));
  await loadRun(runs[0].run_id);
  return true;
}

async function loadRun(runId) {
  const body = $("#run-body");
  body.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const run = await api(`/api/runs/${encodeURIComponent(runId)}`);
    $("#run-meta").textContent = `${run.n_tickets} tickets × ${run.repeats} = ${run.rows.length} rows · ${run.run_id}`;
    body.innerHTML = renderRun(run);
    wireRows(run);
  } catch (err) {
    body.innerHTML = `<div class="failure">${esc(err.message)}</div>`;
  }
}

function renderRun(run) {
  const m = run.metrics;
  const range = (r) => (r && r[0] !== r[1] ? `range ${pct(r[0])}–${pct(r[1])}` : run.repeats > 1 ? "same every run" : "1 run");
  const failCount = Object.values(run.failures || {}).reduce((a, b) => a + b, 0);
  const failDetail = Object.entries(run.failures || {}).map(([k, v]) => `${v} ${k}`).join(", ");

  const gates = (run.gates || [])
    .map((g) => `<div class="gate ${g.passed ? "pass" : "fail"}">
        <span class="name">${g.passed ? "✓" : "✗"} ${esc(g.name)}</span>
        <span class="val">${esc(g.actual)} (needs ${esc(g.required)})</span>
      </div>`)
    .join("");

  const tiles = [
    ["Category accuracy", pct(m.category_accuracy), range(m.category_accuracy_range)],
    ["Priority accuracy", pct(m.priority_accuracy), range(m.priority_accuracy_range)],
    ["Failure rate", pct(m.failure_rate), failCount ? failDetail : "no failures"],
    ["Injection check", `${run.injection?.passed ?? "–"}/${run.injection?.total ?? "–"}`, "passed"],
    ["Cost per 1k tickets", usd(run.cost_usd?.triage_per_1k_tickets), run.judge_model
      ? `this run: ${usd(run.cost_usd?.triage)} triage + ${usd(run.cost_usd?.judge)} judge`
      : `this run: ${usd(run.cost_usd?.triage)}`],
    ["p50 latency", secs(run.triage_latency_p50_s), "per triage call"],
  ]
    .map(([l, v, s]) => `<div class="panel tile"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${esc(s)}</div></div>`)
    .join("");

  const judge = run.judge_pass_rates
    ? `<div class="section-title">Judge pass rates <span class="muted">(${esc(run.judge_model)}, judge/${esc(run.judge_prompt)}; reported, not gating)</span></div>
       <div class="tiles">${Object.entries(run.judge_pass_rates)
         .map(([c, r]) => `<div class="panel tile"><div class="label">${label(c)}</div><div class="value">${pct(r)}</div></div>`)
         .join("")}</div>`
    : "";

  return `
    ${gates ? `<div class="section-title">CI gates <span class="muted">(thresholds as of when this run was saved)</span></div><div class="gates">${gates}</div>` : ""}
    <div class="section-title">Metrics</div>
    <div class="tiles">${tiles}</div>
    ${judge}
    <div class="section-title">Confusion matrices</div>
    <div class="grid-2">
      <div class="panel">${renderConfusion("Category", run.confusion.category)}</div>
      <div class="panel">${renderConfusion("Priority", run.confusion.priority)}</div>
    </div>
    <div class="section-title">Accuracy by slice</div>
    <div class="panel">${renderSlices(run.by_tag)}</div>
    <div class="section-title">Tickets</div>
    <div class="row-filter" role="group">
      <button data-filter="all" aria-pressed="true">All</button>
      <button data-filter="miss" aria-pressed="false">Misses only</button>
    </div>
    <div class="panel">${renderRows(run)}</div>`;
}

function renderConfusion(title, matrix) {
  const expected = Object.keys(matrix);
  const predicted = Object.keys(matrix[expected[0]] || {});
  const head = predicted.map((p) => `<th>${label(p)}</th>`).join("");
  const body = expected
    .map((e) => `<tr><th class="rowhead">${label(e)}</th>${predicted
      .map((p) => {
        const n = matrix[e][p];
        const cls = n === 0 ? "zero" : p === e ? "diag" : "off";
        return `<td class="${cls}">${n}</td>`;
      })
      .join("")}</tr>`)
    .join("");
  return `<table class="confusion"><thead><tr><th class="rowhead">${title}</th>${head}</tr></thead><tbody>${body}</tbody></table>
    <div class="axis-note">Rows: expected label. Columns: predicted.</div>`;
}

function renderSlices(byTag) {
  const rows = Object.entries(byTag || {})
    .map(([tag, s]) => `<tr>
      <td>${esc(tag)}</td><td class="num">${s.n}</td>
      <td class="num ${s.category < 1 ? "wrong" : ""}">${pct(s.category)}</td>
      <td class="num ${s.priority < 1 ? "wrong" : ""}">${pct(s.priority)}</td></tr>`)
    .join("");
  return `<table><thead><tr><th>Slice</th><th class="num">Rows</th><th class="num">Category</th><th class="num">Priority</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function isMiss(row) {
  return (
    !!row.failure ||
    row.predicted?.category !== row.expected.category ||
    row.predicted?.priority !== row.expected.priority ||
    (row.injection && !row.injection.passed) ||
    (row.judge && Object.values(row.judge).some((v) => !v))
  );
}

function renderRows(run) {
  const showRepeat = run.repeats > 1;
  const rows = run.rows
    .map((r, i) => {
      const miss = isMiss(r);
      const cell = (field) => {
        const got = r.predicted?.[field];
        if (!got) return `<span class="wrong">failed</span>`;
        return got === r.expected[field]
          ? label(got)
          : `<span class="wrong">${label(got)}</span> <span class="muted">(exp. ${label(r.expected[field])})</span>`;
      };
      const judge = r.judge
        ? Object.values(r.judge).every(Boolean)
          ? `<span class="chip pass">pass</span>`
          : `<span class="chip fail">${Object.values(r.judge).filter((v) => !v).length} fail</span>`
        : r.judge_failure ? `<span class="chip fail">error</span>` : `<span class="muted">–</span>`;
      return `<tr class="summary-row ${miss ? "miss" : ""}" data-i="${i}" data-miss="${miss}">
        <td class="idcell mono">${esc(r.id)}</td>
        ${showRepeat ? `<td class="num">${r.repeat + 1}</td>` : ""}
        <td>${r.tags.map((t) => `<span class="chip tag">${esc(t)}</span>`).join(" ")}</td>
        <td>${cell("category")}</td>
        <td>${cell("priority")}</td>
        <td>${judge}</td>
      </tr>`;
    })
    .join("");
  return `<table class="rows"><thead><tr>
      <th>Ticket</th>${showRepeat ? `<th class="num">Run</th>` : ""}<th>Slices</th><th>Category</th><th>Priority</th><th>Judge</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

function renderDetail(r) {
  const p = r.predicted || {};
  const judge = r.judge
    ? `<ul class="judge-list">${Object.entries(r.judge)
        .map(([c, ok]) => `<li><span class="chip ${ok ? "pass" : "fail"}">${ok ? "pass" : "fail"}</span> <strong>${label(c)}</strong><br><span class="muted">${esc(r.judge_reasons?.[c])}</span></li>`)
        .join("")}</ul>`
    : r.judge_failure ? `<p class="wrong">${esc(r.judge_failure)}</p>` : `<p class="muted">Not judged in this run.</p>`;
  return `<div class="detail-grid">
    <div>
      <h4>Ticket</h4><pre>${esc(r.text ?? "(ticket text not found in dataset)")}</pre>
      ${r.notes ? `<h4>Why it's labelled ${label(r.expected.category)} / ${esc(r.expected.priority)}</h4><p>${esc(r.notes)}</p>` : ""}
      ${r.injection ? `<h4>Injection check</h4><p class="${r.injection.passed ? "" : "wrong"}">${r.injection.passed ? "passed" : "failed"}: ${esc(r.injection.detail)}</p>` : ""}
    </div>
    <div>
      ${r.failure ? `<h4>Failure</h4><p class="wrong">${label(r.failure)}: ${esc(r.failure_detail)}</p>` : `
        <h4>Summary</h4><p>${esc(p.summary)}</p>
        <h4>Suggested reply</h4><p>${esc(p.suggested_reply)}</p>`}
      <h4>Judge</h4>${judge}
      ${r.stats ? `<p class="muted">${esc(r.stats.model)} · ${secs(r.stats.latency_s)} · ${usd(r.stats.cost_usd)}</p>` : ""}
    </div>
  </div>`;
}

function wireRows(run) {
  const table = document.querySelector("table.rows");
  const cols = table.querySelectorAll("thead th").length;
  table.addEventListener("click", (e) => {
    const tr = e.target.closest("tr.summary-row");
    if (!tr) return;
    const next = tr.nextElementSibling;
    if (next?.classList.contains("detail")) return next.remove();
    const detail = document.createElement("tr");
    detail.className = "detail";
    detail.innerHTML = `<td colspan="${cols}">${renderDetail(run.rows[Number(tr.dataset.i)])}</td>`;
    tr.after(detail);
  });

  document.querySelectorAll(".row-filter button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".row-filter button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const missOnly = b.dataset.filter === "miss";
      table.querySelectorAll("tr.detail").forEach((d) => d.remove());
      table.querySelectorAll("tr.summary-row").forEach((tr) => {
        tr.hidden = missOnly && tr.dataset.miss !== "true";
      });
    });
  });
}

// ---------- Start ----------

initPlayground().catch((err) => {
  $("#outcome").innerHTML = `<div class="failure">Couldn't load options: ${esc(err.message)}</div>`;
});
showView(location.hash === "#results" ? "results" : "playground");
