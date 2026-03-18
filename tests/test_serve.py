"""Tests for owlscale serve helpers."""

import json
import queue
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, ThreadingHTTPServer
from pathlib import Path

import pytest

from owlscale.core import add_agent, dispatch_task, get_status, init_project, pack_task, return_task
from owlscale.serve import (
    _build_state_json,
    _get_task_goal,
    create_server,
    make_handler,
    pull_tasks,
)


@pytest.fixture()
def workspace(tmp_path):
    return init_project(tmp_path)


def _dispatch(workspace: Path, task_id: str, agent_id: str, goal: str = "Ship feature"):
    pack_task(workspace, task_id, goal)
    dispatch_task(workspace, task_id, agent_id)


class TestPullTasks:
    def test_pull_tasks_returns_assigned_packet_data(self, workspace):
        add_agent(workspace, "serve-bot", "Serve Bot", "executor")
        _dispatch(workspace, "serve-001", "serve-bot", goal="Implement push mode")

        tasks = pull_tasks(workspace, "serve-bot")

        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "serve-001"
        assert tasks[0]["goal"] == "Implement push mode"
        assert tasks[0]["assignee"] == "serve-bot"
        assert tasks[0]["claimed"] is False

    def test_pull_tasks_can_claim(self, workspace):
        add_agent(workspace, "serve-bot", "Serve Bot", "executor")
        _dispatch(workspace, "serve-001", "serve-bot")

        tasks = pull_tasks(workspace, "serve-bot", claim=True)
        state = get_status(workspace)

        assert len(tasks) == 1
        assert tasks[0]["claimed"] is True
        assert state.tasks["serve-001"].status.value == "in_progress"


class TestServeHttp:
    def test_http_pull_endpoint_returns_tasks(self, workspace):
        add_agent(workspace, "serve-bot", "Serve Bot", "executor")
        _dispatch(workspace, "serve-001", "serve-bot", goal="Implement push mode")

        server = create_server(workspace, "serve-bot", port=0)
        host, port = server.server_address
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        try:
            thread.start()
            body = json.dumps({"claim": True}).encode("utf-8")
            request = urllib.request.Request(
                f"http://{host}:{port}/tasks/pull",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read())

            assert payload["agent_id"] == "serve-bot"
            assert payload["task_count"] == 1
            assert payload["tasks"][0]["task_id"] == "serve-001"
            assert payload["tasks"][0]["claimed"] is True
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_healthz_reports_ok(self, workspace):
        add_agent(workspace, "serve-bot", "Serve Bot", "executor")

        server = create_server(workspace, "serve-bot", port=0)
        host, port = server.server_address
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        try:
            thread.start()
            with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=5) as response:
                payload = json.loads(response.read())

            assert payload["status"] == "ok"
            assert payload["agent_id"] == "serve-bot"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Dashboard tests (make_handler / _build_state_json API)
# ---------------------------------------------------------------------------


def _setup_workspace_with_returned_task(workspace: Path, task_id: str, agent_id: str, goal: str = "Fix the bug"):
    """Pack → dispatch → return a task so status == 'returned'."""
    from owlscale.core import AgentError
    try:
        add_agent(workspace, agent_id, agent_id.title(), "executor")
    except AgentError:
        pass  # already registered; safe to reuse
    pack_task(workspace, task_id, goal)
    dispatch_task(workspace, task_id, agent_id)
    return_task(workspace, task_id)


def _http_post(url: str, data: dict) -> tuple:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class TestDashboardHandler:
    """Tests for the mobile dashboard make_handler API."""

    @pytest.fixture()
    def dashboard_workspace(self, tmp_path):
        ws = init_project(tmp_path)
        _setup_workspace_with_returned_task(ws, "task-alpha", "bot-a", "Implement JWT auth")
        return ws

    @pytest.fixture()
    def live_server(self, dashboard_workspace):
        handler = make_handler(dashboard_workspace, 0)
        server = HTTPServer(("127.0.0.1", 0), handler)
        host, port = server.server_address
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        yield host, port, dashboard_workspace
        server.shutdown()
        server.server_close()
        t.join(timeout=2)

    def test_html_returns_200_with_owlscale_branding(self, live_server):
        host, port, _ = live_server
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as r:
            status = r.status
            body = r.read()
            ct = r.headers.get("Content-Type", "")
        assert status == 200
        assert b"owlscale" in body
        assert "text/html" in ct

    def test_api_state_returns_valid_json(self, live_server):
        host, port, _ = live_server
        with urllib.request.urlopen(f"http://{host}:{port}/api/state", timeout=5) as r:
            data = json.loads(r.read())
        assert "tasks" in data and "agents" in data and "pending_review" in data
        assert data["pending_review"] == 1
        task = next(t for t in data["tasks"] if t["id"] == "task-alpha")
        assert task["status"] == "returned"
        assert task["assignee"] == "bot-a"

    def test_api_accept_transitions_task_to_accepted(self, live_server):
        host, port, ws = live_server
        code, body = _http_post(f"http://{host}:{port}/api/accept", {"task_id": "task-alpha"})
        assert code == 200
        assert json.loads(body) == {"ok": True}
        data = _build_state_json(ws)
        task = next(t for t in data["tasks"] if t["id"] == "task-alpha")
        assert task["status"] == "accepted"

    def test_api_events_streams_state_updates(self, dashboard_workspace):
        handler = make_handler(dashboard_workspace, 0)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        host, port = server.server_address
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        events: "queue.Queue[dict]" = queue.Queue()

        def _reader():
            seen = 0
            with urllib.request.urlopen(f"http://{host}:{port}/api/events", timeout=5) as response:
                assert "text/event-stream" in response.headers.get("Content-Type", "")
                while True:
                    line = response.readline().decode("utf-8").strip()
                    if line.startswith("data: "):
                        events.put(json.loads(line[6:]))
                        seen += 1
                        if seen >= 2:
                            break

        reader = threading.Thread(target=_reader, daemon=True)
        try:
            thread.start()
            reader.start()

            initial = events.get(timeout=5)
            assert initial["pending_review"] == 1

            code, body = _http_post(f"http://{host}:{port}/api/accept", {"task_id": "task-alpha"})
            assert code == 200
            assert json.loads(body) == {"ok": True}

            updated = events.get(timeout=5)
            task = next(t for t in updated["tasks"] if t["id"] == "task-alpha")
            assert updated["pending_review"] == 0
            assert task["status"] == "accepted"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            reader.join(timeout=2)

    def test_html_contains_pwa_and_refresh_button(self, live_server):
        host, port, _ = live_server
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as r:
            body = r.read()
        assert b'rel="manifest"' in body
        assert b'refresh-btn' in body

    def test_api_reject_returns_400_for_non_returned_task(self, dashboard_workspace):
        pack_task(dashboard_workspace, "task-beta", "Another task")
        dispatch_task(dashboard_workspace, "task-beta", "bot-a")
        handler = make_handler(dashboard_workspace, 0)
        server = HTTPServer(("127.0.0.1", 0), handler)
        host, port = server.server_address
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            code, _ = _http_post(f"http://{host}:{port}/api/reject", {"task_id": "task-beta"})
            assert code == 400
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=2)


class TestBuildStateJson:
    def test_returns_all_sections(self, tmp_path):
        ws = init_project(tmp_path)
        data = _build_state_json(ws)
        assert set(data.keys()) >= {"tasks", "agents", "pending_review"}
        assert data["pending_review"] == 0

    def test_pending_review_counts_returned_tasks(self, tmp_path):
        ws = init_project(tmp_path)
        _setup_workspace_with_returned_task(ws, "t1", "agent-x")
        _setup_workspace_with_returned_task(ws, "t2", "agent-x")
        data = _build_state_json(ws)
        assert data["pending_review"] == 2

    def test_task_goal_read_from_packet_frontmatter(self, tmp_path):
        ws = init_project(tmp_path)
        _setup_workspace_with_returned_task(ws, "t-goal", "agent-y", goal="Deploy the service")
        data = _build_state_json(ws)
        task = next(t for t in data["tasks"] if t["id"] == "t-goal")
        assert task["goal"] == "Deploy the service"


class TestGetTaskGoal:
    def test_reads_goal_from_packet(self, tmp_path):
        ws = init_project(tmp_path)
        pack_task(ws, "mytest", "Clean up the DB")
        assert _get_task_goal(ws, "mytest") == "Clean up the DB"

    def test_returns_none_for_missing_packet(self, tmp_path):
        ws = init_project(tmp_path)
        assert _get_task_goal(ws, "nonexistent") is None


class TestPWARoutes:
    """Tests for PWA manifest and service worker routes."""

    @pytest.fixture()
    def live_server(self, tmp_path):
        ws = init_project(tmp_path)
        handler = make_handler(ws, 0)
        server = HTTPServer(("127.0.0.1", 0), handler)
        host, port = server.server_address
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        yield host, port
        server.shutdown()
        server.server_close()
        t.join(timeout=2)

    def test_manifest_json_returns_valid_json_with_name(self, live_server):
        host, port = live_server
        with urllib.request.urlopen(f"http://{host}:{port}/manifest.json", timeout=5) as r:
            assert r.status == 200
            data = json.loads(r.read())
        assert data["name"] == "owlscale"
        assert data["display"] == "standalone"

    def test_sw_js_returns_200(self, live_server):
        host, port = live_server
        with urllib.request.urlopen(f"http://{host}:{port}/sw.js", timeout=5) as r:
            assert r.status == 200
            body = r.read()
        assert b"owlscale-v1" in body
