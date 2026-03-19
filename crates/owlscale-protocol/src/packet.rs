use crate::types::PacketValidationResult;
use serde_json::{Map, Value};
use std::fs;
use std::path::Path;

enum ExpectedType {
    String,
    StringList,
}

const CONTEXT_REQUIRED: &[(&str, ExpectedType)] = &[
    ("id", ExpectedType::String),
    ("goal", ExpectedType::String),
    ("assignee", ExpectedType::String),
    ("created_at", ExpectedType::String),
];
const CONTEXT_OPTIONAL: &[(&str, ExpectedType)] = &[
    ("title", ExpectedType::String),
    ("current_state", ExpectedType::String),
    ("scope", ExpectedType::StringList),
    ("constraints", ExpectedType::StringList),
    ("relevant_files", ExpectedType::StringList),
    ("validation", ExpectedType::StringList),
    ("expected_output", ExpectedType::StringList),
    ("worktree_hint", ExpectedType::String),
];
const RETURN_REQUIRED: &[(&str, ExpectedType)] = &[
    ("id", ExpectedType::String),
    ("summary", ExpectedType::String),
    ("files_changed", ExpectedType::StringList),
    ("generated_at", ExpectedType::String),
];
const RETURN_OPTIONAL: &[(&str, ExpectedType)] = &[
    ("test_results", ExpectedType::StringList),
    ("remaining_risks", ExpectedType::StringList),
    ("notes_for_reviewer", ExpectedType::StringList),
    ("status_summary", ExpectedType::String),
];

pub fn packet_goal_from_file(packet_path: &Path) -> Option<String> {
    let content = fs::read_to_string(packet_path).ok()?;
    let (frontmatter, _, errors) = parse_frontmatter(&content);
    if !errors.is_empty() {
        return None;
    }
    frontmatter.get("goal")?.as_str().map(ToOwned::to_owned)
}

pub fn validate_context_packet_file(
    path: &Path,
    expected_task_id: Option<&str>,
) -> PacketValidationResult {
    match fs::read_to_string(path) {
        Ok(content) => validate_context_packet_text(&content, expected_task_id),
        Err(err) => PacketValidationResult {
            valid: false,
            errors: vec![format!("read packet: {err}")],
            frontmatter: Map::new(),
            body: String::new(),
        },
    }
}

pub fn validate_return_packet_file(
    path: &Path,
    expected_task_id: Option<&str>,
) -> PacketValidationResult {
    match fs::read_to_string(path) {
        Ok(content) => validate_return_packet_text(&content, expected_task_id),
        Err(err) => PacketValidationResult {
            valid: false,
            errors: vec![format!("read packet: {err}")],
            frontmatter: Map::new(),
            body: String::new(),
        },
    }
}

pub fn validate_context_packet_text(
    content: &str,
    expected_task_id: Option<&str>,
) -> PacketValidationResult {
    validate_packet(
        content,
        expected_task_id,
        CONTEXT_REQUIRED,
        CONTEXT_OPTIONAL,
    )
}

pub fn validate_return_packet_text(
    content: &str,
    expected_task_id: Option<&str>,
) -> PacketValidationResult {
    validate_packet(content, expected_task_id, RETURN_REQUIRED, RETURN_OPTIONAL)
}

fn validate_packet(
    content: &str,
    expected_task_id: Option<&str>,
    required: &[(&str, ExpectedType)],
    optional: &[(&str, ExpectedType)],
) -> PacketValidationResult {
    let (frontmatter, body, mut errors) = parse_frontmatter(content);
    errors.extend(validate_schema(&frontmatter, required, optional));
    if let Some(expected) = expected_task_id {
        if frontmatter.get("id").and_then(Value::as_str) != Some(expected) {
            errors.push(format!("id must match expected task id '{expected}'."));
        }
    }
    PacketValidationResult {
        valid: errors.is_empty(),
        errors,
        frontmatter,
        body,
    }
}

fn parse_frontmatter(content: &str) -> (Map<String, Value>, String, Vec<String>) {
    let mut errors = Vec::new();
    let lines: Vec<&str> = content.lines().collect();
    if lines.first().copied() != Some("---") {
        return (
            Map::new(),
            content.to_string(),
            vec!["missing opening YAML frontmatter delimiter '---'.".to_string()],
        );
    }

    let Some(end_index) = lines.iter().enumerate().skip(1).find_map(|(index, line)| {
        if line.trim() == "---" {
            Some(index)
        } else {
            None
        }
    }) else {
        return (
            Map::new(),
            content.to_string(),
            vec!["missing closing YAML frontmatter delimiter '---'.".to_string()],
        );
    };

    let mut frontmatter = Map::new();
    let mut index = 1usize;
    while index < end_index {
        let line = lines[index];
        let trimmed = line.trim();
        if trimmed.is_empty() {
            index += 1;
            continue;
        }
        if line.starts_with(' ') || line.starts_with('\t') {
            errors.push(format!(
                "unexpected indentation in frontmatter line '{}'.",
                trimmed
            ));
            index += 1;
            continue;
        }
        let Some((raw_key, raw_rest)) = line.split_once(':') else {
            errors.push(format!("invalid frontmatter line '{}'.", trimmed));
            index += 1;
            continue;
        };
        let key = raw_key.trim();
        let rest = raw_rest.trim();
        if rest.is_empty() {
            let mut items = Vec::new();
            let mut lookahead = index + 1;
            while lookahead < end_index {
                let candidate = lines[lookahead];
                let candidate_trimmed = candidate.trim();
                if candidate_trimmed.is_empty() {
                    lookahead += 1;
                    continue;
                }
                if !(candidate.starts_with("  - ") || candidate.starts_with("\t- ")) {
                    break;
                }
                let item = candidate_trimmed
                    .strip_prefix('-')
                    .map(str::trim)
                    .unwrap_or_default();
                items.push(Value::String(strip_wrapping_quotes(item).to_string()));
                lookahead += 1;
            }
            frontmatter.insert(key.to_string(), Value::Array(items));
            index = lookahead;
            continue;
        }
        frontmatter.insert(
            key.to_string(),
            Value::String(strip_wrapping_quotes(rest).to_string()),
        );
        index += 1;
    }

    let body = lines[end_index + 1..]
        .join("\n")
        .trim_start_matches('\n')
        .to_string();
    (frontmatter, body, errors)
}

fn strip_wrapping_quotes(value: &str) -> &str {
    if value.len() >= 2 {
        let bytes = value.as_bytes();
        if (bytes[0] == b'\'' && bytes[value.len() - 1] == b'\'')
            || (bytes[0] == b'"' && bytes[value.len() - 1] == b'"')
        {
            return &value[1..value.len() - 1];
        }
    }
    value
}

fn validate_schema(
    data: &Map<String, Value>,
    required: &[(&str, ExpectedType)],
    optional: &[(&str, ExpectedType)],
) -> Vec<String> {
    let mut errors = Vec::new();

    for (field_name, expected_type) in required {
        match data.get(*field_name) {
            None => errors.push(format!("missing required field '{}'.", field_name)),
            Some(value) if is_empty(value) => {
                errors.push(format!("missing required field '{}'.", field_name))
            }
            Some(value) if !matches_type(value, expected_type) => errors.push(format!(
                "field '{}' must be of type {}.",
                field_name,
                expected_type_name(expected_type)
            )),
            Some(_) => {}
        }
    }

    for (field_name, expected_type) in optional {
        let Some(value) = data.get(*field_name) else {
            continue;
        };
        if !matches_type(value, expected_type) {
            errors.push(format!(
                "field '{}' must be of type {}.",
                field_name,
                expected_type_name(expected_type)
            ));
        }
    }

    errors
}

fn is_empty(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::String(text) => text.is_empty(),
        Value::Array(values) => values.is_empty(),
        _ => false,
    }
}

fn matches_type(value: &Value, expected_type: &ExpectedType) -> bool {
    match expected_type {
        ExpectedType::String => value.as_str().is_some(),
        ExpectedType::StringList => value
            .as_array()
            .map(|items| items.iter().all(|item| item.as_str().is_some()))
            .unwrap_or(false),
    }
}

fn expected_type_name(expected_type: &ExpectedType) -> &'static str {
    match expected_type {
        ExpectedType::String => "string",
        ExpectedType::StringList => "string list",
    }
}
