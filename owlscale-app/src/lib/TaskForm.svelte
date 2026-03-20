<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import type { AgentInfo, WorktreeInfo } from '../types'

  export let agents: AgentInfo[] = []
  export let worktrees: WorktreeInfo[] = []

  const dispatch = createEventDispatcher<{ close: void }>()

  let mode: 'pack' | 'dispatch' = 'pack'
  let taskId = ''
  let goal = ''
  let agentId = ''
  let worktreeMode: 'create' | 'bind' = 'create'
  let worktreeId = ''
  let busy = false
  let error: string | null = null

  $: bindableWorktrees = worktrees.filter(w => w.type === 'coding' || w.type === 'main')

  async function handleSubmit() {
    if (!taskId.trim()) { error = 'Task ID is required'; return }
    busy = true
    error = null
    try {
      if (mode === 'pack') {
        if (!goal.trim()) { error = 'Goal is required'; busy = false; return }
        await invoke('pack_task', { taskId: taskId.trim(), goal: goal.trim() })
      } else {
        if (!agentId) { error = 'Select an agent'; busy = false; return }
        if (worktreeMode === 'bind' && !worktreeId) {
          error = 'Select an existing worktree'
          busy = false
          return
        }
        await invoke('dispatch_task', {
          taskId: taskId.trim(),
          agentId,
          worktreeMode,
          worktreeId: worktreeMode === 'bind' ? worktreeId : null,
        })
      }
      dispatch('close')
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      busy = false
    }
  }

  function close() { dispatch('close') }
</script>

<div class="form-backdrop">
  <button class="backdrop-dismiss" type="button" on:click={close} aria-label="Close"></button>
  <section class="form-panel" role="dialog" aria-modal="true" aria-label="New task">
    <div class="form-header">
      <div class="form-title">New Task</div>
      <button class="icon-button" type="button" on:click={close} aria-label="Close">✕</button>
    </div>

    <div class="form-tabs">
      <button class="tab" class:active={mode === 'pack'} on:click={() => mode = 'pack'}>Pack</button>
      <button class="tab" class:active={mode === 'dispatch'} on:click={() => mode = 'dispatch'}>Dispatch</button>
    </div>

    <form class="form-body" on:submit|preventDefault={handleSubmit}>
      <label class="field">
        <span class="field-label">Task ID</span>
        <input class="field-input" type="text" bind:value={taskId} placeholder="e.g. fix-auth-bug" />
      </label>

      {#if mode === 'pack'}
        <label class="field">
          <span class="field-label">Goal</span>
          <textarea class="field-textarea" bind:value={goal} placeholder="What should be accomplished?" rows="3"></textarea>
        </label>
      {:else}
        <label class="field">
          <span class="field-label">Assign to</span>
          <select class="field-input" bind:value={agentId}>
            <option value="">Select agent…</option>
            {#each agents as agent}
              <option value={agent.id}>{agent.name} ({agent.role})</option>
            {/each}
          </select>
        </label>

        <label class="field">
          <span class="field-label">Worktree</span>
          <select class="field-input" bind:value={worktreeMode}>
            <option value="create">Create default coding worktree</option>
            <option value="bind">Bind existing worktree</option>
          </select>
        </label>

        {#if worktreeMode === 'bind'}
          <label class="field">
            <span class="field-label">Existing worktree</span>
            <select class="field-input" bind:value={worktreeId}>
              <option value="">Select worktree…</option>
              {#each bindableWorktrees as worktree}
                <option value={worktree.id}>{worktree.id} · {worktree.branch}</option>
              {/each}
            </select>
          </label>
        {/if}
      {/if}

      {#if error}
        <div class="form-error">{error}</div>
      {/if}

      <button class="submit-button" type="submit" disabled={busy}>
        {busy ? 'Working…' : mode === 'pack' ? 'Create Task' : 'Dispatch Task'}
      </button>
    </form>
  </section>
</div>

<style>
  .form-backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.4);
  }

  .backdrop-dismiss {
    position: absolute;
    inset: 0;
    border-radius: 0;
  }

  .form-panel {
    position: relative;
    z-index: 1;
    width: 360px;
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    background: #242426;
    box-shadow: 0 20px 32px rgba(0, 0, 0, 0.4);
  }

  .form-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px;
    border-bottom: 1px solid var(--border-color);
  }

  .form-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .icon-button {
    width: 24px;
    height: 24px;
    color: var(--text-secondary);
    border-radius: 6px;
  }

  .icon-button:hover {
    background: var(--bg-tertiary);
  }

  .form-tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border-color);
  }

  .tab {
    flex: 1;
    height: 32px;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-secondary);
    border-bottom: 2px solid transparent;
    transition: color 120ms ease, border-color 120ms ease;
  }

  .tab.active {
    color: var(--accent-purple);
    border-bottom-color: var(--accent-purple);
  }

  .form-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .field-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  .field-input,
  .field-textarea {
    padding: 6px 8px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 12px;
    font-family: inherit;
  }

  .field-input:focus,
  .field-textarea:focus {
    outline: none;
    border-color: var(--accent-purple);
  }

  .field-textarea {
    resize: vertical;
    min-height: 60px;
  }

  .form-error {
    font-size: 11px;
    color: var(--accent-red);
  }

  .submit-button {
    height: 32px;
    border-radius: 6px;
    background: var(--accent-purple);
    color: var(--text-primary);
    font-size: 12px;
    font-weight: 600;
    transition: filter 120ms ease;
  }

  .submit-button:hover:not(:disabled) {
    filter: brightness(0.9);
  }

  .submit-button:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
