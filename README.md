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

- `crates/owlscale-protocol/` — shared Rust protocol crate and CLI
- `owlscale-app/` — Tauri desktop app
- `docs/architecture.md` — public architecture note for this release surface

## Build

### Protocol CLI

```bash
cargo run -p owlscale-protocol --bin owlscale -- --help
```

### Desktop app

```bash
cd owlscale-app
npm install
cd src-tauri
cargo tauri build
```

## Current status

The protocol layer and first desktop task lifecycle slice are now public. The desktop app supports the full create → dispatch → start → return → review (accept/reject) loop. Worktree integration and real agent runtime binding are designed but not yet shipped in this public surface.

`owlscale` is incubated privately and released to this public repo in stable slices. This public repository is the release surface and collaboration surface, not the full internal design workspace.

## Contributing expectations

- Bug fixes and focused improvements are welcome.
- Public contributions should target behavior that is already present in the public release surface.
- Large product-definition, protocol, or architecture shifts are curated before they land publicly.

## License

MIT
