use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::image::Image;
use tauri::{Emitter, Manager};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as AutostartExt};
use tauri_plugin_dialog::{DialogExt, FilePath};

mod config;
mod git_ops;
mod state_reader;
mod watcher;
mod workspace_registry;
mod worktrees;

use config::{load_config, save_config, AppConfig};
use state_reader::{TaskEvent, WorkspaceState};
use workspace_registry::WorkspaceRegistryEntry;
use worktrees::RegisteredWorktree;

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

fn normalize_workspace_dir(path: &Path) -> PathBuf {
    if path.ends_with(".owlscale") {
        path.to_path_buf()
    } else {
        path.join(".owlscale")
    }
}

fn repo_root_from_common_dir(common_dir: &Path) -> Option<PathBuf> {
    if common_dir.file_name().and_then(|value| value.to_str()) == Some(".git") {
        return common_dir.parent().map(Path::to_path_buf);
    }

    for ancestor in common_dir.ancestors() {
        if ancestor.file_name().and_then(|value| value.to_str()) == Some(".git") {
            return ancestor.parent().map(Path::to_path_buf);
        }
    }

    None
}

fn git_workspace_root(path: &Path) -> Result<PathBuf, String> {
    let candidate = if path.ends_with(".owlscale") {
        path.parent().unwrap_or(path)
    } else {
        path
    };

    let output = Command::new("git")
        .arg("-C")
        .arg(candidate)
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .map_err(|e| format!("workspace_not_git: failed to run git: {e}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(format!(
            "workspace_not_git: choose a Git repository or a folder inside one{}",
            if stderr.is_empty() {
                String::new()
            } else {
                format!(" ({stderr})")
            }
        ));
    }

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if stdout.is_empty() {
        return Err("workspace_not_git: git returned an empty repository root".to_string());
    }

    let repo_root = PathBuf::from(stdout);
    let common_output = Command::new("git")
        .arg("-C")
        .arg(candidate)
        .args(["rev-parse", "--path-format=absolute", "--git-common-dir"])
        .output()
        .map_err(|e| format!("workspace_not_git: failed to inspect git common dir: {e}"))?;

    if !common_output.status.success() {
        return Ok(repo_root);
    }

    let common_stdout = String::from_utf8_lossy(&common_output.stdout)
        .trim()
        .to_string();
    if common_stdout.is_empty() {
        return Ok(repo_root);
    }

    let common_root = repo_root_from_common_dir(Path::new(&common_stdout));
    if let Some(root) = common_root {
        if root.join(".owlscale").is_dir() {
            return Ok(root);
        }
    }

    Ok(repo_root)
}

fn validated_workspace_dir(path: &Path) -> Result<PathBuf, String> {
    let repo_root = git_workspace_root(path)?;
    let owlscale_dir = normalize_workspace_dir(&repo_root);
    if !owlscale_dir.exists() {
        return Err(format!("No .owlscale/ found at {}", repo_root.display()));
    }
    Ok(owlscale_dir)
}

fn initialize_or_validate_workspace_dir(path: &Path) -> Result<PathBuf, String> {
    let repo_root = git_workspace_root(path)?;
    let owlscale_dir = normalize_workspace_dir(&repo_root);
    if owlscale_dir.exists() {
        validated_workspace_dir(&repo_root)
    } else {
        state_reader::initialize_workspace_direct(&repo_root)
    }
}

fn resolve_startup_workspace_dir(config: &AppConfig) -> Option<PathBuf> {
    if let Some(saved) = config.workspace_dir.as_deref() {
        if let Ok(path) = validated_workspace_dir(Path::new(saved)) {
            return Some(path);
        }
    }
    if let Ok(Some(project_root)) = workspace_registry::newest_ready_workspace() {
        if let Ok(path) = validated_workspace_dir(&project_root) {
            return Some(path);
        }
    }
    find_owlscale_dir().and_then(|dir| validated_workspace_dir(&dir).ok())
}

fn current_owlscale_dir(state: &tauri::State<'_, AppState>) -> Result<PathBuf, String> {
    state
        .owlscale_dir
        .lock()
        .map_err(|e| e.to_string())?
        .clone()
        .ok_or_else(|| "workspace_not_loaded: no workspace loaded".to_string())
}

fn required_review_agent_id(owlscale_dir: &Path) -> Result<String, String> {
    let workspace = state_reader::read_workspace_state(owlscale_dir)?;
    workspace
        .agent_policy
        .and_then(|policy| policy.default_review_agent_id)
        .ok_or_else(|| "ownership_required: default review agent is not configured".to_string())
}

fn refresh_workspace_state(
    state: &tauri::State<'_, AppState>,
    app: &tauri::AppHandle,
    owlscale_dir: &Path,
) -> Result<WorkspaceState, String> {
    let ws = state_reader::read_workspace_state(owlscale_dir)?;
    if let Ok(mut guard) = state.workspace_state.lock() {
        *guard = Some(ws.clone());
    }
    update_tray_icon(app, ws.pending_review);
    rebuild_tray_menu(app, &ws);
    app.emit("owlscale://state-changed", &ws)
        .map_err(|e| e.to_string())?;
    Ok(ws)
}

fn activate_workspace_dir(
    state: &tauri::State<'_, AppState>,
    app: &tauri::AppHandle,
    owlscale_dir: PathBuf,
) -> Result<(), String> {
    let ws = state_reader::read_workspace_state(&owlscale_dir)?;
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
    workspace_registry::upsert_workspace_registry(
        &owlscale_dir,
        &chrono::Local::now().to_rfc3339(),
    )?;

    update_tray_icon(app, ws.pending_review);
    rebuild_tray_menu(app, &ws);
    app.emit("owlscale://state-changed", &ws)
        .map_err(|e| e.to_string())?;
    let cancel = watcher::start_watcher(
        owlscale_dir,
        app.clone(),
        Arc::clone(&state.workspace_state),
    );
    if let Ok(mut cancel_guard) = state.watcher_cancel.lock() {
        *cancel_guard = Some(cancel);
    }
    Ok(())
}

fn ensure_task_status(owlscale_dir: &Path, task_id: &str, allowed: &[&str]) -> Result<(), String> {
    let workspace = state_reader::read_workspace_state(owlscale_dir)?;
    let task = workspace
        .tasks
        .iter()
        .find(|task| task.id == task_id)
        .ok_or_else(|| format!("Task '{task_id}' not found"))?;
    if allowed.iter().any(|status| *status == task.status) {
        Ok(())
    } else {
        Err(format!(
            "Task '{task_id}' is in '{}' state; expected one of: {}",
            task.status,
            allowed.join(", ")
        ))
    }
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

    let title_item =
        match MenuItem::<tauri::Wry>::with_id(app, "title", &title, false, None::<&str>) {
            Ok(v) => v,
            Err(_) => return,
        };
    let sep1 = match PredefinedMenuItem::<tauri::Wry>::separator(app) {
        Ok(v) => v,
        Err(_) => return,
    };
    let show_item =
        match MenuItem::<tauri::Wry>::with_id(app, "show", "Show Window", true, None::<&str>) {
            Ok(v) => v,
            Err(_) => return,
        };
    let quit_item = match MenuItem::<tauri::Wry>::with_id(app, "quit", "Quit", true, None::<&str>) {
        Ok(v) => v,
        Err(_) => return,
    };

    let returned: Vec<_> = state
        .tasks
        .iter()
        .filter(|t| t.status == "returned")
        .take(3)
        .collect();

    let task_items: Vec<MenuItem<tauri::Wry>> = returned
        .iter()
        .filter_map(|t| {
            let label = format!("\u{21a9} {}", &t.id);
            MenuItem::<tauri::Wry>::with_id(
                app,
                format!("task-{}", t.id),
                label,
                true,
                None::<&str>,
            )
            .ok()
        })
        .collect();

    let sep2 = match PredefinedMenuItem::<tauri::Wry>::separator(app) {
        Ok(v) => v,
        Err(_) => return,
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
fn set_agent_policy(
    execution_agent_id: Option<String>,
    review_agent_id: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<state_reader::AgentPolicy, String> {
    let dir = current_owlscale_dir(&state)?;
    let policy = state_reader::set_agent_policy_direct(
        &dir,
        execution_agent_id.as_deref(),
        review_agent_id.as_deref(),
    )?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(policy)
}

#[tauri::command]
fn get_task_packet(task_id: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    state_reader::read_task_packet(&owlscale_dir, &task_id)
}

#[tauri::command]
fn list_worktrees(state: tauri::State<'_, AppState>) -> Result<Vec<RegisteredWorktree>, String> {
    let owlscale_dir = current_owlscale_dir(&state)?;
    worktrees::list_worktrees(&owlscale_dir)
}

#[tauri::command]
fn accept_task(
    task_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let dir = current_owlscale_dir(&state)?;
    state_reader::accept_task_direct(&dir, &task_id)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(())
}

#[tauri::command]
fn reject_task(
    task_id: String,
    reason: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let dir = current_owlscale_dir(&state)?;
    state_reader::reject_task_direct(&dir, &task_id, reason.as_deref())?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(())
}

#[tauri::command]
fn set_workspace_dir(
    path: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let owlscale_dir = validated_workspace_dir(Path::new(&path))?;
    activate_workspace_dir(&state, &app, owlscale_dir)
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
async fn pick_workspace_dir(app: tauri::AppHandle) -> Result<Option<String>, String> {
    // async commands run off the main thread, preventing deadlock with macOS dialog
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
async fn open_workspace_picker(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<Option<String>, String> {
    let Some(selected) = pick_workspace_dir(app.clone()).await? else {
        return Ok(None);
    };
    let owlscale_dir = initialize_or_validate_workspace_dir(Path::new(&selected))?;
    activate_workspace_dir(&state, &app, owlscale_dir)?;
    let project_root = workspace_registry::project_root_from_owlscale(
        &state
            .owlscale_dir
            .lock()
            .map_err(|e| e.to_string())?
            .clone()
            .ok_or_else(|| "workspace_not_loaded: workspace activation failed".to_string())?,
    );
    Ok(Some(project_root.display().to_string()))
}

#[tauri::command]
fn get_workspace_registry() -> Result<Vec<WorkspaceRegistryEntry>, String> {
    workspace_registry::list_workspace_registry()
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

// ─── New commands ─────────────────────────────────────────────────────────────

#[tauri::command]
fn pack_task(
    task_id: String,
    goal: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let dir = current_owlscale_dir(&state)?;
    state_reader::create_task_direct(&dir, &goal, Some(&task_id))?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(())
}

#[tauri::command]
fn suggest_task_id(goal: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let dir = current_owlscale_dir(&state)?;
    state_reader::suggest_task_id_direct(&dir, &goal)
}

#[tauri::command]
fn create_task(
    goal: String,
    task_id: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<String, String> {
    let dir = current_owlscale_dir(&state)?;
    let final_task_id = state_reader::create_task_direct(&dir, &goal, task_id.as_deref())?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(final_task_id)
}

#[tauri::command]
fn dispatch_task(
    task_id: String,
    agent_id: String,
    worktree_mode: Option<String>,
    worktree_id: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let dir = current_owlscale_dir(&state)?;
    ensure_task_status(&dir, &task_id, &["draft", "ready"])?;
    let selected_worktree_id = match worktree_mode.as_deref() {
        Some("bind") => {
            let worktree_id = worktree_id
                .as_deref()
                .ok_or_else(|| "Select an existing worktree to bind.".to_string())?;
            let worktree = git_ops::ensure_registered_worktree_exists(&dir, worktree_id)?;
            let _ = worktrees::assign_worktree_agent(&dir, &worktree.id, Some(&agent_id))?;
            Some(worktree.id)
        }
        Some("create") | None => {
            let worktree = git_ops::create_coding_worktree(&dir, &task_id, Some(&agent_id))?;
            Some(worktree.id)
        }
        Some(other) => {
            return Err(format!("Unknown worktree mode '{other}'."));
        }
    };
    state_reader::dispatch_task_direct(&dir, &task_id, &agent_id, selected_worktree_id.as_deref())?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(())
}

#[tauri::command]
fn get_return_packet(task_id: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let dir = current_owlscale_dir(&state)?;
    state_reader::read_return_packet(&dir, &task_id)
}

#[tauri::command]
fn get_task_diff(task_id: String, state: tauri::State<'_, AppState>) -> Result<String, String> {
    let dir = current_owlscale_dir(&state)?;
    git_ops::get_task_coding_diff(&dir, &task_id)
}

#[tauri::command]
fn repair_coding_worktree(
    task_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<RegisteredWorktree, String> {
    let dir = current_owlscale_dir(&state)?;
    let worktree = git_ops::repair_coding_worktree(&dir, &task_id)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(worktree)
}

#[tauri::command]
fn get_task_timeline(
    task_id: Option<String>,
    state: tauri::State<'_, AppState>,
) -> Result<Vec<TaskEvent>, String> {
    let dir = current_owlscale_dir(&state)?;
    Ok(state_reader::read_task_events(&dir, task_id.as_deref()))
}

#[tauri::command]
fn create_coding_worktree(
    task_id: String,
    agent_id: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<RegisteredWorktree, String> {
    let dir = current_owlscale_dir(&state)?;
    ensure_task_status(&dir, &task_id, &["draft", "ready", "dispatched"])?;
    let worktree = git_ops::create_coding_worktree(&dir, &task_id, agent_id.as_deref())?;
    state_reader::bind_task_worktree_direct(&dir, &task_id, &worktree.id)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(worktree)
}

#[tauri::command]
fn bind_task_worktree(
    task_id: String,
    worktree_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let dir = current_owlscale_dir(&state)?;
    git_ops::ensure_registered_worktree_exists(&dir, &worktree_id)?;
    let workspace = state_reader::read_workspace_state(&dir)?;
    let agent_id = workspace
        .tasks
        .iter()
        .find(|task| task.id == task_id)
        .and_then(|task| task.assignee.clone());
    let _ = worktrees::assign_worktree_agent(&dir, &worktree_id, agent_id.as_deref())?;
    state_reader::bind_task_worktree_direct(&dir, &task_id, &worktree_id)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(())
}

#[tauri::command]
fn create_review_worktree(
    task_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<RegisteredWorktree, String> {
    let dir = current_owlscale_dir(&state)?;
    ensure_task_status(&dir, &task_id, &["returned"])?;
    let review_agent_id = required_review_agent_id(&dir)?;
    let worktree = git_ops::create_review_worktree(&dir, &task_id, &review_agent_id)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(worktree)
}

#[tauri::command]
fn rebase_review_worktree(
    task_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let dir = current_owlscale_dir(&state)?;
    ensure_task_status(&dir, &task_id, &["returned"])?;
    git_ops::rebase_review_worktree(&dir, &task_id)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(())
}

#[tauri::command]
fn dev_seed_returned_task(
    task_id: Option<String>,
    goal: String,
    summary: Option<String>,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<String, String> {
    let dir = current_owlscale_dir(&state)?;
    let final_task_id = state_reader::create_task_direct(&dir, &goal, task_id.as_deref())?;
    let review_agent_id = required_review_agent_id(&dir)?;
    let coding = git_ops::create_coding_worktree(&dir, &final_task_id, Some(&review_agent_id))?;
    state_reader::dispatch_task_direct(&dir, &final_task_id, &review_agent_id, Some(&coding.id))?;
    let return_summary = summary.unwrap_or_else(|| format!("Returned via dev seed for '{}'", goal));
    state_reader::mark_task_returned_direct(&dir, &final_task_id, &return_summary)?;
    refresh_workspace_state(&state, &app, &dir)?;
    Ok(final_task_id)
}

#[tauri::command]
fn open_worktree(
    worktree_id: String,
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    use tauri_plugin_shell::ShellExt;

    let dir = current_owlscale_dir(&state)?;
    let worktree = git_ops::ensure_registered_worktree_exists(&dir, &worktree_id)?;
    app.shell()
        .command("open")
        .args(["-a", "Terminal", &worktree.path])
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn manual_refresh(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<WorkspaceState, String> {
    let dir = current_owlscale_dir(&state)?;
    refresh_workspace_state(&state, &app, &dir)
}

#[tauri::command]
fn scan_workspaces() -> Vec<String> {
    state_reader::scan_common_workspaces()
}

#[tauri::command]
fn set_notifications_enabled(
    enabled: bool,
    state: tauri::State<'_, AppState>,
) -> Result<(), String> {
    let config_to_save = {
        let mut config = state.config.lock().map_err(|e| e.to_string())?;
        config.notifications_enabled = enabled;
        config.clone()
    };
    save_config(&config_to_save);
    Ok(())
}

#[tauri::command]
fn set_refresh_interval(secs: u64, state: tauri::State<'_, AppState>) -> Result<(), String> {
    let config_to_save = {
        let mut config = state.config.lock().map_err(|e| e.to_string())?;
        config.refresh_interval_secs = secs;
        config.clone()
    };
    save_config(&config_to_save);
    Ok(())
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
            set_agent_policy,
            get_task_packet,
            list_worktrees,
            accept_task,
            reject_task,
            pack_task,
            suggest_task_id,
            create_task,
            dispatch_task,
            get_return_packet,
            get_task_timeline,
            create_coding_worktree,
            bind_task_worktree,
            create_review_worktree,
            rebase_review_worktree,
            dev_seed_returned_task,
            open_worktree,
            manual_refresh,
            scan_workspaces,
            set_workspace_dir,
            set_launch_at_login,
            set_notifications_enabled,
            set_refresh_interval,
            pick_workspace_dir,
            open_workspace_picker,
            get_workspace_registry,
            open_workspace_in_terminal,
            get_task_diff,
            repair_coding_worktree,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::{
        git_workspace_root, initialize_or_validate_workspace_dir, normalize_workspace_dir,
        required_review_agent_id, validated_workspace_dir,
    };
    use crate::{git_ops, state_reader};
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::process::Command;
    use tempfile::TempDir;

    fn setup_workspace(state: &str) -> TempDir {
        let dir = TempDir::new().unwrap();
        let ws = dir.path().join(".owlscale");
        Command::new("git")
            .arg("init")
            .arg(dir.path())
            .output()
            .unwrap();
        fs::create_dir_all(ws.join("packets")).unwrap();
        fs::write(ws.join("state.json"), state).unwrap();
        fs::write(ws.join("roster.json"), r#"{"agents":{}}"#).unwrap();
        dir
    }

    #[test]
    fn required_review_agent_id_reads_default_review_agent() {
        let dir = setup_workspace(
            r#"{"version":1,"agent_policy":{"default_execution_agent_id":"exec-agent","default_review_agent_id":"review-agent"},"tasks":{}}"#,
        );
        let owlscale_dir = dir.path().join(".owlscale");
        let review_agent_id = required_review_agent_id(&owlscale_dir).unwrap();
        assert_eq!(review_agent_id, "review-agent");
    }

    #[test]
    fn required_review_agent_id_returns_ownership_required_when_missing() {
        let dir = setup_workspace(
            r#"{"version":1,"agent_policy":{"default_execution_agent_id":"exec-agent","default_review_agent_id":null},"tasks":{}}"#,
        );
        let owlscale_dir = dir.path().join(".owlscale");
        let err = required_review_agent_id(&owlscale_dir).unwrap_err();
        assert!(err.starts_with("ownership_required:"));
    }

    #[test]
    fn normalize_workspace_dir_appends_dot_owlscale() {
        let path = Path::new("/tmp/demo-workspace");
        assert_eq!(
            normalize_workspace_dir(path),
            PathBuf::from("/tmp/demo-workspace/.owlscale")
        );
    }

    #[test]
    fn validated_workspace_dir_accepts_workspace_root_or_owlscale_dir() {
        let dir = TempDir::new().unwrap();
        let root = dir.path().join("demo");
        fs::create_dir_all(&root).unwrap();
        Command::new("git").arg("init").arg(&root).output().unwrap();
        fs::create_dir_all(root.join(".owlscale")).unwrap();
        let expected = root
            .join(".owlscale")
            .canonicalize()
            .unwrap_or_else(|_| root.join(".owlscale"));

        let from_root = validated_workspace_dir(&root).unwrap();
        assert_eq!(
            from_root.canonicalize().unwrap_or(from_root.clone()),
            expected
        );

        let from_owlscale = validated_workspace_dir(&root.join(".owlscale")).unwrap();
        assert_eq!(
            from_owlscale
                .canonicalize()
                .unwrap_or(from_owlscale.clone()),
            expected
        );
    }

    #[test]
    fn validated_workspace_dir_rejects_missing_owlscale() {
        let dir = TempDir::new().unwrap();
        Command::new("git")
            .arg("init")
            .arg(dir.path())
            .output()
            .unwrap();
        let err = validated_workspace_dir(dir.path()).unwrap_err();
        assert!(err.contains("No .owlscale/ found"));
    }

    #[test]
    fn initialize_or_validate_workspace_dir_bootstraps_missing_workspace() {
        let dir = TempDir::new().unwrap();
        let project_root = dir.path().join("demo");
        fs::create_dir_all(&project_root).unwrap();
        Command::new("git")
            .arg("init")
            .arg(&project_root)
            .output()
            .unwrap();

        let owlscale_dir = initialize_or_validate_workspace_dir(&project_root).unwrap();
        assert!(owlscale_dir.join("tasks").exists());
        assert!(owlscale_dir.join("state.json").exists());
        assert!(owlscale_dir.join("roster.json").exists());
        assert!(owlscale_dir.join("worktrees.json").exists());
    }

    #[test]
    fn git_workspace_root_accepts_subdirectory_inside_repo() {
        let dir = TempDir::new().unwrap();
        let root = dir.path().join("demo");
        let nested = root.join("src/components");
        fs::create_dir_all(&nested).unwrap();
        Command::new("git").arg("init").arg(&root).output().unwrap();
        let expected = root.canonicalize().unwrap_or(root.clone());

        let repo_root = git_workspace_root(&nested).unwrap();
        assert_eq!(repo_root.canonicalize().unwrap_or(repo_root), expected);
    }

    #[test]
    fn validated_workspace_dir_accepts_git_worktree_directory() {
        let dir = TempDir::new().unwrap();
        let root = dir.path().join("demo");
        let branch_worktree = dir.path().join("demo-review");
        fs::create_dir_all(&root).unwrap();
        Command::new("git").arg("init").arg(&root).output().unwrap();
        fs::create_dir_all(root.join(".owlscale")).unwrap();
        fs::write(
            root.join(".owlscale").join("state.json"),
            r#"{"version":1,"tasks":{}}"#,
        )
        .unwrap();
        fs::write(
            root.join(".owlscale").join("roster.json"),
            r#"{"agents":{}}"#,
        )
        .unwrap();
        fs::write(
            root.join(".owlscale").join("worktrees.json"),
            r#"{"version":1,"worktrees":{}}"#,
        )
        .unwrap();

        Command::new("git")
            .arg("-C")
            .arg(&root)
            .args([
                "worktree",
                "add",
                branch_worktree.to_str().unwrap(),
                "-b",
                "review-copy",
            ])
            .output()
            .unwrap();

        let owlscale_dir = validated_workspace_dir(&branch_worktree).unwrap();
        let expected = root
            .join(".owlscale")
            .canonicalize()
            .unwrap_or_else(|_| root.join(".owlscale"));
        assert_eq!(
            owlscale_dir.canonicalize().unwrap_or(owlscale_dir),
            expected
        );
    }

    #[test]
    fn initialize_or_validate_workspace_dir_rejects_non_git_directory() {
        let dir = TempDir::new().unwrap();
        let project_root = dir.path().join("plain-folder");
        fs::create_dir_all(&project_root).unwrap();

        let err = initialize_or_validate_workspace_dir(&project_root).unwrap_err();
        assert!(err.starts_with("workspace_not_git:"));
    }

    #[test]
    fn stable_alpha_backend_smoke_path() {
        let dir = TempDir::new().unwrap();
        let repo_root = dir.path().join("repo");
        fs::create_dir_all(&repo_root).unwrap();
        Command::new("git")
            .arg("init")
            .arg(&repo_root)
            .output()
            .unwrap();

        let owlscale_dir = initialize_or_validate_workspace_dir(&repo_root).unwrap();
        state_reader::set_agent_policy_direct(
            &owlscale_dir,
            Some("executor-default"),
            Some("review-default"),
        )
        .unwrap();

        let task_id = state_reader::create_task_direct(&owlscale_dir, "smoke", None).unwrap();
        let coding =
            git_ops::create_coding_worktree(&owlscale_dir, &task_id, Some("executor-default"))
                .unwrap();
        state_reader::dispatch_task_direct(
            &owlscale_dir,
            &task_id,
            "executor-default",
            Some(&coding.id),
        )
        .unwrap();
        state_reader::mark_task_returned_direct(&owlscale_dir, &task_id, "smoke return").unwrap();

        let review =
            git_ops::create_review_worktree(&owlscale_dir, &task_id, "review-default").unwrap();

        let workspace = state_reader::read_workspace_state(&owlscale_dir).unwrap();
        let task = workspace
            .tasks
            .iter()
            .find(|task| task.id == task_id)
            .unwrap();
        assert_eq!(task.status, "returned");
        assert_eq!(task.assignee.as_deref(), Some("executor-default"));
        assert_eq!(task.review_owner_id.as_deref(), Some("review-default"));
        assert!(task.review_worktree_ready);
        assert_eq!(workspace.pending_review, 1);
        assert_eq!(review.agent_id.as_deref(), Some("review-default"));

        state_reader::accept_task_direct(&owlscale_dir, &task_id).unwrap();

        let workspace = state_reader::read_workspace_state(&owlscale_dir).unwrap();
        let task = workspace
            .tasks
            .iter()
            .find(|task| task.id == task_id)
            .unwrap();
        assert_eq!(task.status, "accepted");
        assert_eq!(workspace.pending_review, 0);
    }
}
