<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import type { AppConfig } from '../types'

  export let currentDir: string | null

  const dispatch = createEventDispatcher<{ close: void }>()

  let settings: AppConfig = {
    workspace_dir: null,
    launch_at_login: false,
  }
  let loading = true
  let busy = false
  let error: string | null = null

  const loadSettings = async () => {
    loading = true
    error = null
    try {
      settings = await invoke<AppConfig>('get_settings')
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load settings.'
    } finally {
      loading = false
    }
  }

  const handlePickWorkspace = async () => {
    busy = true
    error = null
    try {
      const selected = await invoke<string | null>('pick_workspace_dir')
      if (selected) {
        await invoke('set_workspace_dir', { path: selected })
        settings = { ...settings, workspace_dir: selected }
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to change workspace.'
    } finally {
      busy = false
    }
  }

  const handleLaunchToggle = async (event: Event) => {
    const target = event.currentTarget as HTMLInputElement
    const enabled = target.checked
    busy = true
    error = null
    try {
      await invoke('set_launch_at_login', { enabled })
      settings = { ...settings, launch_at_login: enabled }
    } catch (e) {
      target.checked = !enabled
      error = e instanceof Error ? e.message : 'Failed to update launch-at-login.'
    } finally {
      busy = false
    }
  }

  const closePanel = () => {
    dispatch('close')
  }

  onMount(loadSettings)
</script>

<div class="settings-backdrop">
  <button
    class="backdrop-dismiss"
    type="button"
    on:click={closePanel}
    aria-label="Close settings"
  ></button>

  <section class="settings-panel" role="dialog" aria-modal="true" aria-label="Settings">
    <div class="settings-header">
      <div>
        <div class="settings-title">Settings</div>
        <div class="settings-subtitle">Desktop app preferences</div>
      </div>
      <button class="icon-button" type="button" on:click={closePanel} aria-label="Close settings">
        ✕
      </button>
    </div>

    {#if loading}
      <div class="settings-loading">Loading settings…</div>
    {:else}
      <div class="settings-section">
        <div class="setting-row">
          <div class="setting-copy">
            <div class="setting-label">Workspace directory</div>
            <div class="setting-value" title={currentDir ?? settings.workspace_dir ?? ''}>
              {currentDir ?? settings.workspace_dir ?? 'No workspace selected'}
            </div>
          </div>
          <button class="action-button" type="button" on:click={handlePickWorkspace} disabled={busy}>
            {busy ? 'Working…' : 'Change…'}
          </button>
        </div>

        <label class="setting-row toggle-row">
          <div class="setting-copy">
            <div class="setting-label">Launch at login</div>
            <div class="setting-hint">Starts owlscale when you sign in.</div>
          </div>
          <input
            class="toggle"
            type="checkbox"
            checked={settings.launch_at_login}
            on:change={handleLaunchToggle}
            disabled={busy}
          />
        </label>
      </div>
    {/if}

    {#if error}
      <div class="settings-error">{error}</div>
    {/if}

    <div class="settings-footer">
      <button class="close-button" type="button" on:click={closePanel}>Close</button>
    </div>
  </section>
</div>

<style>
  .settings-backdrop {
    position: absolute;
    inset: 0;
    z-index: 10;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 10px;
    background: rgba(0, 0, 0, 0.22);
  }

  .backdrop-dismiss {
    position: absolute;
    inset: 0;
    border-radius: 0;
  }

  .settings-panel {
    position: relative;
    z-index: 1;
    width: 300px;
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    background: #242426;
    box-shadow: 0 20px 32px rgba(0, 0, 0, 0.4);
  }

  .settings-header,
  .settings-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px;
  }

  .settings-header {
    border-bottom: 1px solid var(--border-color);
  }

  .settings-title {
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
  }

  .settings-subtitle,
  .setting-hint,
  .settings-loading {
    color: var(--text-secondary);
    font-size: 11px;
  }

  .settings-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
  }

  .setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .setting-copy {
    flex: 1 1 auto;
    min-width: 0;
  }

  .setting-label {
    color: var(--text-primary);
    font-size: 12px;
    font-weight: 500;
    margin-bottom: 4px;
  }

  .setting-value {
    color: var(--text-secondary);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .toggle-row {
    cursor: default;
  }

  .toggle {
    width: 16px;
    height: 16px;
    accent-color: var(--accent-purple);
    flex: 0 0 auto;
  }

  .action-button,
  .close-button,
  .icon-button {
    border-radius: 6px;
    transition: background-color 120ms ease, color 120ms ease, opacity 120ms ease;
  }

  .action-button,
  .close-button {
    height: 28px;
    padding: 0 10px;
    font-size: 11px;
  }

  .action-button {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }

  .action-button:hover,
  .close-button:hover,
  .icon-button:hover {
    background: var(--bg-tertiary);
  }

  .close-button {
    background: transparent;
    color: var(--text-secondary);
  }

  .icon-button {
    width: 24px;
    height: 24px;
    color: var(--text-secondary);
  }

  .settings-error {
    padding: 0 12px 12px;
    color: var(--accent-red);
    font-size: 11px;
  }
</style>
