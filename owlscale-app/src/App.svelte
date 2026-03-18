<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { listen } from '@tauri-apps/api/event'
  import { onMount, onDestroy } from 'svelte'
  import type { WorkspaceState } from './types'
  import StatusPanel from './lib/StatusPanel.svelte'
  import NoWorkspace from './lib/NoWorkspace.svelte'

  let state: WorkspaceState | null = null
  let loading = true
  let unlisten: (() => void) | null = null

  onMount(async () => {
    try {
      state = await invoke<WorkspaceState>('get_workspace_state')
    } catch {
      state = null
    }
    loading = false
    unlisten = await listen<WorkspaceState>('owlscale://state-changed', (e) => {
      state = e.payload
    })
  })

  onDestroy(() => unlisten?.())
</script>

<main class="app-shell">
  {#if loading}
    <div class="skeleton-shell">
      <div class="sk-header skeleton-block skeleton"></div>
      <div class="sk-label skeleton-block skeleton" style="width:60px"></div>
      <div class="sk-row skeleton-block skeleton"></div>
      <div class="sk-row skeleton-block skeleton"></div>
      <div class="sk-label skeleton-block skeleton" style="width:48px;margin-top:12px"></div>
      <div class="sk-card skeleton-block skeleton"></div>
      <div class="sk-card skeleton-block skeleton"></div>
      <div class="sk-card skeleton-block skeleton"></div>
    </div>
  {:else if !state?.dir}
    <NoWorkspace />
  {:else}
    <StatusPanel {state} />
  {/if}
</main>

<style>
  .app-shell {
    width: 320px;
    min-height: 100vh;
    padding: 0;
    background: var(--bg-primary);
  }

  .skeleton-shell {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
  }

  .sk-header {
    height: 24px;
    width: 80px;
    border-radius: 6px;
    margin-bottom: 10px;
  }

  .sk-label {
    height: 10px;
    border-radius: 4px;
    margin-bottom: 4px;
  }

  .sk-row {
    height: 48px;
    border-radius: 12px;
  }

  .sk-card {
    height: 52px;
    border-radius: 10px;
  }
</style>
