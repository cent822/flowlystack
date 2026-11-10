// The setup card at the top of the Collections home: three steps (Ollama answers, an embedding model is installed, one is chosen for the
// whole app). It never blocks anything: documents can be added first and wait as "Waiting for a model". It disappears once all three are done.
import { toast } from "../toast.js";
import { copy, COPY_ICONS } from "../editor.js";
import { api, esc, ic, I, json } from "./common.js";

let box, onChange, showAll = false, data = null;

export async function mountSetup(el, changed) {
  box = el; onChange = changed;
  if (!box.dataset.wired) { box.dataset.wired = "1"; box.addEventListener("click", click); box.addEventListener("change", change); }
  await refresh();
}

async function refresh() {
  try { data = await api("collections/setup" + (showAll ? "?show_all=true" : "")); }
  catch { data = null; box.hidden = true; box.innerHTML = ""; return; }
  draw();
}

const step = (ok, title, body) => `<li class="co-step${ok ? " done" : ""}"><span class="co-stepic" aria-hidden="true">${ic(ok ? I.check : I.circle, 20)}</span><div><strong>${title}</strong>${body ? `<div class="co-stepbody">${body}</div>` : ""}</div></li>`;

function draw() {
  const d = data, ollama = d.steps.ollama, installed = d.steps.model_installed, ready = d.chosen && d.chosen_installed;
  if (ollama && installed && ready) { box.hidden = true; box.innerHTML = ""; return; }
  const host = d.ollama?.host ? ` at ${esc(d.ollama.host)}` : "";
  const names = showAll ? d.all_models || [] : d.models;
  const opts = [`<option value="">Choose a model…</option>`, ...names.map((m) => `<option value="${esc(m)}"${m === d.chosen ? " selected" : ""}>${esc(m)}</option>`)].join("");
  box.hidden = false;
  box.innerHTML = `
    <h2 class="co-setuptitle">Get ready to search your documents</h2>
    <p class="muted small">You can add documents right away. They wait until a model is chosen, then indexing starts on its own.</p>
    <ol class="co-steps">
      ${step(ollama, ollama ? `Ollama is running${host}` : `Ollama is not reachable${host}`, ollama ? "" : `${esc(d.ollama?.error || "Start Ollama, or check its address in")} <a href="#/settings/connections">Connections</a>.`)}
      ${step(installed, installed ? "An embedding model is installed" : "Install an embedding model", installed ? "" : `Run this in your terminal, then press Check again:
        <div class="co-cmd"><code>${esc(d.pull_command)}</code><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-copy="${esc(d.pull_command)}">${COPY_ICONS}<span>Copy</span></button></div>`)}
      ${step(ready, ready ? `Using ${esc(d.chosen)}` : "Choose the embedding model", `One model serves every collection. ${d.chosen && !d.chosen_installed ? `<span class="set-bad">${esc(d.chosen)} is chosen but not installed.</span> ` : ""}
        <div class="co-pick"><select class="pl-input" id="co-embed" aria-label="Embedding model"${names.length ? "" : " disabled"}>${opts}</select>
        <button type="button" class="btn btn-sm btn-glow btn-glow-md" data-all aria-pressed="${showAll}">${showAll ? "Embedding models only" : "Show all models"}</button></div>`)}
    </ol>
    <div class="co-setupact"><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-check>${ic(I.retry)}<span>Check again</span></button></div>`;
}

async function click(e) {
  const t = e.target;
  const cp = t.closest("[data-copy]"); if (cp) return copy(cp, cp.dataset.copy);
  if (t.closest("[data-check]")) return refresh();
  if (t.closest("[data-all]")) { showAll = !showAll; return refresh(); }
}
async function change(e) {
  if (e.target.id !== "co-embed" || !e.target.value) return;
  try {
    await api("settings/knowledge", json("PUT", { embedding_model: e.target.value }));
    toast({ message: `Using ${e.target.value}. Indexing starts now.`, ms: 4000 });
  } catch (err) { toast({ message: "Could not save the model: " + err.message, ms: 4500 }); }
  await refresh();
  onChange?.();
}
