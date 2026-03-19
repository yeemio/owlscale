use owlscale_protocol::{
    list_tasks, packet_goal_from_file, packet_path_for_task,
    read_return_packet as protocol_read_return_packet,
    read_task_packet as protocol_read_task_packet,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskInfo {
    pub id: String,
    pub status: String,
    pub assignee: Option<String>,
    pub goal: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentInfo {
    pub id: String,
    pub name: String,
    pub role: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceState {
    pub dir: String,
    pub tasks: Vec<TaskInfo>,
    pub agents: Vec<AgentInfo>,
    pub pending_review: usize,
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

pub fn read_task_packet(owlscale_dir: &Path, task_id: &str) -> Result<String, String> {
    protocol_read_task_packet(owlscale_dir, task_id).map_err(|err| err.to_string())
}

pub fn read_return_packet(owlscale_dir: &Path, task_id: &str) -> Result<String, String> {
    protocol_read_return_packet(owlscale_dir, task_id).map_err(|err| err.to_string())
}

pub fn read_workspace_state(owlscale_dir: &Path) -> Result<WorkspaceState, String> {
    let task_records = list_tasks(owlscale_dir).map_err(|err| err.to_string())?;
    let mut tasks = Vec::new();
    let mut pending_review = 0usize;

    for record in task_records {
        let goal = packet_goal_from_file(&packet_path_for_task(owlscale_dir, &record));
        if record.status == "returned" {
            pending_review += 1;
        }
        tasks.push(TaskInfo {
            id: record.id,
            status: record.status,
            assignee: record.assignee,
            goal,
        });
    }

    let mut agents = Vec::new();
    let roster_path = owlscale_dir.join("roster.json");
    if roster_path.exists() {
        let raw = std::fs::read_to_string(&roster_path)
            .map_err(|err| format!("read roster.json: {err}"))?;
        let parsed: RosterJson =
            serde_json::from_str(&raw).map_err(|err| format!("parse roster.json: {err}"))?;
        for (agent_id, entry) in parsed.agents {
            agents.push(AgentInfo {
                id: agent_id,
                name: entry.name,
                role: entry.role,
            });
        }
    }
    agents.sort_by(|left, right| left.id.cmp(&right.id));

    Ok(WorkspaceState {
        dir: owlscale_dir.display().to_string(),
        tasks,
        agents,
        pending_review,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use owlscale_protocol::{create_task, init_protocol_workspace, load_task, transition_task};
    use std::fs;
    use tempfile::TempDir;

    fn setup_workspace() -> (TempDir, std::path::PathBuf) {
        let dir = TempDir::new().unwrap();
        let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
        fs::write(
            owlscale_dir.join("roster.json"),
            r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"coordinator"}}}"#,
        )
        .unwrap();
        (dir, owlscale_dir)
    }

    #[test]
    fn reads_tasks_and_agents() {
        let (_dir, owlscale_dir) = setup_workspace();
        create_task(
            &owlscale_dir,
            "task-1",
            Some(".owlscale/packets/task-1.md".into()),
            None,
            Some("copilot-opus".into()),
            None,
        )
        .unwrap();
        fs::write(
            owlscale_dir.join("packets").join("task-1.md"),
            "---\nid: task-1\ngoal: Human readable task goal\nassignee: copilot-opus\ncreated_at: 2026-03-19T12:00:00+08:00\n---\n\nTask body\n",
        )
        .unwrap();
        create_task(&owlscale_dir, "task-2", None, None, None, None).unwrap();
        let current = load_task(&owlscale_dir, "task-2").unwrap();
        transition_task(
            &owlscale_dir,
            "task-2",
            "dispatched",
            Some(current.version),
            Some("cc-opus".into()),
            None,
            None,
            None,
        )
        .unwrap();
        let current = load_task(&owlscale_dir, "task-2").unwrap();
        transition_task(
            &owlscale_dir,
            "task-2",
            "in_progress",
            Some(current.version),
            None,
            None,
            None,
            None,
        )
        .unwrap();
        let current = load_task(&owlscale_dir, "task-2").unwrap();
        transition_task(
            &owlscale_dir,
            "task-2",
            "returned",
            Some(current.version),
            None,
            None,
            Some(".owlscale/returns/task-2.md".into()),
            None,
        )
        .unwrap();

        let workspace = read_workspace_state(&owlscale_dir).unwrap();
        assert_eq!(workspace.tasks.len(), 2);
        assert_eq!(workspace.agents.len(), 1);
        assert_eq!(workspace.pending_review, 1);

        let task1 = workspace
            .tasks
            .iter()
            .find(|task| task.id == "task-1")
            .unwrap();
        assert_eq!(task1.status, "draft");
        assert_eq!(task1.assignee.as_deref(), Some("copilot-opus"));
        assert_eq!(task1.goal.as_deref(), Some("Human readable task goal"));
    }

    #[test]
    fn missing_files_return_empty_collections() {
        let dir = TempDir::new().unwrap();
        let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
        let workspace = read_workspace_state(&owlscale_dir).unwrap();
        assert!(workspace.tasks.is_empty());
        assert!(workspace.agents.is_empty());
        assert_eq!(workspace.pending_review, 0);
    }

    #[test]
    fn read_task_packet_returns_full_markdown() {
        let (_dir, owlscale_dir) = setup_workspace();
        fs::write(
            owlscale_dir.join("packets").join("task-1.md"),
            "# Packet\n\nBody",
        )
        .unwrap();
        let packet = read_task_packet(&owlscale_dir, "task-1").unwrap();
        assert_eq!(packet, "# Packet\n\nBody");
    }

    #[test]
    fn read_task_packet_errors_for_missing_packet() {
        let (_dir, owlscale_dir) = setup_workspace();
        let err = read_task_packet(&owlscale_dir, "missing").unwrap_err();
        assert!(err.contains("packet not found"));
    }

    #[test]
    fn read_return_packet_returns_full_markdown() {
        let (_dir, owlscale_dir) = setup_workspace();
        create_task(
            &owlscale_dir,
            "task-3",
            None,
            None,
            Some("cc-opus".into()),
            None,
        )
        .unwrap();
        let current = load_task(&owlscale_dir, "task-3").unwrap();
        let current = transition_task(
            &owlscale_dir,
            "task-3",
            "dispatched",
            Some(current.version),
            Some("cc-opus".into()),
            None,
            None,
            None,
        )
        .unwrap();
        let current = transition_task(
            &owlscale_dir,
            "task-3",
            "in_progress",
            Some(current.version),
            None,
            None,
            None,
            None,
        )
        .unwrap();
        std::fs::write(
            owlscale_dir.join("returns").join("task-3.md"),
            "# Return\n\nManual summary",
        )
        .unwrap();
        transition_task(
            &owlscale_dir,
            "task-3",
            "returned",
            Some(current.version),
            None,
            None,
            Some(".owlscale/returns/task-3.md".into()),
            None,
        )
        .unwrap();

        let packet = read_return_packet(&owlscale_dir, "task-3").unwrap();
        assert_eq!(packet, "# Return\n\nManual summary");
    }

    #[test]
    fn read_return_packet_errors_for_missing_packet() {
        let (_dir, owlscale_dir) = setup_workspace();
        let err = read_return_packet(&owlscale_dir, "missing").unwrap_err();
        assert!(
            err.contains("return packet not found") || err.contains("Task 'missing' not found")
        );
    }
}
