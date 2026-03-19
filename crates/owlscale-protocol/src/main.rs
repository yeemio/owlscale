use owlscale_protocol::{
    create_task, init_protocol_workspace, list_tasks, load_task, now_iso8601, transition_task,
    validate_context_packet_text, validate_return_packet_file,
};
use serde_json::json;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    if let Err(err) = run() {
        eprintln!("{err}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().skip(1).collect();
    let Some(command) = args.first().map(String::as_str) else {
        return Err(usage());
    };

    match command {
        "setup" => cmd_setup(&args[1..]),
        "list" => cmd_list(&args[1..]),
        "consume-return" => cmd_consume_return(&args[1..]),
        "accept" => cmd_accept(&args[1..]),
        _ => Err(usage()),
    }
}

fn cmd_setup(args: &[String]) -> Result<(), String> {
    let workspace = args.first().ok_or_else(usage)?;
    let task_id = required_flag(args, "--task-id")?;
    let goal = required_flag(args, "--goal")?;
    let assignee = required_flag(args, "--assignee")?;
    let worktree_id = optional_flag(args, "--worktree-id").unwrap_or_else(|| "wt-demo".to_string());

    let workspace_root = PathBuf::from(workspace);
    fs::create_dir_all(&workspace_root).map_err(|err| err.to_string())?;
    let owlscale_dir =
        init_protocol_workspace(&workspace_root, None).map_err(|err| err.to_string())?;

    let packet_relative = format!(".owlscale/packets/{task_id}.md");
    let packet_path = workspace_root.join(&packet_relative);
    let packet_content = build_context_packet(&task_id, &goal, &assignee, &worktree_id);
    let validation = validate_context_packet_text(&packet_content, Some(&task_id));
    if !validation.valid {
        return Err(format!(
            "Context Packet invalid: {}",
            validation.errors.join("; ")
        ));
    }
    fs::write(&packet_path, packet_content).map_err(|err| err.to_string())?;

    let created = create_task(
        &owlscale_dir,
        &task_id,
        Some(packet_relative.clone()),
        None,
        Some(assignee.clone()),
        Some(worktree_id.clone()),
    )
    .map_err(|err| err.to_string())?;
    let dispatched = transition_task(
        &owlscale_dir,
        &task_id,
        "dispatched",
        Some(created.version),
        Some(assignee.clone()),
        Some(worktree_id.clone()),
        None,
        None,
    )
    .map_err(|err| err.to_string())?;
    let working = transition_task(
        &owlscale_dir,
        &task_id,
        "in_progress",
        Some(dispatched.version),
        None,
        None,
        None,
        None,
    )
    .map_err(|err| err.to_string())?;

    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "workspace": workspace_root,
            "task_id": task_id,
            "packet_path": packet_relative,
            "return_path_hint": format!(".owlscale/returns/{task_id}.md"),
            "status": working.status,
            "version": working.version,
            "next": format!(
                "Write the return packet, then run: owlscale consume-return {} {}",
                workspace_root.display(),
                task_id
            )
        }))
        .map_err(|err| err.to_string())?
    );
    Ok(())
}

fn cmd_list(args: &[String]) -> Result<(), String> {
    let workspace = args.first().ok_or_else(usage)?;
    let owlscale_dir = resolve_owlscale_dir(workspace)?;
    let records = list_tasks(&owlscale_dir).map_err(|err| err.to_string())?;
    println!(
        "{}",
        serde_json::to_string_pretty(&records).map_err(|err| err.to_string())?
    );
    Ok(())
}

fn cmd_consume_return(args: &[String]) -> Result<(), String> {
    let workspace = args.first().ok_or_else(usage)?;
    let task_id = args.get(1).ok_or_else(usage)?;
    let workspace_root = PathBuf::from(workspace);
    let owlscale_dir = resolve_owlscale_dir(workspace)?;
    let return_path = optional_flag(args, "--return-file")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            workspace_root
                .join(".owlscale")
                .join("returns")
                .join(format!("{task_id}.md"))
        });

    let validation = validate_return_packet_file(&return_path, Some(task_id));
    if !validation.valid {
        return Err(format!(
            "Return Packet invalid: {}",
            validation.errors.join("; ")
        ));
    }

    let current = load_task(&owlscale_dir, task_id).map_err(|err| err.to_string())?;
    let relative_return_path = return_path
        .strip_prefix(&workspace_root)
        .unwrap_or(&return_path)
        .display()
        .to_string();
    let returned = transition_task(
        &owlscale_dir,
        task_id,
        "returned",
        Some(current.version),
        None,
        None,
        Some(relative_return_path),
        None,
    )
    .map_err(|err| err.to_string())?;
    println!(
        "{}",
        serde_json::to_string_pretty(&returned).map_err(|err| err.to_string())?
    );
    Ok(())
}

fn cmd_accept(args: &[String]) -> Result<(), String> {
    let workspace = args.first().ok_or_else(usage)?;
    let task_id = args.get(1).ok_or_else(usage)?;
    let owlscale_dir = resolve_owlscale_dir(workspace)?;
    let current = load_task(&owlscale_dir, task_id).map_err(|err| err.to_string())?;
    let accepted = transition_task(
        &owlscale_dir,
        task_id,
        "accepted",
        Some(current.version),
        None,
        None,
        None,
        None,
    )
    .map_err(|err| err.to_string())?;
    println!(
        "{}",
        serde_json::to_string_pretty(&accepted).map_err(|err| err.to_string())?
    );
    Ok(())
}

fn build_context_packet(task_id: &str, goal: &str, assignee: &str, worktree_id: &str) -> String {
    format!(
        "---
id: {task_id}
goal: {goal}
assignee: {assignee}
created_at: {}
scope:
  - protocol slice
validation:
  - packet parses
worktree_hint: {worktree_id}
---

# Context

{goal}
",
        now_iso8601()
    )
}

fn resolve_owlscale_dir(workspace: &str) -> Result<PathBuf, String> {
    let workspace_root = Path::new(workspace);
    let owlscale_dir = workspace_root.join(".owlscale");
    if !owlscale_dir.exists() {
        return Err(format!(
            "Missing protocol workspace: {}",
            owlscale_dir.display()
        ));
    }
    Ok(owlscale_dir)
}

fn required_flag(args: &[String], flag: &str) -> Result<String, String> {
    optional_flag(args, flag).ok_or_else(|| format!("missing required flag {flag}"))
}

fn optional_flag(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn usage() -> String {
    "usage: owlscale <setup|list|consume-return|accept> ...".to_string()
}
