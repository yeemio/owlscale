<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import type { WorkspaceState } from '../types'
  import TaskCard from './TaskCard.svelte'

  export let state: WorkspaceState
  export let selectedTaskId: string | null = null

  const dispatch = createEventDispatcher<{ select: string }>()

  $: draftTasks = state.tasks.filter(t => t.status === 'draft')
  $: dispatchedTasks = state.tasks.filter(t => t.status === 'dispatched')
  $: inProgressTasks = state.tasks.filter(t => t.status === 'in_progress')

  function selectTask(id: string) {
    dispatch('select', id)
  }

  function dispatchNext() {
    if (draftTasks.length > 0) dispatch('select', draftTasks[0].id)
  }
</script>

<div class="focus-view">
  <header class="focus-header">
    <div class="focus-mode-label">EXECUTION FOCUS</div>
    <h2 class="focus-title">
      {draftTasks.length + dispatchedTasks.length + inProgressTasks.length} active task{
        draftTasks.length + dispatchedTasks.length + inProgressTasks.length !== 1 ? 's' : ''
      }
    </h2>
    {#if draftTasks.length > 0}
      <button class="primary-cta" on:click={dispatchNext}>
        Dispatch Next Draft →
      </button>
    {:else}
      <button class="secondary-cta" on:click={() => {}}>
        + Create Task
      </button>
    {/if}
  </header>

  <div class="task-list">
    {#if draftTasks.length > 0}
      <div class="group-label">DRAFT</div>
      {#each draftTasks as task (task.id)}
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div on:click={() => selectTask(task.id)}>
          <TaskCard
            {task}
            selected={task.id === selectedTaskId}
            worktreeOwnerOverride={task.ownership_override}
          />
        </div>
      {/each}
    {/if}

    {#if dispatchedTasks.length > 0}
      <div class="group-label">DISPATCHED</div>
      {#each dispatchedTasks as task (task.id)}
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div on:click={() => selectTask(task.id)}>
          <TaskCard
            {task}
            selected={task.id === selectedTaskId}
            worktreeOwnerOverride={task.ownership_override}
          />
        </div>
      {/each}
    {/if}

    {#if inProgressTasks.length > 0}
      <div class="group-label">IN PROGRESS</div>
      {#each inProgressTasks as task (task.id)}
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div on:click={() => selectTask(task.id)}>
          <TaskCard
            {task}
            selected={task.id === selectedTaskId}
            worktreeOwnerOverride={task.ownership_override}
          />
        </div>
      {/each}
    {/if}

    {#if draftTasks.length === 0 && dispatchedTasks.length === 0 && inProgressTasks.length === 0}
      <div class="empty-state">
        <div class="empty-text">No active tasks</div>
      </div>
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
    color: var(--accent-blue);
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
    background: var(--accent-blue);
    color: var(--bg-primary);
    font-size: 12px;
    font-weight: 600;
    transition: filter 120ms ease;
  }

  .primary-cta:hover {
    filter: brightness(0.9);
  }

  .secondary-cta {
    margin-top: 8px;
    align-self: flex-start;
    height: 32px;
    padding: 0 14px;
    border-radius: 8px;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    font-size: 12px;
    font-weight: 600;
  }

  .task-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .group-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.5px;
    padding: 8px 16px 4px;
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 48px 16px;
    color: var(--text-secondary);
  }

  .empty-text {
    font-size: 13px;
  }
</style>
