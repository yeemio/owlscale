use crate::types::{
    now_iso8601, ProtocolError, TaskRecord, WorkspaceState, WorktreeRecord, SCHEMA_VERSION,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::NamedTempFile;
use uuid::Uuid;

#[derive(Debug, Serialize, Deserialize)]
struct WorktreeRegistry {
    version: u32,
    worktrees: BTreeMap<String, WorktreeRecord>,
}

const TRANSITIONS: &[(&str, &[&str])] = &[
    ("draft", &["dispatched"]),
    ("dispatched", &["in_progress", "stalled", "error"]),
    ("in_progress", &["returned", "stalled", "error"]),
    ("returned", &["accepted", "rejected"]),
    ("rejected", &["dispatched"]),
    ("stalled", &["dispatched", "error"]),
    ("error", &["draft", "dispatched"]),
    ("accepted", &[]),
];

pub fn init_protocol_workspace(
    root_dir: &Path,
    workspace_id: Option<&str>,
) -> Result<PathBuf, ProtocolError> {
    let root_dir = root_dir.canonicalize().or_else(|_| {
        fs::create_dir_all(root_dir)?;
        root_dir.canonicalize()
    })?;
    let owlscale_dir = root_dir.join(".owlscale");
    fs::create_dir_all(owlscale_dir.join("tasks"))?;
    fs::create_dir_all(owlscale_dir.join("packets"))?;
    fs::create_dir_all(owlscale_dir.join("returns"))?;
    fs::create_dir_all(owlscale_dir.join("log"))?;
    fs::create_dir_all(owlscale_dir.join("templates"))?;

    let state_path = owlscale_dir.join("state.json");
    if !state_path.exists() {
        let state = WorkspaceState {
            workspace_id: workspace_id
                .map(ToOwned::to_owned)
                .unwrap_or_else(|| Uuid::new_v4().to_string()),
            repo_root: root_dir.display().to_string(),
            ..WorkspaceState::default()
        };
        atomic_write_json(&state_path, &state)?;
    }

    let roster_path = owlscale_dir.join("roster.json");
    if !roster_path.exists() {
        atomic_write_json(
            &roster_path,
            &serde_json::json!({"version": SCHEMA_VERSION, "agents": {}}),
        )?;
    }

    let worktrees_path = owlscale_dir.join("worktrees.json");
    if !worktrees_path.exists() {
        atomic_write_json(
            &worktrees_path,
            &WorktreeRegistry {
                version: SCHEMA_VERSION,
                worktrees: BTreeMap::new(),
            },
        )?;
    }

    let events_path = owlscale_dir.join("log").join("events.jsonl");
    if !events_path.exists() {
        fs::write(events_path, "")?;
    }

    Ok(owlscale_dir)
}

pub fn load_workspace_state(owlscale_dir: &Path) -> Result<WorkspaceState, ProtocolError> {
    read_json(&owlscale_dir.join("state.json"))
}

pub fn save_workspace_state(
    owlscale_dir: &Path,
    state: &mut WorkspaceState,
) -> Result<(), ProtocolError> {
    state.updated_at = now_iso8601();
    atomic_write_json(&owlscale_dir.join("state.json"), state)
}

pub fn load_worktree_registry(
    owlscale_dir: &Path,
) -> Result<BTreeMap<String, WorktreeRecord>, ProtocolError> {
    let registry: WorktreeRegistry = read_json(&owlscale_dir.join("worktrees.json"))?;
    Ok(registry.worktrees)
}

pub fn save_worktree_registry(
    owlscale_dir: &Path,
    worktrees: &BTreeMap<String, WorktreeRecord>,
) -> Result<(), ProtocolError> {
    let registry = WorktreeRegistry {
        version: SCHEMA_VERSION,
        worktrees: worktrees.clone(),
    };
    atomic_write_json(&owlscale_dir.join("worktrees.json"), &registry)
}

pub fn upsert_worktree(
    owlscale_dir: &Path,
    worktree_id: &str,
    record: WorktreeRecord,
) -> Result<WorktreeRecord, ProtocolError> {
    let mut worktrees = load_worktree_registry(owlscale_dir)?;
    worktrees.insert(worktree_id.to_string(), record.clone());
    save_worktree_registry(owlscale_dir, &worktrees)?;
    Ok(record)
}

pub fn remove_worktree(owlscale_dir: &Path, worktree_id: &str) -> Result<(), ProtocolError> {
    let mut worktrees = load_worktree_registry(owlscale_dir)?;
    if worktrees.remove(worktree_id).is_none() {
        return Err(ProtocolError::Message(format!(
            "Worktree '{worktree_id}' not found."
        )));
    }
    save_worktree_registry(owlscale_dir, &worktrees)
}

pub fn create_task(
    owlscale_dir: &Path,
    task_id: &str,
    packet_path: Option<String>,
    parent: Option<String>,
    assignee: Option<String>,
    worktree_id: Option<String>,
) -> Result<TaskRecord, ProtocolError> {
    let path = task_path(owlscale_dir, task_id);
    if path.exists() {
        return Err(ProtocolError::Message(format!(
            "Task '{task_id}' already exists."
        )));
    }
    let record = TaskRecord {
        version: 1,
        id: task_id.to_string(),
        status: "draft".to_string(),
        assignee,
        worktree_id,
        packet_path,
        return_path: None,
        created_at: Some(now_iso8601()),
        dispatched_at: None,
        returned_at: None,
        accepted_at: None,
        rejected_at: None,
        parent,
        last_error: None,
    };
    atomic_write_json(&path, &record)?;
    Ok(record)
}

pub fn load_task(owlscale_dir: &Path, task_id: &str) -> Result<TaskRecord, ProtocolError> {
    let path = task_path(owlscale_dir, task_id);
    if !path.exists() {
        return Err(ProtocolError::Message(format!(
            "Task '{task_id}' not found."
        )));
    }
    read_json(&path)
}

pub fn list_tasks(owlscale_dir: &Path) -> Result<Vec<TaskRecord>, ProtocolError> {
    let tasks_dir = owlscale_dir.join("tasks");
    if !tasks_dir.exists() {
        return Ok(Vec::new());
    }
    let mut records = Vec::new();
    for entry in fs::read_dir(tasks_dir)? {
        let path = entry?.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        records.push(read_json::<TaskRecord>(&path)?);
    }
    records.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(records)
}

pub fn save_task(
    owlscale_dir: &Path,
    record: &mut TaskRecord,
    expected_version: Option<u32>,
) -> Result<(), ProtocolError> {
    let path = task_path(owlscale_dir, &record.id);
    if path.exists() {
        let current: TaskRecord = read_json(&path)?;
        if let Some(expected) = expected_version {
            if current.version != expected {
                return Err(ProtocolError::Conflict(format!(
                    "Version conflict for task '{}': expected {}, found {}.",
                    record.id, expected, current.version
                )));
            }
        }
        record.version = current.version + 1;
    }
    atomic_write_json(&path, record)
}

pub fn transition_task(
    owlscale_dir: &Path,
    task_id: &str,
    to_status: &str,
    expected_version: Option<u32>,
    assignee: Option<String>,
    worktree_id: Option<String>,
    return_path: Option<String>,
    last_error: Option<String>,
) -> Result<TaskRecord, ProtocolError> {
    let mut record = load_task(owlscale_dir, task_id)?;
    let loaded_version = record.version;
    if let Some(expected) = expected_version {
        if loaded_version != expected {
            return Err(ProtocolError::Conflict(format!(
                "Version conflict for task '{}': expected {}, found {}.",
                task_id, expected, loaded_version
            )));
        }
    }
    if !can_transition(&record.status, to_status) {
        return Err(ProtocolError::Transition(format!(
            "Illegal task transition: {} -> {}",
            record.status, to_status
        )));
    }

    let timestamp = now_iso8601();
    record.status = to_status.to_string();
    if let Some(value) = assignee {
        record.assignee = Some(value);
    }
    if let Some(value) = worktree_id {
        record.worktree_id = Some(value);
    }
    if let Some(value) = return_path {
        record.return_path = Some(value);
    }
    if let Some(value) = last_error {
        record.last_error = Some(value);
    }

    match to_status {
        "dispatched" => {
            if record.assignee.is_none() {
                return Err(ProtocolError::Transition(
                    "Dispatch requires assignee.".to_string(),
                ));
            }
            record.dispatched_at = Some(timestamp);
        }
        "returned" => record.returned_at = Some(timestamp),
        "accepted" => record.accepted_at = Some(timestamp),
        "rejected" => record.rejected_at = Some(timestamp),
        _ => {}
    }

    save_task(owlscale_dir, &mut record, Some(loaded_version))?;
    Ok(record)
}

pub fn packet_path_for_task(owlscale_dir: &Path, record: &TaskRecord) -> PathBuf {
    if let Some(packet_path) = &record.packet_path {
        resolve_workspace_relative_path(owlscale_dir, packet_path)
    } else {
        owlscale_dir
            .join("packets")
            .join(format!("{}.md", record.id))
    }
}

pub fn return_path_for_task(owlscale_dir: &Path, record: &TaskRecord) -> PathBuf {
    if let Some(return_path) = &record.return_path {
        resolve_workspace_relative_path(owlscale_dir, return_path)
    } else {
        owlscale_dir
            .join("returns")
            .join(format!("{}.md", record.id))
    }
}

pub fn read_task_packet(owlscale_dir: &Path, task_id: &str) -> Result<String, ProtocolError> {
    let packet_path = owlscale_dir.join("packets").join(format!("{task_id}.md"));
    match fs::read_to_string(&packet_path) {
        Ok(content) => Ok(content),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Err(ProtocolError::Message(
            format!("packet not found for task '{task_id}'"),
        )),
        Err(err) => Err(ProtocolError::Io(err)),
    }
}

pub fn read_return_packet(owlscale_dir: &Path, task_id: &str) -> Result<String, ProtocolError> {
    let record = load_task(owlscale_dir, task_id)?;
    let return_path = return_path_for_task(owlscale_dir, &record);
    match fs::read_to_string(&return_path) {
        Ok(content) => Ok(content),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Err(ProtocolError::Message(
            format!("return packet not found for task '{task_id}'"),
        )),
        Err(err) => Err(ProtocolError::Io(err)),
    }
}

fn resolve_workspace_relative_path(owlscale_dir: &Path, relative_path: &str) -> PathBuf {
    owlscale_dir
        .parent()
        .unwrap_or(owlscale_dir)
        .join(relative_path)
}

fn can_transition(from_status: &str, to_status: &str) -> bool {
    TRANSITIONS
        .iter()
        .find_map(|(from, allowed)| {
            if *from == from_status {
                Some(*allowed)
            } else {
                None
            }
        })
        .map(|allowed| allowed.iter().any(|candidate| *candidate == to_status))
        .unwrap_or(false)
}

fn task_path(owlscale_dir: &Path, task_id: &str) -> PathBuf {
    owlscale_dir.join("tasks").join(format!("{task_id}.json"))
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, ProtocolError> {
    let raw = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&raw)?)
}

fn atomic_write_json<T: Serialize>(path: &Path, payload: &T) -> Result<(), ProtocolError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let mut file = NamedTempFile::new_in(parent)?;
    serde_json::to_writer_pretty(file.as_file_mut(), payload)?;
    use std::io::Write;
    file.as_file_mut().write_all(
        b"
",
    )?;
    file.persist(path)
        .map_err(|err| ProtocolError::Io(err.error))?;
    Ok(())
}
