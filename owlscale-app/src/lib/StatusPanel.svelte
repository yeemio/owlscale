<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { createEventDispatcher } from 'svelte'
  import SettingsPanel from './SettingsPanel.svelte'
  import { showSettingsStore } from './settingsStore'
  import type { WorkspaceState, SidebarView } from '../types'

  export let state: WorkspaceState | null
  export let currentView: SidebarView = 'setup'

  const dispatch = createEventDispatcher<{ select: string; navigate: SidebarView; seeded: string }>()

  const handleRefresh = async (): Promise<void> => {
    try { await invoke('manual_refresh') } catch (e) { console.error(e) }
  }

  const handleChooseFolder = async (): Promise<void> => {
    try { await invoke('open_workspace_picker') } catch (e) { console.error(e) }
  }

  const openTerminal = (): void => {
    invoke('open_workspace_in_terminal').catch(console.error)
  }

  // Exported methods for keyboard shortcuts (called from App.svelte)
  export function acceptFirst(): void {
    const first = [...(state?.tasks ?? [])]
      .filter(t => t.status === 'returned')
      .sort((a, b) => a.id.localeCompare(b.id))[0]
    if (first) invoke('accept_task', { taskId: first.id }).catch(console.error)
  }

  export function rejectFirst(): void {
    const first = [...(state?.tasks ?? [])]
      .filter(t => t.status === 'returned')
      .sort((a, b) => a.id.localeCompare(b.id))[0]
    if (first) invoke('reject_task', { taskId: first.id, reason: null }).catch(console.error)
  }

  export function openSettings(): void { showSettingsStore.set(true) }
  export function closeSettings(): void { showSettingsStore.set(false) }

  export function focusTask(taskId: string): void {
    dispatch('select', taskId)
  }

  function navigate(view: SidebarView): void {
    dispatch('navigate', view)
  }

  function handleSeeded(event: CustomEvent<string>): void {
    showSettingsStore.set(false)
    dispatch('seeded', event.detail)
  }

  $: pendingReview = state?.pending_review ?? 0
</script>

<aside class="sidebar">
  <header class="header">
    <div class="wordmark">owlscale</div>
    <div class="header-controls">
      <button class="icon-btn" on:click={handleChooseFolder} title="Choose Folder">📂</button>
      <button class="icon-btn" on:click={handleRefresh} title="Refresh">↻</button>
      <button class="icon-btn" on:click={() => showSettingsStore.set(!$showSettingsStore)} title="Settings (⌘,)">⚙</button>
    </div>
  </header>

  {#if $showSettingsStore}
    <SettingsPanel
      currentDir={state?.dir ?? null}
      agents={state?.agents ?? []}
      agentPolicy={state?.agent_policy ?? null}
      on:close={() => showSettingsStore.set(false)}
      on:seeded={handleSeeded}
    />
  {/if}

  <nav class="nav">
    <div class="nav-section-label">PRIMARY</div>
    <button class="nav-item" class:active={currentView === 'review'} on:click={() => navigate('review')}>
      Review
      {#if pendingReview > 0}
        <span class="review-badge">{pendingReview}</span>
      {/if}
    </button>
    <button class="nav-item" class:active={currentView === 'execution'} on:click={() => navigate('execution')}>Tasks</button>
    <button class="nav-item" class:active={currentView === 'activity'} on:click={() => navigate('activity')}>Activity</button>

    <div class="nav-section-label top-gap">SECONDARY</div>
    <button class="nav-item" class:active={currentView === 'agents'} on:click={() => navigate('agents')}>Agents</button>
    <button class="nav-item" class:active={currentView === 'worktrees'} on:click={() => navigate('worktrees')}>Worktrees</button>
  </nav>

  <footer class="footer">
    <button class="footer-button" on:click={openTerminal}>Open Terminal</button>
    <span class="version">v0.6.0</span>
  </footer>
</aside>

<style>
  .sidebar {
    width: 240px;
    min-width: 240px;
    max-width: 240px;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-primary);
    border-right: 1px solid var(--border-color);
    overflow: hidden;
  }

  .header {
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 0 12px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--border-color);
  }

  .wordmark {
    color: var(--accent-purple);
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.01em;
  }

  .header-controls {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .icon-btn {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    color: var(--text-secondary);
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 120ms ease, background-color 120ms ease;
  }

  .icon-btn:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  .nav {
    flex: 1;
    padding: 12px 0 8px;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }

  .nav-section-label {
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: 4px 12px;
  }

  .nav-section-label.top-gap {
    margin-top: 12px;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 13px;
    color: var(--text-secondary);
    border-radius: 6px;
    margin: 1px 6px;
    cursor: pointer;
    border-left: 2px solid transparent;
    transition: color 120ms ease, background-color 120ms ease;
    width: calc(100% - 12px);
    text-align: left;
  }

  .nav-item:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  .nav-item.active {
    color: var(--text-primary);
    background: var(--bg-secondary);
    border-left-color: var(--accent-purple);
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
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 12px;
    border-top: 1px solid var(--border-color);
    flex-shrink: 0;
  }

  .footer-button {
    color: var(--text-secondary);
    font-size: 11px;
    padding: 4px 8px;
    border-radius: 6px;
    transition: color 120ms ease, background-color 120ms ease;
  }

  .footer-button:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  .version {
    color: var(--text-secondary);
    font-size: 10px;
    opacity: 0.5;
  }
</style>
