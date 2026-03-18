# owlscale

**File-level multi-agent task handoff protocol and CLI.**

owlscale is a lightweight coordination layer for teams of AI agents. It structures the handoff of work between agents using two primitives: a **Context Packet** (what to do and why) and a **Return Packet** (what was done and how). The state machine — `draft → dispatched → in_progress → returned → accepted/rejected` — lives in a single `.owlscale/` directory alongside your project files.

No server. No database. Just files and a CLI.

---

## Install

```bash
pip install owlscale
# or with pipx
pipx install owlscale
```

Requires Python 3.10+.

---

## Quick start

```bash
# See what AI tools are installed on your machine
owlscale detect

# Initialize workspace — auto-detects tools, suggests roster, optionally launches terminals
owlscale init

# Or watch a safe demo first (runs in a temp directory, never touches your files)
owlscale demo
```

`owlscale init` detects Claude Code, Copilot CLI, Codex, Cursor, and VSCode, suggests a roster, and optionally opens terminal windows for each agent — all in under 60 seconds.

```bash
# Monitor from your phone — LAN-accessible PWA, installable on iPhone home screen
owlscale serve          # → http://<your-lan-ip>:7331
```

---

## Full workflow

```bash
# Register agents manually (or let init do it)
owlscale roster add copilot --name "GitHub Copilot" --role executor
owlscale roster add cc      --name "Claude Code"    --role coordinator

# Launch agent terminals
owlscale launch cc
owlscale launch --all

# Create a task
owlscale pack implement-auth --goal "Add JWT authentication to the API"

# Dispatch to an agent
owlscale dispatch implement-auth copilot

# Agent claims it
owlscale claim implement-auth

# Agent returns results (after filling .owlscale/returns/implement-auth.md)
owlscale return implement-auth

# Review and accept
owlscale accept implement-auth

# See status
owlscale status
```

---

## How it works

### Context Packet

When you `pack` a task, owlscale creates `.owlscale/packets/<task-id>.md` — a structured markdown file containing:

- **Goal**: what the task is trying to achieve
- **Current State**: starting conditions
- **Execution Plan**: step-by-step approach
- **Scope**: what's in and out
- **Validation**: how to verify the result

The agent reads this file, does the work, fills in `.owlscale/returns/<task-id>.md`, and runs `owlscale return`.

### State machine

```
draft ──► dispatched ──► in_progress ──► returned ──► accepted
                                              │
                                              └──────► rejected
```

### Directory layout

```
your-project/
  .owlscale/
    state.json          # task status index
    roster.json         # registered agents
    packets/            # Context Packets (one per task)
    returns/            # Return Packets (agent output)
    log/                # daily operation log
    templates/          # custom packet templates
```

---

## CLI reference

```
owlscale init [--yes] [--no-launch] [--force]
                                       Initialize workspace with auto-detect
owlscale detect [--json]               Scan for AI tools and terminals
owlscale demo [--fast] [--no-color]    Self-contained onboarding walkthrough

owlscale roster add <id> --name --role Register an agent
owlscale roster list                   List agents
owlscale launch <agent-id>             Open terminal for an agent
owlscale launch --all                  Open terminals for all agents

owlscale pack <id> --goal <text>       Create a Context Packet
owlscale dispatch <id> <agent>         Dispatch task to agent
owlscale claim <id>                    Claim task (→ in_progress)
owlscale return <id>                   Submit return packet
owlscale accept <id>                   Accept result
owlscale reject <id> [--reason]        Reject result
owlscale status                        Show all task states
owlscale log [--task <id>]             Show operation log

owlscale validate <id>                 Validate a Context Packet
owlscale fmt <id>                      Format packet frontmatter
owlscale lint <id> / lint --all        Packet quality checks
owlscale diff <id-a> <id-b>            Diff two packets
owlscale stats                         Workspace statistics
owlscale history <id>                  Full task event timeline
owlscale prune [--days N] [--dry-run]  Archive old completed tasks

owlscale route <id>                    Suggest best agent (roster-based)
owlscale export [--output file.jsonl]  Export training data
owlscale git branch <id>               Show/create branch for task
owlscale git pr <id>                   Print gh pr create command
owlscale git status                    Task-to-branch mapping
owlscale alias set <alias> <agent-id>  Set agent alias
owlscale template list/show/add/remove Manage packet templates
owlscale watch                         Watch for status changes
```

---

## Design principles

- **Zero dependencies** — pure Python stdlib, no external packages
- **File-first** — all state is human-readable files; no lock-in
- **Agent-agnostic** — works with Claude, Copilot, GPT, local models, or humans
- **Git-native** — branch naming and PR commands built in
- **Composable** — export data for fine-tuning, pipe status to CI, webhook to Slack

---

## Changelog

### v0.5.0
- `owlscale serve`: mobile dashboard — LAN-accessible PWA (add to iPhone home screen, offline shell cache)
- Desktop client `owlscale-app`: macOS menu bar app (Tauri + Svelte), real-time file watcher, Accept/Reject with one click, macOS notifications, tray icon badge
- Skeleton loading, polished empty state, Accept/Reject micro-animations, agent activity indicator in desktop UI

### v0.4.0
- `owlscale init` redesigned: auto-detects tools, suggests roster, optional terminal launch (60s to ready)
- `owlscale detect`: scan for Claude Code, Copilot CLI, Codex, Cursor, VSCode, Ghostty, iTerm2, tmux
- `owlscale launch`: open Ghostty / iTerm2 / tmux / Terminal windows for registered agents
- `owlscale demo`: self-contained onboarding walkthrough in temp directory (no side effects)
- `Agent` model extended with `tool`, `delivery`, `launch` fields (roster v2, backward-compatible)
- Ghostty adapter: fix `\n` → Enter bug in shell driving

### v0.3.0
- Background daemon (`owlscale daemon`) for automatic task monitoring and shell driving
- Ghostty AppleScript adapter
- `owlscale history` — full task event timeline

### v0.2.0
- Agent identity system (`owlscale whoami`, per-agent context files)
- `owlscale route` — roster-based agent suggestion

### v0.1.0
- Core protocol: pack / dispatch / claim / return / accept / reject
- State machine, roster, log, validate, fmt, export

---

## License

MIT
