<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import type { WorkspaceState, WorktreeInfo } from '../types'

  export let state: WorkspaceState

  const kindLabel: Record<WorktreeInfo['type'], string> = {
    main:   'MAIN',
    coding: 'CODE',
    review: 'REV',
  }

  const kindColor: Record<WorktreeInfo['type'], string> = {
    main:   'var(--text-secondary)',
    coding: 'var(--accent-blue)',
    review: 'var(--accent-purple)',
  }

  const statusColor: Record<string, string> = {
    ready:   'var(--accent-green)',
    missing: 'var(--accent-red)',
    working: 'var(--accent-blue)',
  }

  // Group: coding first, then review, then main
  $: grouped = (['coding', 'review', 'main'] as WorktreeInfo['type'][]).flatMap(kind =>
    state.worktrees.filter(w => w.type === kind)
  )

  // Derive task for each worktree (coding-{id} or review-{id})
  function taskIdForWorktree(worktree: WorktreeInfo): string | null {
    if (worktree.id.startsWith('coding-')) return worktree.id.slice('coding-'.length)
    if (worktree.id.startsWith('review-')) return worktree.id.slice('review-'.length)
    return null
  }

  async function openWorktree(id: string) {
    try { await invoke('open_worktree', { worktreeId: id }) }
    catch (e) { console.error('open_worktree failed:', e) }
  }
</script>

<div class="panel-root">
  <header class="panel-header">
    <div class="panel-title-row">
      <span class="panel-label">WORKTREES</span>
      <span class="panel-count">{state.worktrees.length}</span>
    </div>
  </header>

  <div class="worktree-list">
    {#each grouped as wt (wt.id)}
      {@const taskId = taskIdForWorktree(wt)}
      <div class="wt-row">
        <span
          class="wt-kind"
          style:color={kindColor[wt.type]}
        >{kindLabel[wt.type]}</span>

        <div class="wt-body">
          <div class="wt-branch">{wt.branch}</div>
          <div class="wt-meta-row">
            {#if taskId}
              <span class="wt-task-id">{taskId}</span>
            {/if}
            {#if wt.agent_id}
              <span class="wt-agent">{wt.agent_id}</span>
            {/if}
            <span class="wt-path" title={wt.path}>{wt.path}</span>
          </div>
        </div>

        <div class="wt-right">
          <span
            class="wt-status"
            style:color={statusColor[wt.status] ?? 'var(--text-secondary)'}
          >{wt.status}</span>
          {#if wt.type !== 'main'}
            <button class="wt-open-btn" on:click={() => openWorktree(wt.id)} title="Open in terminal">
              ↗
            </button>
          {/if}
        </div>
      </div>
    {/each}

    {#if state.worktrees.length === 0}
      <div class="empty-state">
        <div class="empty-icon" aria-hidden="true">⬡</div>
        <div class="empty-text">No worktrees registered</div>
        <div class="empty-hint">Dispatch a task to create a coding worktree</div>
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

  .worktree-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .wt-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    transition: background-color 120ms ease;
  }

  .wt-row:hover {
    background: var(--bg-secondary);
  }

  .wt-kind {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.4px;
    min-width: 36px;
    margin-top: 3px;
  }

  .wt-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .wt-branch {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .wt-meta-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .wt-task-id,
  .wt-agent {
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 10px;
    color: var(--text-secondary);
    background: var(--bg-tertiary);
    padding: 1px 5px;
    border-radius: 3px;
  }

  .wt-path {
    font-size: 10px;
    color: var(--text-secondary);
    opacity: 0.5;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 200px;
  }

  .wt-right {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .wt-status {
    font-size: 10px;
    font-weight: 600;
    text-transform: lowercase;
  }

  .wt-open-btn {
    width: 22px;
    height: 22px;
    border-radius: 5px;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 120ms ease, color 120ms ease;
  }

  .wt-open-btn:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
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
