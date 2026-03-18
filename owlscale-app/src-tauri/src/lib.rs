use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::image::Image;
use tauri::{Emitter, Manager};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as AutostartExt};
use tauri_plugin_dialog::{DialogExt, FilePath};

mod config;
mod state_reader;
mod watcher;

use config::{load_config, save_config, AppConfig};
use state_reader::WorkspaceState;

pub struct AppState {
    pub workspace_state: Arc<Mutex<Option<WorkspaceState>>>,
    pub owlscale_dir: Arc<Mutex<Option<PathBuf>>>,
    pub config: Arc<Mutex<AppConfig>>,
    /// Task IDs that have already triggered a "returned" notification; prevents duplicates.
    pub seen_returned: Arc<Mutex<HashSet<String>>>,
    /// Cancel flag for the active file watcher thread; set to true to stop it.
    pub watcher_cancel: Arc<Mutex<Option<Arc<AtomicBool>>>>,
}

/// Walk parent directories from `cwd` to find `.owlscale/`, mirroring the
/// Python `get_workspace_root()` logic in `owlscale/core.py`.
fn find_owlscale_dir() -> Option<PathBuf> {
    let mut current = std::env::current_dir().ok()?;
    loop {
        let candidate = current.join(".owlscale");
        if candidate.exists() && candidate.is_dir() {
            return Some(candidate);
        }
        let parent = current.parent().map(|p| p.to_path_buf())?;
        current = parent;
    }
}

/// Search for the `owlscale` binary.
/// First checks PATH via `which`, then falls back to common install locations.
fn find_owlscale_binary() -> Result<String, String> {
    if let Ok(out) = std::process::Command::new("which").arg("owlscale").output() {
        if out.status.success() {
            let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !path.is_empty() {
                return Ok(path);
            }
        }
    }

    let home = std::env::var("HOME").unwrap_or_default();
    let candidates = [
        format!("{home}/.local/bin/owlscale"),
        format!("{home}/.poetry/bin/owlscale"),
        "/usr/local/bin/owlscale".to_string(),
        "/opt/homebrew/bin/owlscale".to_string(),
    ];

    for c in &candidates {
        if std::path::Path::new(c).exists() {
            return Ok(c.clone());
        }
    }

    Err("owlscale binary not found in PATH or known locations".to_string())
}

fn normalize_workspace_dir(path: &Path) -> PathBuf {
    if path.ends_with(".owlscale") {
        path.to_path_buf()
    } else {
        path.join(".owlscale")
    }
}

fn resolve_startup_workspace_dir(config: &AppConfig) -> Option<PathBuf> {
    if let Some(saved) = config.workspace_dir.as_deref() {
        let path = normalize_workspace_dir(Path::new(saved));
        if path.exists() && path.is_dir() {
            return Some(path);
        }
    }
    find_owlscale_dir()
}

/// Swap the menu-bar tray icon to reflect pending review count.
/// grey = idle, orange = tasks waiting for review.
pub(crate) fn update_tray_icon(app: &tauri::AppHandle, pending_review: usize) {
    let icon_bytes: &[u8] = if pending_review > 0 {
        include_bytes!("../icons/tray-review.png")
    } else {
        include_bytes!("../icons/tray-idle.png")
    };
    if let Ok(icon) = Image::from_bytes(icon_bytes) {
        if let Some(tray) = app.tray_by_id("main") {
            let _ = tray.set_icon(Some(icon));
        }
    }
}

/// Rebuild the tray menu dynamically to show pending review count and first 3 returned tasks.
pub(crate) fn rebuild_tray_menu(app: &tauri::AppHandle, state: &WorkspaceState) {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};

    let title = if state.pending_review > 0 {
        format!("owlscale \u{00b7} {} to review", state.pending_review)
    } else {
        "owlscale \u{00b7} idle".to_string()
    };

    let title_item = match MenuItem::<tauri::Wry>::with_id(app, "title", &title, false, None::<&str>) {
        Ok(v) => v, Err(_) => return,
    };
    let sep1 = match PredefinedMenuItem::<tauri::Wry>::separator(app) {
        Ok(v) => v, Err(_) => return,
    };
    let show_item = match MenuItem::<tauri::Wry>::with_id(app, "show", "Show Window", true, None::<&str>) {
        Ok(v) => v, Err(_) => return,
    };
    let quit_item = match MenuItem::<tauri::Wry>::with_id(app, "quit", "Quit", true, None::<&str>) {
        Ok(v) => v, Err(_) => return,
    };

    let returned: Vec<_> = state.tasks.iter()
        .filter(|t| t.status == "returned")
        .take(3)
        .collect();

    let task_items: Vec<MenuItem<tauri::Wry>> = returned.iter()
        .filter_map(|t| {
            let label = format!("\u{21a9} {}", &t.id);
            MenuItem::<tauri::Wry>::with_id(app, format!("task-{}", t.id), label, true, None::<&str>).ok()
        })
        .collect();

    let sep2 = match PredefinedMenuItem::<tauri::Wry>::separator(app) {
        Ok(v) => v, Err(_) => return,
    };

    let mut items: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> = vec![&title_item, &sep1];
    for ti in &task_items {
        items.push(ti);
    }
    if !task_items.is_empty() {
        items.push(&sep2);
    }
    items.push(&show_item);
    items.push(&quit_item);

    if let Ok(menu) = Menu::<tauri::Wry>::with_items(app, &items) {
        if let Some(tray) = app.tray_by_id("main") {
            let _ = tray.set_menu(Some(menu));
        }
    }
}

// ─── Tauri commands ───────────────────────────────────────────────────────────

#[tauri::command]
fn get_workspace_state(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<WorkspaceState, String> {
    let guard = state.workspace_state.lock().map_err(|e| e.to_string())?;
    let ws = guard
        .clone()
        .ok_or_else(|| "No workspace loaded — call set_workspace_dir first".to_string())?;
    let pending = ws.pending_review;
    drop(guard);
    update_tray_icon(&app, pending);
    Ok(ws)
}

#[tauri::command]
fn get_settings(state: tauri::State<'_, AppState>) -> Result<AppConfig, String> {
    let config = state.config.lock().map_err(|e| e.to_string())?;
    Ok(config.clone())
}

#[tauri::command]
fn get_task_packet(task_id: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let owlscale_dir = state
        .owlscale_dir
        .lock()
        .map_err(|e| e.to_string())?
        .clone()
        .ok_or_else(|| "No workspace loaded — call set_workspace_dir first".to_string())?;
    state_reader::read_task_packet(&owlscale_dir, &task_id)
}

#[tauri::command]
fn accept_task(task_id: String) -> Result<(), String> {
    let owlscale = find_owlscale_binary()?;
    let out = std::process::Command::new(&owlscale)
        .args(["accept", &task_id])
        .output()
        .map_err(|e| format!("failed to run owlscale: {e}"))?;

    if out.status.success() {
        Ok(())
    } else {
        Err(format!(
            "owlscale accept failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ))
    }
}

#[tauri::command]
fn reject_task(task_id: String, reason: Option<String>) -> Result<(), String> {
    let owlscale = find_owlscale_binary()?;
    let mut cmd = std::process::Command::new(&owlscale);
    cmd.arg("reject").arg(&task_id);
    if let Some(r) = reason {
        cmd.arg(r);
    }
    let out = cmd
        .output()
        .map_err(|e| format!("failed to run owlscale: {e}"))?;

    if out.status.success() {
        Ok(())
    } else {
        Err(format!(
            "owlscale reject failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ))
    }
}

#[tauri::command]
fn set_workspace_dir(
    path: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = normalize_workspace_dir(Path::new(&path));

    if !owlscale_dir.exists() {
        return Err(format!("No .owlscale/ found at {path}"));
    }

    let ws = state_reader::read_workspace_state(&owlscale_dir)?;
    // Stop the old watcher before starting a new one
    if let Ok(mut cancel_guard) = state.watcher_cancel.lock() {
        if let Some(old_cancel) = cancel_guard.take() {
            old_cancel.store(true, Ordering::Relaxed);
        }
    }

    let config_to_save = {
        let mut ws_guard = state.workspace_state.lock().map_err(|e| e.to_string())?;
        *ws_guard = Some(ws.clone());

        let mut dir_guard = state.owlscale_dir.lock().map_err(|e| e.to_string())?;
        *dir_guard = Some(owlscale_dir.clone());

        let mut config_guard = state.config.lock().map_err(|e| e.to_string())?;
        config_guard.workspace_dir = Some(owlscale_dir.display().to_string());

        let mut seen_guard = state.seen_returned.lock().map_err(|e| e.to_string())?;
        seen_guard.clear();

        config_guard.clone()
    };
    save_config(&config_to_save);

    update_tray_icon(&app, ws.pending_review);
    rebuild_tray_menu(&app, &ws);
    app.emit("owlscale://state-changed", &ws)
        .map_err(|e| e.to_string())?;
    let cancel = watcher::start_watcher(owlscale_dir, app, Arc::clone(&state.workspace_state));
    if let Ok(mut cancel_guard) = state.watcher_cancel.lock() {
        *cancel_guard = Some(cancel);
    }
    Ok(())
}

#[tauri::command]
fn set_launch_at_login(
    enabled: bool,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    if enabled {
        app.autolaunch()
            .enable()
            .map_err(|e| format!("enable autostart failed: {e}"))?;
    } else {
        app.autolaunch()
            .disable()
            .map_err(|e| format!("disable autostart failed: {e}"))?;
    }

    let config_to_save = {
        let mut config_guard = state.config.lock().map_err(|e| e.to_string())?;
        config_guard.launch_at_login = enabled;
        config_guard.clone()
    };
    save_config(&config_to_save);
    Ok(())
}

#[tauri::command]
fn pick_workspace_dir(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let selected = app.dialog().file().blocking_pick_folder();
    Ok(selected.and_then(|path| match path {
        FilePath::Path(path_buf) => Some(path_buf.to_string_lossy().into_owned()),
        FilePath::Url(url) => url
            .to_file_path()
            .ok()
            .map(|path_buf| path_buf.to_string_lossy().into_owned()),
    }))
}

#[tauri::command]
fn open_workspace_in_terminal(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    use tauri_plugin_shell::ShellExt;

    let dir = state
        .owlscale_dir
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| "no workspace loaded".to_string())?;

    // Open the parent of .owlscale/ (the project root) in Terminal.app
    let project_root = dir
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| dir.clone());

    let path_str = project_root
        .to_str()
        .ok_or_else(|| "invalid workspace path".to_string())?;

    app.shell()
        .command("open")
        .args(["-a", "Terminal", path_str])
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

// ─── App entry point ─────────────────────────────────────────────────────────

pub fn run() {
    let config = load_config();
    let app_state = AppState {
        workspace_state: Arc::new(Mutex::new(None)),
        owlscale_dir: Arc::new(Mutex::new(None)),
        config: Arc::new(Mutex::new(config.clone())),
        seen_returned: Arc::new(Mutex::new(HashSet::new())),
        watcher_cancel: Arc::new(Mutex::new(None)),
    };

    // Prefer saved config workspace and fall back to auto-detect from cwd.
    if let Some(owlscale_dir) = resolve_startup_workspace_dir(&config) {
        if let Ok(ws) = state_reader::read_workspace_state(&owlscale_dir) {
            *app_state.workspace_state.lock().unwrap() = Some(ws);
        }
        *app_state.owlscale_dir.lock().unwrap() = Some(owlscale_dir);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(app_state)
        .setup(|app| {
            let state = app.state::<AppState>();
            let owlscale_dir = state.owlscale_dir.lock().unwrap().clone();

            // Start the file watcher if a workspace was detected
            if let Some(dir) = owlscale_dir {
                let cancel = watcher::start_watcher(
                    dir,
                    app.handle().clone(),
                    Arc::clone(&state.workspace_state),
                );
                if let Ok(mut guard) = state.watcher_cancel.lock() {
                    *guard = Some(cancel);
                }
            }

            // ── System tray (id = "main" so update_tray_icon can find it) ──
            let icon_bytes = include_bytes!("../icons/tray-idle.png");
            let icon =
                Image::from_bytes(icon_bytes).map_err(|e| format!("tray icon error: {e}"))?;

            let show_item =
                tauri::menu::MenuItem::with_id(app, "show", "Show", true, None::<&str>)?;
            let quit_item =
                tauri::menu::MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = tauri::menu::Menu::with_items(app, &[&show_item, &quit_item])?;

            tauri::tray::TrayIconBuilder::with_id("main")
                .icon(icon)
                .tooltip("owlscale")
                .menu(&menu)
                .on_menu_event(|app: &tauri::AppHandle, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    id if id.starts_with("task-") => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                        let task_id = id.strip_prefix("task-").unwrap_or("").to_string();
                        let _ = app.emit("owlscale://focus-task", task_id);
                    }
                    _ => {}
                })
                .build(app)?;

            // Rebuild tray menu with initial workspace state
            if let Ok(guard) = state.workspace_state.lock() {
                if let Some(ws) = guard.as_ref() {
                    rebuild_tray_menu(app.handle(), ws);
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_workspace_state,
            get_settings,
            get_task_packet,
            accept_task,
            reject_task,
            set_workspace_dir,
            set_launch_at_login,
            pick_workspace_dir,
            open_workspace_in_terminal,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
