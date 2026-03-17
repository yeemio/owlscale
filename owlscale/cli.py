"""CLI entry point for owlscale."""

import sys
import argparse
import json
from pathlib import Path

from owlscale import __version__
from owlscale.core import (
    OwlscaleError, get_workspace_root, init_project, add_agent, remove_agent,
    list_agents, pack_task, dispatch_task, claim_task, return_task, accept_task,
    reject_task, get_status, get_log
)
from owlscale.export import export_training_data
from owlscale.models import TaskStatus
from owlscale.watch import watch_once, watch_poll


def _maybe_fire_webhook(owlscale_dir: Path, event: dict) -> None:
    """Fire webhook event if a URL is configured. Non-fatal."""
    try:
        from owlscale.webhook import get_webhook, fire
        url = get_webhook(owlscale_dir)
        if url:
            fire(url, event)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: webhook delivery failed: {exc}", file=sys.stderr)


def _refresh_context_safe(owlscale_dir: Path, agent_id: str) -> None:
    """Refresh an agent's context file. Non-fatal."""
    try:
        from owlscale.identity import refresh_agent_context
        refresh_agent_context(owlscale_dir, agent_id)
    except Exception:  # noqa: BLE001
        pass


def _refresh_all_contexts_safe(owlscale_dir: Path) -> None:
    """Refresh all agents' context files. Non-fatal."""
    try:
        from owlscale.identity import refresh_all_contexts
        refresh_all_contexts(owlscale_dir)
    except Exception:  # noqa: BLE001
        pass


def main():
    parser = argparse.ArgumentParser(
        prog="owlscale",
        description="File-level agent collaboration protocol CLI",
    )
    parser.add_argument("--version", action="version", version=f"owlscale {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize .owlscale/ directory")
    init_parser.add_argument(
        "--register-defaults", action="store_true",
        help="Auto-detect AI agents (CC, Copilot, Cursor, etc.) and register them",
    )
    init_parser.add_argument(
        "--name", metavar="PROJECT_NAME",
        help="Set project name (stored in .owlscale/config.json)",
    )
    init_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Accept all defaults without prompting (for CI/scripted use)",
    )
    init_parser.add_argument(
        "--no-launch", action="store_true",
        help="Skip opening terminal windows for agents",
    )
    init_parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing .owlscale/ directory without confirmation",
    )
    init_parser.set_defaults(func=cmd_init)

    # roster
    roster_parser = subparsers.add_parser("roster", help="Manage agent roster")
    roster_subs = roster_parser.add_subparsers(dest="roster_cmd")

    roster_add = roster_subs.add_parser("add", help="Register an agent")
    roster_add.add_argument("agent_id", help="Agent ID")
    roster_add.add_argument("--name", required=True, help="Agent name")
    roster_add.add_argument("--role", required=True, choices=["coordinator", "executor", "hub"], help="Agent role")
    roster_add.set_defaults(func=cmd_roster_add)

    roster_list = roster_subs.add_parser("list", help="List registered agents")
    roster_list.set_defaults(func=cmd_roster_list)

    roster_remove = roster_subs.add_parser("remove", help="Unregister an agent")
    roster_remove.add_argument("agent_id", help="Agent ID")
    roster_remove.set_defaults(func=cmd_roster_remove)

    # pack
    pack_parser = subparsers.add_parser("pack", help="Create a Context Packet")
    pack_parser.add_argument("task_id", help="Task ID")
    pack_parser.add_argument("--goal", required=True, help="Task goal")
    pack_parser.add_argument("--tags", help="Comma-separated tags")
    pack_parser.add_argument("--parent", help="Parent task ID")
    pack_parser.add_argument("--template", help="Template name to pre-fill sections")
    pack_parser.set_defaults(func=cmd_pack)

    # template
    tmpl_parser = subparsers.add_parser("template", help="Manage reusable packet templates")
    tmpl_subs = tmpl_parser.add_subparsers(dest="template_cmd")

    tmpl_list = tmpl_subs.add_parser("list", help="List available templates")
    tmpl_list.set_defaults(func=cmd_template_list)

    tmpl_show = tmpl_subs.add_parser("show", help="Print template body")
    tmpl_show.add_argument("name", help="Template name")
    tmpl_show.set_defaults(func=cmd_template_show)

    tmpl_add = tmpl_subs.add_parser("add", help="Add template from file")
    tmpl_add.add_argument("name", help="Template name")
    tmpl_add.add_argument("--file", required=True, help="Path to Markdown file")
    tmpl_add.set_defaults(func=cmd_template_add)

    tmpl_remove = tmpl_subs.add_parser("remove", help="Remove a user-defined template")
    tmpl_remove.add_argument("name", help="Template name")
    tmpl_remove.set_defaults(func=cmd_template_remove)

    # dispatch
    dispatch_parser = subparsers.add_parser("dispatch", help="Dispatch task to agent")
    dispatch_parser.add_argument("task_id", help="Task ID")
    dispatch_parser.add_argument("agent_id", help="Agent ID")
    dispatch_parser.add_argument("--git", action="store_true", help="Auto-create git branch <agent>/<task-id>")
    dispatch_parser.set_defaults(func=cmd_dispatch)

    # claim
    claim_parser = subparsers.add_parser("claim", help="Claim a dispatched task")
    claim_parser.add_argument("task_id", help="Task ID")
    claim_parser.set_defaults(func=cmd_claim)

    # return
    return_parser = subparsers.add_parser("return", help="Mark task as returned")
    return_parser.add_argument("task_id", help="Task ID")
    return_parser.set_defaults(func=cmd_return)

    # accept
    accept_parser = subparsers.add_parser("accept", help="Accept a returned task")
    accept_parser.add_argument("task_id", help="Task ID")
    accept_parser.set_defaults(func=cmd_accept)

    # reject
    reject_parser = subparsers.add_parser("reject", help="Reject a returned task")
    reject_parser.add_argument("task_id", help="Task ID")
    reject_parser.add_argument("--reason", default="", help="Rejection reason")
    reject_parser.set_defaults(func=cmd_reject)

    # status
    status_parser = subparsers.add_parser("status", help="Show global task status")
    status_parser.set_defaults(func=cmd_status)

    # log
    log_parser = subparsers.add_parser("log", help="Show operation log")
    log_parser.add_argument("--task", help="Filter by task ID")
    log_parser.add_argument("-n", "--limit", type=int, help="Limit number of entries")
    log_parser.set_defaults(func=cmd_log)

    # validate
    validate_parser = subparsers.add_parser("validate", help="Check packet completeness")
    validate_parser.add_argument("task_id", help="Task ID")
    validate_parser.set_defaults(func=cmd_validate)

    # fmt
    fmt_parser = subparsers.add_parser("fmt", help="Format a packet")
    fmt_parser.add_argument("task_id", help="Task ID")
    fmt_parser.add_argument("--check", action="store_true", help="Exit 1 if not formatted")
    fmt_parser.add_argument("--dry-run", action="store_true", help="Print formatted output without writing")
    fmt_parser.set_defaults(func=cmd_fmt)

    # export
    export_parser = subparsers.add_parser("export", help="Export training data as JSONL")
    export_parser.add_argument("--output", help="Output file path (default: stdout)")
    export_parser.add_argument(
        "--status",
        choices=["accepted", "rejected", "all"],
        default="all",
        help="Filter by outcome",
    )
    export_parser.set_defaults(func=cmd_export)

    # watch
    watch_parser = subparsers.add_parser("watch", help="Watch for dispatched tasks")
    watch_parser.add_argument("--agent", required=True, help="Agent ID to watch for")
    watch_parser.add_argument("--once", action="store_true", help="Check once and exit (default)")
    watch_parser.add_argument("--poll", type=int, help="Continuous polling interval in seconds")
    watch_parser.set_defaults(func=cmd_watch)

    # serve
    serve_parser = subparsers.add_parser("serve", help="Run lightweight HTTP task delivery service")
    serve_parser.add_argument("--agent", required=True, help="Agent ID to serve for")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    serve_parser.set_defaults(func=cmd_serve)

    # review
    review_parser = subparsers.add_parser("review", help="Review a Return Packet against Expected Output")
    review_parser.add_argument("task_id", help="Task ID")
    review_parser.add_argument("--json", action="store_true", dest="as_json", help="Output review as JSON")
    review_parser.set_defaults(func=cmd_review)

    # mcp server
    mcp_parser = subparsers.add_parser("mcp-server", help="Run owlscale as an MCP stdio server")
    mcp_parser.set_defaults(func=cmd_mcp_server)

    # route
    route_parser = subparsers.add_parser("route", help="Auto-route task to best agent")
    route_parser.add_argument("task_id", help="Task ID")
    route_parser.add_argument("--dispatch", action="store_true", help="Auto-dispatch to top candidate")
    route_parser.add_argument("-n", "--top", type=int, default=3, help="Number of candidates to show")
    route_parser.set_defaults(func=cmd_route)

    # diff
    diff_parser = subparsers.add_parser("diff", help="Compare two packet versions")
    diff_parser.add_argument("task_id_a", help="First task ID")
    diff_parser.add_argument("task_id_b", help="Second task ID")
    diff_parser.add_argument("-C", "--context", type=int, default=3, help="Context lines")
    diff_parser.set_defaults(func=cmd_diff)

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show flywheel metrics")
    stats_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    stats_parser.set_defaults(func=cmd_stats)

    # prune
    prune_parser = subparsers.add_parser("prune", help="Archive old completed tasks")
    prune_parser.add_argument("--days", type=int, default=30, help="Archive tasks completed more than N days ago (default: 30)")
    prune_parser.add_argument("--dry-run", action="store_true", help="Show candidates without making changes")
    prune_parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    prune_parser.set_defaults(func=cmd_prune)

    # git
    git_parser = subparsers.add_parser("git", help="Git workflow integration")
    git_subs = git_parser.add_subparsers(dest="git_cmd")

    git_branch = git_subs.add_parser("branch", help="Show or create branch for a task")
    git_branch.add_argument("task_id", help="Task ID")
    git_branch.set_defaults(func=cmd_git_branch)

    git_pr = git_subs.add_parser("pr", help="Print gh pr create command for a task")
    git_pr.add_argument("task_id", help="Task ID")
    git_pr.add_argument("--base", default="main", help="Base branch (default: main)")
    git_pr.set_defaults(func=cmd_git_pr)

    git_status = git_subs.add_parser("status", help="Show task-to-branch mapping for open tasks")
    git_status.set_defaults(func=cmd_git_status)

    # flywheel
    flywheel_parser = subparsers.add_parser("flywheel", help="Convert export JSONL into SFT/DPO training data")
    flywheel_subs = flywheel_parser.add_subparsers(dest="flywheel_cmd")

    fw_prepare = flywheel_subs.add_parser("prepare", help="Generate training dataset from export JSONL")
    fw_prepare.add_argument("input", help="Path to export JSONL file")
    fw_prepare.add_argument("--format", choices=["sft", "dpo", "both"], default="sft", dest="fmt", help="Output format (default: sft)")
    fw_prepare.add_argument("--output", default=".", help="Output directory (default: .)")
    fw_prepare.set_defaults(func=cmd_flywheel_prepare)

    fw_stats = flywheel_subs.add_parser("stats", help="Print statistics for export JSONL")
    fw_stats.add_argument("input", help="Path to export JSONL file")
    fw_stats.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    fw_stats.set_defaults(func=cmd_flywheel_stats)

    # hub
    hub_parser = subparsers.add_parser("hub", help="Local LLM coordinator")
    hub_subs = hub_parser.add_subparsers(dest="hub_cmd")

    hub_route_p = hub_subs.add_parser("route", help="Ask LLM to recommend an agent for a task")
    hub_route_p.add_argument("task_id", help="Task ID")
    hub_route_p.add_argument("--model", default="Qwen3.5-35B-A3B", help="Model name")
    hub_route_p.add_argument("--endpoint", default="http://127.0.0.1:8009/v1", help="LLM endpoint base URL")
    hub_route_p.set_defaults(func=cmd_hub_route)

    hub_draft_p = hub_subs.add_parser("draft", help="Ask LLM to draft a Context Packet body")
    hub_draft_p.add_argument("task_id", help="Task ID")
    hub_draft_p.add_argument("--model", default="Qwen3.5-35B-A3B", help="Model name")
    hub_draft_p.add_argument("--endpoint", default="http://127.0.0.1:8009/v1", help="LLM endpoint base URL")
    hub_draft_p.set_defaults(func=cmd_hub_draft)

    hub_ask_p = hub_subs.add_parser("ask", help="Send an arbitrary prompt to the local LLM")
    hub_ask_p.add_argument("prompt", help="Prompt text")
    hub_ask_p.add_argument("--model", default="Qwen3.5-35B-A3B", help="Model name")
    hub_ask_p.add_argument("--endpoint", default="http://127.0.0.1:8009/v1", help="LLM endpoint base URL")
    hub_ask_p.set_defaults(func=cmd_hub_ask)

    # snapshot
    snap_parser = subparsers.add_parser("snapshot", help="Save/restore state.json snapshots")
    snap_subs = snap_parser.add_subparsers(dest="snap_cmd")

    snap_save = snap_subs.add_parser("save", help="Save current state.json as a snapshot")
    snap_save.add_argument("--name", help="Snapshot name (default: auto-generated from timestamp)")
    snap_save.set_defaults(func=cmd_snapshot_save)

    snap_list = snap_subs.add_parser("list", help="List available snapshots")
    snap_list.set_defaults(func=cmd_snapshot_list)

    snap_restore = snap_subs.add_parser("restore", help="Restore state.json from a snapshot")
    snap_restore.add_argument("name", help="Snapshot name to restore")
    snap_restore.set_defaults(func=cmd_snapshot_restore)

    snap_diff = snap_subs.add_parser("diff", help="Diff two snapshots")
    snap_diff.add_argument("name_a", help="First snapshot name")
    snap_diff.add_argument("name_b", help="Second snapshot name")
    snap_diff.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    snap_diff.set_defaults(func=cmd_snapshot_diff)

    # notify
    notify_parser = subparsers.add_parser("notify", help="Deliver pending notifications")
    notify_parser.add_argument("--webhook", metavar="URL", help="POST notifications to this URL")
    notify_parser.add_argument("--list", action="store_true", dest="list_only", help="List pending without delivering")
    notify_parser.set_defaults(func=cmd_notify)
    # batch
    batch_parser = subparsers.add_parser("batch", help="Create multiple tasks from a YAML spec")
    batch_subs = batch_parser.add_subparsers(dest="batch_cmd")

    batch_pack_p = batch_subs.add_parser("pack", help="Pack tasks from YAML spec file")
    batch_pack_p.add_argument("spec", help="Path to YAML spec file")
    batch_pack_p.set_defaults(func=cmd_batch_pack)
    # lint
    lint_parser = subparsers.add_parser("lint", help="Run comprehensive quality checks on a packet")
    lint_parser.add_argument("task_id", nargs="?", help="Task ID (omit with --all)")
    lint_parser.add_argument("--all", action="store_true", dest="lint_all", help="Lint all tasks")
    lint_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    lint_parser.set_defaults(func=cmd_lint)
    # alias
    alias_parser = subparsers.add_parser("alias", help="Manage Agent ID aliases")
    alias_subs = alias_parser.add_subparsers(dest="alias_cmd")

    alias_set = alias_subs.add_parser("set", help="Set an alias")
    alias_set.add_argument("alias", help="Alias name")
    alias_set.add_argument("agent_id", help="Target agent ID")
    alias_set.set_defaults(func=cmd_alias_set)

    alias_list = alias_subs.add_parser("list", help="List all aliases")
    alias_list.set_defaults(func=cmd_alias_list)

    alias_remove = alias_subs.add_parser("remove", help="Remove an alias")
    alias_remove.add_argument("alias", help="Alias to remove")
    alias_remove.set_defaults(func=cmd_alias_remove)
    # history
    history_parser = subparsers.add_parser("history", help="Show complete task event timeline")
    history_parser.add_argument("task_id", help="Task ID")
    history_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    history_parser.set_defaults(func=cmd_history)

    # whoami
    whoami_parser = subparsers.add_parser("whoami", help="Print agent context file")
    whoami_parser.add_argument("agent_id", nargs="?", help="Agent ID to show context for")
    whoami_parser.add_argument("--all", action="store_true", dest="all_agents",
                               help="Refresh and list context files for all agents")
    whoami_parser.set_defaults(func=cmd_whoami)

    # daemon
    daemon_parser = subparsers.add_parser("daemon", help="Background task monitor")
    daemon_subs = daemon_parser.add_subparsers(dest="daemon_cmd")

    daemon_run = daemon_subs.add_parser("run", help="Run daemon in foreground")
    daemon_run.add_argument("--poll", type=float, default=1.0, metavar="SECS",
                            help="Poll interval in seconds (default: 1.0)")
    daemon_run.add_argument("--drive-shell", action="store_true",
                            help="Also drive terminal adapters (Ghostty, tmux)")
    daemon_run.set_defaults(func=cmd_daemon_run)

    daemon_start = daemon_subs.add_parser("start", help="Start daemon in background")
    daemon_start.add_argument("--poll", type=float, default=1.0, metavar="SECS",
                              help="Poll interval in seconds (default: 1.0)")
    daemon_start.add_argument("--drive-shell", action="store_true",
                              help="Also drive terminal adapters")
    daemon_start.set_defaults(func=cmd_daemon_start)

    daemon_stop = daemon_subs.add_parser("stop", help="Stop background daemon")
    daemon_stop.set_defaults(func=cmd_daemon_stop)

    daemon_status_p = daemon_subs.add_parser("status", help="Show daemon status")
    daemon_status_p.set_defaults(func=cmd_daemon_status)

    daemon_logs = daemon_subs.add_parser("logs", help="Show daemon log")
    daemon_logs.add_argument("-n", type=int, default=50, help="Number of lines (default: 50)")
    daemon_logs.set_defaults(func=cmd_daemon_logs)

    # demo
    demo_parser = subparsers.add_parser("demo", help="Run a self-contained owlscale walkthrough")
    demo_parser.add_argument("--fast", action="store_true", help="Skip animation delays")
    demo_parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    demo_parser.set_defaults(func=cmd_demo)

    # schema
    schema_parser = subparsers.add_parser("schema", help="Validate workspace schema")
    schema_subs = schema_parser.add_subparsers(dest="schema_cmd")
    schema_check = schema_subs.add_parser("check", help="Validate state.json against schema")
    schema_check.set_defaults(func=cmd_schema_check)

    # config
    config_parser = subparsers.add_parser("config", help="Manage .owlscale/config.toml project settings")
    config_subs = config_parser.add_subparsers(dest="config_cmd")
    config_get = config_subs.add_parser("get", help="Get a config value")
    config_get.add_argument("key", help="Dot-notation key (e.g. hub.endpoint)")
    config_get.set_defaults(func=cmd_config_get)
    config_set = config_subs.add_parser("set", help="Set a config value")
    config_set.add_argument("key", help="Dot-notation key")
    config_set.add_argument("value", help="Value to set")
    config_set.set_defaults(func=cmd_config_set)
    config_list = config_subs.add_parser("list", help="List all config values")
    config_list.set_defaults(func=cmd_config_list)

    # search
    search_parser = subparsers.add_parser("search", help="Full-text search across packets and returns")
    search_parser.add_argument("query", help="Search query (literal string)")
    search_parser.add_argument("--case-sensitive", action="store_true", help="Case-sensitive search")
    search_parser.add_argument("--packets", action="store_true", help="Search only packets (default: both)")
    search_parser.add_argument("--returns", action="store_true", help="Search only returns (default: both)")
    search_parser.set_defaults(func=cmd_search)

    # tag
    tag_parser = subparsers.add_parser("tag", help="Manage task tags")
    tag_subs = tag_parser.add_subparsers(dest="tag_cmd")
    tag_list = tag_subs.add_parser("list", help="List all tags and their tasks")
    tag_list.set_defaults(func=cmd_tag_list)
    tag_filter = tag_subs.add_parser("filter", help="List tasks with a given tag")
    tag_filter.add_argument("tag", help="Tag to filter by")
    tag_filter.set_defaults(func=cmd_tag_filter)
    tag_add = tag_subs.add_parser("add", help="Add a tag to a task")
    tag_add.add_argument("task_id", help="Task ID")
    tag_add.add_argument("tag", help="Tag to add")
    tag_add.set_defaults(func=cmd_tag_add)
    tag_remove = tag_subs.add_parser("remove", help="Remove a tag from a task")
    tag_remove.add_argument("task_id", help="Task ID")
    tag_remove.add_argument("tag", help="Tag to remove")
    tag_remove.set_defaults(func=cmd_tag_remove)

    # timeline
    timeline_parser = subparsers.add_parser("timeline", help="Show cross-task event timeline")
    timeline_parser.add_argument("--since", metavar="YYYY-MM-DD", help="Show events on or after this date")
    timeline_parser.add_argument("--until", metavar="YYYY-MM-DD", help="Show events on or before this date")
    timeline_parser.add_argument("--task", metavar="ID", action="append", dest="task_ids",
                                 help="Filter to specific task (repeatable)")
    timeline_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    timeline_parser.set_defaults(func=cmd_timeline)

    # repair
    repair_parser = subparsers.add_parser("repair", help="Detect and repair workspace inconsistencies")
    repair_parser.add_argument("--dry-run", action="store_true", default=False,
                               help="Report issues without writing (default behavior)")
    repair_parser.add_argument("--force", action="store_true",
                               help="Apply repairs (overrides --dry-run)")
    repair_parser.set_defaults(func=cmd_repair)

    # pin / unpin
    pin_parser = subparsers.add_parser("pin", help="Pin a task or list pinned tasks")
    pin_parser.add_argument("task_id", nargs="?", help="Task ID to pin (omit to list pinned tasks)")
    pin_parser.add_argument("--list", action="store_true", dest="list_pins", help="List all pinned tasks")
    pin_parser.set_defaults(func=cmd_pin)
    unpin_parser = subparsers.add_parser("unpin", help="Unpin a task")
    unpin_parser.add_argument("task_id", help="Task ID to unpin")
    unpin_parser.set_defaults(func=cmd_unpin)

    # checkpoint
    ckpt_parser = subparsers.add_parser("checkpoint", help="Save and restore workspace checkpoints")
    ckpt_subs = ckpt_parser.add_subparsers(dest="ckpt_cmd")
    ckpt_save = ckpt_subs.add_parser("save", help="Create a checkpoint archive")
    ckpt_save.add_argument("--name", help="Checkpoint name (default: timestamp)")
    ckpt_save.set_defaults(func=cmd_checkpoint_save)
    ckpt_list = ckpt_subs.add_parser("list", help="List saved checkpoints")
    ckpt_list.set_defaults(func=cmd_checkpoint_list)
    ckpt_restore = ckpt_subs.add_parser("restore", help="Restore a checkpoint")
    ckpt_restore.add_argument("name", help="Checkpoint name")
    ckpt_restore.set_defaults(func=cmd_checkpoint_restore)

    # report
    report_parser = subparsers.add_parser("report", help="Generate a markdown project report")
    report_parser.add_argument("--output", metavar="FILE", help="Write report to file instead of stdout")
    report_parser.set_defaults(func=cmd_report)

    # webhook
    webhook_parser = subparsers.add_parser("webhook", help="Manage lifecycle event webhook")
    webhook_subs = webhook_parser.add_subparsers(dest="webhook_cmd")
    webhook_set = webhook_subs.add_parser("set", help="Set webhook URL")
    webhook_set.add_argument("url", help="Webhook endpoint URL")
    webhook_set.set_defaults(func=cmd_webhook_set)
    webhook_get = webhook_subs.add_parser("get", help="Show configured webhook URL")
    webhook_get.set_defaults(func=cmd_webhook_get)
    webhook_clear = webhook_subs.add_parser("clear", help="Remove webhook URL")
    webhook_clear.set_defaults(func=cmd_webhook_clear)
    webhook_test = webhook_subs.add_parser("test", help="Fire a test event to the webhook")
    webhook_test.set_defaults(func=cmd_webhook_test)

    launch_parser = subparsers.add_parser("launch", help="Open terminal window for an agent")
    launch_parser.add_argument("agent_id", nargs="?", help="Agent ID to launch")
    launch_parser.add_argument("--all", action="store_true", help="Launch all registered agents")
    launch_parser.set_defaults(func=cmd_launch)

    detect_parser = subparsers.add_parser("detect", help="Scan for installed AI tools and terminals")
    detect_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    detect_parser.set_defaults(func=cmd_detect)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        args.func(args)
    except OwlscaleError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


def _confirm(prompt: str, default: bool = True) -> bool:
    """Prompt user for Y/n confirmation. Returns default if stdin is not a TTY."""
    try:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        return default
    except EOFError:
        return default


def _suggest_roster(detect_result) -> list[dict]:
    """
    Build a suggested agent list from DetectionResult.
    Returns a list of agent config dicts ready for roster creation.
    """
    from owlscale.models import AgentRole

    tools = detect_result.tools if detect_result else {}
    terminals = detect_result.terminals if detect_result else {}

    # Pick the first available terminal
    preferred_terminal = "system"
    for t in ("ghostty", "iterm2", "tmux"):
        ti = terminals.get(t)
        if ti and ti.found:
            preferred_terminal = t
            break

    suggestions = []

    cc = tools.get("claude-code")
    copilot = tools.get("copilot-cli")
    codex = tools.get("codex")
    cursor = tools.get("cursor")

    if cc and cc.found:
        suggestions.append({
            "id": "orchestrator",
            "name": "Claude Code",
            "role": "coordinator",
            "tool": "claude-code",
            "launch": {"terminal": preferred_terminal, "cmd": ["claude"]},
        })
    if copilot and copilot.found:
        suggestions.append({
            "id": "worker-1",
            "name": "Copilot CLI",
            "role": "executor",
            "tool": "copilot-cli",
            "launch": {"terminal": preferred_terminal, "cmd": ["gh", "copilot", "suggest"]},
        })
    if codex and codex.found:
        suggestions.append({
            "id": "worker-2",
            "name": "Codex CLI",
            "role": "executor",
            "tool": "codex",
            "launch": {"terminal": preferred_terminal, "cmd": ["codex"]},
        })
    if cursor and cursor.found:
        suggestions.append({
            "id": "cursor-1",
            "name": "Cursor",
            "role": "executor",
            "tool": "cursor",
            "launch": {},  # IDE — no terminal launch
        })

    # If nothing found, promote first executor to coordinator; or add placeholders
    if not suggestions:
        suggestions = [
            {
                "id": "agent-1",
                "name": "Agent 1 (configure me)",
                "role": "coordinator",
                "tool": None,
                "launch": {},
            },
            {
                "id": "agent-2",
                "name": "Agent 2 (configure me)",
                "role": "executor",
                "tool": None,
                "launch": {},
            },
        ]
    elif not any(s["role"] == "coordinator" for s in suggestions):
        # Promote first executor to coordinator if CC not found
        suggestions[0]["role"] = "coordinator"

    return suggestions


def _print_detection(detect_result) -> None:
    """Print scan results."""
    print("Scanning for AI tools...")
    tools = detect_result.tools if detect_result else {}
    for tool_id, info in tools.items():
        mark = "✓" if info.found else "✗"
        loc = f"({info.path})" if info.found and info.path else "(not installed)"
        print(f"  {mark} {info.name:<26} {loc}")


def _print_roster_suggestions(suggestions: list[dict]) -> None:
    """Print suggested roster in a table."""
    print("\nSuggested roster:")
    for s in suggestions:
        tool_label = s.get("tool") or "(placeholder)"
        print(f"  {s['id']:<16} {tool_label:<20} role: {s['role']}")


def _print_next_steps() -> None:
    """Print onboarding guide."""
    print("\nYour workspace is ready. Next:")
    print("  owlscale whoami <agent-id>    # run this in each agent terminal")
    print("  owlscale pack \"<task>\"        # create your first task")
    print("  owlscale status               # see the full picture")


def cmd_init(args):
    """Initialize workspace with auto-detect, suggested roster, and optional terminal launch."""
    import json as _json
    root = Path.cwd()
    existed = (root / ".owlscale").exists()
    yes = getattr(args, "yes", False)
    no_launch = getattr(args, "no_launch", False)
    force = getattr(args, "force", False)

    register_defaults = getattr(args, "register_defaults", False)

    # Guard against overwriting existing workspace
    if existed and not force and not yes and not register_defaults:
        if not _confirm(f".owlscale/ already exists at {root / '.owlscale'}. Reinitialize? [y/N] ", default=False):
            print("Aborted.")
            return

    owlscale_dir = init_project(root)
    if existed:
        print(f"✓ Re-initialized .owlscale/ at {owlscale_dir}")
    else:
        print(f"✓ Initialized .owlscale/ at {owlscale_dir}")

    # Project name
    if getattr(args, "name", None):
        config_path = owlscale_dir / "config.json"
        cfg = {}
        if config_path.exists():
            try:
                cfg = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        cfg["project_name"] = args.name
        config_path.write_text(_json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Project name: {args.name}")

    # Legacy --register-defaults path (kept for backward compat)
    if register_defaults:
        from owlscale.defaults import register_defaults as _register_defaults
        registered = _register_defaults(owlscale_dir, root)
        if registered:
            for agent_id, name, role in registered:
                print(f"  ✓ Registered {name} ({agent_id}) as {role}")
        else:
            print("  No new agents detected to register.")
        return

    # --- New flow: detect → suggest → confirm → create → launch ---

    # Step 1: Detect
    detect_result = None
    try:
        from owlscale.detect import scan
        detect_result = scan()
        _print_detection(detect_result)
    except Exception:
        print("  (detection unavailable — using placeholder roster)")

    # Step 2: Suggest roster
    suggestions = _suggest_roster(detect_result)
    _print_roster_suggestions(suggestions)

    # Step 3: Confirm roster creation
    if not yes:
        if not _confirm("\nCreate this roster? [Y/n] ", default=True):
            print("Aborted. No roster created.")
            _print_next_steps()
            return

    # Step 4: Create roster
    from owlscale.core import load_roster, save_roster
    from owlscale.models import Agent, AgentRole
    roster = load_roster(owlscale_dir)
    created = 0
    for s in suggestions:
        if s["id"] in roster:
            continue
        try:
            agent = Agent(
                id=s["id"],
                name=s["name"],
                role=AgentRole(s["role"]),
                tool=s.get("tool"),
                launch=s.get("launch") or {},
            )
            roster[s["id"]] = agent
            created += 1
        except Exception:
            pass
    save_roster(owlscale_dir, roster)
    print(f"✓ Roster created ({created} agent{'s' if created != 1 else ''})")

    # Step 5: Offer terminal launch
    if not no_launch:
        do_launch = yes or _confirm("Launch agent terminals now? [Y/n] ", default=True)
        if do_launch:
            from owlscale.launch import launch_agent
            roster = load_roster(owlscale_dir)
            for agent in roster.values():
                if not agent.launch and agent.tool in (None, "cursor"):
                    continue  # IDE-only agents or placeholders skip terminal launch
                launch_config = agent.launch or {}
                terminal = launch_config.get("terminal", "system")
                print(f"  → Opening {terminal} window for {agent.id}"
                      + (f" ({' '.join(agent.launch.get('cmd', []))})" if agent.launch.get("cmd") else ""))
                ok = launch_agent(agent, owlscale_dir)
                if not ok:
                    print(f"    ⚠ Could not launch {agent.id} (terminal may not be running)")
            print("✓ Terminals launched")

    _print_next_steps()


def cmd_roster_add(args):
    """Add agent to roster."""
    owlscale_dir = get_workspace_root()
    agent = add_agent(owlscale_dir, args.agent_id, args.name, args.role)
    print(f"✓ Registered agent: {agent.id} ({agent.role.value})")
    _refresh_context_safe(owlscale_dir, agent.id)


def cmd_roster_list(args):
    """List agents."""
    owlscale_dir = get_workspace_root()
    agents = list_agents(owlscale_dir)

    if not agents:
        print("No agents registered.")
        return

    print("Registered agents:")
    for agent_id, agent in sorted(agents.items()):
        print(f"  {agent_id:20} {agent.name:30} [{agent.role.value}]")


def cmd_roster_remove(args):
    """Remove agent from roster."""
    owlscale_dir = get_workspace_root()
    remove_agent(owlscale_dir, args.agent_id)
    print(f"✓ Removed agent: {args.agent_id}")


def cmd_pack(args):
    """Create a Context Packet."""
    owlscale_dir = get_workspace_root()
    tags = args.tags.split(",") if args.tags else []
    template = getattr(args, "template", None)
    packet_path = pack_task(owlscale_dir, args.task_id, args.goal, tags=tags, parent=args.parent, template=template)
    print(f"✓ Created packet: {packet_path}")
    if template:
        print(f"  Pre-filled with template: {template}")
    print(f"  Edit the file and run: owlscale dispatch {args.task_id} <agent_id>")


def cmd_template_list(args):
    """List available templates."""
    from owlscale.template import list_templates, BUILTIN_TEMPLATES
    owlscale_dir = get_workspace_root()
    templates = list_templates(owlscale_dir)
    if not templates:
        print("No templates available.")
        return
    for name in templates:
        tag = " (builtin)" if name in BUILTIN_TEMPLATES else ""
        print(f"  {name}{tag}")


def cmd_template_show(args):
    """Print template body."""
    from owlscale.template import get_template
    owlscale_dir = get_workspace_root()
    try:
        body = get_template(owlscale_dir, args.name)
        print(body)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_template_add(args):
    """Import a template from a Markdown file."""
    from owlscale.template import save_template
    owlscale_dir = get_workspace_root()
    src = Path(args.file)
    if not src.exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    body = src.read_text()
    path = save_template(owlscale_dir, args.name, body)
    print(f"✓ Template '{args.name}' saved to {path}")


def cmd_template_remove(args):
    """Remove a user-defined template."""
    from owlscale.template import delete_template, TemplateError
    owlscale_dir = get_workspace_root()
    try:
        delete_template(owlscale_dir, args.name)
        print(f"✓ Template '{args.name}' removed.")
    except TemplateError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dispatch(args):
    """Dispatch task to agent."""
    from owlscale.alias import resolve_alias
    owlscale_dir = get_workspace_root()
    agent_id = resolve_alias(owlscale_dir, args.agent_id)
    dispatch_task(owlscale_dir, args.task_id, agent_id)
    print(f"✓ Dispatched task '{args.task_id}' to '{agent_id}'"
          + (f" (alias: {args.agent_id})" if agent_id != args.agent_id else ""))
    _maybe_fire_webhook(owlscale_dir, {"event": "dispatched", "task_id": args.task_id, "agent_id": agent_id})
    _refresh_context_safe(owlscale_dir, agent_id)

    if getattr(args, "git", False):
        from owlscale.git import is_git_repo, create_branch, task_branch_name
        project_root = owlscale_dir.parent
        if not is_git_repo(project_root):
            print("  ⚠ Not a git repository — skipping branch creation.")
        else:
            branch = task_branch_name(args.task_id, agent_id)
            created = create_branch(project_root, branch)
            if created:
                print(f"  ✓ Created branch: {branch}")
            else:
                print(f"  ⚠ Branch already exists: {branch}")


def cmd_git_branch(args):
    """Show or create git branch for a task."""
    from owlscale.git import is_git_repo, create_branch, task_branch_name, branch_exists
    from owlscale.core import load_state
    owlscale_dir = get_workspace_root()
    project_root = owlscale_dir.parent

    if not is_git_repo(project_root):
        print("Error: Not a git repository.", file=sys.stderr)
        sys.exit(1)

    state = load_state(owlscale_dir)
    if args.task_id not in state.tasks:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    task_state = state.tasks[args.task_id]
    assignee = task_state.assignee or "unknown"
    branch = task_branch_name(args.task_id, assignee)

    if branch_exists(project_root, branch):
        print(f"Branch exists: {branch}")
    else:
        create_branch(project_root, branch)
        print(f"✓ Created branch: {branch}")


def cmd_git_pr(args):
    """Print gh pr create command for a task."""
    from owlscale.git import get_pr_command, task_branch_name
    from owlscale.core import load_state
    owlscale_dir = get_workspace_root()
    state = load_state(owlscale_dir)

    if args.task_id not in state.tasks:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        sys.exit(1)

    task_state = state.tasks[args.task_id]
    assignee = task_state.assignee or "unknown"
    cmd = get_pr_command(args.task_id, assignee, base=args.base)
    print(cmd)


def cmd_git_status(args):
    """Show task-to-branch mapping for open tasks."""
    from owlscale.git import is_git_repo, get_open_task_branches
    owlscale_dir = get_workspace_root()
    project_root = owlscale_dir.parent

    tasks = get_open_task_branches(project_root if is_git_repo(project_root) else owlscale_dir, owlscale_dir)

    if not tasks:
        print("No open tasks with assignees.")
        return

    for t in tasks:
        exists_marker = "✓" if t["exists"] else "✗"
        print(f"  {exists_marker} {t['branch']:40}  [{t['status']}]  {t['task_id']}")


def cmd_claim(args):
    """Claim a dispatched task."""
    owlscale_dir = get_workspace_root()
    claim_task(owlscale_dir, args.task_id)
    print(f"✓ Claimed task '{args.task_id}' (now in_progress)")


def cmd_return(args):
    """Mark task as returned."""
    owlscale_dir = get_workspace_root()
    return_task(owlscale_dir, args.task_id)
    print(f"✓ Marked task '{args.task_id}' as returned")
    _maybe_fire_webhook(owlscale_dir, {"event": "returned", "task_id": args.task_id})
    _refresh_all_contexts_safe(owlscale_dir)


def cmd_accept(args):
    """Accept a returned task."""
    owlscale_dir = get_workspace_root()
    accept_task(owlscale_dir, args.task_id)
    print(f"✓ Accepted task '{args.task_id}'")
    _maybe_fire_webhook(owlscale_dir, {"event": "accepted", "task_id": args.task_id})
    _refresh_all_contexts_safe(owlscale_dir)


def cmd_reject(args):
    """Reject a returned task."""
    owlscale_dir = get_workspace_root()
    reject_task(owlscale_dir, args.task_id, reason=args.reason)
    print(f"✓ Rejected task '{args.task_id}'")
    if args.reason:
        print(f"  Reason: {args.reason}")
    _maybe_fire_webhook(owlscale_dir, {"event": "rejected", "task_id": args.task_id})
    _refresh_all_contexts_safe(owlscale_dir)


def cmd_status(args):
    """Show global task status."""
    owlscale_dir = get_workspace_root()
    state = get_status(owlscale_dir)

    if not state.tasks:
        print("No tasks.")
        return

    # Group by status
    by_status = {}
    for task_id, task_state in state.tasks.items():
        status = task_state.status.value
        if status not in by_status:
            by_status[status] = []
        by_status[status].append((task_id, task_state))

    # Display each status group
    status_order = ["draft", "ready", "dispatched", "in_progress", "returned", "accepted", "rejected"]
    for status in status_order:
        if status not in by_status:
            continue
        tasks = by_status[status]
        print(f"\n{status.upper()}:")
        for task_id, task_state in tasks:
            assignee_str = f" → {task_state.assignee}" if task_state.assignee else ""
            print(f"  {task_id}{assignee_str}")


def cmd_log(args):
    """Show operation log."""
    owlscale_dir = get_workspace_root()
    entries = get_log(owlscale_dir, task_id=args.task if hasattr(args, 'task') else None, limit=args.limit if hasattr(args, 'limit') else None)

    if not entries:
        print("No log entries.")
        return

    for entry in entries:
        print(entry)


def cmd_validate(args):
    """Validate packet completeness."""
    from owlscale.validate import validate_packet
    owlscale_dir = get_workspace_root()
    results = validate_packet(owlscale_dir, args.task_id)

    print(f"Validating packet: {args.task_id}")
    passed_count = 0
    for r in results:
        icon = "✓" if r.passed else "✗"
        suffix = "" if r.passed else f" — {r.message}"
        print(f"  {icon} {r.name}{suffix}")
        if r.passed:
            passed_count += 1

    total = len(results)
    print()
    if passed_count == total:
        print(f"Result: {passed_count}/{total} checks passed. Packet is ready for dispatch.")
    else:
        print(f"Result: {passed_count}/{total} checks passed. Packet is NOT ready for dispatch.")
        sys.exit(1)


def cmd_fmt(args):
    """Format a packet."""
    from owlscale.fmt import fmt_task_packet
    owlscale_dir = get_workspace_root()

    if args.check:
        _, changed = fmt_task_packet(owlscale_dir, args.task_id, write=False)
        if changed:
            print(f"✗ {args.task_id} needs formatting")
            sys.exit(1)
        else:
            print(f"✓ {args.task_id} already formatted")
    elif args.dry_run:
        formatted, _ = fmt_task_packet(owlscale_dir, args.task_id, write=False)
        print(formatted, end="")
    else:
        _, changed = fmt_task_packet(owlscale_dir, args.task_id, write=True)
        if changed:
            print(f"✓ Formatted {args.task_id}")
        else:
            print(f"✓ Already formatted")


def cmd_export(args):
    """Export accepted/rejected tasks as JSONL."""
    owlscale_dir = get_workspace_root()
    output_path = Path(args.output) if args.output else None
    records = export_training_data(owlscale_dir, output_path=output_path, status_filter=args.status)

    if output_path is not None:
        print(f"✓ Exported {len(records)} record(s) to {output_path}")
        return

    for record in records:
        print(json.dumps(record, ensure_ascii=False))


def cmd_watch(args):
    """Watch for dispatched tasks assigned to an agent."""
    owlscale_dir = get_workspace_root()

    if args.poll:
        watch_poll(owlscale_dir, args.agent, interval=args.poll)
        return

    found = watch_once(owlscale_dir, args.agent)
    if not found:
        sys.exit(1)


def cmd_serve(args):
    """Run the lightweight HTTP task delivery service."""
    from owlscale.serve import serve_agent

    owlscale_dir = get_workspace_root()
    serve_agent(owlscale_dir, args.agent, host=args.host, port=args.port)


def cmd_review(args):
    """Review a Return Packet against Expected Output."""
    from owlscale.review import review_return_packet

    owlscale_dir = get_workspace_root()
    review = review_return_packet(owlscale_dir, args.task_id)

    if args.as_json:
        print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Reviewing Return Packet: {args.task_id}")
        print(f"Score: {review.score:.2f}/100")
        print(f"Expected Output: {review.expected_output or '(none)'}")
        print()
        for check in review.checks:
            icon = "✓" if check.passed else "✗"
            print(f"  {icon} {check.name} [{check.score:.2f}/{check.max_score:.0f}] — {check.message}")
        print()
        print(f"Verdict: {'PASS' if review.passed else 'FAIL'}")

    if not review.passed:
        sys.exit(1)


def cmd_mcp_server(args):
    """Run the owlscale MCP stdio server."""
    from owlscale.mcp_server import OwlscaleMCPServer

    OwlscaleMCPServer().serve_forever()


def cmd_route(args):
    """Auto-route task to best agent."""
    from owlscale.route import route_task
    owlscale_dir = get_workspace_root()
    candidates = route_task(owlscale_dir, args.task_id, top_n=args.top)

    if not candidates:
        print("No eligible agents found.")
        sys.exit(1)

    if args.dispatch:
        from owlscale.alias import resolve_alias
        best = candidates[0]
        agent_id = resolve_alias(owlscale_dir, best.agent_id)
        dispatch_task(owlscale_dir, args.task_id, agent_id)
        print(f"✓ Auto-dispatched '{args.task_id}' to '{agent_id}' (score: {best.score:.1f})")
        for r in best.reasons:
            print(f"  {r}")
        return

    print(f"Route candidates for '{args.task_id}':")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c.agent_id:20} score={c.score:.1f}")
        for r in c.reasons:
            print(f"     {r}")


def cmd_diff(args):
    """Compare two packet versions."""
    from owlscale.diff import diff_task_packets
    owlscale_dir = get_workspace_root()
    result = diff_task_packets(owlscale_dir, args.task_id_a, args.task_id_b,
                               context_lines=args.context)
    if not result.has_changes:
        print("No differences found.")
        return
    if result.frontmatter_changes:
        print("Frontmatter changes:")
        for change in result.frontmatter_changes:
            print(f"  {change}")
        print()
    if result.body_diff:
        print("Body changes:")
        print(result.body_diff)


def cmd_stats(args):
    """Show flywheel metrics."""
    from owlscale.stats import compute_stats
    owlscale_dir = get_workspace_root()
    stats = compute_stats(owlscale_dir)

    if args.as_json:
        print(json.dumps(stats.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Total tasks: {stats.total_tasks}")
    if stats.by_status:
        parts = [f"{s}={n}" for s, n in sorted(stats.by_status.items())]
        print(f"  By status: {', '.join(parts)}")
    if stats.agents:
        print(f"\nPer-agent metrics:")
        for agent_id in sorted(stats.agents.keys()):
            a = stats.agents[agent_id]
            pr = f"{a.pass_rate:.0%}" if a.pass_rate is not None else "n/a"
            rr = f"{a.rework_rate:.0%}" if a.rework_rate is not None else "n/a"
            dur = f"{a.avg_duration_hours:.1f}h" if a.avg_duration_hours is not None else "n/a"
            print(f"  {agent_id:20} tasks={a.total_tasks:3}  pass={pr:>5}  rework={rr:>5}  avg_time={dur}")
    else:
        print("\nNo agent activity yet.")


def cmd_prune(args):
    """Archive old completed tasks."""
    from owlscale.prune import prune_workspace
    owlscale_dir = get_workspace_root()

    result = prune_workspace(owlscale_dir, days=args.days, dry_run=True)

    if not result.archived:
        print(f"No completed tasks older than {args.days} day(s) to archive.")
        return

    print(f"{'Would archive' if args.dry_run else 'Ready to archive'} {len(result.archived)} task(s):")
    for task_id in result.archived:
        print(f"  - {task_id}")

    if args.dry_run:
        return

    if not args.force:
        answer = input(f"\nArchive {len(result.archived)} task(s)? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    result = prune_workspace(owlscale_dir, days=args.days, dry_run=False)
    print(f"\n✓ Archived {len(result.archived)} task(s).")


def cmd_hub_route(args):
    """Ask LLM to recommend an agent for a task."""
    from owlscale.hub import hub_route
    owlscale_dir = get_workspace_root()
    result = hub_route(owlscale_dir, args.task_id, model=args.model, endpoint=args.endpoint)
    print(result)


def cmd_hub_draft(args):
    """Ask LLM to draft a Context Packet body."""
    from owlscale.hub import hub_draft
    owlscale_dir = get_workspace_root()
    result = hub_draft(owlscale_dir, args.task_id, model=args.model, endpoint=args.endpoint)
    print(result)


def cmd_hub_ask(args):
    """Send an arbitrary prompt to the local LLM."""
    from owlscale.hub import hub_ask
    result = hub_ask(args.prompt, model=args.model, endpoint=args.endpoint)
    print(result)


def cmd_snapshot_save(args):
    """Save current state.json as a snapshot."""
    from owlscale.snapshot import save_snapshot
    owlscale_dir = get_workspace_root()
    name = save_snapshot(owlscale_dir, name=getattr(args, "name", None))
    print(f"✓ Snapshot saved: {name}")


def cmd_snapshot_list(args):
    """List available snapshots."""
    from owlscale.snapshot import list_snapshots
    owlscale_dir = get_workspace_root()
    snapshots = list_snapshots(owlscale_dir)
    if not snapshots:
        print("No snapshots found.")
        return
    for name in snapshots:
        print(f"  {name}")


def cmd_snapshot_restore(args):
    """Restore state.json from a snapshot."""
    from owlscale.snapshot import restore_snapshot
    owlscale_dir = get_workspace_root()
    restore_snapshot(owlscale_dir, args.name)
    print(f"✓ Restored state.json from snapshot: {args.name}")


def cmd_snapshot_diff(args):
    """Diff two snapshots."""
    from owlscale.snapshot import diff_snapshots
    owlscale_dir = get_workspace_root()
    diff = diff_snapshots(owlscale_dir, args.name_a, args.name_b)

    if args.as_json:
        print(json.dumps(diff, indent=2, ensure_ascii=False))
        return

    if diff["added"]:
        print(f"Added ({len(diff['added'])}):")
        for tid in diff["added"]:
            print(f"  + {tid}")
    if diff["removed"]:
        print(f"Removed ({len(diff['removed'])}):")
        for tid in diff["removed"]:
            print(f"  - {tid}")
    if diff["changed"]:
        print(f"Changed ({len(diff['changed'])}):")
        for tid, fields in diff["changed"].items():
            print(f"  ~ {tid}")
            for field, (old, new) in fields.items():
                print(f"      {field}: {old!r} → {new!r}")
    if not any([diff["added"], diff["removed"], diff["changed"]]):
        print("No differences.")


def cmd_notify(args):
    """Deliver pending notifications."""
    from owlscale.notify import list_pending, deliver
    owlscale_dir = get_workspace_root()

    if args.list_only:
        notifications = list_pending(owlscale_dir)
        if not notifications:
            print("No pending notifications.")
            return
        print(f"{len(notifications)} pending notification(s):")
        for n in notifications:
            file_name = n.pop("_file", "?")
            print(f"  {file_name}: {n.get('event', '?')} — {n.get('task_id', '?')}")
        return

    delivered = deliver(owlscale_dir, webhook_url=args.webhook)
    if not delivered:
        print("No pending notifications.")
    else:
        target = args.webhook or "stdout"
        print(f"✓ Delivered {len(delivered)} notification(s) to {target}")
def cmd_batch_pack(args):
    """Pack multiple tasks from a YAML spec file."""
    from owlscale.batch import load_batch_spec, batch_pack
    owlscale_dir = get_workspace_root()
    spec_path = Path(args.spec)
    spec = load_batch_spec(spec_path)
    result = batch_pack(owlscale_dir, spec)

    for task_id in result["created"]:
        print(f"✓ Created: {task_id}")
    for task_id in result["skipped"]:
        print(f"  Skipped (exists): {task_id}")

    if not result["created"] and not result["skipped"]:
        print("No tasks in spec.")
    else:
        print(f"\nDone: {len(result['created'])} created, {len(result['skipped'])} skipped.")
def _print_lint_results(task_id: str, results, as_json: bool = False) -> bool:
    """Print lint results. Returns True if all passed."""
    from owlscale.lint import LintResult
    all_passed = all(r.passed for r in results)

    if as_json:
        import json
        data = {
            "task_id": task_id,
            "passed": all_passed,
            "checks": [{"name": r.name, "passed": r.passed, "message": r.message} for r in results],
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return all_passed

    status = "✓ PASS" if all_passed else "✗ FAIL"
    print(f"\n{task_id}  [{status}]")
    for r in results:
        icon = "✓" if r.passed else "✗"
        print(f"  {icon} {r.name:12} {r.message}")
    return all_passed


def cmd_lint(args):
    """Run comprehensive lint checks on one or all tasks."""
    from owlscale.lint import lint_packet
    from owlscale.core import load_state
    owlscale_dir = get_workspace_root()

    if args.lint_all:
        state = load_state(owlscale_dir)
        task_ids = sorted(state.tasks.keys())
        if not task_ids:
            print("No tasks to lint.")
            return
        any_failed = False
        for task_id in task_ids:
            results = lint_packet(owlscale_dir, task_id)
            passed = _print_lint_results(task_id, results, as_json=args.as_json)
            if not passed:
                any_failed = True
        if any_failed:
            sys.exit(1)
        return

    if not args.task_id:
        print("Error: provide a task ID or use --all", file=sys.stderr)
        sys.exit(1)

    results = lint_packet(owlscale_dir, args.task_id)
    passed = _print_lint_results(args.task_id, results, as_json=args.as_json)
    if not passed:
        sys.exit(1)


def cmd_alias_set(args):
    """Set an agent ID alias."""
    from owlscale.alias import set_alias
    owlscale_dir = get_workspace_root()
    set_alias(owlscale_dir, args.alias, args.agent_id)
    print(f"✓ Alias set: {args.alias} → {args.agent_id}")


def cmd_alias_list(args):
    """List all aliases."""
    from owlscale.alias import list_aliases
    owlscale_dir = get_workspace_root()
    aliases = list_aliases(owlscale_dir)
    if not aliases:
        print("No aliases defined.")
        return
    for alias, agent_id in sorted(aliases.items()):
        print(f"  {alias:20} → {agent_id}")


def cmd_alias_remove(args):
    """Remove an alias."""
    from owlscale.alias import remove_alias
    owlscale_dir = get_workspace_root()
    try:
        remove_alias(owlscale_dir, args.alias)
        print(f"✓ Removed alias: {args.alias}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_history(args):
    """Show complete task event timeline."""
    from owlscale.history import get_task_history
    owlscale_dir = get_workspace_root()

    try:
        history = get_task_history(owlscale_dir, args.task_id)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        data = {
            "task_id": history.task_id,
            "events": [
                {"timestamp": e.timestamp, "action": e.action, "detail": e.detail}
                for e in history.events
            ],
            "return_preview": history.return_preview,
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    print(f"Timeline for '{history.task_id}':")
    if not history.events:
        print("  (no events found)")
    else:
        for e in history.events:
            detail = f"  {e.detail}" if e.detail else ""
            print(f"  {e.timestamp}  {e.action:<12}{detail}")

    if history.return_preview:
        print(f"\nReturn preview:")
        for line in history.return_preview.splitlines():
            print(f"  {line}")


def cmd_schema_check(args):
    """Validate state.json against schema."""
    from owlscale.schema import check_state_file
    owlscale_dir = get_workspace_root()
    errors = check_state_file(owlscale_dir)
    if not errors:
        print("✓ state.json is valid.")
        return
    print(f"✗ state.json has {len(errors)} error(s):")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)


def cmd_config_get(args):
    """Get a config value."""
    from owlscale.config import get
    owlscale_dir = get_workspace_root()
    value = get(owlscale_dir, args.key)
    if value is None:
        print(f"(not set)")
    else:
        print(value)


def cmd_config_set(args):
    """Set a config value."""
    from owlscale.config import set_value
    owlscale_dir = get_workspace_root()
    set_value(owlscale_dir, args.key, args.value)
    print(f"✓ Set {args.key} = {args.value}")


def cmd_config_list(args):
    """List all config values."""
    from owlscale.config import load_config
    owlscale_dir = get_workspace_root()
    cfg = load_config(owlscale_dir)
    if not cfg:
        print("(empty config)")
        return
    def _print_dict(d, prefix=""):
        for k, v in sorted(d.items()):
            if isinstance(v, dict):
                _print_dict(v, f"{prefix}{k}.")
            else:
                print(f"  {prefix}{k} = {v}")
    _print_dict(cfg)


def cmd_search(args):
    """Full-text search across packets and returns."""
    from owlscale.search import search_packets
    owlscale_dir = get_workspace_root()

    include_packets = True
    include_returns = True
    if args.packets and not args.returns:
        include_returns = False
    elif args.returns and not args.packets:
        include_packets = False

    results = search_packets(
        owlscale_dir,
        args.query,
        case_sensitive=args.case_sensitive,
        include_packets=include_packets,
        include_returns=include_returns,
    )

    if not results:
        print("No matches found.")
        return

    for r in results:
        print(f"{r.file}:{r.line_no}: {r.line_text.rstrip()}")


def cmd_tag_list(args):
    """List all tags and their tasks."""
    from owlscale.tag import list_all_tags
    owlscale_dir = get_workspace_root()
    tag_map = list_all_tags(owlscale_dir)
    if not tag_map:
        print("No tags found.")
        return
    for tag, task_ids in sorted(tag_map.items()):
        print(f"  {tag}: {', '.join(sorted(task_ids))}")


def cmd_tag_filter(args):
    """List tasks with a given tag."""
    from owlscale.tag import get_tasks_by_tag
    owlscale_dir = get_workspace_root()
    task_ids = get_tasks_by_tag(owlscale_dir, args.tag)
    if not task_ids:
        print(f"No tasks with tag '{args.tag}'.")
        return
    for tid in sorted(task_ids):
        print(f"  {tid}")


def cmd_tag_add(args):
    """Add a tag to a task."""
    from owlscale.tag import add_tag
    owlscale_dir = get_workspace_root()
    add_tag(owlscale_dir, args.task_id, args.tag)
    print(f"✓ Added tag '{args.tag}' to '{args.task_id}'")


def cmd_tag_remove(args):
    """Remove a tag from a task."""
    from owlscale.tag import remove_tag
    owlscale_dir = get_workspace_root()
    remove_tag(owlscale_dir, args.task_id, args.tag)
    print(f"✓ Removed tag '{args.tag}' from '{args.task_id}'")


def cmd_timeline(args):
    """Show cross-task event timeline."""
    from owlscale.timeline import get_timeline
    from dataclasses import asdict
    owlscale_dir = get_workspace_root()

    events = get_timeline(
        owlscale_dir,
        since=args.since,
        until=args.until,
        task_ids=args.task_ids,
    )

    if not events:
        print("No events found.")
        return

    if args.as_json:
        print(json.dumps([asdict(e) for e in events], indent=2, ensure_ascii=False))
        return

    for e in events:
        detail = f"  {e.detail}" if e.detail else ""
        print(f"  {e.timestamp}  {e.task_id:<30}  {e.action:<14}{detail}")


def cmd_repair(args):
    """Detect and repair inconsistencies between state.json and packets/."""
    from owlscale.repair import repair
    owlscale_dir = get_workspace_root()

    dry_run = not args.force
    report = repair(owlscale_dir, dry_run=dry_run)
    mode = "DRY RUN" if dry_run else "APPLIED"

    if not report.has_issues:
        print("✓ Workspace is consistent.")
        return

    print(f"[{mode}] Repair report:")
    if report.orphan_packets:
        print(f"\n  Orphan packets ({len(report.orphan_packets)}):")
        for tid in report.orphan_packets:
            action = "would register" if dry_run else "registered"
            print(f"    {tid}  →  {action} in state.json (status=draft)")

    if report.missing_packets:
        print(f"\n  Missing packets ({len(report.missing_packets)}):")
        for tid in report.missing_packets:
            action = "would remove" if dry_run else "removed"
            print(f"    {tid}  →  {action} from state.json")

    if report.status_mismatches:
        print(f"\n  Status mismatches ({len(report.status_mismatches)}):")
        for tid, state_s, fm_s in report.status_mismatches:
            action = "would update" if dry_run else "updated"
            print(f"    {tid}  state={state_s}  frontmatter={fm_s}  →  {action} frontmatter")

    if dry_run:
        print("\nRun with --force to apply repairs.")


def cmd_pin(args):
    """Pin a task or list pinned tasks."""
    from owlscale.pin import pin_task, list_pinned
    owlscale_dir = get_workspace_root()
    if args.list_pins or not args.task_id:
        pins = list_pinned(owlscale_dir)
        if not pins:
            print("No pinned tasks.")
        else:
            for tid in pins:
                print(f"  {tid}")
        return
    pin_task(owlscale_dir, args.task_id)
    print(f"✓ Pinned '{args.task_id}'")


def cmd_unpin(args):
    """Unpin a task."""
    from owlscale.pin import unpin_task
    owlscale_dir = get_workspace_root()
    unpin_task(owlscale_dir, args.task_id)
    print(f"✓ Unpinned '{args.task_id}'")


def cmd_checkpoint_save(args):
    """Create a checkpoint archive of the current workspace."""
    from owlscale.checkpoint import create_checkpoint
    owlscale_dir = get_workspace_root()
    path = create_checkpoint(owlscale_dir, name=args.name)
    print(f"✓ Checkpoint saved: {path}")


def cmd_checkpoint_list(args):
    """List available checkpoints."""
    from owlscale.checkpoint import list_checkpoints
    owlscale_dir = get_workspace_root()
    names = list_checkpoints(owlscale_dir)
    if not names:
        print("No checkpoints found.")
        return
    for name in names:
        print(f"  {name}")


def cmd_checkpoint_restore(args):
    """Restore a checkpoint."""
    from owlscale.checkpoint import restore_checkpoint
    owlscale_dir = get_workspace_root()
    try:
        restore_checkpoint(owlscale_dir, args.name)
        print(f"✓ Restored checkpoint: {args.name}")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_report(args):
    """Generate a markdown project report."""
    from owlscale.report import generate_report
    owlscale_dir = get_workspace_root()
    report_text = generate_report(owlscale_dir)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report_text, encoding="utf-8")
        print(f"✓ Report written to {output_path}")
    else:
        print(report_text, end="")


def cmd_webhook_set(args):
    """Set webhook URL."""
    from owlscale.webhook import register_webhook
    owlscale_dir = get_workspace_root()
    register_webhook(owlscale_dir, args.url)
    print(f"✓ Webhook set: {args.url}")


def cmd_webhook_get(args):
    """Show configured webhook URL."""
    from owlscale.webhook import get_webhook
    owlscale_dir = get_workspace_root()
    url = get_webhook(owlscale_dir)
    print(url if url else "(not set)")


def cmd_webhook_clear(args):
    """Remove webhook URL."""
    from owlscale.webhook import clear_webhook
    owlscale_dir = get_workspace_root()
    clear_webhook(owlscale_dir)
    print("✓ Webhook cleared")


def cmd_webhook_test(args):
    """Fire a test event to the webhook."""
    from owlscale.webhook import get_webhook, fire
    owlscale_dir = get_workspace_root()
    url = get_webhook(owlscale_dir)
    if not url:
        print("No webhook configured. Use: owlscale webhook set <url>")
        sys.exit(1)
    try:
        fire(url, {"event": "test", "task_id": None, "timestamp": None, "detail": {}})
        print(f"✓ Test event fired to {url}")
    except Exception as exc:
        print(f"✗ Webhook test failed: {exc}", file=sys.stderr)
        sys.exit(1)



def cmd_flywheel_prepare(args):
    """Generate SFT/DPO training datasets from export JSONL."""
    from owlscale.flywheel import load_jsonl, prepare_sft, prepare_dpo
    import json

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(input_path)
    written = []

    if args.fmt in ("sft", "both"):
        sft_data = prepare_sft(records)
        sft_path = output_dir / "sft.jsonl"
        sft_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sft_data) + ("\n" if sft_data else ""))
        written.append(f"SFT: {sft_path} ({len(sft_data)} records)")

    if args.fmt in ("dpo", "both"):
        dpo_data = prepare_dpo(records)
        dpo_path = output_dir / "dpo.jsonl"
        dpo_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in dpo_data) + ("\n" if dpo_data else ""))
        written.append(f"DPO: {dpo_path} ({len(dpo_data)} pairs)")

    for w in written:
        print(f"✓ {w}")


def cmd_flywheel_stats(args):
    """Print statistics for export JSONL."""
    from owlscale.flywheel import load_jsonl, flywheel_stats

    input_path = Path(args.input)
    records = load_jsonl(input_path)
    stats = flywheel_stats(records)

    if args.as_json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    print(f"Total records : {stats['total']}")
    print(f"  Accepted    : {stats['accepted']}")
    print(f"  Rejected    : {stats['rejected']}")
    print(f"DPO pairs     : {stats['dpo_pairs']}")
    print(f"Avg tokens/rec: {stats['avg_token_len']:.1f}")


def cmd_whoami(args):
    """Print or refresh agent context file(s)."""
    owlscale_dir = get_workspace_root()

    if getattr(args, "all_agents", False):
        from owlscale.identity import refresh_all_contexts, get_agent_context
        from owlscale.core import load_roster
        refresh_all_contexts(owlscale_dir)
        agents = load_roster(owlscale_dir)
        if not agents:
            print("No agents registered.")
            return
        for agent_id in sorted(agents):
            path = owlscale_dir / "agents" / f"{agent_id}.md"
            print(f"  {agent_id}: {path}")
        return

    agent_id = getattr(args, "agent_id", None)
    if not agent_id:
        print("Usage: owlscale whoami <agent-id> | --all", file=sys.stderr)
        sys.exit(1)

    from owlscale.identity import refresh_agent_context, get_agent_context
    refresh_agent_context(owlscale_dir, agent_id)
    content = get_agent_context(owlscale_dir, agent_id)
    print(content)


def cmd_daemon_run(args):
    """Run daemon in foreground."""
    owlscale_dir = get_workspace_root()
    from owlscale.daemon import run_daemon
    run_daemon(owlscale_dir, poll_interval=args.poll, drive_shell=args.drive_shell)


def cmd_daemon_start(args):
    """Start daemon in background."""
    owlscale_dir = get_workspace_root()
    from owlscale.daemon import start_daemon, get_daemon_status
    status = get_daemon_status(owlscale_dir)
    if status["running"]:
        print(f"owlscale daemon: already running (pid {status['pid']})")
        return
    pid = start_daemon(owlscale_dir, poll_interval=args.poll, drive_shell=args.drive_shell)
    print(f"✓ owlscale daemon started (pid {pid})")


def cmd_daemon_stop(args):
    """Stop background daemon."""
    owlscale_dir = get_workspace_root()
    from owlscale.daemon import stop_daemon
    stopped = stop_daemon(owlscale_dir)
    if stopped:
        print("✓ owlscale daemon stopped")
    else:
        print("owlscale daemon: not running")


def cmd_daemon_status(args):
    """Show daemon status."""
    owlscale_dir = get_workspace_root()
    from owlscale.daemon import get_daemon_status
    status = get_daemon_status(owlscale_dir)
    if status["running"]:
        print(f"owlscale daemon: running (pid {status['pid']})")
        if status["started_at"]:
            print(f"  started:  {status['started_at']}")
        if status["poll_interval"] is not None:
            print(f"  poll:     {status['poll_interval']}s")
        print(f"  triggers: {status['trigger_seq']}")
    else:
        print("owlscale daemon: not running")


def cmd_daemon_logs(args):
    """Show daemon log."""
    owlscale_dir = get_workspace_root()
    from owlscale.daemon import tail_daemon_log
    lines = tail_daemon_log(owlscale_dir, n=args.n)
    if not lines:
        print("(no daemon log)")
        return
    for line in lines:
        print(line)


def cmd_demo(args):
    """Run the self-contained onboarding demo."""
    from owlscale.demo import run_demo
    run_demo(fast=args.fast, no_color=args.no_color)


def cmd_detect(args):
    """Scan for installed AI tools and terminals."""
    import json
    from owlscale.detect import scan, fmt_detection

    result = scan()
    if getattr(args, "json", False):
        data = {
            "tools": {k: {"id": v.id, "name": v.name, "found": v.found, "path": v.path, "launch_cmd": v.launch_cmd} for k, v in result.tools.items()},
            "terminals": {k: {"id": v.id, "name": v.name, "found": v.found, "path": v.path, "adapter": v.adapter} for k, v in result.terminals.items()},
            "platform": result.platform,
        }
        print(json.dumps(data, indent=2))
    else:
        print(fmt_detection(result))


def cmd_launch(args):
    """Launch a terminal session for an agent."""
    from owlscale.launch import launch_agent
    from owlscale.core import load_roster

    owlscale_dir = get_workspace_root()
    roster = load_roster(owlscale_dir)

    if getattr(args, "all", False):
        if not roster:
            print("No agents registered.")
            return
        for agent in roster.values():
            ok = launch_agent(agent, owlscale_dir)
            if ok:
                print(f"✓ launched {agent.id}")
            else:
                print(f"✗ failed  {agent.id} (skipped)")
        return

    if not args.agent_id:
        print("Error: specify <agent-id> or --all", file=sys.stderr)
        sys.exit(1)

    agent = next((a for a in roster.values() if a.id == args.agent_id), None)
    if agent is None:
        print(f"Error: agent '{args.agent_id}' not found in roster", file=sys.stderr)
        sys.exit(1)

    ok = launch_agent(agent, owlscale_dir)
    if ok:
        print(f"✓ launched {agent.id}")
    else:
        print(f"✗ failed to launch {agent.id}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
