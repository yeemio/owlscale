use owlscale_protocol::{
    create_task, init_protocol_workspace, list_tasks, load_task, load_workspace_state,
    load_worktree_registry, read_return_packet, transition_task, upsert_worktree,
    validate_context_packet_text, validate_return_packet_text, ProtocolError, WorktreeRecord,
};
use std::fs;
use std::process::Command;
use tempfile::tempdir;

#[test]
fn init_protocol_workspace_creates_contract_layout() {
    let dir = tempdir().unwrap();
    let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();

    assert!(owlscale_dir.join("tasks").is_dir());
    assert!(owlscale_dir.join("packets").is_dir());
    assert!(owlscale_dir.join("returns").is_dir());
    assert!(owlscale_dir.join("worktrees.json").exists());
    let state = load_workspace_state(&owlscale_dir).unwrap();
    assert_eq!(state.workspace_id, "ws-test");
    assert!(!state.repo_root.is_empty());
}

#[test]
fn create_task_and_transition_with_version_guard() {
    let dir = tempdir().unwrap();
    let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
    let task = create_task(
        &owlscale_dir,
        "task-1",
        Some(".owlscale/packets/task-1.md".into()),
        None,
        None,
        None,
    )
    .unwrap();
    assert_eq!(task.status, "draft");
    assert_eq!(task.version, 1);

    let updated = transition_task(
        &owlscale_dir,
        "task-1",
        "dispatched",
        Some(1),
        Some("bot".into()),
        Some("wt-1".into()),
        None,
        None,
    )
    .unwrap();
    assert_eq!(updated.status, "dispatched");
    assert_eq!(updated.assignee.as_deref(), Some("bot"));
    assert_eq!(updated.worktree_id.as_deref(), Some("wt-1"));
    assert_eq!(updated.version, 2);

    let err = transition_task(
        &owlscale_dir,
        "task-1",
        "in_progress",
        Some(1),
        None,
        None,
        None,
        None,
    )
    .unwrap_err();
    assert!(matches!(err, ProtocolError::Conflict(_)));
}

#[test]
fn transition_rejects_illegal_move() {
    let dir = tempdir().unwrap();
    let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
    create_task(&owlscale_dir, "task-2", None, None, None, None).unwrap();
    let err = transition_task(
        &owlscale_dir,
        "task-2",
        "accepted",
        Some(1),
        None,
        None,
        None,
        None,
    )
    .unwrap_err();
    assert!(matches!(err, ProtocolError::Transition(_)));
}

#[test]
fn worktree_registry_round_trip() {
    let dir = tempdir().unwrap();
    let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
    let record = WorktreeRecord {
        path: "/tmp/repo-wt".into(),
        branch: "feature/task-1".into(),
        kind: "coding".into(),
        agent_id: Some("bot".into()),
        status: "ready".into(),
        last_synced_at: None,
        last_seen_at: None,
    };
    upsert_worktree(&owlscale_dir, "wt-1", record).unwrap();

    let registry = load_worktree_registry(&owlscale_dir).unwrap();
    assert!(registry.contains_key("wt-1"));
    assert_eq!(registry["wt-1"].branch, "feature/task-1");
    assert_eq!(registry["wt-1"].agent_id.as_deref(), Some("bot"));
}

#[test]
fn validate_context_packet_reports_missing_required_fields() {
    let result = validate_context_packet_text(
        "---
id: task-ctx
goal: Ship it
---

Body",
        None,
    );
    assert!(!result.valid);
    assert!(result.errors.iter().any(|error| error.contains("assignee")));
    assert!(result
        .errors
        .iter()
        .any(|error| error.contains("created_at")));
}

#[test]
fn validate_return_packet_accepts_minimal_valid_packet() {
    let result = validate_return_packet_text(
        "---
id: task-ret
summary: Finished implementation
files_changed:
  - src/app.rs
generated_at: 2026-03-19T10:45:00+08:00
---

All done.
",
        Some("task-ret"),
    );
    assert!(result.valid);
    assert_eq!(result.frontmatter["files_changed"][0], "src/app.rs");
}

#[test]
fn list_tasks_returns_sorted_records() {
    let dir = tempdir().unwrap();
    let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
    create_task(&owlscale_dir, "task-b", None, None, None, None).unwrap();
    create_task(&owlscale_dir, "task-a", None, None, None, None).unwrap();

    let records = list_tasks(&owlscale_dir).unwrap();
    let ids: Vec<_> = records.into_iter().map(|record| record.id).collect();
    assert_eq!(ids, vec!["task-a", "task-b"]);
}

#[test]
fn cli_round_trip() {
    let dir = tempdir().unwrap();
    let workspace = dir.path().join("workspace");
    let bin = env!("CARGO_BIN_EXE_owlscale");

    let setup = Command::new(bin)
        .args([
            "setup",
            workspace.to_str().unwrap(),
            "--task-id",
            "task-flow",
            "--goal",
            "Ship the slice",
            "--assignee",
            "bot",
        ])
        .output()
        .unwrap();
    assert!(setup.status.success());
    assert!(String::from_utf8_lossy(&setup.stdout).contains(r#""status": "in_progress""#));

    let return_path = workspace
        .join(".owlscale")
        .join("returns")
        .join("task-flow.md");
    fs::create_dir_all(return_path.parent().unwrap()).unwrap();
    fs::write(
        &return_path,
        "---
id: task-flow
summary: Finished protocol slice
files_changed:
  - crates/owlscale-protocol/src/lib.rs
generated_at: 2026-03-19T13:00:00+08:00
---

Ready for review.
",
    )
    .unwrap();

    let consume = Command::new(bin)
        .args(["consume-return", workspace.to_str().unwrap(), "task-flow"])
        .output()
        .unwrap();
    assert!(consume.status.success());
    assert!(String::from_utf8_lossy(&consume.stdout).contains(r#""status": "returned""#));

    let accept = Command::new(bin)
        .args(["accept", workspace.to_str().unwrap(), "task-flow"])
        .output()
        .unwrap();
    assert!(accept.status.success());
    assert!(String::from_utf8_lossy(&accept.stdout).contains(r#""status": "accepted""#));

    let final_task = load_task(&workspace.join(".owlscale"), "task-flow").unwrap();
    assert_eq!(final_task.status, "accepted");
}

#[test]
fn read_return_packet_uses_recorded_return_path() {
    let dir = tempdir().unwrap();
    let owlscale_dir = init_protocol_workspace(dir.path(), Some("ws-test")).unwrap();
    create_task(
        &owlscale_dir,
        "task-ret",
        None,
        None,
        Some("bot".into()),
        None,
    )
    .unwrap();
    let current = load_task(&owlscale_dir, "task-ret").unwrap();
    let current = transition_task(
        &owlscale_dir,
        "task-ret",
        "dispatched",
        Some(current.version),
        Some("bot".into()),
        None,
        None,
        None,
    )
    .unwrap();
    let current = transition_task(
        &owlscale_dir,
        "task-ret",
        "in_progress",
        Some(current.version),
        None,
        None,
        None,
        None,
    )
    .unwrap();
    let return_path = dir
        .path()
        .join(".owlscale")
        .join("returns")
        .join("task-ret.md");
    fs::write(
        &return_path,
        "# Return

Done",
    )
    .unwrap();
    transition_task(
        &owlscale_dir,
        "task-ret",
        "returned",
        Some(current.version),
        None,
        None,
        Some(".owlscale/returns/task-ret.md".into()),
        None,
    )
    .unwrap();

    let packet = read_return_packet(&owlscale_dir, "task-ret").unwrap();
    assert_eq!(
        packet,
        "# Return

Done"
    );
}
