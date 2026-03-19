mod io;
mod packet;
mod types;

pub use io::{
    create_task, init_protocol_workspace, list_tasks, load_task, load_workspace_state,
    load_worktree_registry, packet_path_for_task, read_return_packet, read_task_packet,
    remove_worktree, return_path_for_task, save_task, save_workspace_state, save_worktree_registry,
    transition_task, upsert_worktree,
};
pub use packet::{
    packet_goal_from_file, validate_context_packet_file, validate_context_packet_text,
    validate_return_packet_file, validate_return_packet_text,
};
pub use types::{
    now_iso8601, PacketValidationResult, ProtocolError, TaskRecord, WorkspaceState, WorktreeRecord,
    SCHEMA_VERSION,
};
