use owlscale_protocol::{
    create_task as protocol_create_task, load_task, now_iso8601, transition_task,
    validate_context_packet_text, validate_return_packet_text,
};
use std::collections::HashSet;
use std::fs;
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
    pub seen_returned: Arc<Mutex<HashSet<String>>>,
    pub watcher_cancel: Arc<Mutex<Option<Arc<AtomicBool>>>>,
}

fn find_owlscale_dir() -> Option<PathBuf> {
    let mut current = std::env::current_dir().ok()?;
    loop {
        let candidate = current.join(".owlscale");
        if candidate.exists() && candidate.is_dir() {
            return Some(candidate);
        }
        let parent = current.parent().map(|value| value.to_path_buf())?;
        current = parent;
    }
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

pub(crate) fn rebuild_tray_menu(app: &tauri::AppHandle, state: &WorkspaceState) {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};

    let title = if state.pending_review > 0 {
        format!("owlscale · {} to review", state.pending_review)
    } else {
        "owlscale · idle".to_string()
    };

    let title_item =
        match MenuItem::<tauri::Wry>::with_id(app, "title", &title, false, None::<&str>) {
            Ok(value) => value,
            Err(_) => return,
        };
    let sep1 = match PredefinedMenuItem::<tauri::Wry>::separator(app) {
        Ok(value) => value,
        Err(_) => return,
    };
    let show_item =
        match MenuItem::<tauri::Wry>::with_id(app, "show", "Show Window", true, None::<&str>) {
            Ok(value) => value,
            Err(_) => return,
        };
    let quit_item = match MenuItem::<tauri::Wry>::with_id(app, "quit", "Quit", true, None::<&str>) {
        Ok(value) => value,
        Err(_) => return,
    };

    let returned: Vec<_> = state
        .tasks
        .iter()
        .filter(|task| task.status == "returned")
        .take(3)
        .collect();
    let task_items: Vec<MenuItem<tauri::Wry>> = returned
        .iter()
        .filter_map(|task| {
            let label = format!("↩ {}", task.id);
            MenuItem::<tauri::Wry>::with_id(
                app,
                format!("task-{}", task.id),
                label,
                true,
                None::<&str>,
            )
            .ok()
        })
        .collect();
    let sep2 = match PredefinedMenuItem::<tauri::Wry>::separator(app) {
        Ok(value) => value,
        Err(_) => return,
    };

    let mut items: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> = vec![&title_item, &sep1];
    for item in &task_items {
        items.push(item);
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

fn current_owlscale_dir(state: &tauri::State<'_, AppState>) -> Result<PathBuf, String> {
    state
        .owlscale_dir
        .lock()
        .map_err(|err| err.to_string())?
        .clone()
        .ok_or_else(|| "No workspace loaded — call set_workspace_dir first".to_string())
}

fn emit_workspace_refresh(
    state: &tauri::State<'_, AppState>,
    app: &tauri::AppHandle,
    owlscale_dir: &Path,
) -> Result<(), String> {
    let workspace = state_reader::read_workspace_state(owlscale_dir)?;
    {
        let mut guard = state
            .workspace_state
            .lock()
            .map_err(|err| err.to_string())?;
        *guard = Some(workspace.clone());
    }
    update_tray_icon(app, workspace.pending_review);
    rebuild_tray_menu(app, &workspace);
    app.emit("owlscale://state-changed", &workspace)
        .map_err(|err| err.to_string())
}

fn build_context_packet(task_id: &str, goal: &str, assignee: &str) -> String {
    format!(
        "---\nid: {}\ngoal: {}\nassignee: {}\ncreated_at: {}\n---\n\n# Context\n\n{}\n",
        yaml_scalar(task_id),
        yaml_scalar(goal),
        yaml_scalar(assignee),
        now_iso8601(),
        goal
    )
}

fn yaml_scalar(value: &str) -> String {
    format!("{value:?}")
}

fn build_return_packet(task_id: &str, summary: &str, files_changed: &[String]) -> String {
    let mut packet = format!(
        "---\nid: {}\nsummary: {}\nfiles_changed:\n",
        yaml_scalar(task_id),
        yaml_scalar(summary)
    );
    for path in files_changed {
        packet.push_str(&format!("  - {}\n", yaml_scalar(path)));
    }
    packet.push_str(&format!(
        "generated_at: {}\n---\n\n# Return\n\n{}\n",
        now_iso8601(),
        summary
    ));
    packet
}

#[tauri::command]
fn get_workspace_state(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<WorkspaceState, String> {
    let guard = state
        .workspace_state
        .lock()
        .map_err(|err| err.to_string())?;
    let workspace = guard
        .clone()
        .ok_or_else(|| "No workspace loaded — call set_workspace_dir first".to_string())?;
    let pending = workspace.pending_review;
    drop(guard);
    update_tray_icon(&app, pending);
    Ok(workspace)
}

#[tauri::command]
fn get_settings(state: tauri::State<'_, AppState>) -> Result<AppConfig, String> {
    let config = state.config.lock().map_err(|err| err.to_string())?;
    Ok(config.clone())
}

#[tauri::command]
fn get_task_packet(task_id: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    state_reader::read_task_packet(&owlscale_dir, &task_id)
}

#[tauri::command]
fn get_return_packet(task_id: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    state_reader::read_return_packet(&owlscale_dir, &task_id)
}

#[tauri::command]
fn create_task(
    task_id: String,
    goal: String,
    assignee: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    let task_id = task_id.trim().to_string();
    let goal = goal.trim().to_string();
    let assignee = assignee.trim().to_string();

    if task_id.is_empty() {
        return Err("Task ID is required.".to_string());
    }
    if goal.is_empty() {
        return Err("Goal is required.".to_string());
    }
    if assignee.is_empty() {
        return Err("Assignee is required.".to_string());
    }

    let task_path = owlscale_dir.join("tasks").join(format!("{task_id}.json"));
    if task_path.exists() {
        return Err(format!("Task '{task_id}' already exists."));
    }

    let packet_relative = format!(".owlscale/packets/{task_id}.md");
    let packet_path = owlscale_dir
        .parent()
        .unwrap_or(&owlscale_dir)
        .join(&packet_relative);
    if packet_path.exists() {
        return Err(format!("Packet '{packet_relative}' already exists."));
    }

    let packet_content = build_context_packet(&task_id, &goal, &assignee);
    let validation = validate_context_packet_text(&packet_content, Some(&task_id));
    if !validation.valid {
        return Err(format!(
            "Context Packet invalid: {}",
            validation.errors.join("; ")
        ));
    }

    fs::write(&packet_path, packet_content).map_err(|err| err.to_string())?;
    protocol_create_task(
        &owlscale_dir,
        &task_id,
        Some(packet_relative),
        None,
        Some(assignee),
        None,
    )
    .map_err(|err| err.to_string())?;

    emit_workspace_refresh(&state, &app, &owlscale_dir)
}

#[tauri::command]
fn dispatch_task(
    task_id: String,
    assignee: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    let current = load_task(&owlscale_dir, &task_id).map_err(|err| err.to_string())?;
    let final_assignee = assignee
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .or_else(|| current.assignee.clone())
        .ok_or_else(|| "Dispatch requires assignee.".to_string())?;

    transition_task(
        &owlscale_dir,
        &task_id,
        "dispatched",
        Some(current.version),
        Some(final_assignee),
        current.worktree_id.clone(),
        None,
        None,
    )
    .map_err(|err| err.to_string())?;

    emit_workspace_refresh(&state, &app, &owlscale_dir)
}

#[tauri::command]
fn start_task(
    task_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    let current = load_task(&owlscale_dir, &task_id).map_err(|err| err.to_string())?;
    transition_task(
        &owlscale_dir,
        &task_id,
        "in_progress",
        Some(current.version),
        None,
        None,
        None,
        None,
    )
    .map_err(|err| err.to_string())?;

    emit_workspace_refresh(&state, &app, &owlscale_dir)
}

#[tauri::command]
fn return_task(
    task_id: String,
    summary: String,
    files_changed: Vec<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    let current = load_task(&owlscale_dir, &task_id).map_err(|err| err.to_string())?;
    let summary = summary.trim().to_string();
    if summary.is_empty() {
        return Err("Return summary is required.".to_string());
    }

    let files_changed: Vec<String> = files_changed
        .into_iter()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .collect();
    if files_changed.is_empty() {
        return Err("At least one changed file is required.".to_string());
    }

    let return_relative = format!(".owlscale/returns/{task_id}.md");
    let return_path = owlscale_dir
        .parent()
        .unwrap_or(&owlscale_dir)
        .join(&return_relative);
    let packet_content = build_return_packet(&task_id, &summary, &files_changed);
    let validation = validate_return_packet_text(&packet_content, Some(&task_id));
    if !validation.valid {
        return Err(format!(
            "Return Packet invalid: {}",
            validation.errors.join("; ")
        ));
    }

    fs::write(&return_path, packet_content).map_err(|err| err.to_string())?;
    transition_task(
        &owlscale_dir,
        &task_id,
        "returned",
        Some(current.version),
        None,
        None,
        Some(return_relative),
        None,
    )
    .map_err(|err| err.to_string())?;

    emit_workspace_refresh(&state, &app, &owlscale_dir)
}

#[tauri::command]
fn accept_task(
    task_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    let current = load_task(&owlscale_dir, &task_id).map_err(|err| err.to_string())?;
    transition_task(
        &owlscale_dir,
        &task_id,
        "accepted",
        Some(current.version),
        None,
        None,
        None,
        None,
    )
    .map_err(|err| err.to_string())?;
    emit_workspace_refresh(&state, &app, &owlscale_dir)
}

#[tauri::command]
fn reject_task(
    task_id: String,
    reason: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    let current = load_task(&owlscale_dir, &task_id).map_err(|err| err.to_string())?;
    transition_task(
        &owlscale_dir,
        &task_id,
        "rejected",
        Some(current.version),
        None,
        None,
        None,
        reason,
    )
    .map_err(|err| err.to_string())?;
    emit_workspace_refresh(&state, &app, &owlscale_dir)
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

    let workspace = state_reader::read_workspace_state(&owlscale_dir)?;
    if let Ok(mut cancel_guard) = state.watcher_cancel.lock() {
        if let Some(old_cancel) = cancel_guard.take() {
            old_cancel.store(true, Ordering::Relaxed);
        }
    }

    let config_to_save = {
        let mut workspace_guard = state
            .workspace_state
            .lock()
            .map_err(|err| err.to_string())?;
        *workspace_guard = Some(workspace.clone());

        let mut dir_guard = state.owlscale_dir.lock().map_err(|err| err.to_string())?;
        *dir_guard = Some(owlscale_dir.clone());

        let mut config_guard = state.config.lock().map_err(|err| err.to_string())?;
        config_guard.workspace_dir = Some(owlscale_dir.display().to_string());

        let mut seen_guard = state.seen_returned.lock().map_err(|err| err.to_string())?;
        seen_guard.clear();

        config_guard.clone()
    };
    save_config(&config_to_save);

    update_tray_icon(&app, workspace.pending_review);
    rebuild_tray_menu(&app, &workspace);
    app.emit("owlscale://state-changed", &workspace)
        .map_err(|err| err.to_string())?;
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
            .map_err(|err| format!("enable autostart failed: {err}"))?;
    } else {
        app.autolaunch()
            .disable()
            .map_err(|err| format!("disable autostart failed: {err}"))?;
    }

    let config_to_save = {
        let mut config_guard = state.config.lock().map_err(|err| err.to_string())?;
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
        .map_err(|err| err.to_string())?
        .clone()
        .ok_or_else(|| "no workspace loaded".to_string())?;
    let project_root = dir
        .parent()
        .map(|value| value.to_path_buf())
        .unwrap_or_else(|| dir.clone());
    let path_str = project_root
        .to_str()
        .ok_or_else(|| "invalid workspace path".to_string())?;

    app.shell()
        .command("open")
        .args(["-a", "Terminal", path_str])
        .spawn()
        .map(|_| ())
        .map_err(|err| err.to_string())
}

pub fn run() {
    let config = load_config();
    let app_state = AppState {
        workspace_state: Arc::new(Mutex::new(None)),
        owlscale_dir: Arc::new(Mutex::new(None)),
        config: Arc::new(Mutex::new(config.clone())),
        seen_returned: Arc::new(Mutex::new(HashSet::new())),
        watcher_cancel: Arc::new(Mutex::new(None)),
    };

    if let Some(owlscale_dir) = resolve_startup_workspace_dir(&config) {
        if let Ok(workspace) = state_reader::read_workspace_state(&owlscale_dir) {
            *app_state.workspace_state.lock().unwrap() = Some(workspace);
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

            let icon_bytes = include_bytes!("../icons/tray-idle.png");
            let icon =
                Image::from_bytes(icon_bytes).map_err(|err| format!("tray icon error: {err}"))?;
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
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    id if id.starts_with("task-") => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                        let task_id = id.strip_prefix("task-").unwrap_or("").to_string();
                        let _ = app.emit("owlscale://focus-task", task_id);
                    }
                    _ => {}
                })
                .build(app)?;

            if let Ok(guard) = state.workspace_state.lock() {
                if let Some(workspace) = guard.as_ref() {
                    rebuild_tray_menu(app.handle(), workspace);
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_workspace_state,
            get_settings,
            get_task_packet,
            get_return_packet,
            create_task,
            dispatch_task,
            start_task,
            return_task,
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
