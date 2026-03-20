<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import type { WorkspaceState } from '../types'
  import TaskCard from './TaskCard.svelte'

  export let state: WorkspaceState
  export let selectedTaskId: string | null = null

  const dispatch = createEventDispatcher<{ select: string }>()

  $: returnedTasks = state.tasks.filter(t => t.status === 'returned')

  function selectTask(id: string) {
    dispatch('select', id)
  }

  function reviewNext() {
    if (returnedTasks.length > 0) {
      dispatch('select', returnedTasks[0].id)
    }
  }

</script>

<div class="focus-view">
  <header class="focus-header">
    <div class="focus-mode-label">REVIEW FOCUS</div>
    <h2 class="focus-title">
      {returnedTasks.length} task{returnedTasks.length !== 1 ? 's' : ''} awaiting review
    </h2>
    {#if returnedTasks.length > 0}
      <button class="primary-cta" on:click={reviewNext}>
        Review Next Task →
      </button>
    {/if}
  </header>

  <div class="task-list">
    {#if returnedTasks.length === 0}
      <div class="empty-state">
        <div class="empty-icon">✓</div>
        <div class="empty-text">No tasks awaiting review</div>
      </div>
    {:else}
      {#each returnedTasks as task (task.id)}
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div on:click={() => selectTask(task.id)}>
          <TaskCard
            {task}
            selected={task.id === selectedTaskId}
            reviewWorktreeReady={task.review_worktree_ready}
            codingWorktreeMissing={task.coding_worktree_missing}
            worktreeOwnerOverride={task.ownership_override}
            showWorktreeSignals={true}
          />
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .focus-view {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .focus-header {
    padding: 20px 16px 16px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .focus-mode-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--accent-orange);
    letter-spacing: 0.5px;
  }

  .focus-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }

  .primary-cta {
    margin-top: 8px;
    align-self: flex-start;
    height: 32px;
    padding: 0 14px;
    border-radius: 8px;
    background: var(--accent-orange);
    color: var(--bg-primary);
    font-size: 12px;
    font-weight: 600;
    transition: filter 120ms ease;
  }

  .primary-cta:hover {
    filter: brightness(0.9);
  }

  .task-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 48px 16px;
    color: var(--text-secondary);
  }

  .empty-icon {
    font-size: 32px;
    color: var(--accent-green);
    opacity: 0.6;
  }

  .empty-text {
    font-size: 13px;
  }
</style>
