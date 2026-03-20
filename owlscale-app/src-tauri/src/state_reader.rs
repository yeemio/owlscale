use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::Path;

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
    #[serde(default)]
    tasks: HashMap<String, TaskEntry>,
    agent_policy: Option<AgentPolicyJson>,
}

#[derive(Debug, Deserialize)]
struct AgentPolicyJson {
    default_execution_agent_id: Option<String>,
    default_review_agent_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TaskEntry {
    status: String,
    assignee: Option<String>,
    worktree_id: Option<String>,
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
    let mut task_entries: Vec<(String, TaskEntry)> = Vec::new();
    let mut pending_review: usize = 0;
    let mut agent_policy: Option<AgentPolicy> = None;

    let state_path = owlscale_dir.join("state.json");
    if state_path.exists() {
        let raw =
            std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
        let parsed: StateJson =
            serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

        for (task_id, entry) in parsed.tasks {
            if entry.status == "returned" {
                pending_review += 1;
            }
            task_entries.push((task_id, entry));
        }

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
    let worktree_index: HashMap<&str, &RegisteredWorktree> =
        worktrees.iter().map(|worktree| (worktree.id.as_str(), worktree)).collect();
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
    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let parsed: StateJson =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;
    Ok(parsed.tasks.into_keys().collect())
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
    let final_task_id = match requested_task_id.map(str::trim).filter(|value| !value.is_empty()) {
        Some(requested) => {
            let canonical = slugify_task_seed(requested);
            if canonical.is_empty() {
                return Err("invalid_task_id: task id must contain ascii letters or digits".to_string());
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
    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

    let tasks = state
        .get_mut("tasks")
        .and_then(|t| t.as_object_mut())
        .ok_or_else(|| "state.json missing tasks".to_string())?;

    let task = tasks
        .get_mut(task_id)
        .ok_or_else(|| format!("Task '{task_id}' not found"))?;

    let status = task.get("status").and_then(|s| s.as_str()).unwrap_or("");
    if status != "returned" {
        return Err(format!(
            "Cannot accept task in '{status}' state. Must be 'returned'."
        ));
    }

    let now = now_iso8601();
    task["status"] = serde_json::Value::String("accepted".into());
    task["accepted_at"] = serde_json::Value::String(now);

    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

    write_log(owlscale_dir, &format!("ACCEPT  {task_id}"));
    Ok(())
}

/// Reject a returned task by directly updating state.json.
pub fn reject_task_direct(
    owlscale_dir: &Path,
    task_id: &str,
    reason: Option<&str>,
) -> Result<(), String> {
    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

    let tasks = state
        .get_mut("tasks")
        .and_then(|t| t.as_object_mut())
        .ok_or_else(|| "state.json missing tasks".to_string())?;

    let task = tasks
        .get_mut(task_id)
        .ok_or_else(|| format!("Task '{task_id}' not found"))?;

    let status = task.get("status").and_then(|s| s.as_str()).unwrap_or("");
    if status != "returned" {
        return Err(format!(
            "Cannot reject task in '{status}' state. Must be 'returned'."
        ));
    }

    let now = now_iso8601();
    task["status"] = serde_json::Value::String("rejected".into());
    task["rejected_at"] = serde_json::Value::String(now);

    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

    let reason_part = reason.map(|r| format!(" reason={r}")).unwrap_or_default();
    write_log(owlscale_dir, &format!("REJECT  {task_id}{reason_part}"));
    Ok(())
}

/// Create a new task (pack) by adding to state.json and creating a packet file.
pub fn pack_task_direct(owlscale_dir: &Path, task_id: &str, goal: &str) -> Result<(), String> {
    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

    let tasks = state
        .get_mut("tasks")
        .and_then(|t| t.as_object_mut())
        .ok_or_else(|| "state.json missing tasks".to_string())?;

    if tasks.contains_key(task_id) {
        return Err(format!("Task '{task_id}' already exists"));
    }

    let now = now_iso8601();
    let task_entry = serde_json::json!({
        "status": "draft",
        "created_at": now
    });
    tasks.insert(task_id.to_string(), task_entry);

    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

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
    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

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

    let tasks = state
        .get_mut("tasks")
        .and_then(|t| t.as_object_mut())
        .ok_or_else(|| "state.json missing tasks".to_string())?;

    let task = tasks
        .get_mut(task_id)
        .ok_or_else(|| format!("Task '{task_id}' not found"))?;

    let status = task.get("status").and_then(|s| s.as_str()).unwrap_or("");
    if status != "draft" && status != "ready" {
        return Err(format!(
            "Cannot dispatch task in '{status}' state. Must be 'draft' or 'ready'."
        ));
    }

    let now = now_iso8601();
    task["status"] = serde_json::Value::String("dispatched".into());
    task["assignee"] = serde_json::Value::String(agent_id.into());
    task["dispatched_at"] = serde_json::Value::String(now);
    if let Some(worktree_id) = worktree_id {
        task["worktree_id"] = serde_json::Value::String(worktree_id.to_string());
    }

    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

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
    let state_path = owlscale_dir.join("state.json");
    let raw = std::fs::read_to_string(&state_path).map_err(|e| format!("read state.json: {e}"))?;
    let mut state: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

    let tasks = state
        .get_mut("tasks")
        .and_then(|t| t.as_object_mut())
        .ok_or_else(|| "state.json missing tasks".to_string())?;

    let task = tasks
        .get_mut(task_id)
        .ok_or_else(|| format!("Task '{task_id}' not found"))?;

    let status = task.get("status").and_then(|s| s.as_str()).unwrap_or("");
    if status == "accepted" || status == "rejected" {
        return Err(format!("Cannot bind worktree to task in '{status}' state."));
    }

    task["worktree_id"] = serde_json::Value::String(worktree_id.to_string());
    let output =
        serde_json::to_string_pretty(&state).map_err(|e| format!("serialize state.json: {e}"))?;
    std::fs::write(&state_path, output).map_err(|e| format!("write state.json: {e}"))?;

    write_log(
        owlscale_dir,
        &format!("BINDWT {task_id} worktree={worktree_id}"),
    );
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

    #[test]
    fn reads_tasks_and_agents() {
        let state = r#"{"version":1,"agent_policy":{"default_execution_agent_id":"cc-opus","default_review_agent_id":"review-agent"},"tasks":{"task-1":{"status":"dispatched","assignee":"copilot-opus","worktree_id":"coding-task-1"},"task-2":{"status":"returned","assignee":"review-agent","worktree_id":"coding-task-2"}}}"#;
        let roster = r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"coordinator","strengths":[],"constraints":{}}}}"#;
        let dir = setup_workspace(state, roster);
        let ws_dir = dir.path().join(".owlscale");
        fs::write(
            ws_dir.join("worktrees.json"),
            r#"{"version":1,"worktrees":{"coding-task-1":{"path":"/tmp/coding-task-1","branch":"owlscale/task-1","type":"coding","agent_id":"copilot-opus","status":"ready"},"coding-task-2":{"path":"/tmp/coding-task-2","branch":"owlscale/task-2","type":"coding","agent_id":"review-agent","status":"missing"},"review-task-2":{"path":"/tmp/review-task-2","branch":"owlscale/task-2-review","type":"review","agent_id":"review-agent","status":"ready"}}}"#,
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
        let dir = setup_workspace(r#"{"version":1,"tasks":{"fix-auth-loop":{"status":"draft"}}}"#, r#"{"agents":{}}"#);
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
        assert!(ws_dir.join("packets").join(format!("{task_id}.md")).exists());
    }

    #[test]
    fn create_task_direct_rejects_conflicting_explicit_id() {
        let dir = setup_workspace(r#"{"version":1,"tasks":{"fix-auth-loop":{"status":"draft"}}}"#, r#"{"agents":{}}"#);
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
}
