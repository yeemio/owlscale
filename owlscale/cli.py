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
from owlscale.models import TaskStatus
from owlscale.watch import watch_once, watch_poll


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
    init_parser.add_argument("--name", help="Project name (stored in .owlscale/config.json)")
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

    whoami_parser = subparsers.add_parser("whoami", help="Print agent context file")
    whoami_parser.add_argument("agent_id", nargs="?", help="Agent ID to show context for")
    whoami_parser.add_argument("--all", action="store_true", dest="all_agents",
                               help="Refresh all agents and list paths")
    whoami_parser.set_defaults(func=cmd_whoami)

    daemon_parser = subparsers.add_parser("daemon", help="Background task monitor")
    daemon_subs = daemon_parser.add_subparsers(dest="daemon_cmd")
    daemon_parser.set_defaults(func=cmd_daemon_help)

    d_run = daemon_subs.add_parser("run", help="Run daemon in foreground")
    d_run.add_argument("--poll", type=float, default=1.0, help="Poll interval in seconds")
    d_run.add_argument("--drive-shell", action="store_true", help="Invoke delivery adapters")
    d_run.set_defaults(func=cmd_daemon_run)

    d_start = daemon_subs.add_parser("start", help="Start daemon in background")
    d_start.add_argument("--poll", type=float, default=1.0)
    d_start.add_argument("--drive-shell", action="store_true")
    d_start.set_defaults(func=cmd_daemon_start)

    d_stop = daemon_subs.add_parser("stop", help="Stop background daemon")
    d_stop.set_defaults(func=cmd_daemon_stop)

    d_status = daemon_subs.add_parser("status", help="Show daemon status")
    d_status.set_defaults(func=cmd_daemon_status)

    d_logs = daemon_subs.add_parser("logs", help="Tail daemon log")
    d_logs.add_argument("-n", type=int, default=50, help="Number of lines")
    d_logs.set_defaults(func=cmd_daemon_logs)

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


def cmd_init(args):
    """Initialize workspace."""
    root = Path.cwd()
    existed = (root / ".owlscale").exists()

    owlscale_dir = init_project(root)

    project_name = getattr(args, "name", None)
    if project_name:
        import json as _json
        config_path = owlscale_dir / "config.json"
        config = _json.loads(config_path.read_text()) if config_path.exists() else {}
        config["name"] = project_name
        config_path.write_text(_json.dumps(config, indent=2))

    if existed:
        print(f"✓ .owlscale/ already exists at {owlscale_dir} (not overwriting)")
    else:
        print(f"✓ Initialized .owlscale/ at {owlscale_dir}")
        print("  Created: packets/, returns/, log/, templates/")
        print("  Created: state.json, roster.json")
    if project_name:
        print(f"  Project name: {project_name}")

    if hasattr(args, "register_defaults") and args.register_defaults:
        from owlscale.defaults import register_defaults
        registered = register_defaults(owlscale_dir, root)
        if registered:
            for agent_id, name, role in registered:
                print(f"  ✓ Registered {name} ({agent_id}) as {role}")
        else:
            print("  No new agents detected to register.")
        return

    if existed:
        return


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

    _refresh_context_safe(owlscale_dir, agent_id)


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
    _refresh_all_contexts_safe(owlscale_dir)


def cmd_accept(args):
    """Accept a returned task."""
    owlscale_dir = get_workspace_root()
    accept_task(owlscale_dir, args.task_id)
    print(f"✓ Accepted task '{args.task_id}'")
    _refresh_all_contexts_safe(owlscale_dir)


def cmd_reject(args):
    """Reject a returned task."""
    owlscale_dir = get_workspace_root()
    reject_task(owlscale_dir, args.task_id, reason=args.reason)
    print(f"✓ Rejected task '{args.task_id}'")
    if args.reason:
        print(f"  Reason: {args.reason}")
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
    from owlscale.export import export_training_data
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


def _print_lint_results(task_id: str, results, as_json: bool = False) -> bool:
    """Print lint results. Returns True if all passed."""
    from owlscale.lint import LintResult
    all_passed = all(r.passed for r in results)

    if as_json:
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


def cmd_whoami(args):
    """Print or refresh agent context file(s)."""
    owlscale_dir = get_workspace_root()

    if getattr(args, "all_agents", False):
        from owlscale.identity import refresh_all_contexts
        refresh_all_contexts(owlscale_dir)
        agents = list_agents(owlscale_dir)
        if not agents:
            print("No agents registered.")
            return
        for agent in sorted(agents, key=lambda a: a.id):
            path = owlscale_dir / "agents" / f"{agent.id}.md"
            print(f"  {agent.id}: {path}")
        return

    agent_id = getattr(args, "agent_id", None)
    if not agent_id:
        print("Usage: owlscale whoami <agent-id> | --all", file=sys.stderr)
        sys.exit(1)

    from owlscale.identity import refresh_agent_context, get_agent_context
    refresh_agent_context(owlscale_dir, agent_id)
    content = get_agent_context(owlscale_dir, agent_id)
    print(content)


def cmd_daemon_help(args):
    """Print daemon subcommand help."""
    print("Usage: owlscale daemon <run|start|stop|status|logs>")


def cmd_daemon_run(args):
    """Run daemon in foreground."""
    from owlscale.daemon import run_daemon
    owlscale_dir = get_workspace_root()
    print(f"Starting daemon (foreground, poll={args.poll}s) — Ctrl-C to stop")
    run_daemon(owlscale_dir, poll_interval=args.poll, drive_shell=args.drive_shell)


def cmd_daemon_start(args):
    """Start daemon in background."""
    from owlscale.daemon import start_daemon, get_daemon_status
    owlscale_dir = get_workspace_root()
    status = get_daemon_status(owlscale_dir)
    if status["running"]:
        print(f"owlscale daemon: already running (pid {status['pid']})")
        return
    pid = start_daemon(owlscale_dir, poll_interval=args.poll, drive_shell=args.drive_shell)
    print(f"✓ owlscale daemon started (pid {pid})")


def cmd_daemon_stop(args):
    """Stop background daemon."""
    from owlscale.daemon import stop_daemon
    owlscale_dir = get_workspace_root()
    stopped = stop_daemon(owlscale_dir)
    if stopped:
        print("✓ owlscale daemon stopped")
    else:
        print("owlscale daemon: not running")


def cmd_daemon_status(args):
    """Show daemon status."""
    from owlscale.daemon import get_daemon_status
    owlscale_dir = get_workspace_root()
    s = get_daemon_status(owlscale_dir)
    if s["running"]:
        print(f"owlscale daemon: running (pid {s['pid']})")
        if s["started_at"]:
            print(f"  started:  {s['started_at']}")
        if s["poll_interval"] is not None:
            print(f"  poll:     {s['poll_interval']}s")
        if s["mode"]:
            print(f"  mode:     {s['mode']}")
        print(f"  triggers: {s['trigger_seq']}")
    else:
        print("owlscale daemon: not running")


def cmd_daemon_logs(args):
    """Tail daemon log."""
    from owlscale.daemon import tail_daemon_log
    owlscale_dir = get_workspace_root()
    lines = tail_daemon_log(owlscale_dir, n=args.n)
    if not lines:
        print("(no daemon log)")
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
