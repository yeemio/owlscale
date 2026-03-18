export interface TaskInfo {
  id: string
  status: 'draft' | 'dispatched' | 'in_progress' | 'returned' | 'accepted' | 'rejected'
  assignee: string | null
  goal: string | null
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
  pending_review: number
}

export interface AppConfig {
  workspace_dir: string | null
  launch_at_login: boolean
}
