// The update notice: when the server knows a newer release exists (GET /api/update, answered from its stored result; the server asks GitHub
// at most once a day and Settings > Updates switches it off), show a toast once per new version and a quiet badge on the version line of the
// account menu. It only tells: updating is the user's own two commands. Plain DOM; nothing here talks to the internet itself.
import { toast } from "./toast.js";
import { COPY_ICONS, copy } from "./editor.js";

const DOCKER = ["docker compose pull", "docker compose up -d"];
const SOURCE = ["git pull", "./run.sh"];

async function check() {
  let u;
  try { u = await (await fetch("/api/update")).json(); } catch { return; }
  if (!u || !u.enabled || !u.newer) return;
  const badge = () => {   // the badge stays until the user updates; the menu line already links to Settings > About
    const v = document.querySelector("#account-version");
    if (!v || v.hidden || v.querySelector(".acct-ver-new")) return;
    const mark = document.createElement("span");
    mark.className = "acct-ver-new";
    mark.textContent = `v${u.latest} available`;
    v.append(" · ", mark);
    v.classList.add("has-update");
    v.title = `FlowlyStack v${u.latest} is available`;
  };
  badge();
  addEventListener("flowlystack-version", badge);   // account.js writes the version line after its own fetch and says so; the badge goes on again
  if (u.dismissed) return;
  const cmds = u.in_docker ? DOCKER : SOURCE;
  const node = document.createElement("div");
  node.className = "cb-toast-cmds";
  node.innerHTML = `<div class="cb-toast-hint">${u.in_docker ? "In a terminal, in your install folder, run" : "In a terminal, in the FlowlyStack folder, run"}</div>`;
  const row = document.createElement("div");
  row.className = "cb-toast-row";
  const code = document.createElement("code");
  code.textContent = cmds.join("\n");
  const b = document.createElement("button");
  b.type = "button";
  b.className = "btn btn-sm btn-glow";
  b.innerHTML = `${COPY_ICONS}<span>Copy</span>`;
  b.addEventListener("click", () => copy(b, cmds.join("\n")));
  row.append(code, b);
  node.append(row);
  toast({ message: `Update available: FlowlyStack ${u.latest} (you have ${u.current}).`, node, action: "What's new", onAction: () => { location.hash = "#/whatsnew"; }, ms: 30000 });
  fetch("/api/update/dismiss", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: u.latest }) }).catch(() => {});   // once per version
}

check();
