use notify::{Config, RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};
use tauri_plugin_notification::NotificationExt;

use crate::state_reader::{read_workspace_state, WorkspaceState};
use crate::AppState;

/// Spawn a background thread that watches `owlscale_dir` for changes to
/// `state.json` or `roster.json`. On each relevant change (debounced to
/// 500 ms):
///   1. Re-reads the workspace state and updates `workspace_state`.
///   2. Emits `"owlscale://state-changed"` with the new payload.
///   3. Updates the menu-bar tray icon.
///   4. Fires macOS notifications for newly-returned tasks.
pub fn start_watcher(
    owlscale_dir: PathBuf,
    app_handle: tauri::AppHandle,
    workspace_state: Arc<Mutex<Option<WorkspaceState>>>,
) -> Arc<AtomicBool> {
    let cancel = Arc::new(AtomicBool::new(false));
    let cancel_clone = cancel.clone();
    std::thread::spawn(move || {
        let (tx, rx) = std::sync::mpsc::channel::<notify::Result<notify::Event>>();

        let mut watcher = match RecommendedWatcher::new(tx, Config::default()) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("[owlscale watcher] failed to create watcher: {e}");
                return;
            }
        };

        if let Err(e) = watcher.watch(&owlscale_dir, RecursiveMode::NonRecursive) {
            eprintln!(
                "[owlscale watcher] failed to watch {}: {e}",
                owlscale_dir.display()
            );
            return;
        }

        // Allow first event immediately
        let mut last_emit = Instant::now() - Duration::from_secs(10);

        loop {
            if cancel_clone.load(Ordering::Relaxed) {
                break;
            }
            let result = rx.recv_timeout(Duration::from_millis(500));
            if cancel_clone.load(Ordering::Relaxed) {
                break;
            }
            match result {
                Ok(Ok(event)) => {
                    let is_relevant = event.paths.iter().any(|p| {
                        p.file_name()
                            .and_then(|n| n.to_str())
                            .map(|n| n == "state.json" || n == "roster.json")
                            .unwrap_or(false)
                    });

                    if !is_relevant {
                        continue;
                    }

                    // Debounce: skip if last emit was < 500 ms ago
                    let now = Instant::now();
                    if now.duration_since(last_emit) < Duration::from_millis(500) {
                        continue;
                    }
                    last_emit = now;

                    match read_workspace_state(&owlscale_dir) {
                        Ok(new_state) => {
                            if let Ok(mut guard) = workspace_state.lock() {
                                *guard = Some(new_state.clone());
                            }

                            if let Err(e) =
                                app_handle.emit("owlscale://state-changed", &new_state)
                            {
                                eprintln!("[owlscale watcher] emit error: {e}");
                            }

                            // Update tray icon to reflect pending review count
                            crate::update_tray_icon(&app_handle, new_state.pending_review);

                            // ── Notifications ──────────────────────────────
                            if new_state.pending_review > 0 {
                                notify_new_returned(&app_handle, &new_state);
                            } else {
                                // All tasks left 'returned' — clear seen set
                                if let Some(app_state) =
                                    app_handle.try_state::<AppState>()
                                {
                                    if let Ok(mut seen) =
                                        app_state.seen_returned.lock()
                                    {
                                        seen.retain(|id| {
                                            new_state
                                                .tasks
                                                .iter()
                                                .any(|t| &t.id == id && t.status == "returned")
                                        });
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            eprintln!("[owlscale watcher] re-read failed: {e}");
                        }
                    }
                }
                Ok(Err(e)) => {
                    eprintln!("[owlscale watcher] watch error: {e}");
                }
                Err(_timeout) => {
                    // Normal timeout — just loop and check cancel flag
                }
            }
        }
    });
    cancel
}

/// Fire one macOS notification per task that newly transitioned to `returned`.
/// Tasks already in `seen_returned` are skipped to prevent duplicates.
fn notify_new_returned(app: &tauri::AppHandle, state: &WorkspaceState) {
    let returned_ids: HashSet<String> = state
        .tasks
        .iter()
        .filter(|t| t.status == "returned")
        .map(|t| t.id.clone())
        .collect();

    let app_state = match app.try_state::<AppState>() {
        Some(s) => s,
        None => return,
    };

    let mut seen = match app_state.seen_returned.lock() {
        Ok(g) => g,
        Err(_) => return,
    };

    for task_id in returned_ids.difference(&*seen) {
        let _ = app
            .notification()
            .builder()
            .title("owlscale")
            .body(format!("{task_id} is ready for review"))
            .show();
    }

    // Replace seen set with current returned IDs so accepted/rejected tasks
    // can re-notify if they ever return again.
    *seen = returned_ids;
}


