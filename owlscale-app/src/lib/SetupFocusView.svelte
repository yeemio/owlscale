<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { createEventDispatcher } from 'svelte'
  import { showSettingsStore } from './settingsStore'
  import type { WorkspaceState } from '../types'

  export let state: WorkspaceState | null

  const dispatch = createEventDispatcher<{ 'create-task': void }>()

  // S3: session-only dismiss, not persisted
  let ownershipDismissed = false

  $: ownershipNeeded =
    state?.agent_policy === null ||
    (state?.agent_policy !== undefined &&
      state.agent_policy !== null &&
      state.agent_policy.default_execution_agent_id === null &&
      state.agent_policy.default_review_agent_id === null)

  let workspacePickerError: string | null = null

  async function handleChooseWorkspace() {
    workspacePickerError = null
    try {
      // Backend picks dir, validates .owlscale/, activates, refreshes state.
      // State update arrives via owlscale://state-changed event — no manual refresh needed.
      await invoke<string | null>('open_workspace_picker')
    } catch (e) {
      workspacePickerError = typeof e === 'string' ? e : 'Could not open workspace'
      console.error('workspace picker failed:', e)
    }
  }

  function handleCreateFirstTask() {
    dispatch('create-task')
  }

  function handleSetDefaultAgents() {
    showSettingsStore.set(true)
  }

  function dismissOwnership() {
    ownershipDismissed = true
  }
</script>

<div class="focus-view">
  <header class="focus-header">
    <div class="focus-mode-label">SETUP</div>
    {#if !state?.dir}
      <h2 class="focus-title">Choose a workspace to get started</h2>
    {:else}
      <h2 class="focus-title">Workspace ready</h2>
      <p class="focus-subtitle">{state.dir}</p>
    {/if}
  </header>

  <div class="setup-body">
    {#if !state?.dir}
      <!-- No workspace -->
      <div class="setup-card">
        <div class="setup-card-icon">📂</div>
        <div class="setup-card-title">No workspace selected</div>
        <p class="setup-card-body">
          Select an <code>.owlscale</code> workspace directory to start coordinating agents.
        </p>
        <button class="primary-btn" on:click={handleChooseWorkspace}>
          Choose Workspace
        </button>
        {#if workspacePickerError}
          <div class="picker-error">{workspacePickerError}</div>
        {/if}
      </div>
    {:else}
      <!-- Has workspace -->
      {#if ownershipNeeded && !ownershipDismissed}
        <!-- S3: Ownership notice -->
        <div class="ownership-notice">
          <div class="notice-title">Default agents not configured</div>
          <p class="notice-body">
            You can still create tasks, but each dispatch will require manually choosing an agent.
            Set defaults to skip this step.
          </p>
          <div class="notice-actions">
            <button class="primary-btn small" on:click={handleSetDefaultAgents}>
              Set Default Agents
            </button>
            <button class="text-btn" on:click={dismissOwnership}>
              Skip For Now
            </button>
          </div>
        </div>
      {/if}

      <!-- Create first task -->
      {#if state.tasks.length === 0}
        <div class="setup-card">
          <div class="setup-card-icon">✦</div>
          <div class="setup-card-title">No tasks yet</div>
          <p class="setup-card-body">Create your first task to dispatch to an agent.</p>
          <button class="primary-btn" on:click={handleCreateFirstTask}>
            Create First Task
          </button>
        </div>
      {:else}
        <div class="all-good">
          <div class="all-good-icon">✓</div>
          <div class="all-good-text">All tasks are settled</div>
          <div class="all-good-hint">No review or active work pending</div>
        </div>
      {/if}
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
  }

  .focus-mode-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--accent-purple);
    letter-spacing: 0.5px;
    margin-bottom: 6px;
  }

  .focus-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }

  .focus-subtitle {
    font-size: 11px;
    color: var(--text-secondary);
    margin: 4px 0 0;
    font-family: ui-monospace, "SF Mono", monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .setup-body {
    flex: 1;
    padding: 20px 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow-y: auto;
  }

  /* Ownership notice (S3) */
  .ownership-notice {
    border: 1px solid var(--accent-orange);
    border-radius: 10px;
    padding: 16px;
    background: rgba(255, 159, 10, 0.06);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .notice-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--accent-orange);
  }

  .notice-body {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin: 0;
  }

  .notice-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 4px;
  }

  /* Setup card (no workspace / no tasks) */
  .setup-card {
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 24px;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 8px;
    background: var(--bg-secondary);
  }

  .setup-card-icon {
    font-size: 28px;
    margin-bottom: 4px;
  }

  .setup-card-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .setup-card-body {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin: 0;
  }

  .setup-card-body code {
    font-family: ui-monospace, "SF Mono", monospace;
    background: var(--bg-tertiary);
    padding: 1px 5px;
    border-radius: 4px;
  }

  /* All good state */
  .all-good {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 48px 16px;
    color: var(--text-secondary);
  }

  .all-good-icon {
    font-size: 32px;
    color: var(--accent-green);
    opacity: 0.7;
  }

  .all-good-text {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .all-good-hint {
    font-size: 12px;
  }

  /* Shared button styles */
  .primary-btn {
    height: 34px;
    padding: 0 16px;
    border-radius: 8px;
    background: var(--accent-purple);
    color: var(--bg-primary);
    font-size: 12px;
    font-weight: 600;
    transition: filter 120ms ease;
    white-space: nowrap;
  }

  .primary-btn:hover {
    filter: brightness(0.85);
  }

  .primary-btn.small {
    height: 28px;
    font-size: 11px;
  }

  .text-btn {
    font-size: 12px;
    color: var(--text-secondary);
    padding: 4px 0;
    transition: color 120ms ease;
  }

  .text-btn:hover {
    color: var(--text-primary);
  }

  .picker-error {
    font-size: 11px;
    color: var(--accent-red);
    text-align: center;
    margin-top: 2px;
  }
</style>
