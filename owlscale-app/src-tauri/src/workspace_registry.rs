use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

const REGISTRY_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceRegistryEntry {
    pub path: String,
    pub display_name: String,
    pub last_opened_at: String,
    pub status: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct WorkspaceRegistryFile {
    version: u32,
    #[serde(default)]
    workspaces: BTreeMap<String, WorkspaceRegistryEntry>,
}

pub fn project_root_from_owlscale(owlscale_dir: &Path) -> PathBuf {
    owlscale_dir
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| owlscale_dir.to_path_buf())
}

pub fn load_workspace_registry() -> Result<BTreeMap<String, WorkspaceRegistryEntry>, String> {
    let path = registry_path();
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw = std::fs::read_to_string(&path).map_err(|err| format!("read registry.json: {err}"))?;
    let parsed: WorkspaceRegistryFile =
        serde_json::from_str(&raw).map_err(|err| format!("parse registry.json: {err}"))?;
    Ok(parsed.workspaces)
}

pub fn list_workspace_registry() -> Result<Vec<WorkspaceRegistryEntry>, String> {
    let mut items: Vec<WorkspaceRegistryEntry> = load_workspace_registry()?
        .into_values()
        .map(|mut entry| {
            entry.status = workspace_status(Path::new(&entry.path));
            entry
        })
        .collect();
    items.sort_by(|left, right| right.last_opened_at.cmp(&left.last_opened_at));
    Ok(items)
}

pub fn upsert_workspace_registry(owlscale_dir: &Path, opened_at: &str) -> Result<(), String> {
    let project_root = project_root_from_owlscale(owlscale_dir);
    let path_key = project_root.display().to_string();
    let display_name = project_root
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("workspace")
        .to_string();

    let mut registry = load_workspace_registry()?;
    registry.insert(
        path_key.clone(),
        WorkspaceRegistryEntry {
            path: path_key,
            display_name,
            last_opened_at: opened_at.to_string(),
            status: workspace_status(&project_root),
        },
    );
    save_workspace_registry(&registry)
}

fn save_workspace_registry(
    workspaces: &BTreeMap<String, WorkspaceRegistryEntry>,
) -> Result<(), String> {
    let payload = WorkspaceRegistryFile {
        version: REGISTRY_VERSION,
        workspaces: workspaces.clone(),
    };
    let path = registry_path();
    let parent = path
        .parent()
        .ok_or_else(|| format!("invalid registry path: {}", path.display()))?;
    std::fs::create_dir_all(parent).map_err(|err| format!("create registry dir: {err}"))?;
    let tmp_path = path.with_extension(format!("{}.tmp", std::process::id()));
    let output = serde_json::to_string_pretty(&payload)
        .map_err(|err| format!("serialize registry.json: {err}"))?;
    std::fs::write(&tmp_path, output).map_err(|err| format!("write temp registry.json: {err}"))?;
    std::fs::rename(&tmp_path, &path).map_err(|err| format!("replace registry.json: {err}"))
}

pub fn newest_ready_workspace() -> Result<Option<PathBuf>, String> {
    let entries = list_workspace_registry()?;
    Ok(entries
        .into_iter()
        .find(|entry| entry.status == "ready")
        .map(|entry| PathBuf::from(entry.path)))
}

fn workspace_status(project_root: &Path) -> String {
    if project_root.join(".owlscale").is_dir() {
        "ready".to_string()
    } else {
        "missing".to_string()
    }
}

fn registry_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home)
        .join(".config")
        .join("owlscale")
        .join("registry.json")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, OnceLock};
    use tempfile::TempDir;

    fn env_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    fn with_home(temp: &TempDir, run: impl FnOnce()) {
        let _guard = env_lock().lock().unwrap();
        let old_home = std::env::var("HOME").ok();
        // SAFETY: tests run in-process; these tests are small and restore HOME before returning.
        unsafe { std::env::set_var("HOME", temp.path()) };
        run();
        match old_home {
            Some(value) => unsafe { std::env::set_var("HOME", value) },
            None => unsafe { std::env::remove_var("HOME") },
        }
    }

    #[test]
    fn registry_round_trip_and_status_refresh() {
        let temp = TempDir::new().unwrap();
        with_home(&temp, || {
            let project = temp.path().join("demo");
            std::fs::create_dir_all(project.join(".owlscale")).unwrap();

            upsert_workspace_registry(&project.join(".owlscale"), "2026-03-20T10:00:00+08:00")
                .unwrap();

            let entries = list_workspace_registry().unwrap();
            assert_eq!(entries.len(), 1);
            assert_eq!(entries[0].display_name, "demo");
            assert_eq!(entries[0].status, "ready");

            std::fs::remove_dir_all(project.join(".owlscale")).unwrap();
            let refreshed = list_workspace_registry().unwrap();
            assert_eq!(refreshed[0].status, "missing");
        });
    }

    #[test]
    fn newest_ready_workspace_prefers_latest_opened() {
        let temp = TempDir::new().unwrap();
        with_home(&temp, || {
            let older = temp.path().join("older");
            let newer = temp.path().join("newer");
            std::fs::create_dir_all(older.join(".owlscale")).unwrap();
            std::fs::create_dir_all(newer.join(".owlscale")).unwrap();

            upsert_workspace_registry(&older.join(".owlscale"), "2026-03-20T09:00:00+08:00")
                .unwrap();
            upsert_workspace_registry(&newer.join(".owlscale"), "2026-03-20T10:00:00+08:00")
                .unwrap();

            let selected = newest_ready_workspace().unwrap().unwrap();
            assert_eq!(selected, newer);
        });
    }
}
