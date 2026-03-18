# owlscale desktop app

`owlscale-app/` is the Tauri-based desktop companion for monitoring and reviewing an `owlscale` workspace.

## Prerequisites

- Node.js and npm
- Rust toolchain with Cargo
- Tauri CLI: `cargo install tauri-cli --version '^2'`
- macOS build tools (Xcode Command Line Tools) for `.app` bundle packaging

## Install dependencies

```bash
cd owlscale-app
npm install
```

## Run in development

```bash
cd owlscale-app
cargo tauri dev
```

The desktop app expects an `.owlscale/` workspace in the current directory or one of its parent directories. If none is found, use the settings panel to pick a workspace after launch.

## Build a production macOS app

```bash
cd owlscale-app
cargo tauri build
```

Output bundle:

```text
owlscale-app/src-tauri/target/release/bundle/macos/owlscale.app
```

## Notes

- `cargo tauri build` runs `npm run build` automatically via `src-tauri/tauri.conf.json`.
- macOS signing and notarization are intentionally not configured in this repository yet; builds are unsigned local bundles.
