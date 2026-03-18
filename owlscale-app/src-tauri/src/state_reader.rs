use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

/// A single task exposed to the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskInfo {
    pub id: String,
    pub status: String,
    pub assignee: Option<String>,
    pub goal: Option<String>,
}

/// An agent entry from roster.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentInfo {
    pub id: String,
    pub name: String,
    pub role: String,
}

/// Combined workspace snapshot returned by `get_workspace_state`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceState {
    pub dir: String,
    pub tasks: Vec<TaskInfo>,
    pub agents: Vec<AgentInfo>,
    /// Number of tasks with status == "returned" (awaiting coordinator review).
    pub pending_review: usize,
}

// ── internal JSON shapes ──────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct StateJson {
    #[serde(default)]
    tasks: HashMap<String, TaskEntry>,
}

#[derive(Debug, Deserialize)]
struct TaskEntry {
    status: String,
    assignee: Option<String>,
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

/// Read `state.json` and `roster.json` from `owlscale_dir` and return a
/// combined `WorkspaceState`. Missing files are treated as empty collections.
pub fn read_workspace_state(owlscale_dir: &Path) -> Result<WorkspaceState, String> {
    let mut tasks: Vec<TaskInfo> = Vec::new();
    let mut pending_review: usize = 0;

    let state_path = owlscale_dir.join("state.json");
    if state_path.exists() {
        let raw = std::fs::read_to_string(&state_path)
            .map_err(|e| format!("read state.json: {e}"))?;
        let parsed: StateJson =
            serde_json::from_str(&raw).map_err(|e| format!("parse state.json: {e}"))?;

        for (task_id, entry) in parsed.tasks {
            let goal = parse_packet_goal(
                &owlscale_dir
                    .join("packets")
                    .join(format!("{task_id}.md")),
            );
            if entry.status == "returned" {
                pending_review += 1;
            }
            tasks.push(TaskInfo {
                id: task_id,
                status: entry.status,
                assignee: entry.assignee,
                goal,
            });
        }
    }

    // Sort by id for deterministic ordering
    tasks.sort_by(|a, b| a.id.cmp(&b.id));

    let mut agents: Vec<AgentInfo> = Vec::new();

    let roster_path = owlscale_dir.join("roster.json");
    if roster_path.exists() {
        let raw = std::fs::read_to_string(&roster_path)
            .map_err(|e| format!("read roster.json: {e}"))?;
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

    Ok(WorkspaceState {
        dir: owlscale_dir.display().to_string(),
        tasks,
        agents,
        pending_review,
    })
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
        let state = r#"{"version":1,"tasks":{"task-1":{"status":"dispatched","assignee":"copilot-opus"},"task-2":{"status":"returned"}}}"#;
        let roster = r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"coordinator","strengths":[],"constraints":{}}}}"#;
        let dir = setup_workspace(state, roster);
        let ws_dir = dir.path().join(".owlscale");
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
        assert_eq!(ws.pending_review, 1);

        let task1 = ws.tasks.iter().find(|t| t.id == "task-1").unwrap();
        assert_eq!(task1.status, "dispatched");
        assert_eq!(task1.assignee.as_deref(), Some("copilot-opus"));
        assert_eq!(task1.goal.as_deref(), Some("Human readable task goal"));

        let task2 = ws.tasks.iter().find(|t| t.id == "task-2").unwrap();
        assert_eq!(task2.goal, None);

        let agent = &ws.agents[0];
        assert_eq!(agent.id, "cc-opus");
        assert_eq!(agent.role, "coordinator");
    }

    #[test]
    fn missing_files_return_empty_collections() {
        let dir = TempDir::new().unwrap();
        let ws_dir = dir.path().join(".owlscale");
        std::fs::create_dir_all(&ws_dir).unwrap();

        let ws = read_workspace_state(&ws_dir).unwrap();
        assert!(ws.tasks.is_empty());
        assert!(ws.agents.is_empty());
        assert_eq!(ws.pending_review, 0);
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
}
