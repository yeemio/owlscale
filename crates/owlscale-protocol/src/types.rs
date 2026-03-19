use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fmt::{Display, Formatter};
use std::io;
use uuid::Uuid;

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug)]
pub enum ProtocolError {
    Message(String),
    Conflict(String),
    Transition(String),
    Io(io::Error),
    Json(serde_json::Error),
}

impl Display for ProtocolError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Message(message) | Self::Conflict(message) | Self::Transition(message) => {
                write!(f, "{message}")
            }
            Self::Io(err) => write!(f, "{err}"),
            Self::Json(err) => write!(f, "{err}"),
        }
    }
}

impl std::error::Error for ProtocolError {}

impl From<io::Error> for ProtocolError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<serde_json::Error> for ProtocolError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceState {
    pub version: u32,
    pub workspace_id: String,
    pub repo_root: String,
    pub default_branch: String,
    pub created_at: String,
    pub updated_at: String,
    pub registry_ref: Option<String>,
}

impl Default for WorkspaceState {
    fn default() -> Self {
        Self {
            version: SCHEMA_VERSION,
            workspace_id: Uuid::new_v4().to_string(),
            repo_root: String::new(),
            default_branch: "main".to_string(),
            created_at: now_iso8601(),
            updated_at: now_iso8601(),
            registry_ref: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TaskRecord {
    pub version: u32,
    pub id: String,
    pub status: String,
    pub assignee: Option<String>,
    pub worktree_id: Option<String>,
    pub packet_path: Option<String>,
    pub return_path: Option<String>,
    pub created_at: Option<String>,
    pub dispatched_at: Option<String>,
    pub returned_at: Option<String>,
    pub accepted_at: Option<String>,
    pub rejected_at: Option<String>,
    pub parent: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorktreeRecord {
    pub path: String,
    pub branch: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub agent_id: Option<String>,
    pub status: String,
    pub last_synced_at: Option<String>,
    pub last_seen_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PacketValidationResult {
    pub valid: bool,
    pub errors: Vec<String>,
    pub frontmatter: Map<String, Value>,
    pub body: String,
}

pub fn now_iso8601() -> String {
    Local::now().to_rfc3339()
}
