import type { WorkspaceState } from './types'

export const mockState: WorkspaceState = {
  dir: '/Users/yeemio/myproject/.owlscale',
  pending_review: 2,
  agents: [
    { id: 'cc', name: 'Claude Code', role: 'coordinator' },
    { id: 'copilot', name: 'GitHub Copilot', role: 'executor' },
    { id: 'codex', name: 'Codex CLI', role: 'executor' },
  ],
  tasks: [
    { id: 'implement-auth', status: 'returned', assignee: 'copilot', goal: 'Add JWT authentication to the API' },
    { id: 'fix-login-bug', status: 'returned', assignee: 'codex', goal: 'Fix session expiry not clearing cookie' },
    { id: 'add-rate-limiting', status: 'dispatched', assignee: 'copilot', goal: 'Add rate limiting middleware' },
    { id: 'write-api-docs', status: 'accepted', assignee: 'cc', goal: 'Document all REST endpoints' },
  ],
}
