<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import AgentCard from './AgentCard.svelte'
  import SettingsPanel from './SettingsPanel.svelte'
  import TaskCard from './TaskCard.svelte'
  import type { TaskInfo, WorkspaceState } from '../types'

  export let state: WorkspaceState
  let showSettings = false
  let createTaskId = ''
  let createGoal = ''
  let createAssignee = ''
  let creating = false
  let createError = ''

  const taskOrder: Record<TaskInfo['status'], number> = {
    returned: 0,
    draft: 1,
    dispatched: 2,
    in_progress: 3,
    accepted: 4,
    rejected: 5,
  }

  const sortTasks = (tasks: TaskInfo[]): TaskInfo[] =>
    [...tasks].sort((left, right) => {
      const priorityDelta = taskOrder[left.status] - taskOrder[right.status]
      return priorityDelta !== 0 ? priorityDelta : left.id.localeCompare(right.id)
    })

  const openTerminal = (): void => {
    invoke('open_workspace_in_terminal').catch((e: unknown) =>
      console.error('open_workspace_in_terminal failed:', e)
    )
  }

  const toggleSettings = (): void => {
    showSettings = !showSettings
  }

  const handleCreate = async (): Promise<void> => {
    createError = ''
    creating = true
    try {
      await invoke('create_task', {
        taskId: createTaskId,
        goal: createGoal,
        assignee: createAssignee,
      })
      createTaskId = ''
      createGoal = ''
    } catch (e) {
      createError = e instanceof Error ? e.message : String(e)
      console.error('create_task failed:', e)
    } finally {
      creating = false
    }
  }

  export function openSettings(): void { showSettings = true }
  export function closeSettings(): void { showSettings = false }

  export function acceptFirst(): void {
    const first = [...state.tasks]
      .filter(t => t.status === 'returned')
      .sort((a, b) => a.id.localeCompare(b.id))[0]
    if (first) invoke('accept_task', { taskId: first.id }).catch(console.error)
  }

  export function rejectFirst(): void {
    const first = [...state.tasks]
      .filter(t => t.status === 'returned')
      .sort((a, b) => a.id.localeCompare(b.id))[0]
    if (first) invoke('reject_task', { taskId: first.id, reason: null }).catch(console.error)
  }

  $: if (!createAssignee && state.agents.length > 0) {
    createAssignee = state.agents[0].id
  }

  $: sortedTasks = sortTasks(state.tasks)
  $: activeAgentIds = new Set(
    state.tasks
      .filter(t => t.status === 'dispatched' || t.status === 'in_progress')
      .map(t => t.assignee)
      .filter((a): a is string => !!a)
  )
</script>

<section class="panel">
  <header class="header">
    <div class="wordmark">owlscale</div>
    <div class="header-controls">
      <div class="workspace-path" title={state.dir ?? ''}>{state.dir}</div>
      <button
        class="settings-button"
        type="button"
        on:click={toggleSettings}
        aria-label="Open settings"
      >
        ⚙
      </button>
    </div>
  </header>

  {#if showSettings}
    <SettingsPanel currentDir={state.dir} on:close={closeSettings} />
  {/if}

  <div class="divider"></div>

  <section class="section">
    <div class="section-label">AGENTS</div>
    <div class="section-list">
      {#each state.agents as agent (agent.id)}
        <AgentCard {agent} active={activeAgentIds.has(agent.id)} />
      {/each}
    </div>
  </section>

  <div class="divider"></div>

  <section class="section">
    <div class="section-heading">
      <div class="section-label">TASKS</div>
      {#if state.pending_review > 0}
        {#key state.pending_review}
          <div class="review-badge badge-pop-anim">{state.pending_review}</div>
        {/key}
      {/if}
    </div>

    <div class="composer-shell">
      <input
        class="composer-input"
        bind:value={createTaskId}
        placeholder="task id"
        autocomplete="off"
      />
      <input
        class="composer-input"
        bind:value={createGoal}
        placeholder="goal"
        autocomplete="off"
      />
      <div class="composer-row">
        <select class="composer-select" bind:value={createAssignee} disabled={state.agents.length === 0}>
          {#if state.agents.length === 0}
            <option value="">No agents</option>
          {:else}
            {#each state.agents as agent (agent.id)}
              <option value={agent.id}>{agent.id}</option>
            {/each}
          {/if}
        </select>
        <button
          class="composer-button"
          on:click={handleCreate}
          disabled={creating || !createTaskId.trim() || !createGoal.trim() || !createAssignee}
        >
          {creating ? '…' : 'Create Draft'}
        </button>
      </div>
      {#if createError}
        <div class="composer-error">{createError}</div>
      {/if}
    </div>

    <div class="section-list">
      {#each sortedTasks as task (task.id)}
        <TaskCard {task} />
      {/each}
    </div>
  </section>

  <footer class="footer">
    <button class="footer-button" on:click={openTerminal}>Open Terminal</button>
  </footer>
</section>

<style>
  .panel {
    position: relative;
    width: 320px;
    overflow: hidden;
    background: var(--bg-primary);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: var(--radius-panel);
    box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
  }

  .header {
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 0 12px;
  }

  .wordmark {
    flex: 0 0 auto;
    color: var(--accent-purple);
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.01em;
  }

  .header-controls {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    min-width: 0;
    flex: 1 1 auto;
  }

  .workspace-path {
    max-width: 132px;
    color: var(--text-secondary);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: right;
  }

  .settings-button {
    width: 24px;
    height: 24px;
    flex: 0 0 auto;
    border-radius: 6px;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1;
    transition: color 120ms ease, background-color 120ms ease;
  }

  .settings-button:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  .divider {
    width: 100%;
    height: 1px;
    background: var(--border-color);
  }

  .section {
    padding: 8px 0;
  }

  .section-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 4px 12px;
  }

  .section-label {
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }

  .composer-shell {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px 12px 10px;
  }

  .composer-row {
    display: flex;
    gap: 8px;
  }

  .composer-input,
  .composer-select,
  .composer-button {
    height: 30px;
    border-radius: 8px;
    font-size: 12px;
  }

  .composer-input,
  .composer-select {
    width: 100%;
    padding: 0 10px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
  }

  .composer-button {
    min-width: 96px;
    padding: 0 12px;
    background: var(--accent-purple);
    color: var(--text-primary);
  }

  .composer-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .composer-error {
    font-size: 11px;
    color: var(--accent-red);
  }

  .section-list {
    display: flex;
    flex-direction: column;
  }

  .review-badge {
    min-width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 6px;
    border-radius: 999px;
    background: var(--accent-orange);
    color: var(--bg-primary);
    font-size: 10px;
    font-weight: 700;
  }

  .footer {
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-top: 1px solid var(--border-color);
  }

  .footer-button {
    color: var(--text-secondary);
    font-size: 12px;
    padding: 6px 10px;
    border-radius: 6px;
    transition: color 120ms ease, background-color 120ms ease;
  }

  .footer-button:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }
</style>
