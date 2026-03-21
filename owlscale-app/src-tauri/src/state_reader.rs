use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use crate::worktrees::{list_worktrees, RegisteredWorktree};

/// A single task exposed to the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskInfo {
    pub id: String,
    pub status: String,
    pub assignee: Option<String>,
    pub goal: Option<String>,
    pub worktree_id: Option<String>,
    pub review_worktree_id: Option<String>,
    pub review_worktree_ready: bool,
    pub review_owner_id: Option<String>,
    pub coding_worktree_assigned: bool,
    pub coding_worktree_missing: bool,
    pub ownership_override: bool,
    pub needs_attention: Vec<String>,
    pub review_stale: bool,
    pub rejected_reason: Option<String>,
}

/// An agent entry from roster.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentInfo {
    pub id: String,
    pub name: String,
    pub role: String,
}

/// Default agent assignments for the workspace.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentPolicy {
    pub default_execution_agent_id: Option<String>,
    pub default_review_agent_id: Option<String>,
}

/// Combined workspace snapshot returned by `get_workspace_state`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceState {
    pub dir: String,
    pub tasks: Vec<TaskInfo>,
    pub agents: Vec<AgentInfo>,
    pub worktrees: Vec<RegisteredWorktree>,
    /// Number of tasks with status == "returned" (awaiting coordinator review).
    pub pending_review: usize,
    /// Default agent policy, None when not configured.
    pub agent_policy: Option<AgentPolicy>,
}

// ── internal JSON shapes ──────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct StateJson {
    agent_policy: Option<AgentPolicyJson>,
}

#[derive(Debug, Deserialize)]
struct LegacyStateJson {
    #[serde(default)]
    tasks: HashMap<String, TaskEntry>,
}

#[derive(Debug, Deserialize)]
struct AgentPolicyJson {
    default_execution_agent_id: Option<String>,
    default_review_agent_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TaskEntry {
    status: String,
    #[serde(default)]
    assignee: Option<String>,
    #[serde(default)]
    worktree_id: Option<String>,
    #[serde(flatten)]
    extra: serde_json::Map<String, serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct RosterJson {
    #[serde(default)]
    agents: HashMap<String, AgentEntry>,
}

#[derive(Debug, Deserialize)]
struct AgentEntry {
    name: String,
    role: String,
}

// ─────────────────────────────────────────────────────────────────────────────

fn strip_wrapping_quotes(value: &str) -> &str {
    if value.len() >= 2
        && ((value.starts_with('\'') && value.ends_with('\''))
            || (value.starts_with('"') && value.ends_with('"')))
    {
        &value[1..value.len() - 1]
    } else {
        value
    }
}

fn parse_packet_goal(packet_path: &Path) -> Option<String> {
    let content = std::fs::read_to_string(packet_path).ok()?;
    let mut lines = content.lines();

    if lines.next()?.trim() != "---" {
        return None;
    }

    let mut frontmatter_lines = Vec::new();
    let mut found_closing_delimiter = false;

    for line in lines {
        if line.trim() == "---" {
            found_closing_delimiter = true;
            break;
        }
        frontmatter_lines.push(line);
    }

    if !found_closing_delimiter {
        return None;
    }

    for line in frontmatter_lines {
        if let Some(rest) = line.trim_start().strip_prefix("goal:") {
            let value = strip_wrapping_quotes(rest.trim()).trim();
            if value.is_empty() {
                return None;
            }
            return Some(value.to_string());
        }
    }

    None
}

fn review_worktree_id(task_id: &str) -> String {
    format!("review-{task_id}")
}

fn tasks_dir(owlscale_dir: &Path) -> PathBuf {
    owlscale_dir.join("tasks")
}

fn task_file_path(owlscale_dir: &Path, task_id: &str) -> PathBuf {
    tasks_dir(owlscale_dir).join(format!("{task_id}.json"))
}

fn ensure_tasks_dir(owlscale_dir: &Path) -> Result<PathBuf, String> {
    let dir = tasks_dir(owlscale_dir);
    std::fs::create_dir_all(&dir).map_err(|e| format!("create tasks dir: {e}"))?;
    Ok(dir)
}

fn list_task_file_paths(owlscale_dir: &Path) -> Result<Vec<PathBuf>, String> {
    let dir = ensure_tasks_dir(owlscale_dir)?;
    let mut task_files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .map_err(|e| format!("read tasks dir: {e}"))?
        .filter_map(|entry| entry.ok().map(|value| value.path()))
        .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("json"))
        .collect();
    task_files.sort();
    Ok(task_files)
}

fn read_task_entry_from_path(path: &Path) -> Result<TaskEntry, String> {
    let raw = std::fs::read_to_string(path)
        .map_err(|e| format!("read task file {}: {e}", path.display()))?;
    serde_json::from_str(&raw).map_err(|e| format!("parse task file {}: {e}", path.display()))
}

fn read_task_entry_direct(owlscale_dir: &Path, task_id: &str) -> Result<TaskEntry, String> {
    migrate_legacy_tasks_if_needed(owlscale_dir)?;
    let path = task_file_path(owlscale_dir, task_id);
    if !path.exists() {
        return Err(format!("Task '{task_id}' not found"));
    }
    read_task_entry_from_path(&path)
}

fn write_task_entry_direct(
    owlscale_dir: &Path,
    task_id: &str,
    entry: &TaskEntry,
) -> Result<(), String> {
    ensure_tasks_dir(owlscale_dir)?;
    let raw = serde_json::to_string_pretty(entry)
        .map_err(|e| format!("serialize task '{task_id}': {e}"))?;
    std::fs::write(task_file_path(owlscale_dir, task_id), raw)
        .map_err(|e| format!("write task '{task_id}': {e}"))
}

fn migrate_legacy_tasks_if_needed(owlscale_dir: &Path) -> Result<(), String> {
    let task_files = list_task_file_paths(owlscale_dir)?;
    if !task_files.is_empty() {
        return Ok(());
    }

    let state_path = owlscale_dir.join("state.json");
    if !state_path.exists() {
        return Ok(());
    }

    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let legacy: LegacyStateJson =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;
    if legacy.tasks.is_empty() {
        return Ok(());
    }

    for (task_id, entry) in legacy.tasks {
        write_task_entry_direct(owlscale_dir, &task_id, &entry)?;
    }

    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;
    if let Some(object) = state.as_object_mut() {
        object.remove("tasks");
    }
    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

    Ok(())
}

fn load_task_entries(owlscale_dir: &Path) -> Result<Vec<(String, TaskEntry)>, String> {
    migrate_legacy_tasks_if_needed(owlscale_dir)?;
    let mut entries = Vec::new();
    for path in list_task_file_paths(owlscale_dir)? {
        let Some(task_id) = path
            .file_stem()
            .and_then(|value| value.to_str())
            .map(str::to_string)
        else {
            continue;
        };
        let entry = read_task_entry_from_path(&path)?;
        entries.push((task_id, entry));
    }
    entries.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(entries)
}

fn task_declares_override(entry: &TaskEntry) -> bool {
    entry
        .extra
        .get("ownership_override")
        .and_then(|value| value.as_bool())
        .unwrap_or(false)
}

fn task_review_stale(entry: &TaskEntry) -> bool {
    entry
        .extra
        .get("review_stale")
        .and_then(|value| value.as_bool())
        .unwrap_or(false)
}

fn task_rejected_reason(entry: &TaskEntry) -> Option<String> {
    entry
        .extra
        .get("rejected_reason")
        .and_then(|value| value.as_str())
        .map(str::to_string)
}

fn parse_task_timestamp(
    entry: &TaskEntry,
    key: &str,
) -> Option<chrono::DateTime<chrono::FixedOffset>> {
    entry
        .extra
        .get(key)
        .and_then(|value| value.as_str())
        .and_then(|value| chrono::DateTime::parse_from_rfc3339(value).ok())
}

const STALLED_THRESHOLD_MINUTES: i64 = 30;

fn repo_root_from_owlscale_dir(owlscale_dir: &Path) -> &Path {
    owlscale_dir.parent().unwrap_or(owlscale_dir)
}

fn current_main_head(repo_root: &Path) -> Option<String> {
    let output = std::process::Command::new("git")
        .arg("-C")
        .arg(repo_root)
        .args(["rev-parse", "main"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

fn review_merge_base(repo_root: &Path, branch: &str) -> Option<String> {
    let output = std::process::Command::new("git")
        .arg("-C")
        .arg(repo_root)
        .args(["merge-base", branch, "main"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

pub fn reconcile_workspace_direct(owlscale_dir: &Path) -> Result<(), String> {
    migrate_legacy_tasks_if_needed(owlscale_dir)?;

    let mut worktree_registry = crate::worktrees::load_worktree_registry(owlscale_dir)?;
    let mut worktree_dirty = false;
    for record in worktree_registry.values_mut() {
        let exists = Path::new(&record.path).exists();
        let next_status = if exists {
            if record.status == "missing" {
                Some("ready".to_string())
            } else {
                None
            }
        } else if record.status != "missing" {
            Some("missing".to_string())
        } else {
            None
        };
        if let Some(status) = next_status {
            record.status = status;
            worktree_dirty = true;
        }
    }
    if worktree_dirty {
        crate::worktrees::save_worktree_registry(owlscale_dir, &worktree_registry)?;
    }

    let worktree_index: HashMap<String, RegisteredWorktree> =
        crate::worktrees::list_worktrees(owlscale_dir)?
            .into_iter()
            .map(|worktree| (worktree.id.clone(), worktree))
            .collect();

    let repo_root = repo_root_from_owlscale_dir(owlscale_dir);
    let main_head = current_main_head(repo_root);
    let task_entries = load_task_entries(owlscale_dir)?;
    for (task_id, mut entry) in task_entries {
        let next_review_stale = if entry.status == "returned" {
            let review_id = review_worktree_id(&task_id);
            worktree_index
                .get(&review_id)
                .filter(|worktree| worktree.status != "missing")
                .and_then(|worktree| {
                    main_head.as_ref().and_then(|head| {
                        review_merge_base(repo_root, &worktree.branch)
                            .map(|merge_base| merge_base != *head)
                    })
                })
                .unwrap_or(false)
        } else {
            false
        };

        if task_review_stale(&entry) != next_review_stale {
            entry.extra.insert(
                "review_stale".to_string(),
                serde_json::Value::Bool(next_review_stale),
            );
            write_task_entry_direct(owlscale_dir, &task_id, &entry)?;
        }
    }

    Ok(())
}

pub fn read_task_packet(owlscale_dir: &Path, task_id: &str) -> Result<String, String> {
    let packet_path = owlscale_dir.join("packets").join(format!("{task_id}.md"));
    std::fs::read_to_string(&packet_path).map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            format!("packet not found for task '{task_id}'")
        } else {
            format!("read packet {task_id}: {e}")
        }
    })
}

/// Read `state.json` and `roster.json` from `owlscale_dir` and return a
/// combined `WorkspaceState`. Missing files are treated as empty collections.
pub fn read_workspace_state(owlscale_dir: &Path) -> Result<WorkspaceState, String> {
    reconcile_workspace_direct(owlscale_dir)?;
    let task_entries = load_task_entries(owlscale_dir)?;
    let pending_review = task_entries
        .iter()
        .filter(|(_, entry)| entry.status == "returned")
        .count();
    let mut agent_policy: Option<AgentPolicy> = None;

    let state_path = owlscale_dir.join("state.json");
    if state_path.exists() {
        let raw =
            std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
        let parsed: StateJson =
            serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

        agent_policy = parsed.agent_policy.map(|p| AgentPolicy {
            default_execution_agent_id: p.default_execution_agent_id,
            default_review_agent_id: p.default_review_agent_id,
        });
    }

    let mut agents: Vec<AgentInfo> = Vec::new();

    let roster_path = owlscale_dir.join("roster.json");
    if roster_path.exists() {
        let raw =
            std::fs::read_to_string(&roster_path).map_err(|e| format!("read roster.json: {e}"))?;
        let parsed: RosterJson =
            serde_json::from_str(&raw).map_err(|e| format!("parse roster.json: {e}"))?;

        for (agent_id, entry) in parsed.agents {
            agents.push(AgentInfo {
                id: agent_id,
                name: entry.name,
                role: entry.role,
            });
        }
    }

    agents.sort_by(|a, b| a.id.cmp(&b.id));

    let worktrees = list_worktrees(owlscale_dir)?;
    let worktree_index: HashMap<&str, &RegisteredWorktree> = worktrees
        .iter()
        .map(|worktree| (worktree.id.as_str(), worktree))
        .collect();
    let mut tasks: Vec<TaskInfo> = Vec::new();

    for (task_id, entry) in task_entries {
        let goal = parse_packet_goal(&owlscale_dir.join("packets").join(format!("{task_id}.md")));
        let review_worktree_key = review_worktree_id(&task_id);
        let review_worktree = worktree_index.get(review_worktree_key.as_str()).copied();
        let coding_worktree = entry
            .worktree_id
            .as_deref()
            .and_then(|worktree_id| worktree_index.get(worktree_id).copied());
        let coding_worktree_assigned = entry.worktree_id.is_some();
        let coding_worktree_missing = coding_worktree_assigned
            && coding_worktree
                .map(|worktree| worktree.status == "missing")
                .unwrap_or(true);
        let ownership_override = entry
            .assignee
            .as_deref()
            .zip(coding_worktree.and_then(|worktree| worktree.agent_id.as_deref()))
            .map(|(assignee, worktree_agent)| assignee != worktree_agent)
            .unwrap_or(false);
        let declared_override = task_declares_override(&entry);
        let review_stale = task_review_stale(&entry);
        let rejected_reason = task_rejected_reason(&entry);
        let mut needs_attention = Vec::new();

        if entry.status == "in_progress" && coding_worktree_missing {
            needs_attention.push("needs_attention:worktree_missing".to_string());
        }

        if entry.status == "returned"
            && coding_worktree
                .map(|worktree| worktree.status == "working")
                .unwrap_or(false)
        {
            needs_attention.push("needs_attention:return_state_mismatch".to_string());
        }

        if entry.status == "in_progress" && ownership_override && !declared_override {
            needs_attention.push("needs_attention:ownership_drift".to_string());
        }

        if entry.status == "dispatched" {
            if let Some(dispatched_at) = parse_task_timestamp(&entry, "dispatched_at") {
                let stalled_after =
                    dispatched_at + chrono::Duration::minutes(STALLED_THRESHOLD_MINUTES);
                if chrono::Local::now().fixed_offset() >= stalled_after {
                    needs_attention.push("needs_attention:stalled".to_string());
                }
            }
        }

        if review_stale {
            needs_attention.push("needs_attention:review_stale".to_string());
        }

        tasks.push(TaskInfo {
            id: task_id,
            status: entry.status,
            assignee: entry.assignee,
            goal,
            worktree_id: entry.worktree_id,
            review_worktree_id: review_worktree.map(|worktree| worktree.id.clone()),
            review_worktree_ready: review_worktree
                .map(|worktree| worktree.status != "missing")
                .unwrap_or(false),
            review_owner_id: review_worktree.and_then(|worktree| worktree.agent_id.clone()),
            coding_worktree_assigned,
            coding_worktree_missing,
            ownership_override,
            needs_attention,
            review_stale,
            rejected_reason,
        });
    }

    tasks.sort_by(|a, b| a.id.cmp(&b.id));

    Ok(WorkspaceState {
        dir: owlscale_dir.display().to_string(),
        tasks,
        agents,
        worktrees,
        pending_review,
        agent_policy,
    })
}

// ─── Timeline events ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskEvent {
    pub timestamp: String,
    pub task_id: String,
    pub action: String,
    pub detail: Option<String>,
}

/// Read timeline events from log/ directory, optionally filtered to a single task.
pub fn read_task_events(owlscale_dir: &Path, filter_task_id: Option<&str>) -> Vec<TaskEvent> {
    let log_dir = owlscale_dir.join("log");
    let mut events = Vec::new();

    if !log_dir.exists() {
        return events;
    }

    let mut log_files: Vec<_> = std::fs::read_dir(&log_dir)
        .into_iter()
        .flatten()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().map(|x| x == "log").unwrap_or(false))
        .collect();
    log_files.sort_by_key(|e| e.file_name());

    for entry in log_files {
        let content = match std::fs::read_to_string(entry.path()) {
            Ok(c) => c,
            Err(_) => continue,
        };
        for line in content.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() < 3 {
                continue;
            }
            let timestamp = parts[0];
            let action = parts[1];
            let task_id = parts[2];
            let detail = if parts.len() > 3 {
                Some(parts[3..].join(" "))
            } else {
                None
            };

            if let Some(filter) = filter_task_id {
                if task_id != filter {
                    continue;
                }
            }

            events.push(TaskEvent {
                timestamp: timestamp.to_string(),
                task_id: task_id.to_string(),
                action: action.to_string(),
                detail,
            });
        }
    }

    events.sort_by(|a, b| a.timestamp.cmp(&b.timestamp));
    events
}

// ─── Direct state manipulation ───────────────────────────────────────────────

fn now_iso8601() -> String {
    chrono::Local::now()
        .format("%Y-%m-%dT%H:%M:%S%.6f%:z")
        .to_string()
}

pub fn initialize_workspace_direct(project_root: &Path) -> Result<std::path::PathBuf, String> {
    let owlscale_dir = project_root.join(".owlscale");
    std::fs::create_dir_all(owlscale_dir.join("tasks"))
        .map_err(|e| format!("init_workspace: create tasks dir: {e}"))?;
    std::fs::create_dir_all(owlscale_dir.join("packets"))
        .map_err(|e| format!("init_workspace: create packets dir: {e}"))?;
    std::fs::create_dir_all(owlscale_dir.join("returns"))
        .map_err(|e| format!("init_workspace: create returns dir: {e}"))?;
    std::fs::create_dir_all(owlscale_dir.join("log"))
        .map_err(|e| format!("init_workspace: create log dir: {e}"))?;

    let now = now_iso8601();
    let state_path = owlscale_dir.join("state.json");
    if !state_path.exists() {
        let state = serde_json::json!({
            "version": 1,
            "repo_root": project_root.display().to_string(),
            "default_branch": "main",
            "agent_policy": {
                "default_execution_agent_id": "executor-default",
                "default_review_agent_id": "review-default"
            },
            "created_at": now,
            "updated_at": now
        });
        let raw = serde_json::to_string_pretty(&state)
            .map_err(|e| format!("init_workspace: serialize state.json: {e}"))?;
        std::fs::write(&state_path, raw)
            .map_err(|e| format!("init_workspace: write state.json: {e}"))?;
    }

    let roster_path = owlscale_dir.join("roster.json");
    if !roster_path.exists() {
        let roster = serde_json::json!({
            "agents": {
                "coordinator-default": {
                    "name": "Coordinator",
                    "role": "coordinator"
                },
                "executor-default": {
                    "name": "Execution Agent",
                    "role": "executor"
                },
                "review-default": {
                    "name": "Review Agent",
                    "role": "executor"
                }
            }
        });
        let raw = serde_json::to_string_pretty(&roster)
            .map_err(|e| format!("init_workspace: serialize roster.json: {e}"))?;
        std::fs::write(&roster_path, raw)
            .map_err(|e| format!("init_workspace: write roster.json: {e}"))?;
    }

    let worktrees_path = owlscale_dir.join("worktrees.json");
    if !worktrees_path.exists() {
        let worktrees = serde_json::json!({
            "version": 1,
            "worktrees": {}
        });
        let raw = serde_json::to_string_pretty(&worktrees)
            .map_err(|e| format!("init_workspace: serialize worktrees.json: {e}"))?;
        std::fs::write(&worktrees_path, raw)
            .map_err(|e| format!("init_workspace: write worktrees.json: {e}"))?;
    }

    Ok(owlscale_dir)
}

fn fallback_task_id() -> String {
    chrono::Local::now()
        .format("task-%Y%m%d-%H%M%S")
        .to_string()
}

fn slugify_task_seed(value: &str) -> String {
    let mut output = String::new();
    let mut last_was_dash = false;

    for ch in value.chars().flat_map(|ch| ch.to_lowercase()) {
        if ch.is_ascii_alphanumeric() {
            output.push(ch);
            last_was_dash = false;
        } else if !last_was_dash {
            output.push('-');
            last_was_dash = true;
        }
    }

    let trimmed = output.trim_matches('-');
    let truncated = if trimmed.len() > 48 {
        &trimmed[..48]
    } else {
        trimmed
    };

    truncated.trim_matches('-').to_string()
}

fn existing_task_ids(owlscale_dir: &Path) -> Result<HashSet<String>, String> {
    Ok(load_task_entries(owlscale_dir)?
        .into_iter()
        .map(|(task_id, _)| task_id)
        .collect())
}

fn unique_task_id(existing: &HashSet<String>, base: &str) -> String {
    if !existing.contains(base) {
        return base.to_string();
    }

    let mut suffix = 2usize;
    loop {
        let suffix_text = format!("-{suffix}");
        let max_base_len = 48usize.saturating_sub(suffix_text.len());
        let truncated = if base.len() > max_base_len {
            &base[..max_base_len]
        } else {
            base
        };
        let candidate = format!("{}{}", truncated.trim_matches('-'), suffix_text);
        if !existing.contains(&candidate) {
            return candidate;
        }
        suffix += 1;
    }
}

pub fn suggest_task_id_direct(owlscale_dir: &Path, goal: &str) -> Result<String, String> {
    let goal = goal.trim();
    if goal.is_empty() {
        return Err("invalid_task_goal: goal is required".to_string());
    }

    let existing = existing_task_ids(owlscale_dir)?;
    let base = {
        let slug = slugify_task_seed(goal);
        if slug.is_empty() {
            fallback_task_id()
        } else {
            slug
        }
    };
    Ok(unique_task_id(&existing, &base))
}

pub fn create_task_direct(
    owlscale_dir: &Path,
    goal: &str,
    requested_task_id: Option<&str>,
) -> Result<String, String> {
    let goal = goal.trim();
    if goal.is_empty() {
        return Err("invalid_task_goal: goal is required".to_string());
    }

    let existing = existing_task_ids(owlscale_dir)?;
    let final_task_id = match requested_task_id
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        Some(requested) => {
            let canonical = slugify_task_seed(requested);
            if canonical.is_empty() {
                return Err(
                    "invalid_task_id: task id must contain ascii letters or digits".to_string(),
                );
            }
            if existing.contains(&canonical) {
                return Err(format!("task_conflict: task '{canonical}' already exists"));
            }
            canonical
        }
        None => suggest_task_id_direct(owlscale_dir, goal)?,
    };

    pack_task_direct(owlscale_dir, &final_task_id, goal)
        .map_err(|err| format!("write_failed: {err}"))?;
    Ok(final_task_id)
}

pub fn set_agent_policy_direct(
    owlscale_dir: &Path,
    execution_agent_id: Option<&str>,
    review_agent_id: Option<&str>,
) -> Result<AgentPolicy, String> {
    let roster_path = owlscale_dir.join("roster.json");
    let valid_agents: HashSet<String> = if roster_path.exists() {
        let roster_raw =
            std::fs::read_to_string(&roster_path).map_err(|e| format!("read roster.json: {e}"))?;
        let roster: RosterJson =
            serde_json::from_str(&roster_raw).map_err(|e| format!("parse roster.json: {e}"))?;
        roster.agents.into_keys().collect()
    } else {
        HashSet::new()
    };

    for (label, candidate) in [
        ("execution", execution_agent_id),
        ("review", review_agent_id),
    ] {
        if let Some(agent_id) = candidate.filter(|value| !value.trim().is_empty()) {
            if !valid_agents.contains(agent_id) {
                return Err(format!(
                    "invalid_agent_policy: {label} agent '{agent_id}' is not registered in roster"
                ));
            }
        }
    }

    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

    state["agent_policy"] = serde_json::json!({
        "default_execution_agent_id": execution_agent_id.filter(|value| !value.trim().is_empty()),
        "default_review_agent_id": review_agent_id.filter(|value| !value.trim().is_empty()),
    });

    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

    let execution_display = execution_agent_id.unwrap_or("null");
    let review_display = review_agent_id.unwrap_or("null");
    write_log(
        owlscale_dir,
        &format!("POLICY execution={execution_display} review={review_display}"),
    );

    Ok(AgentPolicy {
        default_execution_agent_id: execution_agent_id.map(str::to_string),
        default_review_agent_id: review_agent_id.map(str::to_string),
    })
}

fn write_log(owlscale_dir: &Path, entry: &str) {
    let log_dir = owlscale_dir.join("log");
    let _ = std::fs::create_dir_all(&log_dir);
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let log_path = log_dir.join(format!("{today}.log"));
    let timestamp = now_iso8601();
    let line = format!("{timestamp} {entry}\n");
    let _ = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .and_then(|mut f| std::io::Write::write_all(&mut f, line.as_bytes()));
}

/// Accept a returned task by directly updating state.json.
pub fn accept_task_direct(owlscale_dir: &Path, task_id: &str) -> Result<(), String> {
    let mut task = read_task_entry_direct(owlscale_dir, task_id)?;
    let status = task.status.as_str();
    if status != "returned" {
        return Err(format!(
            "Cannot accept task in '{status}' state. Must be 'returned'."
        ));
    }

    task.status = "accepted".to_string();
    task.extra.insert(
        "accepted_at".to_string(),
        serde_json::Value::String(now_iso8601()),
    );
    write_task_entry_direct(owlscale_dir, task_id, &task)?;

    write_log(owlscale_dir, &format!("ACCEPT  {task_id}"));
    Ok(())
}

/// Reject a returned task by directly updating state.json.
pub fn reject_task_direct(
    owlscale_dir: &Path,
    task_id: &str,
    reason: Option<&str>,
) -> Result<(), String> {
    let mut task = read_task_entry_direct(owlscale_dir, task_id)?;
    let status = task.status.as_str();
    if status != "returned" {
        return Err(format!(
            "Cannot reject task in '{status}' state. Must be 'returned'."
        ));
    }

    task.status = "rejected".to_string();
    task.extra.insert(
        "rejected_at".to_string(),
        serde_json::Value::String(now_iso8601()),
    );
    let normalized_reason = reason.map(str::trim).filter(|value| !value.is_empty());
    match normalized_reason {
        Some(value) => {
            task.extra.insert(
                "rejected_reason".to_string(),
                serde_json::Value::String(value.to_string()),
            );
        }
        None => {
            task.extra.remove("rejected_reason");
        }
    }
    write_task_entry_direct(owlscale_dir, task_id, &task)?;

    let reason_part = normalized_reason
        .map(|r| format!(" reason={r}"))
        .unwrap_or_default();
    write_log(owlscale_dir, &format!("REJECT  {task_id}{reason_part}"));
    Ok(())
}

/// Create a new task (pack) by adding to state.json and creating a packet file.
pub fn pack_task_direct(owlscale_dir: &Path, task_id: &str, goal: &str) -> Result<(), String> {
    migrate_legacy_tasks_if_needed(owlscale_dir)?;
    if task_file_path(owlscale_dir, task_id).exists() {
        return Err(format!("Task '{task_id}' already exists"));
    }

    let now = now_iso8601();
    let mut extra = serde_json::Map::new();
    extra.insert(
        "created_at".to_string(),
        serde_json::Value::String(now.clone()),
    );
    let task_entry = TaskEntry {
        status: "draft".to_string(),
        assignee: None,
        worktree_id: None,
        extra,
    };
    write_task_entry_direct(owlscale_dir, task_id, &task_entry)?;

    // Create packet file
    let packets_dir = owlscale_dir.join("packets");
    let _ = std::fs::create_dir_all(&packets_dir);
    let packet_path = packets_dir.join(format!("{task_id}.md"));
    let packet_content = format!(
        "---\n\
         id: {task_id}\n\
         type: context\n\
         goal: \"{goal}\"\n\
         status: draft\n\
         created: '{now}'\n\
         tags: []\n\
         ---\n\n\
         ## Goal\n\n\
         {goal}\n\n\
         ## Relevant Files\n\n\
         - \n\n\
         ## Scope\n\n\
         **In scope:**\n\
         - \n\n\
         **Out of scope:**\n\
         - \n\n\
         ## Execution Plan\n\n\
         1. \n\n\
         ## Validation\n\n\
         ## Expected Output\n"
    );
    std::fs::write(&packet_path, packet_content).map_err(|e| format!("write packet: {e}"))?;

    write_log(owlscale_dir, &format!("PACK   {task_id}"));
    Ok(())
}

/// Dispatch a task to an agent.
pub fn dispatch_task_direct(
    owlscale_dir: &Path,
    task_id: &str,
    agent_id: &str,
    worktree_id: Option<&str>,
) -> Result<(), String> {
    // Validate agent exists in roster
    let roster_path = owlscale_dir.join("roster.json");
    if roster_path.exists() {
        let roster_raw =
            std::fs::read_to_string(&roster_path).map_err(|e| format!("read roster.json: {e}"))?;
        let roster: serde_json::Value =
            serde_json::from_str(&roster_raw).map_err(|e| format!("parse roster.json: {e}"))?;
        let agents = roster
            .get("agents")
            .and_then(|a| a.as_object())
            .ok_or_else(|| "roster.json missing agents".to_string())?;
        if !agents.contains_key(agent_id) {
            return Err(format!("Agent '{agent_id}' not registered in roster"));
        }
    }

    let mut task = read_task_entry_direct(owlscale_dir, task_id)?;
    let status = task.status.as_str();
    if status != "draft" && status != "ready" {
        return Err(format!(
            "Cannot dispatch task in '{status}' state. Must be 'draft' or 'ready'."
        ));
    }

    let now = now_iso8601();
    task.status = "dispatched".to_string();
    task.assignee = Some(agent_id.to_string());
    task.extra
        .insert("dispatched_at".to_string(), serde_json::Value::String(now));
    let ownership_override = worktree_id
        .and_then(|selected_worktree_id| {
            crate::worktrees::load_worktree_registry(owlscale_dir)
                .ok()
                .and_then(|registry| registry.get(selected_worktree_id).cloned())
                .and_then(|record| record.agent_id)
                .map(|worktree_agent| worktree_agent != agent_id)
        })
        .unwrap_or(false);
    task.extra.insert(
        "ownership_override".to_string(),
        serde_json::Value::Bool(ownership_override),
    );
    if let Some(worktree_id) = worktree_id {
        task.worktree_id = Some(worktree_id.to_string());
    }
    write_task_entry_direct(owlscale_dir, task_id, &task)?;

    // Create return template if it doesn't exist
    let returns_dir = owlscale_dir.join("returns");
    let _ = std::fs::create_dir_all(&returns_dir);
    let return_path = returns_dir.join(format!("{task_id}.md"));
    if !return_path.exists() {
        let goal = parse_packet_goal(&owlscale_dir.join("packets").join(format!("{task_id}.md")))
            .unwrap_or_else(|| "(no goal specified)".to_string());
        let template = format!(
            "# Return Packet: {task_id}\n\n\
             ## Summary\n\n\
             {goal}\n\n\
             ## Files Modified\n\n\
             - \n\n\
             ## Key Decisions\n\n\
             - \n\n\
             ## Tests Run\n\n\
             ## Remaining Risks\n\n\
             - None identified\n\n\
             ## Unfinished Items\n\n\
             - None\n"
        );
        let _ = std::fs::write(&return_path, template);
    }

    write_log(owlscale_dir, &format!("DISPATCH {task_id}  to={agent_id}"));
    Ok(())
}

pub fn bind_task_worktree_direct(
    owlscale_dir: &Path,
    task_id: &str,
    worktree_id: &str,
) -> Result<(), String> {
    let mut task = read_task_entry_direct(owlscale_dir, task_id)?;
    let status = task.status.as_str();
    if status == "accepted" || status == "rejected" {
        return Err(format!("Cannot bind worktree to task in '{status}' state."));
    }

    task.worktree_id = Some(worktree_id.to_string());
    write_task_entry_direct(owlscale_dir, task_id, &task)?;

    write_log(
        owlscale_dir,
        &format!("BINDWT {task_id} worktree={worktree_id}"),
    );
    Ok(())
}

pub fn mark_task_returned_direct(
    owlscale_dir: &Path,
    task_id: &str,
    summary: &str,
) -> Result<(), String> {
    let mut task = read_task_entry_direct(owlscale_dir, task_id)?;
    let status = task.status.as_str();
    if status != "dispatched" && status != "in_progress" {
        return Err(format!(
            "Cannot mark task returned in '{status}' state. Must be 'dispatched' or 'in_progress'."
        ));
    }

    let now = now_iso8601();
    task.status = "returned".to_string();
    task.extra.insert(
        "returned_at".to_string(),
        serde_json::Value::String(now.clone()),
    );
    write_task_entry_direct(owlscale_dir, task_id, &task)?;

    let returns_dir = owlscale_dir.join("returns");
    let _ = std::fs::create_dir_all(&returns_dir);
    let return_path = returns_dir.join(format!("{task_id}.md"));
    let packet = format!(
        "---\n\
         id: {task_id}\n\
         type: return\n\
         summary: \"{summary}\"\n\
         generated_at: '{now}'\n\
         files_changed: []\n\
         ---\n\n\
         ## Summary\n\n\
         {summary}\n\n\
         ## Files Changed\n\n\
         - \n\n\
         ## Notes\n\n\
         - \n"
    );
    std::fs::write(&return_path, packet).map_err(|e| format!("write return packet: {e}"))?;

    write_log(owlscale_dir, &format!("RETURN {task_id}"));
    Ok(())
}

/// Read the return packet content for a task.
pub fn read_return_packet(owlscale_dir: &Path, task_id: &str) -> Result<String, String> {
    let return_path = owlscale_dir.join("returns").join(format!("{task_id}.md"));
    std::fs::read_to_string(&return_path).map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            format!("return packet not found for task '{task_id}'")
        } else {
            format!("read return packet {task_id}: {e}")
        }
    })
}

/// Scan common project directories for .owlscale/ workspaces.
pub fn scan_common_workspaces() -> Vec<String> {
    let home = std::env::var("HOME").unwrap_or_default();
    if home.is_empty() {
        return Vec::new();
    }

    let candidates = [
        format!("{home}/Documents"),
        format!("{home}/Developer"),
        format!("{home}/Projects"),
        format!("{home}/Code"),
        format!("{home}/workspace"),
        format!("{home}/repos"),
        format!("{home}/src"),
        format!("{home}/AI"),
        format!("{home}/Desktop"),
    ];

    let mut results = Vec::new();

    for dir in &candidates {
        let path = std::path::Path::new(dir);
        if !path.exists() {
            continue;
        }
        if path.join(".owlscale").is_dir() {
            results.push(path.display().to_string());
        }
        if let Ok(entries) = std::fs::read_dir(path) {
            for entry in entries.flatten() {
                let child = entry.path();
                if child.is_dir() && child.join(".owlscale").is_dir() {
                    results.push(child.display().to_string());
                }
            }
        }
    }

    results.sort();
    results.dedup();
    results
}

// ─── unit tests ──────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::process::Command;
    use tempfile::TempDir;

    fn setup_workspace(state: &str, roster: &str) -> TempDir {
        let dir = TempDir::new().unwrap();
        let ws = dir.path().join(".owlscale");
        fs::create_dir_all(&ws).unwrap();
        fs::create_dir_all(ws.join("packets")).unwrap();
        fs::write(ws.join("state.json"), state).unwrap();
        fs::write(ws.join("roster.json"), roster).unwrap();
        dir
    }

    fn setup_git_workspace() -> (TempDir, std::path::PathBuf) {
        let dir = TempDir::new().unwrap();
        let project_root = dir.path().join("repo");
        fs::create_dir_all(&project_root).unwrap();
        Command::new("git")
            .arg("init")
            .arg(&project_root)
            .output()
            .unwrap();
        Command::new("git")
            .arg("-C")
            .arg(&project_root)
            .args(["config", "user.email", "owlscale@example.com"])
            .output()
            .unwrap();
        Command::new("git")
            .arg("-C")
            .arg(&project_root)
            .args(["config", "user.name", "owlscale"])
            .output()
            .unwrap();
        fs::write(project_root.join("README.md"), "seed\n").unwrap();
        Command::new("git")
            .arg("-C")
            .arg(&project_root)
            .args(["add", "README.md"])
            .output()
            .unwrap();
        Command::new("git")
            .arg("-C")
            .arg(&project_root)
            .args(["commit", "-m", "init"])
            .output()
            .unwrap();
        let owlscale_dir = initialize_workspace_direct(&project_root).unwrap();
        (dir, owlscale_dir)
    }

    #[test]
    fn reads_tasks_and_agents() {
        let state = r#"{"version":1,"agent_policy":{"default_execution_agent_id":"cc-opus","default_review_agent_id":"review-agent"},"tasks":{"task-1":{"status":"dispatched","assignee":"copilot-opus","worktree_id":"coding-task-1"},"task-2":{"status":"returned","assignee":"review-agent","worktree_id":"coding-task-2"}}}"#;
        let roster = r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"coordinator","strengths":[],"constraints":{}}}}"#;
        let dir = setup_workspace(state, roster);
        let ws_dir = dir.path().join(".owlscale");
        let coding_ready_path = dir.path().join("coding-task-1");
        let review_ready_path = dir.path().join("review-task-2");
        fs::create_dir_all(&coding_ready_path).unwrap();
        fs::create_dir_all(&review_ready_path).unwrap();
        fs::write(
            ws_dir.join("worktrees.json"),
            format!(
                r#"{{"version":1,"worktrees":{{"coding-task-1":{{"path":"{}","branch":"owlscale/task-1","type":"coding","agent_id":"copilot-opus","status":"ready"}},"coding-task-2":{{"path":"/tmp/coding-task-2","branch":"owlscale/task-2","type":"coding","agent_id":"review-agent","status":"missing"}},"review-task-2":{{"path":"{}","branch":"owlscale/task-2-review","type":"review","agent_id":"review-agent","status":"ready"}}}}}}"#,
                coding_ready_path.display(),
                review_ready_path.display()
            ),
        )
        .unwrap();
        fs::write(
            ws_dir.join("packets").join("task-1.md"),
            r#"---
id: task-1
type: context
goal: "Human readable task goal"
status: dispatched
---

Task body
"#,
        )
        .unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        assert_eq!(ws.tasks.len(), 2);
        assert_eq!(ws.agents.len(), 1);
        assert_eq!(ws.worktrees.len(), 3);
        assert_eq!(ws.pending_review, 1);
        assert_eq!(
            ws.agent_policy
                .as_ref()
                .and_then(|policy| policy.default_execution_agent_id.as_deref()),
            Some("cc-opus")
        );

        let task1 = ws.tasks.iter().find(|t| t.id == "task-1").unwrap();
        assert_eq!(task1.status, "dispatched");
        assert_eq!(task1.assignee.as_deref(), Some("copilot-opus"));
        assert_eq!(task1.goal.as_deref(), Some("Human readable task goal"));
        assert_eq!(task1.worktree_id.as_deref(), Some("coding-task-1"));
        assert_eq!(task1.review_worktree_id, None);
        assert!(!task1.review_worktree_ready);
        assert!(!task1.coding_worktree_missing);
        assert!(task1.coding_worktree_assigned);
        assert!(!task1.ownership_override);

        let task2 = ws.tasks.iter().find(|t| t.id == "task-2").unwrap();
        assert_eq!(task2.goal, None);
        assert_eq!(task2.review_worktree_id.as_deref(), Some("review-task-2"));
        assert!(task2.review_worktree_ready);
        assert_eq!(task2.review_owner_id.as_deref(), Some("review-agent"));
        assert!(task2.coding_worktree_assigned);
        assert!(task2.coding_worktree_missing);
        assert!(!task2.ownership_override);

        let agent = &ws.agents[0];
        assert_eq!(agent.id, "cc-opus");
        assert_eq!(agent.role, "coordinator");

        let worktree = ws
            .worktrees
            .iter()
            .find(|worktree| worktree.id == "coding-task-1")
            .unwrap();
        assert_eq!(worktree.branch, "owlscale/task-1");
    }

    #[test]
    fn missing_files_return_empty_collections() {
        let dir = TempDir::new().unwrap();
        let ws_dir = dir.path().join(".owlscale");
        std::fs::create_dir_all(&ws_dir).unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        assert!(ws.tasks.is_empty());
        assert!(ws.agents.is_empty());
        assert!(ws.worktrees.is_empty());
        assert_eq!(ws.pending_review, 0);
        assert_eq!(ws.agent_policy, None);
    }

    #[test]
    fn parse_goal_from_packet() {
        let dir = TempDir::new().unwrap();
        let packet_path = dir.path().join("task.md");
        fs::write(
            &packet_path,
            r#"---
id: task-1
type: context
goal: 'Add rate limiting to the API'
status: dispatched
---

Body
"#,
        )
        .unwrap();

        assert_eq!(
            parse_packet_goal(&packet_path).as_deref(),
            Some("Add rate limiting to the API")
        );
    }

    #[test]
    fn missing_packet_returns_none() {
        let dir = TempDir::new().unwrap();
        let missing_path = dir.path().join("missing.md");

        assert_eq!(parse_packet_goal(&missing_path), None);
    }

    #[test]
    fn read_task_packet_returns_full_markdown() {
        let dir = setup_workspace(r#"{"version":1,"tasks":{}}"#, r#"{"agents":{}}"#);
        let ws_dir = dir.path().join(".owlscale");
        fs::write(ws_dir.join("packets").join("task-1.md"), "# Packet\n\nBody").unwrap();

        let packet = read_task_packet(&ws_dir, "task-1").unwrap();
        assert_eq!(packet, "# Packet\n\nBody");
    }

    #[test]
    fn read_task_packet_errors_for_missing_packet() {
        let dir = setup_workspace(r#"{"version":1,"tasks":{}}"#, r#"{"agents":{}}"#);
        let ws_dir = dir.path().join(".owlscale");

        let err = read_task_packet(&ws_dir, "missing").unwrap_err();
        assert!(err.contains("packet not found"));
    }

    #[test]
    fn ownership_override_is_based_on_worktree_owner() {
        let state = r#"{"version":1,"agent_policy":{"default_execution_agent_id":"workspace-default","default_review_agent_id":"review-agent"},"tasks":{"task-1":{"status":"dispatched","assignee":"other-agent","worktree_id":"coding-task-1"}}}"#;
        let roster = r#"{"agents":{}}"#;
        let dir = setup_workspace(state, roster);
        let ws_dir = dir.path().join(".owlscale");
        fs::write(
            ws_dir.join("worktrees.json"),
            r#"{"version":1,"worktrees":{"coding-task-1":{"path":"/tmp/coding-task-1","branch":"owlscale/task-1","type":"coding","agent_id":"agent-a","status":"ready"}}}"#,
        )
        .unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert!(task.ownership_override);
    }

    #[test]
    fn suggest_task_id_slugifies_and_deduplicates() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"fix-auth-loop":{"status":"draft"}}}"#,
            r#"{"agents":{}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");

        let suggestion = suggest_task_id_direct(&ws_dir, "Fix auth loop").unwrap();
        assert_eq!(suggestion, "fix-auth-loop-2");
    }

    #[test]
    fn suggest_task_id_falls_back_for_non_ascii_goal() {
        let dir = setup_workspace(r#"{"version":1,"tasks":{}}"#, r#"{"agents":{}}"#);
        let ws_dir = dir.path().join(".owlscale");

        let suggestion = suggest_task_id_direct(&ws_dir, "修复首次进入工作台空状态").unwrap();
        assert!(suggestion.starts_with("task-"));
    }

    #[test]
    fn create_task_direct_creates_draft_and_packet() {
        let dir = setup_workspace(r#"{"version":1,"tasks":{}}"#, r#"{"agents":{}}"#);
        let ws_dir = dir.path().join(".owlscale");

        let task_id = create_task_direct(&ws_dir, "Add rate limiting middleware", None).unwrap();
        assert_eq!(task_id, "add-rate-limiting-middleware");

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == task_id).unwrap();
        assert_eq!(task.status, "draft");
        assert_eq!(task.goal.as_deref(), Some("Add rate limiting middleware"));
        assert!(ws_dir
            .join("packets")
            .join(format!("{task_id}.md"))
            .exists());
    }

    #[test]
    fn create_task_direct_rejects_conflicting_explicit_id() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"fix-auth-loop":{"status":"draft"}}}"#,
            r#"{"agents":{}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");

        let err = create_task_direct(&ws_dir, "Something else", Some("fix-auth-loop")).unwrap_err();
        assert!(err.starts_with("task_conflict:"));
    }

    #[test]
    fn create_task_direct_rejects_empty_goal() {
        let dir = setup_workspace(r#"{"version":1,"tasks":{}}"#, r#"{"agents":{}}"#);
        let ws_dir = dir.path().join(".owlscale");

        let err = create_task_direct(&ws_dir, "   ", None).unwrap_err();
        assert!(err.starts_with("invalid_task_goal:"));
    }

    #[test]
    fn mark_task_returned_direct_updates_state_and_writes_packet() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"task-1":{"status":"dispatched","assignee":"cc-opus","worktree_id":"coding-task-1"}}}"#,
            r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"executor"}}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");

        mark_task_returned_direct(&ws_dir, "task-1", "Implemented the requested change").unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert_eq!(task.status, "returned");

        let return_packet = read_return_packet(&ws_dir, "task-1").unwrap();
        assert!(return_packet.contains("Implemented the requested change"));
    }

    #[test]
    fn reject_task_direct_persists_reason_and_logs_it() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"task-1":{"status":"returned","assignee":"cc-opus","worktree_id":"coding-task-1"}}}"#,
            r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"executor"}}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");

        reject_task_direct(&ws_dir, "task-1", Some("Needs stronger validation coverage")).unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert_eq!(task.status, "rejected");
        assert_eq!(
            task.rejected_reason.as_deref(),
            Some("Needs stronger validation coverage")
        );

        let log_dir = ws_dir.join("log");
        let log_file = fs::read_dir(&log_dir)
            .unwrap()
            .next()
            .unwrap()
            .unwrap()
            .path();
        let log_content = fs::read_to_string(log_file).unwrap();
        assert!(log_content.contains("REJECT  task-1 reason=Needs stronger validation coverage"));
    }

    #[test]
    fn set_agent_policy_direct_round_trip() {
        let dir = TempDir::new().unwrap();
        let project_root = dir.path().join("demo");
        fs::create_dir_all(&project_root).unwrap();
        let ws_dir = initialize_workspace_direct(&project_root).unwrap();

        let policy =
            set_agent_policy_direct(&ws_dir, Some("review-default"), Some("executor-default"))
                .unwrap();

        assert_eq!(
            policy,
            AgentPolicy {
                default_execution_agent_id: Some("review-default".to_string()),
                default_review_agent_id: Some("executor-default".to_string()),
            }
        );

        let ws = read_workspace_state(&ws_dir).unwrap();
        assert_eq!(ws.agent_policy, Some(policy));
    }

    #[test]
    fn set_agent_policy_direct_rejects_unknown_agent() {
        let dir = TempDir::new().unwrap();
        let project_root = dir.path().join("demo");
        fs::create_dir_all(&project_root).unwrap();
        let ws_dir = initialize_workspace_direct(&project_root).unwrap();

        let error = set_agent_policy_direct(&ws_dir, Some("missing-agent"), Some("review-default"))
            .unwrap_err();

        assert!(error.starts_with("invalid_agent_policy:"));
    }

    #[test]
    fn initialize_workspace_direct_creates_minimal_workspace() {
        let dir = TempDir::new().unwrap();
        let project_root = dir.path().join("demo");
        fs::create_dir_all(&project_root).unwrap();

        let owlscale_dir = initialize_workspace_direct(&project_root).unwrap();
        assert!(owlscale_dir.join("tasks").exists());
        assert!(owlscale_dir.join("packets").exists());
        assert!(owlscale_dir.join("returns").exists());
        assert!(owlscale_dir.join("log").exists());
        assert!(owlscale_dir.join("state.json").exists());
        assert!(owlscale_dir.join("roster.json").exists());
        assert!(owlscale_dir.join("worktrees.json").exists());

        let ws = read_workspace_state(&owlscale_dir).unwrap();
        assert_eq!(
            ws.agent_policy
                .as_ref()
                .and_then(|policy| policy.default_execution_agent_id.as_deref()),
            Some("executor-default")
        );
        assert_eq!(ws.agents.len(), 3);
        assert!(ws.tasks.is_empty());
    }

    #[test]
    fn read_workspace_state_migrates_legacy_tasks_out_of_state_json() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"legacy-task":{"status":"draft","assignee":"executor-default"}}}"#,
            r#"{"agents":{"executor-default":{"name":"Execution Agent","role":"executor"}}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws
            .tasks
            .iter()
            .find(|task| task.id == "legacy-task")
            .unwrap();
        assert_eq!(task.status, "draft");
        assert_eq!(task.assignee.as_deref(), Some("executor-default"));
        assert!(ws_dir.join("tasks").join("legacy-task.json").exists());

        let state_raw = fs::read_to_string(ws_dir.join("state.json")).unwrap();
        let state_json: serde_json::Value = serde_json::from_str(&state_raw).unwrap();
        assert!(state_json.get("tasks").is_none());
    }

    #[test]
    fn read_workspace_state_marks_missing_worktree_attention() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"task-1":{"status":"in_progress","assignee":"executor-default","worktree_id":"coding-task-1"}}}"#,
            r#"{"agents":{"executor-default":{"name":"Execution Agent","role":"executor"}}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");
        fs::write(
            ws_dir.join("worktrees.json"),
            r#"{"version":1,"worktrees":{"coding-task-1":{"path":"/tmp/does-not-exist-owlscale","branch":"owlscale/task-1","type":"coding","agent_id":"executor-default","status":"ready"}}}"#,
        )
        .unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert!(task
            .needs_attention
            .contains(&"needs_attention:worktree_missing".to_string()));

        let worktree = ws
            .worktrees
            .iter()
            .find(|worktree| worktree.id == "coding-task-1")
            .unwrap();
        assert_eq!(worktree.status, "missing");
    }

    #[test]
    fn read_workspace_state_flags_stalled_dispatch() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"task-1":{"status":"dispatched","assignee":"executor-default","dispatched_at":"2026-03-20T10:00:00+08:00"}}}"#,
            r#"{"agents":{"executor-default":{"name":"Execution Agent","role":"executor"}}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert!(task
            .needs_attention
            .contains(&"needs_attention:stalled".to_string()));
    }

    #[test]
    fn read_workspace_state_flags_ownership_drift_without_explicit_override() {
        let dir = setup_workspace(
            r#"{"version":1,"tasks":{"task-1":{"status":"in_progress","assignee":"executor-b","worktree_id":"coding-task-1"}}}"#,
            r#"{"agents":{"executor-a":{"name":"Execution A","role":"executor"},"executor-b":{"name":"Execution B","role":"executor"}}}"#,
        );
        let ws_dir = dir.path().join(".owlscale");
        let existing_path = dir.path().join("coding-task-1");
        fs::create_dir_all(&existing_path).unwrap();
        fs::write(
            ws_dir.join("worktrees.json"),
            format!(
                r#"{{"version":1,"worktrees":{{"coding-task-1":{{"path":"{}","branch":"owlscale/task-1","type":"coding","agent_id":"executor-a","status":"ready"}}}}}}"#,
                existing_path.display()
            ),
        )
        .unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert!(task
            .needs_attention
            .contains(&"needs_attention:ownership_drift".to_string()));
    }

    #[test]
    fn reconcile_workspace_marks_review_stale_when_main_head_changes() {
        let (_dir, ws_dir) = setup_git_workspace();
        pack_task_direct(&ws_dir, "task-1", "Review stale").unwrap();
        let coding =
            crate::git_ops::create_coding_worktree(&ws_dir, "task-1", Some("executor-default"))
                .unwrap();
        bind_task_worktree_direct(&ws_dir, "task-1", &coding.id).unwrap();
        dispatch_task_direct(&ws_dir, "task-1", "executor-default", Some(&coding.id)).unwrap();
        mark_task_returned_direct(&ws_dir, "task-1", "Return for stale test").unwrap();
        crate::git_ops::create_review_worktree(&ws_dir, "task-1", "review-default").unwrap();

        let project_root = ws_dir.parent().unwrap();
        fs::write(project_root.join("README.md"), "changed\n").unwrap();
        Command::new("git")
            .arg("-C")
            .arg(project_root)
            .args(["add", "README.md"])
            .output()
            .unwrap();
        Command::new("git")
            .arg("-C")
            .arg(project_root)
            .args(["commit", "-m", "advance main"])
            .output()
            .unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        let task = ws.tasks.iter().find(|task| task.id == "task-1").unwrap();
        assert!(task.review_stale);
        assert!(task
            .needs_attention
            .contains(&"needs_attention:review_stale".to_string()));
    }
}
