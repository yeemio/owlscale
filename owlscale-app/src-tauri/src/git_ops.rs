use std::path::{Path, PathBuf};
use std::process::Command;

use crate::worktrees::{
    load_worktree_registry, upsert_worktree, RegisteredWorktree, WorktreeRecord,
};

pub fn coding_worktree_id(task_id: &str) -> String {
    format!("coding-{task_id}")
}

pub fn review_worktree_id(task_id: &str) -> String {
    format!("review-{task_id}")
}

pub fn coding_branch(task_id: &str) -> String {
    format!("owlscale/{task_id}")
}

pub fn review_branch(task_id: &str) -> String {
    format!("owlscale/{task_id}-review")
}

pub fn create_coding_worktree(
    owlscale_dir: &Path,
    task_id: &str,
    agent_id: Option<&str>,
) -> Result<RegisteredWorktree, String> {
    create_worktree(
        owlscale_dir,
        &coding_worktree_id(task_id),
        &coding_branch(task_id),
        "coding",
        agent_id,
    )
}

pub fn create_review_worktree(
    owlscale_dir: &Path,
    task_id: &str,
    agent_id: &str,
) -> Result<RegisteredWorktree, String> {
    create_worktree(
        owlscale_dir,
        &review_worktree_id(task_id),
        &review_branch(task_id),
        "review",
        Some(agent_id),
    )
}

pub fn rebase_review_worktree(owlscale_dir: &Path, task_id: &str) -> Result<(), String> {
    let review = ensure_registered_worktree_exists(owlscale_dir, &review_worktree_id(task_id))?;
    run_git(Path::new(&review.path), &["rebase", "main"])
}

/// Re-attach a coding worktree whose directory was deleted but whose git branch
/// and registry entry still exist. Runs `git worktree prune` first to clear
/// stale admin files, then `git worktree add {path} {branch}`.
pub fn repair_coding_worktree(
    owlscale_dir: &Path,
    task_id: &str,
) -> Result<RegisteredWorktree, String> {
    let worktree_id = coding_worktree_id(task_id);
    let registry = load_worktree_registry(owlscale_dir)?;
    let record = registry
        .get(&worktree_id)
        .ok_or_else(|| format!("worktree '{worktree_id}' not found in registry"))?;

    let path = PathBuf::from(&record.path);
    if path.exists() {
        return Err(format!(
            "worktree path already exists — no repair needed: {}",
            path.display()
        ));
    }

    let branch = record.branch.clone();
    let repo_root = repo_root(owlscale_dir)?;

    // Clear stale .git/worktrees admin entries before re-adding.
    let _ = Command::new("git")
        .args(["worktree", "prune"])
        .current_dir(&repo_root)
        .output();

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create dir: {e}"))?;
    }

    // Reattach to the existing branch (no -b flag).
    run_git(
        &repo_root,
        &[
            "worktree",
            "add",
            path.to_str().ok_or("invalid worktree path")?,
            &branch,
        ],
    )?;

    upsert_worktree(
        owlscale_dir,
        &worktree_id,
        WorktreeRecord {
            path: record.path.clone(),
            branch: branch.clone(),
            kind: record.kind.clone(),
            agent_id: record.agent_id.clone(),
            status: "ready".to_string(),
        },
    )
}

/// Return the unified diff between `main` and the coding branch for `task_id`.
/// Capped at ~200 KB to avoid UI performance issues.
pub fn get_task_coding_diff(owlscale_dir: &Path, task_id: &str) -> Result<String, String> {
    let repo_root = repo_root(owlscale_dir)?;
    let branch = coding_branch(task_id);

    if !branch_exists(&repo_root, &branch)? {
        return Err(format!("coding branch '{branch}' not found"));
    }

    let output = Command::new("git")
        .args(["diff", &format!("main...{branch}")])
        .current_dir(&repo_root)
        .output()
        .map_err(|e| format!("run git diff: {e}"))?;

    if !output.status.success() {
        return Err(stderr_message("git diff", &output.stderr));
    }

    let text = String::from_utf8_lossy(&output.stdout).to_string();
    const MAX_BYTES: usize = 200_000;
    if text.len() > MAX_BYTES {
        let cut = text[..MAX_BYTES].rfind('\n').unwrap_or(MAX_BYTES);
        return Ok(format!(
            "{}\n\n[... diff truncated at ~200KB ...]",
            &text[..cut]
        ));
    }
    Ok(text)
}

pub fn ensure_registered_worktree_exists(
    owlscale_dir: &Path,
    worktree_id: &str,
) -> Result<RegisteredWorktree, String> {
    let registry = load_worktree_registry(owlscale_dir)?;
    let record = registry
        .get(worktree_id)
        .ok_or_else(|| format!("Worktree '{worktree_id}' not found in registry."))?;
    let path = PathBuf::from(&record.path);
    if !path.exists() {
        return Err(format!(
            "Worktree '{worktree_id}' path is missing: {}",
            path.display()
        ));
    }
    Ok(RegisteredWorktree {
        id: worktree_id.to_string(),
        path: record.path.clone(),
        branch: record.branch.clone(),
        kind: record.kind.clone(),
        agent_id: record.agent_id.clone(),
        status: record.status.clone(),
    })
}

fn create_worktree(
    owlscale_dir: &Path,
    worktree_id: &str,
    branch: &str,
    kind: &str,
    agent_id: Option<&str>,
) -> Result<RegisteredWorktree, String> {
    if load_worktree_registry(owlscale_dir)?.contains_key(worktree_id) {
        return Err(format!(
            "Worktree '{worktree_id}' already exists in registry."
        ));
    }

    let repo_root = repo_root(owlscale_dir)?;
    let worktree_path = planned_worktree_path(&repo_root, worktree_id);
    if worktree_path.exists() {
        return Err(format!(
            "Worktree path already exists: {}",
            worktree_path.display()
        ));
    }
    if branch_exists(&repo_root, branch)? {
        return Err(format!("Branch '{branch}' already exists."));
    }

    if let Some(parent) = worktree_path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| format!("create worktree dir: {err}"))?;
    }

    run_git(
        &repo_root,
        &[
            "worktree",
            "add",
            "-b",
            branch,
            worktree_path
                .to_str()
                .ok_or_else(|| "invalid worktree path".to_string())?,
        ],
    )?;

    upsert_worktree(
        owlscale_dir,
        worktree_id,
        WorktreeRecord {
            path: worktree_path.display().to_string(),
            branch: branch.to_string(),
            kind: kind.to_string(),
            agent_id: agent_id.map(ToOwned::to_owned),
            status: "ready".to_string(),
        },
    )
}

fn repo_root(owlscale_dir: &Path) -> Result<PathBuf, String> {
    let output = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(owlscale_dir)
        .output()
        .map_err(|err| format!("run git rev-parse: {err}"))?;
    if !output.status.success() {
        return Err(stderr_message(
            "git rev-parse --show-toplevel",
            &output.stderr,
        ));
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.is_empty() {
        return Err("git rev-parse returned empty repo root".to_string());
    }
    Ok(PathBuf::from(text))
}

fn planned_worktree_path(repo_root: &Path, worktree_id: &str) -> PathBuf {
    let repo_name = repo_root
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("repo");
    repo_root
        .parent()
        .unwrap_or(repo_root)
        .join(".owlscale-worktrees")
        .join(repo_name)
        .join(worktree_id)
}

fn branch_exists(repo_root: &Path, branch: &str) -> Result<bool, String> {
    let output = Command::new("git")
        .args([
            "show-ref",
            "--verify",
            "--quiet",
            &format!("refs/heads/{branch}"),
        ])
        .current_dir(repo_root)
        .output()
        .map_err(|err| format!("run git show-ref: {err}"))?;
    Ok(output.status.success())
}

fn run_git(repo_root: &Path, args: &[&str]) -> Result<(), String> {
    let output = Command::new("git")
        .args(args)
        .current_dir(repo_root)
        .output()
        .map_err(|err| format!("run git {}: {err}", args.join(" ")))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(stderr_message(
            &format!("git {}", args.join(" ")),
            &output.stderr,
        ))
    }
}

fn stderr_message(action: &str, stderr: &[u8]) -> String {
    let text = String::from_utf8_lossy(stderr).trim().to_string();
    if text.is_empty() {
        format!("{action} failed")
    } else {
        format!("{action} failed: {text}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state_reader::{
        bind_task_worktree_direct, dispatch_task_direct, pack_task_direct, read_workspace_state,
    };
    use crate::worktrees::list_worktrees;
    use serde_json::Value;
    use tempfile::TempDir;

    fn setup_git_workspace() -> (TempDir, PathBuf) {
        let dir = TempDir::new().unwrap();
        run_git_raw(dir.path(), &["init"]).unwrap();
        run_git_raw(
            dir.path(),
            &["config", "user.email", "owlscale@example.com"],
        )
        .unwrap();
        run_git_raw(dir.path(), &["config", "user.name", "owlscale"]).unwrap();
        std::fs::write(dir.path().join("README.md"), "seed\n").unwrap();
        run_git_raw(dir.path(), &["add", "README.md"]).unwrap();
        run_git_raw(dir.path(), &["commit", "-m", "init"]).unwrap();
        let owlscale_dir = dir.path().join(".owlscale");
        std::fs::create_dir_all(&owlscale_dir).unwrap();
        std::fs::create_dir_all(owlscale_dir.join("tasks")).unwrap();
        std::fs::create_dir_all(owlscale_dir.join("packets")).unwrap();
        std::fs::create_dir_all(owlscale_dir.join("returns")).unwrap();
        std::fs::write(
            owlscale_dir.join("state.json"),
            r#"{"version":1,"tasks":{}}"#,
        )
        .unwrap();
        std::fs::write(
            owlscale_dir.join("roster.json"),
            r#"{"agents":{"cc-opus":{"name":"Claude Code Opus","role":"coordinator"}}}"#,
        )
        .unwrap();
        (dir, owlscale_dir)
    }

    fn mark_task_returned(owlscale_dir: &Path, task_id: &str) {
        let task_path = owlscale_dir.join("tasks").join(format!("{task_id}.json"));
        let raw = std::fs::read_to_string(&task_path).unwrap();
        let mut task: Value = serde_json::from_str(&raw).unwrap();
        task["status"] = Value::String("returned".into());
        task["returned_at"] = Value::String("2026-03-19T12:00:00+08:00".into());
        std::fs::write(&task_path, serde_json::to_string_pretty(&task).unwrap()).unwrap();
    }

    fn run_git_raw(cwd: &Path, args: &[&str]) -> Result<(), String> {
        let output = Command::new("git")
            .args(args)
            .current_dir(cwd)
            .output()
            .map_err(|err| format!("run git {}: {err}", args.join(" ")))?;
        if output.status.success() {
            Ok(())
        } else {
            Err(stderr_message(
                &format!("git {}", args.join(" ")),
                &output.stderr,
            ))
        }
    }

    #[test]
    fn create_coding_worktree_registers_default_naming() {
        let (_dir, owlscale_dir) = setup_git_workspace();
        let worktree = create_coding_worktree(&owlscale_dir, "task-1", Some("cc-opus")).unwrap();
        assert_eq!(worktree.id, "coding-task-1");
        assert_eq!(worktree.branch, "owlscale/task-1");
        assert_eq!(worktree.kind, "coding");
        assert_eq!(worktree.agent_id.as_deref(), Some("cc-opus"));
        assert!(Path::new(&worktree.path).exists());

        let registry = list_worktrees(&owlscale_dir).unwrap();
        assert_eq!(registry.len(), 1);
        assert_eq!(registry[0].id, "coding-task-1");
    }

    #[test]
    fn create_review_worktree_registers_review_branch() {
        let (_dir, owlscale_dir) = setup_git_workspace();
        let worktree = create_review_worktree(&owlscale_dir, "task-2", "cc-opus").unwrap();
        assert_eq!(worktree.id, "review-task-2");
        assert_eq!(worktree.branch, "owlscale/task-2-review");
        assert_eq!(worktree.kind, "review");
        assert_eq!(worktree.agent_id.as_deref(), Some("cc-opus"));
        assert!(Path::new(&worktree.path).exists());
    }

    #[test]
    fn smoke_dispatch_with_default_coding_worktree_updates_workspace_state() {
        let (_dir, owlscale_dir) = setup_git_workspace();
        pack_task_direct(&owlscale_dir, "task-3", "Ship worktree-aware dispatch").unwrap();

        let coding = create_coding_worktree(&owlscale_dir, "task-3", Some("cc-opus")).unwrap();
        bind_task_worktree_direct(&owlscale_dir, "task-3", &coding.id).unwrap();
        dispatch_task_direct(&owlscale_dir, "task-3", "cc-opus", Some(&coding.id)).unwrap();

        let workspace = read_workspace_state(&owlscale_dir).unwrap();
        let task = workspace
            .tasks
            .iter()
            .find(|task| task.id == "task-3")
            .unwrap();
        assert_eq!(task.status, "dispatched");
        assert_eq!(task.assignee.as_deref(), Some("cc-opus"));
        assert_eq!(task.worktree_id.as_deref(), Some("coding-task-3"));

        let worktree = workspace
            .worktrees
            .iter()
            .find(|worktree| worktree.id == "coding-task-3")
            .unwrap();
        assert_eq!(worktree.branch, "owlscale/task-3");
        assert!(Path::new(&worktree.path).exists());
    }

    #[test]
    fn smoke_returned_task_can_create_review_worktree() {
        let (_dir, owlscale_dir) = setup_git_workspace();
        pack_task_direct(&owlscale_dir, "task-4", "Review returned task").unwrap();
        let coding = create_coding_worktree(&owlscale_dir, "task-4", Some("cc-opus")).unwrap();
        bind_task_worktree_direct(&owlscale_dir, "task-4", &coding.id).unwrap();
        dispatch_task_direct(&owlscale_dir, "task-4", "cc-opus", Some(&coding.id)).unwrap();
        mark_task_returned(&owlscale_dir, "task-4");

        let review = create_review_worktree(&owlscale_dir, "task-4", "cc-opus").unwrap();
        assert_eq!(review.id, "review-task-4");
        assert_eq!(review.branch, "owlscale/task-4-review");
        assert_eq!(review.agent_id.as_deref(), Some("cc-opus"));
        assert!(Path::new(&review.path).exists());

        let checked = ensure_registered_worktree_exists(&owlscale_dir, "review-task-4").unwrap();
        assert_eq!(checked.id, "review-task-4");
        assert!(Path::new(&checked.path).exists());
    }
}
