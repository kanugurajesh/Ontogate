from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .runtime.dag import Plan

if TYPE_CHECKING:
    from .runtime.orchestrator import RunResult

# Uses plain %%TOKEN%% substitution (not str.format/Template) so the CSS
# `{ }` and JS template-literal `${ }` below can be written verbatim with no
# escaping.
_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Ontogate Agent Runtime - Trace %%RUN_ID%%</title>
<style>
  :root {
    --bg: #0f1117; --panel: #171a23; --border: #2a2e3a; --text: #e6e8ef;
    --muted: #8b90a0; --ok: #3ecf8e; --fail: #ef5a5a; --skip: #8b90a0; --wave: #232734;
    --accent: #7c9dfd;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, "Segoe UI", Inter, sans-serif;
    background: var(--bg); color: var(--text);
  }
  header { padding: 20px 28px; border-bottom: 1px solid var(--border); }
  header h1 { margin: 0 0 4px; font-size: 18px; font-weight: 600; }
  header .meta { color: var(--muted); font-size: 13px; }
  header .meta code { color: var(--text); }
  .status { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .status.SUCCEEDED { background: rgba(62,207,142,.15); color: var(--ok); }
  .status.FAILED { background: rgba(239,90,90,.15); color: var(--fail); }
  main { display: grid; grid-template-columns: 1.4fr 1fr; height: calc(100vh - 78px); }
  .waves { overflow: auto; padding: 24px 28px; }
  .wave { margin-bottom: 22px; }
  .wave .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 8px; }
  .steps { display: flex; gap: 10px; flex-wrap: wrap; }
  .step {
    border: 1px solid var(--border); background: var(--panel); border-radius: 10px;
    padding: 10px 14px; min-width: 180px; cursor: pointer; transition: border-color .15s;
  }
  .step:hover { border-color: var(--accent); }
  .step .name { font-weight: 600; font-size: 13px; }
  .step .tool { color: var(--muted); font-size: 11px; margin-top: 2px; }
  .step .dur { color: var(--muted); font-size: 11px; margin-top: 6px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .dot.SUCCEEDED { background: var(--ok); }
  .dot.FAILED { background: var(--fail); }
  .dot.SKIPPED { background: var(--skip); }
  .step.SUCCEEDED { border-left: 3px solid var(--ok); }
  .step.FAILED { border-left: 3px solid var(--fail); }
  .step.SKIPPED { border-left: 3px solid var(--skip); opacity: .6; }
  aside { border-left: 1px solid var(--border); padding: 24px; overflow: auto; background: #12141c; }
  aside h2 { font-size: 14px; margin: 18px 0 6px; }
  aside h2:first-child { margin-top: 0; }
  pre { background: var(--wave); border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-size: 12px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
  .empty { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>Ontogate Agent Runtime &mdash; <span class="status %%STATUS%%">%%STATUS%%</span></h1>
  <div class="meta">run <code>%%RUN_ID%%</code> &middot; task: &ldquo;%%TASK%%&rdquo;</div>
</header>
<main>
  <div class="waves" id="waves"></div>
  <aside id="detail"><p class="empty">Click a step to see its args/output.</p></aside>
</main>
<script>
const DATA = %%DATA_JSON%%;
const wavesEl = document.getElementById('waves');
const detailEl = document.getElementById('detail');

const byWave = {};
for (const s of DATA.steps) {
  (byWave[s.wave] = byWave[s.wave] || []).push(s);
}

Object.keys(byWave).sort((a, b) => a - b).forEach(w => {
  const waveDiv = document.createElement('div');
  waveDiv.className = 'wave';
  waveDiv.innerHTML = '<div class="label">wave ' + w + '</div>';
  const stepsDiv = document.createElement('div');
  stepsDiv.className = 'steps';
  for (const s of byWave[w]) {
    const el = document.createElement('div');
    el.className = 'step ' + s.status;
    el.innerHTML =
      '<div class="name"><span class="dot ' + s.status + '"></span>' + s.id + '</div>' +
      '<div class="tool">' + s.tool + '</div>' +
      '<div class="dur">' + (s.duration_ms != null ? Math.round(s.duration_ms) + 'ms' : s.status.toLowerCase()) + '</div>';
    el.onclick = () => showDetail(s);
    stepsDiv.appendChild(el);
  }
  waveDiv.appendChild(stepsDiv);
  wavesEl.appendChild(waveDiv);
});

function showDetail(s) {
  const bits = ['tool: ' + s.tool, 'status: ' + s.status];
  if (s.duration_ms != null) bits.push(Math.round(s.duration_ms) + 'ms');
  if (s.attempts) bits.push('attempts: ' + s.attempts);
  if (s.cache) bits.push('cache: ' + s.cache);
  detailEl.innerHTML =
    '<h2>' + s.id + '</h2>' +
    '<p class="empty">' + bits.join(' &middot; ') + '</p>' +
    '<h2>args</h2><pre>' + JSON.stringify(s.args, null, 2) + '</pre>' +
    '<h2>' + (s.status === 'FAILED' ? 'error' : 'output') + '</h2>' +
    '<pre>' + JSON.stringify(s.status === 'FAILED' ? s.error : s.output, null, 2) + '</pre>';
}

if (DATA.steps.length) {
  showDetail(DATA.steps[0]);
}
</script>
</body>
</html>
"""


def render_trace_html(plan: Plan, result: "RunResult", out_path: str | Path) -> None:
    span_by_name = {sp.name: sp for sp in result.tracer.spans}
    steps_data = []
    for step in plan.steps.values():
        span = span_by_name.get(step.id)
        status = span.status if span else "SKIPPED"
        steps_data.append(
            {
                "id": step.id,
                "tool": step.tool,
                "wave": span.wave if span else _wave_of(plan, step.id),
                "status": status,
                "duration_ms": span.duration_ms if span else None,
                "attempts": span.attributes.get("attempts") if span else None,
                "cache": span.attributes.get("cache") if span else None,
                "args": (span.attributes.get("args") if span else step.args),
                "output": result.outputs.get(step.id),
                "error": result.errors.get(step.id),
            }
        )

    html = (
        _TEMPLATE.replace("%%RUN_ID%%", result.run_id)
        .replace("%%STATUS%%", result.status)
        .replace("%%TASK%%", result.task)
        .replace("%%DATA_JSON%%", json.dumps({"steps": steps_data}))
    )
    Path(out_path).write_text(html, encoding="utf-8")


def _wave_of(plan: Plan, step_id: str) -> int:
    for i, wave in enumerate(plan.waves()):
        if step_id in wave:
            return i
    return -1
