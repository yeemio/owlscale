<script lang="ts">
  import type { WorkspaceState, TaskInfo } from '../types'

  export let state: WorkspaceState

  const roleColor: Record<string, string> = {
    coordinator: 'var(--accent-purple)',
    executor:    'var(--accent-green)',
    hub:         'var(--accent-orange)',
  }

  const taskStatusLabel: Record<string, string> = {
    dispatched:  'dispatched',
    in_progress: 'in progress',
    returned:    'returned',
  }

  const taskStatusColor: Record<string, string> = {
    dispatched:  'var(--text-secondary)',
    in_progress: 'var(--accent-blue)',
    returned:    'var(--accent-orange)',
  }

  // Live tasks per agent (dispatched / in_progress / returned)
  $: liveTasksByAgent = state.tasks.reduce((acc, task) => {
    if (
      task.assignee &&
      (task.status === 'dispatched' || task.status === 'in_progress' || task.status === 'returned')
    ) {
      ;(acc[task.assignee] ??= []).push(task)
    }
    return acc
  }, {} as Record<string, TaskInfo[]>)
</script>

<div class="panel-root">
  <header class="panel-header">
    <div class="panel-title-row">
      <span class="panel-label">AGENTS</span>
      <span class="panel-count">{state.agents.length}</span>
    </div>
  </header>

  <div class="agent-list">
    {#each state.agents as agent (agent.id)}
      {@const liveTasks = liveTasksByAgent[agent.id] ?? []}
      {@const isActive = liveTasks.length > 0}
      <div class="agent-row" class:agent-active={isActive}>
        <span
          class="agent-dot"
          style:background-color={roleColor[agent.role] ?? 'var(--text-secondary)'}
          style:opacity={isActive ? '1' : '0.4'}
        ></span>
        <div class="agent-body">
          <div class="agent-name-row">
            <span class="agent-name">{agent.name}</span>
            <span class="agent-role">{agent.role}</span>
          </div>
          {#if liveTasks.length > 0}
            <div class="agent-tasks">
              {#each liveTasks as task (task.id)}
                <span class="task-chip">
                  <span class="task-chip-id">{task.id}</span>
                  <span
                    class="task-chip-status"
                    style:color={taskStatusColor[task.status] ?? 'var(--text-secondary)'}
                  >{taskStatusLabel[task.status] ?? task.status}</span>
                </span>
              {/each}
            </div>
          {:else}
            <div class="agent-idle">idle</div>
          {/if}
        </div>
      </div>
    {/each}

    {#if state.agents.length === 0}
      <div class="empty-state">
        <div class="empty-icon" aria-hidden="true">◎</div>
        <div class="empty-text">No agents in roster</div>
        <div class="empty-hint">Add agents to roster.json to get started</div>
      </div>
    {/if}
  </div>
</div>

<style>
  .panel-root {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .panel-header {
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
  }

  .panel-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .panel-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: var(--text-secondary);
  }

  .panel-count {
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--bg-tertiary);
    padding: 1px 7px;
    border-radius: 999px;
  }

  .agent-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .agent-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    transition: background-color 120ms ease;
  }

  .agent-row:hover {
    background: var(--bg-secondary);
  }

  .agent-dot {
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 999px;
    margin-top: 5px;
  }

  .agent-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .agent-name-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .agent-name {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .agent-role {
    font-size: 10px;
    color: var(--text-secondary);
    background: var(--bg-tertiary);
    padding: 1px 6px;
    border-radius: 3px;
    flex-shrink: 0;
  }

  .agent-tasks {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .task-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
  }

  .task-chip-id {
    font-family: ui-monospace, "SF Mono", monospace;
    color: var(--text-primary);
  }

  .task-chip-status {
    font-size: 10px;
  }

  .agent-idle {
    font-size: 11px;
    color: var(--text-secondary);
    opacity: 0.5;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 200px;
    gap: 6px;
    color: var(--text-secondary);
  }

  .empty-icon {
    font-size: 32px;
    opacity: 0.25;
  }

  .empty-text {
    font-size: 13px;
    font-weight: 500;
  }

  .empty-hint {
    font-size: 11px;
    opacity: 0.6;
    text-align: center;
    max-width: 200px;
  }
</style>
