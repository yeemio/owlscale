export type FocusMode = 'review' | 'execution' | 'setup'

export interface AgentPolicy {
  default_execution_agent_id: string | null
  default_review_agent_id: string | null
}

export interface TaskInfo {
  id: string
  status: 'draft' | 'dispatched' | 'in_progress' | 'returned' | 'accepted' | 'rejected'
  assignee: string | null
  goal: string | null
  worktree_id: string | null
  review_worktree_id: string | null
  review_worktree_ready: boolean
  review_owner_id: string | null
  coding_worktree_assigned: boolean
  coding_worktree_missing: boolean
  ownership_override: boolean
  needs_attention: string[]
  review_stale: boolean
}

export interface AgentInfo {
  id: string
  name: string
  role: 'coordinator' | 'executor' | 'hub'
}

export interface WorkspaceState {
  dir: string | null
  tasks: TaskInfo[]
  agents: AgentInfo[]
  worktrees: WorktreeInfo[]
  pending_review: number
  agent_policy: AgentPolicy | null
}

export interface WorktreeInfo {
  id: string
  path: string
  branch: string
  type: 'main' | 'coding' | 'review'
  agent_id: string | null
  status: string
}

export interface AppConfig {
  workspace_dir: string | null
  launch_at_login: boolean
  notifications_enabled: boolean
  refresh_interval_secs: number
}

export interface TaskEvent {
  timestamp: string
  task_id: string
  action: string
  detail: string | null
}

export interface TaskFilter {
  text: string
  status: string
}
