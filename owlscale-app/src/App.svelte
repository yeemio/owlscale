<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { listen } from '@tauri-apps/api/event'
  import { onMount, onDestroy } from 'svelte'
  import type { WorkspaceState, FocusMode } from './types'
  import StatusPanel from './lib/StatusPanel.svelte'
  import FocusPanel from './lib/FocusPanel.svelte'
  import DetailPanel from './lib/DetailPanel.svelte'

  let state: WorkspaceState | null = null
  let loading = true
  let selectedTaskId: string | null = null
  let statusPanel: StatusPanel
  let unlistenState: (() => void) | null = null
  let unlistenFocus: (() => void) | null = null

  // Derive focusMode from current state — purely reactive, no persistence
  $: activeTasks = state?.tasks.filter(t =>
    t.status === 'draft' || t.status === 'dispatched' || t.status === 'in_progress'
  ) ?? []

  $: focusMode = (!state?.dir
    ? 'setup'
    : (state.pending_review > 0)
      ? 'review'
      : activeTasks.length > 0
        ? 'execution'
        : 'setup') as FocusMode

  function handleKeydown(e: KeyboardEvent) {
    if (!state?.dir) return
    if (e.metaKey && e.key === 'a') { e.preventDefault(); statusPanel?.acceptFirst() }
    if (e.metaKey && e.key === 'r') { e.preventDefault(); statusPanel?.rejectFirst() }
    if (e.metaKey && e.key === ',') { e.preventDefault(); statusPanel?.openSettings() }
    if (e.key === 'Escape') { statusPanel?.closeSettings() }
  }

  function handleSelect(e: CustomEvent<string>) {
    selectedTaskId = e.detail
  }

  onMount(async () => {
    try {
      state = await invoke<WorkspaceState>('get_workspace_state')
    } catch {
      state = null
    }
    loading = false

    unlistenState = await listen<WorkspaceState>('owlscale://state-changed', (e) => {
      state = e.payload
    })

    unlistenFocus = await listen<string>('owlscale://focus-task', (e) => {
      selectedTaskId = e.payload
      statusPanel?.focusTask(e.payload)
    })
  })

  onDestroy(() => {
    unlistenState?.()
    unlistenFocus?.()
  })
</script>

<svelte:window on:keydown={handleKeydown} />

<main class="app-shell">
  {#if loading}
    <div class="skeleton-shell">
      <div class="sk-sidebar">
        <div class="sk-header skeleton-block skeleton"></div>
        <div class="sk-row skeleton-block skeleton"></div>
        <div class="sk-row skeleton-block skeleton"></div>
        <div class="sk-card skeleton-block skeleton"></div>
        <div class="sk-card skeleton-block skeleton"></div>
      </div>
      <div class="sk-focus skeleton-block skeleton"></div>
      <div class="sk-inspector">
        <div class="sk-detail-block skeleton-block skeleton"></div>
      </div>
    </div>
  {:else if !state?.dir}
    <div class="app-layout">
      <StatusPanel bind:this={statusPanel} state={null} focusMode="setup" on:select={handleSelect} />
      <FocusPanel state={null} focusMode="setup" {selectedTaskId} on:select={handleSelect} />
      <DetailPanel task={null} worktrees={[]} agents={[]} agentPolicy={null} />
    </div>
  {:else}
    <div class="app-layout">
      <StatusPanel
        bind:this={statusPanel}
        {state}
        {focusMode}
        on:select={handleSelect}
      />
      <FocusPanel
        {state}
        {focusMode}
        {selectedTaskId}
        on:select={handleSelect}
      />
      <DetailPanel
        task={state.tasks.find(t => t.id === selectedTaskId) ?? null}
        worktrees={state.worktrees}
        agents={state.agents}
        agentPolicy={state.agent_policy}
      />
    </div>
  {/if}
</main>

<style>
  .app-shell {
    width: 100%;
    min-height: 100vh;
    background: var(--bg-primary);
  }

  .app-layout {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr) 360px;
    min-height: 100vh;
  }

  .skeleton-shell {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr) 360px;
    min-height: 100vh;
  }

  .sk-sidebar {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border-right: 1px solid var(--border-color);
  }

  .sk-focus {
    border-right: 1px solid var(--border-color);
  }

  .sk-inspector {
    padding: 20px;
  }

  .sk-header {
    height: 24px;
    width: 80px;
    border-radius: 6px;
    margin-bottom: 10px;
  }

  .sk-row {
    height: 32px;
    border-radius: 8px;
  }

  .sk-card {
    height: 48px;
    border-radius: 10px;
  }

  .sk-detail-block {
    height: 200px;
    border-radius: 10px;
  }
</style>
