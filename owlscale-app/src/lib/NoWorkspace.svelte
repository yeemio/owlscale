<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { onMount } from 'svelte'

  let detectedWorkspaces: string[] = []
  let scanning = false

  const pickFolder = async () => {
    try {
      const dir = await invoke<string | null>('pick_workspace_dir')
      if (dir) await invoke('set_workspace_dir', { path: dir })
    } catch (e) {
      console.error('pick_workspace_dir failed:', e)
    }
  }

  const selectWorkspace = async (path: string) => {
    try {
      await invoke('set_workspace_dir', { path })
    } catch (e) {
      console.error('set_workspace_dir failed:', e)
    }
  }

  onMount(async () => {
    scanning = true
    try {
      detectedWorkspaces = await invoke<string[]>('scan_workspaces')
    } catch {
      detectedWorkspaces = []
    }
    scanning = false
  })
</script>

<div class="empty-state">
  <div class="empty-icon" aria-hidden="true">⬡</div>
  <div class="empty-title">No workspace</div>
  <div class="empty-subtitle">
    cd into a project and run
    <code class="inline-cmd">owlscale init</code>
  </div>

  {#if scanning}
    <div class="detect-hint">Scanning for workspaces…</div>
  {:else if detectedWorkspaces.length > 0}
    <div class="detected-section">
      <div class="detected-label">Detected workspaces</div>
      <div class="detected-list">
        {#each detectedWorkspaces as ws}
          <button class="ws-item" on:click={() => selectWorkspace(ws)}>
            <span class="ws-icon">📂</span>
            <span class="ws-path">{ws}</span>
          </button>
        {/each}
      </div>
    </div>
  {/if}

  <button class="pick-link" type="button" on:click={pickFolder}>
    or open a folder…
  </button>
</div>

<style>
  .empty-state {
    width: 100%;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 20px 24px;
    background: var(--bg-primary);
  }

  .empty-icon {
    font-size: 40px;
    line-height: 1;
    color: var(--accent-purple);
    margin-bottom: 4px;
  }

  .empty-title {
    font-size: 15px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .empty-subtitle {
    font-size: 13px;
    color: var(--text-secondary);
    text-align: center;
  }

  .inline-cmd {
    display: inline-block;
    background: rgba(124, 58, 237, 0.18);
    color: var(--accent-purple);
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 12px;
    padding: 1px 6px;
    border-radius: 4px;
  }

  .detect-hint {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 8px;
  }

  .detected-section {
    margin-top: 12px;
    width: 100%;
    max-width: 340px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .detected-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.4px;
    text-transform: uppercase;
    padding: 0 4px;
  }

  .detected-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .ws-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    border-radius: 6px;
    text-align: left;
    transition: background-color 120ms ease;
  }

  .ws-item:hover {
    background: var(--bg-secondary);
  }

  .ws-icon {
    font-size: 14px;
    flex-shrink: 0;
  }

  .ws-path {
    font-size: 12px;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .pick-link {
    margin-top: 4px;
    font-size: 12px;
    color: var(--text-secondary);
    border-radius: 4px;
    padding: 2px 6px;
    transition: color 120ms ease;
  }

  .pick-link:hover {
    color: var(--text-primary);
  }
</style>
