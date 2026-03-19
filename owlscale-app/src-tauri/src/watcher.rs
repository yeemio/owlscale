use notify::{Config, RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};
use tauri_plugin_notification::NotificationExt;

use crate::state_reader::{read_workspace_state, WorkspaceState};
use crate::AppState;

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
            Ok(value) => value,
            Err(err) => {
                eprintln!("[owlscale watcher] failed to create watcher: {err}");
                return;
            }
        };

        if let Err(err) = watcher.watch(&owlscale_dir, RecursiveMode::Recursive) {
            eprintln!(
                "[owlscale watcher] failed to watch {}: {err}",
                owlscale_dir.display()
            );
            return;
        }

        let mut last_emit = Instant::now() - Duration::from_secs(10);
        let tasks_dir = owlscale_dir.join("tasks");
        let returns_dir = owlscale_dir.join("returns");
        let packets_dir = owlscale_dir.join("packets");

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
                    let is_relevant = event.paths.iter().any(|path| {
                        path.starts_with(&tasks_dir)
                            || path.starts_with(&returns_dir)
                            || path.starts_with(&packets_dir)
                            || matches!(
                                file_name(path),
                                Some("roster.json") | Some("state.json") | Some("worktrees.json")
                            )
                    });
                    if !is_relevant {
                        continue;
                    }

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
                            if let Err(err) =
                                app_handle.emit("owlscale://state-changed", &new_state)
                            {
                                eprintln!("[owlscale watcher] emit error: {err}");
                            }
                            crate::update_tray_icon(&app_handle, new_state.pending_review);
                            crate::rebuild_tray_menu(&app_handle, &new_state);

                            if new_state.pending_review > 0 {
                                notify_new_returned(&app_handle, &new_state);
                            } else if let Some(app_state) = app_handle.try_state::<AppState>() {
                                if let Ok(mut seen) = app_state.seen_returned.lock() {
                                    seen.retain(|id| {
                                        new_state
                                            .tasks
                                            .iter()
                                            .any(|task| &task.id == id && task.status == "returned")
                                    });
                                }
                            }
                        }
                        Err(err) => {
                            eprintln!("[owlscale watcher] re-read failed: {err}");
                        }
                    }
                }
                Ok(Err(err)) => {
                    eprintln!("[owlscale watcher] watch error: {err}");
                }
                Err(_) => {}
            }
        }
    });
    cancel
}

fn file_name(path: &Path) -> Option<&str> {
    path.file_name().and_then(|value| value.to_str())
}

fn notify_new_returned(app: &tauri::AppHandle, state: &WorkspaceState) {
    let returned_ids: HashSet<String> = state
        .tasks
        .iter()
        .filter(|task| task.status == "returned")
        .map(|task| task.id.clone())
        .collect();

    let app_state = match app.try_state::<AppState>() {
        Some(value) => value,
        None => return,
    };
    let mut seen = match app_state.seen_returned.lock() {
        Ok(value) => value,
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

    *seen = returned_ids;
}
