use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;

const REGISTRY_VERSION: u32 = 1;
const ALLOWED_TYPES: &[&str] = &["main", "coding", "review"];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorktreeRecord {
    pub path: String,
    pub branch: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub agent_id: Option<String>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RegisteredWorktree {
    pub id: String,
    pub path: String,
    pub branch: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub agent_id: Option<String>,
    pub status: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct WorktreeRegistryFile {
    version: u32,
    #[serde(default)]
    worktrees: BTreeMap<String, WorktreeRecord>,
}

pub fn load_worktree_registry(
    owlscale_dir: &Path,
) -> Result<BTreeMap<String, WorktreeRecord>, String> {
    let path = registry_path(owlscale_dir);
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw =
        std::fs::read_to_string(&path).map_err(|err| format!("read worktrees.json: {err}"))?;
    let parsed: WorktreeRegistryFile =
        serde_json::from_str(&raw).map_err(|err| format!("parse worktrees.json: {err}"))?;
    Ok(parsed.worktrees)
}

pub fn list_worktrees(owlscale_dir: &Path) -> Result<Vec<RegisteredWorktree>, String> {
    let mut items: Vec<RegisteredWorktree> = load_worktree_registry(owlscale_dir)?
        .into_iter()
        .map(|(id, record)| RegisteredWorktree {
            id,
            path: record.path,
            branch: record.branch,
            kind: record.kind,
            agent_id: record.agent_id,
            status: record.status,
        })
        .collect();
    items.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(items)
}

pub fn save_worktree_registry(
    owlscale_dir: &Path,
    worktrees: &BTreeMap<String, WorktreeRecord>,
) -> Result<(), String> {
    for (worktree_id, record) in worktrees {
        validate_record(worktree_id, record)?;
    }
    let payload = WorktreeRegistryFile {
        version: REGISTRY_VERSION,
        worktrees: worktrees.clone(),
    };
    atomic_write_json(&registry_path(owlscale_dir), &payload)
}

pub fn upsert_worktree(
    owlscale_dir: &Path,
    worktree_id: &str,
    record: WorktreeRecord,
) -> Result<RegisteredWorktree, String> {
    validate_record(worktree_id, &record)?;
    let mut worktrees = load_worktree_registry(owlscale_dir)?;
    worktrees.insert(worktree_id.to_string(), record.clone());
    save_worktree_registry(owlscale_dir, &worktrees)?;
    Ok(RegisteredWorktree {
        id: worktree_id.to_string(),
        path: record.path,
        branch: record.branch,
        kind: record.kind,
        agent_id: record.agent_id,
        status: record.status,
    })
}

pub fn assign_worktree_agent(
    owlscale_dir: &Path,
    worktree_id: &str,
    agent_id: Option<&str>,
) -> Result<RegisteredWorktree, String> {
    let mut worktrees = load_worktree_registry(owlscale_dir)?;
    let record = worktrees
        .get_mut(worktree_id)
        .ok_or_else(|| format!("Worktree '{worktree_id}' not found."))?;
    record.agent_id = agent_id.map(ToOwned::to_owned);
    let updated = record.clone();
    save_worktree_registry(owlscale_dir, &worktrees)?;
    Ok(RegisteredWorktree {
        id: worktree_id.to_string(),
        path: updated.path,
        branch: updated.branch,
        kind: updated.kind,
        agent_id: updated.agent_id,
        status: updated.status,
    })
}

#[allow(dead_code)]
pub fn remove_worktree(owlscale_dir: &Path, worktree_id: &str) -> Result<(), String> {
    let mut worktrees = load_worktree_registry(owlscale_dir)?;
    if worktrees.remove(worktree_id).is_none() {
        return Err(format!("Worktree '{worktree_id}' not found."));
    }
    save_worktree_registry(owlscale_dir, &worktrees)
}

fn validate_record(worktree_id: &str, record: &WorktreeRecord) -> Result<(), String> {
    if worktree_id.trim().is_empty() {
        return Err("worktree id is required.".to_string());
    }
    if record.path.trim().is_empty() {
        return Err(format!("Worktree '{worktree_id}' must include path."));
    }
    if record.branch.trim().is_empty() {
        return Err(format!("Worktree '{worktree_id}' must include branch."));
    }
    if !ALLOWED_TYPES.contains(&record.kind.as_str()) {
        return Err(format!(
            "Worktree '{worktree_id}' has invalid type '{}'.",
            record.kind
        ));
    }
    if record.status.trim().is_empty() {
        return Err(format!("Worktree '{worktree_id}' must include status."));
    }
    Ok(())
}

fn registry_path(owlscale_dir: &Path) -> std::path::PathBuf {
    owlscale_dir.join("worktrees.json")
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("invalid registry path: {}", path.display()))?;
    std::fs::create_dir_all(parent).map_err(|err| format!("create registry dir: {err}"))?;
    let tmp_path = path.with_extension(format!("{}.tmp", std::process::id()));
    let output = serde_json::to_string_pretty(value)
        .map_err(|err| format!("serialize worktrees.json: {err}"))?;
    std::fs::write(&tmp_path, output).map_err(|err| format!("write temp worktrees.json: {err}"))?;
    std::fs::rename(&tmp_path, path).map_err(|err| format!("replace worktrees.json: {err}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn setup_workspace() -> TempDir {
        let dir = TempDir::new().unwrap();
        std::fs::create_dir_all(dir.path().join(".owlscale")).unwrap();
        dir
    }

    #[test]
    fn missing_registry_returns_empty_collection() {
        let dir = setup_workspace();
        let registry = load_worktree_registry(&dir.path().join(".owlscale")).unwrap();
        assert!(registry.is_empty());
        let listed = list_worktrees(&dir.path().join(".owlscale")).unwrap();
        assert!(listed.is_empty());
    }

    #[test]
    fn upsert_and_list_round_trip() {
        let dir = setup_workspace();
        let owlscale_dir = dir.path().join(".owlscale");
        upsert_worktree(
            &owlscale_dir,
            "coding-task-1",
            WorktreeRecord {
                path: "/tmp/coding-task-1".into(),
                branch: "owlscale/task-1".into(),
                kind: "coding".into(),
                agent_id: Some("cc-opus".into()),
                status: "ready".into(),
            },
        )
        .unwrap();

        let listed = list_worktrees(&owlscale_dir).unwrap();
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].id, "coding-task-1");
        assert_eq!(listed[0].branch, "owlscale/task-1");
        assert_eq!(listed[0].kind, "coding");
        assert_eq!(listed[0].agent_id.as_deref(), Some("cc-opus"));
    }

    #[test]
    fn remove_worktree_updates_registry() {
        let dir = setup_workspace();
        let owlscale_dir = dir.path().join(".owlscale");
        upsert_worktree(
            &owlscale_dir,
            "review-task-1",
            WorktreeRecord {
                path: "/tmp/review-task-1".into(),
                branch: "owlscale/task-1-review".into(),
                kind: "review".into(),
                agent_id: None,
                status: "ready".into(),
            },
        )
        .unwrap();

        remove_worktree(&owlscale_dir, "review-task-1").unwrap();
        assert!(list_worktrees(&owlscale_dir).unwrap().is_empty());
    }

    #[test]
    fn invalid_worktree_type_is_rejected() {
        let dir = setup_workspace();
        let owlscale_dir = dir.path().join(".owlscale");
        let err = upsert_worktree(
            &owlscale_dir,
            "bad-worktree",
            WorktreeRecord {
                path: "/tmp/bad".into(),
                branch: "owlscale/bad".into(),
                kind: "sidequest".into(),
                agent_id: None,
                status: "ready".into(),
            },
        )
        .unwrap_err();
        assert!(err.contains("invalid type"));
    }

    #[test]
    fn assign_worktree_agent_updates_registry() {
        let dir = setup_workspace();
        let owlscale_dir = dir.path().join(".owlscale");
        upsert_worktree(
            &owlscale_dir,
            "coding-task-9",
            WorktreeRecord {
                path: "/tmp/coding-task-9".into(),
                branch: "owlscale/task-9".into(),
                kind: "coding".into(),
                agent_id: None,
                status: "ready".into(),
            },
        )
        .unwrap();

        let updated =
            assign_worktree_agent(&owlscale_dir, "coding-task-9", Some("cc-opus")).unwrap();
        assert_eq!(updated.agent_id.as_deref(), Some("cc-opus"));
    }
}
