<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { listen } from '@tauri-apps/api/event'
  import { onMount, onDestroy } from 'svelte'
  import type { WorkspaceState, FocusMode, SidebarView } from './types'
  import StatusPanel from './lib/StatusPanel.svelte'
  import FocusPanel from './lib/FocusPanel.svelte'
  import DetailPanel from './lib/DetailPanel.svelte'
  import CreateTaskSheet from './lib/CreateTaskSheet.svelte'

  let state: WorkspaceState | null = null
  let loading = true
  let selectedTaskId: string | null = null
  let statusPanel: StatusPanel
  let showCreateTaskSheet = false
  let selectedSidebarView: SidebarView | null = null
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

  $: currentView = (selectedSidebarView ?? focusMode) as SidebarView

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

  function handleNavigate(e: CustomEvent<SidebarView>) {
    selectedSidebarView = e.detail
    if (e.detail === 'review') {
      const firstReturned = state?.tasks.find((task) => task.status === 'returned') ?? null
      selectedTaskId = firstReturned?.id ?? null
      return
    }
    if (e.detail === 'activity' || e.detail === 'agents' || e.detail === 'worktrees') {
      selectedTaskId = null
    }
  }

  function handleCreateTask() {
    showCreateTaskSheet = true
  }

  function handleSheetCreated(e: CustomEvent<string>) {
    showCreateTaskSheet = false
    selectedTaskId = e.detail
  }

  function firstActiveTaskId(nextState: WorkspaceState): string | null {
    return (
      nextState.tasks.find(
        (task) =>
          task.status === 'draft' ||
          task.status === 'dispatched' ||
          task.status === 'in_progress'
      )?.id ?? null
    )
  }

  async function handleSeeded(e: CustomEvent<string>) {
    selectedSidebarView = 'review'
    selectedTaskId = e.detail
    try {
      state = await invoke<WorkspaceState>('get_workspace_state')
    } catch (error) {
      console.error('refresh after seeded task failed:', error)
    }
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
      const effectiveView: SidebarView =
        selectedSidebarView ?? (
          !e.payload.dir
            ? 'setup'
            : e.payload.pending_review > 0
              ? 'review'
              : e.payload.tasks.some((task) =>
                    task.status === 'draft' || task.status === 'dispatched' || task.status === 'in_progress'
                  )
                ? 'execution'
                : 'setup'
        )

      if (effectiveView === 'review') {
        const selectedTask = selectedTaskId
          ? e.payload.tasks.find((task) => task.id === selectedTaskId) ?? null
          : null
        const selectedStillReview = selectedTask?.status === 'returned'

        if (!selectedStillReview) {
          const nextReturned = e.payload.tasks.find((task) => task.status === 'returned') ?? null
          selectedTaskId = nextReturned?.id ?? null
        }
      }

      if (selectedSidebarView === 'review' && e.payload.pending_review === 0) {
        selectedSidebarView = null
        selectedTaskId = firstActiveTaskId(e.payload)
      }
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
      <StatusPanel
        bind:this={statusPanel}
        state={null}
        currentView="setup"
        on:select={handleSelect}
        on:navigate={handleNavigate}
        on:seeded={handleSeeded}
      />
      <FocusPanel state={null} view="setup" {selectedTaskId} on:select={handleSelect} on:create-task={handleCreateTask} />
      <DetailPanel task={null} worktrees={[]} agents={[]} agentPolicy={null} />
    </div>
  {:else}
    <div class="app-layout">
      <StatusPanel
        bind:this={statusPanel}
        {state}
        currentView={currentView}
        on:select={handleSelect}
        on:navigate={handleNavigate}
        on:seeded={handleSeeded}
      />
      <FocusPanel
        {state}
        view={currentView}
        {selectedTaskId}
        on:select={handleSelect}
        on:create-task={handleCreateTask}
      />
      <DetailPanel
        task={state.tasks.find(t => t.id === selectedTaskId) ?? null}
        worktrees={state.worktrees}
        agents={state.agents}
        agentPolicy={state.agent_policy}
      />
    </div>
  {/if}

  <CreateTaskSheet
    show={showCreateTaskSheet}
    on:close={() => (showCreateTaskSheet = false)}
    on:created={handleSheetCreated}
  />
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
