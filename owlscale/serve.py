"""Lightweight HTTP service for owlscale task delivery."""

from __future__ import annotations

import json
import socket
import struct
import threading
import zlib as _zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from owlscale.core import TaskError, claim_task, load_roster, load_state
from owlscale.models import Packet, TaskStatus
from owlscale.watch import find_pending_tasks


_ACTIVE_SERVERS: dict[str, tuple[ThreadingHTTPServer, threading.Thread]] = {}


def _serialize_task(task_id: str, packet_path: Path) -> dict:
    packet_markdown = packet_path.read_text() if packet_path.exists() else ""
    goal = ""
    assignee = None
    if packet_markdown:
        packet = Packet.from_markdown(packet_markdown)
        goal = packet.frontmatter.goal
        assignee = packet.frontmatter.assignee

    return {
        "task_id": task_id,
        "packet_path": str(packet_path),
        "assignee": assignee,
        "goal": goal,
        "packet_markdown": packet_markdown,
    }


def pull_tasks(
    owlscale_dir: Path,
    agent_id: str,
    *,
    limit: Optional[int] = None,
    claim: bool = False,
) -> list[dict]:
    """Return pending tasks for an agent, optionally claiming them."""
    pending = find_pending_tasks(owlscale_dir, agent_id)
    if limit is not None:
        pending = pending[:limit]

    tasks = []
    for task_id, packet_path in pending:
        task_data = _serialize_task(task_id, packet_path)
        if claim:
            claim_task(owlscale_dir, task_id)
            task_data["claimed"] = True
        else:
            task_data["claimed"] = False
        tasks.append(task_data)
    return tasks


def _build_handler(owlscale_dir: Path, agent_id: str):
    class OwlscaleServeHandler(BaseHTTPRequestHandler):
        def _write_json(self, status_code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/healthz":
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return

            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "agent_id": agent_id,
                    "workspace": str(owlscale_dir),
                },
            )

        def do_POST(self) -> None:
            if self.path != "/tasks/pull":
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length else b""
            payload = json.loads(raw_body.decode("utf-8") or "{}")

            tasks = pull_tasks(
                owlscale_dir,
                agent_id,
                limit=payload.get("limit"),
                claim=payload.get("claim", False),
            )
            self._write_json(
                HTTPStatus.OK,
                {
                    "agent_id": agent_id,
                    "task_count": len(tasks),
                    "tasks": tasks,
                },
            )

        def log_message(self, format: str, *args) -> None:
            return

    return OwlscaleServeHandler


def create_server(
    owlscale_dir: Path,
    agent_id: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create a configured HTTP server instance."""
    handler = _build_handler(owlscale_dir, agent_id)
    return ThreadingHTTPServer((host, port), handler)


def start_background_server(
    owlscale_dir: Path,
    agent_id: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict:
    """Start the HTTP server in a background thread and return its metadata."""
    server = create_server(owlscale_dir, agent_id, host=host, port=port)
    actual_host, actual_port = server.server_address
    server_id = f"{agent_id}@{actual_host}:{actual_port}"
    if server_id in _ACTIVE_SERVERS:
        server.server_close()
        raise ValueError(f"Server already running: {server_id}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _ACTIVE_SERVERS[server_id] = (server, thread)
    return {
        "server_id": server_id,
        "agent_id": agent_id,
        "host": actual_host,
        "port": actual_port,
        "workspace": str(owlscale_dir),
    }


def stop_background_server(server_id: str) -> dict:
    """Stop a previously started background HTTP server."""
    if server_id not in _ACTIVE_SERVERS:
        raise ValueError(f"Server not running: {server_id}")

    server, thread = _ACTIVE_SERVERS.pop(server_id)
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    return {"server_id": server_id, "stopped": True}


def list_background_servers() -> list[dict]:
    """Return metadata for currently active background HTTP servers."""
    servers = []
    for server_id, (server, _) in sorted(_ACTIVE_SERVERS.items()):
        host, port = server.server_address
        agent_id = server_id.split("@", 1)[0]
        servers.append(
            {
                "server_id": server_id,
                "agent_id": agent_id,
                "host": host,
                "port": port,
            }
        )
    return servers


def serve_agent(
    owlscale_dir: Path,
    agent_id: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the HTTP delivery service in the foreground."""
    server = create_server(owlscale_dir, agent_id, host=host, port=port)
    actual_host, actual_port = server.server_address
    print(f"Serving owlscale push API for '{agent_id}' on http://{actual_host}:{actual_port}")
    print("POST /tasks/pull to receive assigned tasks; GET /healthz for status.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped server.")
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Mobile dashboard (owlscale serve — no --agent required)
# ---------------------------------------------------------------------------


def _make_solid_png(size: int, r: int, g: int, b: int) -> bytes:
    """Generate a minimal valid PNG with a solid color, using stdlib only."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", _zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    scanline = b"\x00" + bytes([r, g, b]) * size
    idat = _zlib.compress(scanline * size, 9)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


ICON_192_PNG: bytes = _make_solid_png(192, 124, 58, 237)  # #7c3aed
ICON_512_PNG: bytes = _make_solid_png(512, 124, 58, 237)  # #7c3aed

_MANIFEST_JSON = json.dumps({
    "name": "owlscale",
    "short_name": "owlscale",
    "description": "Multi-agent AI coordination dashboard",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#1c1c1e",
    "theme_color": "#7c3aed",
    "orientation": "portrait",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}).encode()

_SW_JS = b"""const CACHE = 'owlscale-v1';
const SHELL = ['/'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))));
self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return;
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
"""

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>owlscale</title>
<link rel="manifest" href="/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="owlscale">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="theme-color" content="#1c1c1e">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1c1c1e; color: #fff; font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif; font-size: 16px; }
.container { max-width: 480px; margin: 0 auto; min-height: 100vh; display: flex; flex-direction: column; }
.header { height: 56px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; border-bottom: 1px solid #2c2c2e; }
.logo { color: #7c3aed; font-weight: 700; font-size: 17px; letter-spacing: 0.01em; }
.server-host { color: #8e8e93; font-size: 12px; }
.section-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 16px 8px; }
.section-label { color: #8e8e93; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
.review-badge { background: #ff9f0a; color: #1c1c1e; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
.agent-row { display: flex; align-items: center; justify-content: space-between; padding: 0 16px; min-height: 48px; border-bottom: 1px solid #2c2c2e; }
.agent-left { display: flex; align-items: center; gap: 10px; }
.agent-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.agent-name { font-size: 15px; color: #fff; }
.agent-role { font-size: 13px; color: #8e8e93; }
.task-list { padding: 0 16px 8px; display: flex; flex-direction: column; gap: 8px; }
.task-card { background: #2c2c2e; border-radius: 10px; padding: 12px; }
.task-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.task-badge { font-size: 10px; font-weight: 700; letter-spacing: 0.25px; padding: 3px 8px; border-radius: 999px; }
.task-assignee { font-size: 12px; color: #8e8e93; }
.task-goal { font-size: 12px; color: #fff; margin-bottom: 4px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.task-id-small { font-size: 10px; color: #636366; margin-bottom: 8px; }
.task-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.btn { height: 44px; border-radius: 8px; font-size: 15px; font-weight: 600; border: none; cursor: pointer; transition: opacity 120ms ease; }
.btn:disabled { opacity: 0.5; cursor: default; }
.btn-accept { background: #30d158; color: #1c1c1e; }
.btn-reject { background: transparent; border: 1px solid #ff453a; color: #ff453a; }
.footer { margin-top: auto; text-align: center; padding: 16px; color: #636366; font-size: 12px; border-top: 1px solid #2c2c2e; }
.badge-review   { background: #ff9f0a; color: #1c1c1e; }
.badge-working  { background: #3a3a3c; color: #8e8e93; }
.badge-inprog   { background: #0a84ff; color: #fff; }
.badge-done     { background: #30d158; color: #1c1c1e; }
.badge-rejected { background: #3a3a3c; color: #ff453a; }
.badge-draft    { background: #3a3a3c; color: #8e8e93; }
.empty-hint { color: #636366; font-size: 13px; padding: 8px 16px; }
</style>
</head>
<body>
<div class="container">
  <header class="header">
    <div class="logo">&#11041; owlscale</div>
    <div class="server-host" id="server-host"></div>
  </header>
  <div id="app"><div class="empty-hint">Loading&#8230;</div></div>
  <footer class="footer">owlscale serve &middot; :{{PORT}}</footer>
</div>
<script>
const ROLE_COLORS = { coordinator: '#7c3aed', executor: '#30d158', hub: '#ffd60a' };
const BADGE_MAP = {
  returned:    { cls: 'badge-review',   label: '\\u21a9 REVIEW' },
  dispatched:  { cls: 'badge-working',  label: '\\u27f3 WORKING' },
  in_progress: { cls: 'badge-inprog',   label: '\\u25b6 IN PROG' },
  accepted:    { cls: 'badge-done',     label: '\\u2713 DONE' },
  rejected:    { cls: 'badge-rejected', label: '\\u2717 REJECTED' },
  draft:       { cls: 'badge-draft',    label: '\\u25cb DRAFT' },
};
const STATUS_ORDER = { returned:0, dispatched:1, in_progress:2, draft:3, accepted:4, rejected:5 };

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderState(state) {
  const hostEl = document.getElementById('server-host');
  if (hostEl) hostEl.textContent = window.location.host;

  const tasks   = state.tasks   || [];
  const agents  = state.agents  || [];
  const pending = state.pending_review || 0;
  let html = '';

  html += '<div class="section-header"><span class="section-label">Agents</span></div>';
  if (!agents.length) html += '<div class="empty-hint">No agents registered</div>';
  for (const a of agents) {
    const dot = ROLE_COLORS[a.role] || '#636366';
    html += `<div class="agent-row"><div class="agent-left"><div class="agent-dot" style="background:${dot}"></div><span class="agent-name">${esc(a.name)}</span></div><span class="agent-role">${esc(a.role)}</span></div>`;
  }

  const badge_html = pending > 0 ? `<span class="review-badge">${pending} &#8629;</span>` : '';
  html += `<div class="section-header"><span class="section-label">Tasks</span>${badge_html}</div>`;

  const sorted = [...tasks].sort((a, b) =>
    ((STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)) || a.id.localeCompare(b.id)
  );

  if (!sorted.length) html += '<div class="empty-hint">No tasks</div>';

  html += '<div class="task-list">';
  for (const t of sorted) {
    const badge    = BADGE_MAP[t.status] || { cls: 'badge-draft', label: esc(t.status.toUpperCase()) };
    const assignee = t.assignee || 'unassigned';
    const goalHtml = t.goal
      ? `<div class="task-goal">${esc(t.goal)}</div><div class="task-id-small">${esc(t.id)}</div>`
      : `<div class="task-goal">${esc(t.id)}</div>`;
    const actionsHtml = t.status === 'returned'
      ? `<div class="task-actions"><button class="btn btn-accept" onclick="acceptTask('${esc(t.id)}', this)">Accept</button><button class="btn btn-reject" onclick="rejectTask('${esc(t.id)}', this)">Reject</button></div>`
      : '';
    html += `<div class="task-card"><div class="task-top"><span class="task-badge ${badge.cls}">${badge.label}</span><span class="task-assignee">${esc(assignee)}</span></div>${goalHtml}${actionsHtml}</div>`;
  }
  html += '</div>';
  document.getElementById('app').innerHTML = html;
}

async function refresh() {
  try {
    const r = await fetch('/api/state');
    renderState(await r.json());
  } catch (e) {
    console.error('refresh failed', e);
  }
}

async function _action(url, data, btn) {
  const card = btn.closest('.task-card');
  const btns = card ? card.querySelectorAll('.btn') : [btn];
  btns.forEach(b => { b.disabled = true; });
  btn.textContent = '\\u2026';
  try {
    await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  } finally {
    await refresh();
  }
}

function acceptTask(taskId, btn) { _action('/api/accept', { task_id: taskId }, btn); }
function rejectTask(taskId, btn) { _action('/api/reject', { task_id: taskId, reason: null }, btn); }

setInterval(refresh, 3000);
refresh();
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js'); }
</script>
</body>
</html>"""


def _get_lan_ip() -> str:
    """Return best-guess LAN IP for display in startup banner."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_task_goal(owlscale_dir: Path, task_id: str) -> Optional[str]:
    """Try to read goal from the task packet's YAML frontmatter."""
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"
    if not packet_path.exists():
        return None
    try:
        content = packet_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        end = content.index("---", 3)
        for line in content[3:end].splitlines():
            if line.startswith("goal:"):
                raw = line[5:].strip().strip("'\"")
                return raw or None
    except Exception:
        return None
    return None


def _build_state_json(owlscale_dir: Path) -> dict:
    """Build the /api/state payload from .owlscale/ data files."""
    state = load_state(owlscale_dir)
    roster = load_roster(owlscale_dir)

    pending_review = 0
    tasks = []
    for task_id, task_state in sorted(state.tasks.items()):
        if task_state.status == TaskStatus.returned:
            pending_review += 1
        tasks.append({
            "id": task_id,
            "status": task_state.status.value,
            "assignee": task_state.assignee,
            "goal": _get_task_goal(owlscale_dir, task_id),
        })

    agents = [
        {"id": agent_id, "name": agent.name, "role": agent.role.value}
        for agent_id, agent in sorted(roster.items())
    ]

    return {"tasks": tasks, "agents": agents, "pending_review": pending_review}


def make_handler(owlscale_dir: Path, port: int):
    """Return a BaseHTTPRequestHandler class for the mobile dashboard."""

    class OwlscaleDashboardHandler(BaseHTTPRequestHandler):
        _owlscale_dir = owlscale_dir
        _port = port

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._serve_html()
            elif path == "/api/state":
                self._serve_state()
            elif path == "/manifest.json":
                self._write_response(200, "application/manifest+json", _MANIFEST_JSON)
            elif path == "/sw.js":
                self._write_response(200, "application/javascript; charset=utf-8", _SW_JS)
            elif path == "/icon-192.png":
                self._write_response(200, "image/png", ICON_192_PNG)
            elif path == "/icon-512.png":
                self._write_response(200, "image/png", ICON_512_PNG)
            else:
                self.send_error(404, "Not Found")

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/accept":
                self._handle_action("accept")
            elif path == "/api/reject":
                self._handle_action("reject")
            else:
                self.send_error(404, "Not Found")

        def _serve_html(self):
            html = HTML_DASHBOARD.replace("{{PORT}}", str(self._port))
            body = html.encode("utf-8")
            self._write_response(200, "text/html; charset=utf-8", body)

        def _serve_state(self):
            try:
                data = _build_state_json(self._owlscale_dir)
                self._write_response(200, "application/json", json.dumps(data).encode())
            except Exception as exc:
                self._write_response(500, "application/json", json.dumps({"error": str(exc)}).encode())

        def _handle_action(self, action: str):
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw)
                task_id = body.get("task_id", "")
                reason = body.get("reason") or ""
                if not task_id:
                    self._write_response(400, "application/json", b'{"error":"task_id required"}')
                    return
                if action == "accept":
                    from owlscale.core import accept_task as _accept
                    _accept(self._owlscale_dir, task_id)
                else:
                    from owlscale.core import reject_task as _reject
                    _reject(self._owlscale_dir, task_id, reason)
                self._write_response(200, "application/json", b'{"ok":true}')
            except TaskError as exc:
                self._write_response(400, "application/json", json.dumps({"error": str(exc)}).encode())
            except Exception as exc:
                self._write_response(500, "application/json", json.dumps({"error": str(exc)}).encode())

        def _write_response(self, code: int, content_type: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # suppress default stderr log
            pass

    return OwlscaleDashboardHandler


def run_server(host: str, port: int, owlscale_dir: Path) -> None:
    """Start the mobile dashboard HTTP server (blocking)."""
    lan_ip = _get_lan_ip()
    handler = make_handler(owlscale_dir, port)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"owlscale serve → http://{lan_ip}:{port}")
    print(f"  workspace: {owlscale_dir.parent}")
    print("  Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

