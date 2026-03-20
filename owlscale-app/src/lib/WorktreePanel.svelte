<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import type { WorktreeInfo } from '../types'

  export let worktrees: WorktreeInfo[] = []
  export let selectedWorktreeId: string | null = null

  const kindLabel: Record<WorktreeInfo['type'], string> = {
    main: 'MAIN',
    coding: 'CODE',
    review: 'REVIEW',
  }

  async function openWorktree(id: string) {
    try {
      await invoke('open_worktree', { worktreeId: id })
    } catch (e) {
      console.error('open_worktree failed:', e)
    }
  }
</script>

<section class="section">
  <div class="section-label pad-h">WORKTREES</div>
  <div class="section-list">
    {#each worktrees as worktree (worktree.id)}
      <button
        class="worktree-row"
        class:selected={selectedWorktreeId === worktree.id}
        on:click={() => openWorktree(worktree.id)}
        title={worktree.path}
      >
        <span class="worktree-kind">{kindLabel[worktree.type]}</span>
        <span class="worktree-branch">{worktree.branch}</span>
        <span class="worktree-status">{worktree.status}</span>
      </button>
    {/each}
    {#if worktrees.length === 0}
      <div class="empty-hint">No worktrees registered</div>
    {/if}
  </div>
</section>

<style>
  .section {
    padding: 6px 0;
    flex-shrink: 0;
  }

  .pad-h {
    padding: 4px 12px;
  }

  .section-label {
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }

  .section-list {
    display: flex;
    flex-direction: column;
  }

  .empty-hint {
    padding: 6px 12px;
    color: var(--text-secondary);
    font-size: 11px;
  }

  .worktree-row {
    height: 32px;
    display: grid;
    grid-template-columns: 48px 1fr auto;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    text-align: left;
    transition: background-color 120ms ease;
    border-left: 2px solid transparent;
  }

  .worktree-row:hover {
    background: var(--bg-secondary);
  }

  .worktree-row.selected {
    background: var(--bg-secondary);
    border-left-color: var(--accent-blue);
  }

  .worktree-kind,
  .worktree-status {
    font-size: 10px;
    color: var(--text-secondary);
    white-space: nowrap;
  }

  .worktree-branch {
    min-width: 0;
    color: var(--text-primary);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
