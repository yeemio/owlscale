<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import type { WorkspaceState, SidebarView } from '../types'
  import ReviewFocusView from './ReviewFocusView.svelte'
  import ExecutionFocusView from './ExecutionFocusView.svelte'
  import SetupFocusView from './SetupFocusView.svelte'
  import AgentsFocusView from './AgentsFocusView.svelte'
  import WorktreesFocusView from './WorktreesFocusView.svelte'
  import ActivityFocusView from './ActivityFocusView.svelte'

  export let state: WorkspaceState | null
  export let view: SidebarView
  export let selectedTaskId: string | null = null

  const dispatch = createEventDispatcher<{ select: string; 'create-task': void }>()
</script>

<section class="focus-panel">
  {#if view === 'review' && state}
    <ReviewFocusView {state} {selectedTaskId} on:select />
  {:else if view === 'execution' && state}
    <ExecutionFocusView {state} {selectedTaskId} on:select on:create-task />
  {:else if view === 'setup'}
    <SetupFocusView {state} on:create-task />
  {:else if view === 'agents' && state}
    <AgentsFocusView {state} />
  {:else if view === 'worktrees' && state}
    <WorktreesFocusView {state} />
  {:else if view === 'activity'}
    <ActivityFocusView />
  {:else}
    <div class="placeholder-view">
      <div class="placeholder-label">{view.toUpperCase()}</div>
      <div class="placeholder-hint">No content for this view.</div>
    </div>
  {/if}
</section>

<style>
  .focus-panel {
    height: 100vh;
    overflow-y: auto;
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
  }

  .placeholder-view {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 20px 16px;
  }

  .placeholder-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.5px;
  }

  .placeholder-hint {
    font-size: 12px;
    color: var(--text-secondary);
    opacity: 0.5;
  }
</style>
