# owlscale

Desktop-first local workspace for coordinating multiple AI coding agents.

`owlscale` is a local-first multi-agent workbench. The desktop app is the primary entry point for workspace selection, task dispatch, execution tracking, review, and recovery. Under the hood, `owlscale` uses a local `.owlscale/` workspace, a shared Rust protocol layer, and Git/worktree isolation to keep collaboration visible, controllable, and auditable.

## What it is

- A desktop-first control surface for local multi-agent collaboration
- A local workspace model built around `.owlscale/`
- A review-and-dispatch loop for coordinating coding agents
- A Git/worktree-aware system for parallel execution isolation

## What it is not

- Not a cloud orchestration platform
- Not a chat-first agent shell
- Not a Python CLI package
- Not a full autonomous system that removes the human coordinator

## Public repo layout

- `owlscale-app/` — Tauri v2 desktop app (Svelte 4 frontend, Rust backend)
- `owlscale-app/src-tauri/src/` — Rust: state aggregation, worktree registry, git_ops, Tauri commands
- `owlscale-app/src/` — Svelte: three-focus workbench UI

## Build

```bash
cd owlscale-app
npm install
npm run desktop:build   # or: cargo tauri build inside src-tauri/
```

Dev mode:

```bash
npm run desktop:dev
```

## Current status

v0.7.1-alpha. The desktop app ships a three-focus workbench (Review / Execution / Setup) with a status-aware inspector. The full create → dispatch → review (accept/reject) loop is usable. Worktree isolation is wired: coding worktrees are created and bound at dispatch time; review worktrees are created with an enforced owner from the workspace agent policy.

Derived state fields (review_worktree_ready, coding_worktree_missing, ownership_override, review_owner_id) are computed by the Rust backend and surfaced directly to the UI — the frontend does not re-derive business semantics from raw data.

Remaining before stable: Create Task UI, workspace picker dialog, and global agent registry layer.

`owlscale` is incubated privately and released to this public repo in stable slices. This public repository is the release surface and collaboration surface, not the full internal design workspace.

## Contributing expectations

- Bug fixes and focused improvements are welcome.
- Public contributions should target behavior that is already present in the public release surface.
- Large product-definition, protocol, or architecture shifts are curated before they land publicly.

## License

MIT
