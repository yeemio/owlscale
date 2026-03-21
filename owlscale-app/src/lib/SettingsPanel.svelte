<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import type { AgentInfo, AgentPolicy, AppConfig } from '../types'

  export let currentDir: string | null
  export let agents: AgentInfo[] = []
  export let agentPolicy: AgentPolicy | null = null

  const dispatch = createEventDispatcher<{ close: void; seeded: string }>()

  const APP_VERSION = '0.6.0'
  const SHOW_DEV_UTILITIES = true

  let settings: AppConfig = {
    workspace_dir: null,
    launch_at_login: false,
    notifications_enabled: true,
    refresh_interval_secs: 3,
  }
  let loading = true
  let busy = false
  let error: string | null = null
  let devBusy = false
  let devMessage: string | null = null
  let executionAgentId: string | null = null
  let reviewAgentId: string | null = null

  $: if (!busy) {
    executionAgentId = agentPolicy?.default_execution_agent_id ?? null
    reviewAgentId = agentPolicy?.default_review_agent_id ?? null
  }

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
      const selected = await invoke<string | null>('open_workspace_picker')
      if (selected) {
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

  const handleNotificationsToggle = async (event: Event) => {
    const target = event.currentTarget as HTMLInputElement
    const enabled = target.checked
    busy = true
    error = null
    try {
      await invoke('set_notifications_enabled', { enabled })
      settings = { ...settings, notifications_enabled: enabled }
    } catch (e) {
      target.checked = !enabled
      error = e instanceof Error ? e.message : 'Failed to update notifications.'
    } finally {
      busy = false
    }
  }

  const handleRefreshInterval = async (event: Event) => {
    const target = event.currentTarget as HTMLSelectElement
    const secs = parseInt(target.value, 10)
    busy = true
    error = null
    try {
      await invoke('set_refresh_interval', { secs })
      settings = { ...settings, refresh_interval_secs: secs }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to update refresh interval.'
    } finally {
      busy = false
    }
  }

  const closePanel = () => {
    dispatch('close')
  }

  const handleSeedReviewDemo = async () => {
    devBusy = true
    devMessage = null
    error = null
    try {
      const taskId = await invoke<string>('dev_seed_returned_task', {
        goal: 'Demo review task',
        summary: 'Generated from Settings for review/demo flow verification.',
      })
      devMessage = `Generated returned task: ${taskId}`
      dispatch('seeded', taskId)
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to generate demo review task.'
    } finally {
      devBusy = false
    }
  }

  const handleAgentPolicyChange = async (
    kind: 'execution' | 'review',
    event: Event,
  ) => {
    const target = event.currentTarget as HTMLSelectElement
    const nextValue = target.value || null
    const nextExecutionAgentId = kind === 'execution' ? nextValue : executionAgentId
    const nextReviewAgentId = kind === 'review' ? nextValue : reviewAgentId

    busy = true
    error = null
    try {
      await invoke<AgentPolicy>('set_agent_policy', {
        executionAgentId: nextExecutionAgentId,
        reviewAgentId: nextReviewAgentId,
      })
      executionAgentId = nextExecutionAgentId
      reviewAgentId = nextReviewAgentId
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to update default agents.'
      executionAgentId = agentPolicy?.default_execution_agent_id ?? null
      reviewAgentId = agentPolicy?.default_review_agent_id ?? null
    } finally {
      busy = false
    }
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
        <div class="section-heading">General</div>

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

      <div class="settings-divider"></div>

      <div class="settings-section">
        <div class="section-heading">Default Agents</div>

        {#if agents.length === 0}
          <div class="setting-hint">No agents in roster.</div>
        {:else}
          <div class="setting-row stacked-row">
            <div class="setting-copy">
              <div class="setting-label">Default Execution Agent</div>
              <div class="setting-hint">Used to prefill dispatch for new draft tasks.</div>
            </div>
            <select
              class="interval-select full-width-select"
              value={executionAgentId ?? ''}
              on:change={(event) => handleAgentPolicyChange('execution', event)}
              disabled={busy}
            >
              <option value="">None</option>
              {#each agents as agent (agent.id)}
                <option value={agent.id}>{agent.name} ({agent.id})</option>
              {/each}
            </select>
          </div>

          <div class="setting-row stacked-row">
            <div class="setting-copy">
              <div class="setting-label">Default Review Agent</div>
              <div class="setting-hint">Used when creating review worktrees for returned tasks.</div>
            </div>
            <select
              class="interval-select full-width-select"
              value={reviewAgentId ?? ''}
              on:change={(event) => handleAgentPolicyChange('review', event)}
              disabled={busy}
            >
              <option value="">None</option>
              {#each agents as agent (agent.id)}
                <option value={agent.id}>{agent.name} ({agent.id})</option>
              {/each}
            </select>
          </div>
        {/if}
      </div>

      <div class="settings-divider"></div>

      <div class="settings-section">
        <div class="section-heading">Notifications &amp; Refresh</div>

        <label class="setting-row toggle-row">
          <div class="setting-copy">
            <div class="setting-label">Desktop notifications</div>
            <div class="setting-hint">Show alerts when tasks are returned for review.</div>
          </div>
          <input
            class="toggle"
            type="checkbox"
            checked={settings.notifications_enabled}
            on:change={handleNotificationsToggle}
            disabled={busy}
          />
        </label>

        <div class="setting-row">
          <div class="setting-copy">
            <div class="setting-label">Refresh interval</div>
            <div class="setting-hint">How often to poll for file changes (watcher debounce).</div>
          </div>
          <select
            class="interval-select"
            value={settings.refresh_interval_secs}
            on:change={handleRefreshInterval}
            disabled={busy}
          >
            <option value={1}>1s</option>
            <option value={2}>2s</option>
            <option value={3}>3s</option>
            <option value={5}>5s</option>
            <option value={10}>10s</option>
          </select>
        </div>
      </div>

      <div class="settings-divider"></div>

      {#if SHOW_DEV_UTILITIES}
        <div class="settings-section">
          <div class="section-heading">Development &amp; Demo</div>

          <div class="setting-row">
            <div class="setting-copy">
              <div class="setting-label">Generate returned review task</div>
              <div class="setting-hint">
                Creates a returned task in the current workspace so review flows can be demonstrated
                and verified without hand-editing files.
              </div>
            </div>
            <button
              class="action-button"
              type="button"
              on:click={handleSeedReviewDemo}
              disabled={busy || devBusy || !currentDir}
            >
              {devBusy ? 'Generating…' : 'Generate'}
            </button>
          </div>

          {#if devMessage}
            <div class="dev-success">{devMessage}</div>
          {/if}
        </div>

        <div class="settings-divider"></div>
      {/if}

      <div class="settings-section about-section">
        <div class="section-heading">About</div>
        <div class="about-row">
          <span class="about-label">owlscale</span>
          <span class="about-version">v{APP_VERSION}</span>
        </div>
        <div class="about-desc">Multi-agent AI coordination dashboard</div>
        <div class="about-copy">© 2026 owlscale contributors</div>
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
    position: fixed;
    inset: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.4);
  }

  .backdrop-dismiss {
    position: absolute;
    inset: 0;
    border-radius: 0;
  }

  .settings-panel {
    position: relative;
    z-index: 1;
    width: 360px;
    max-height: 80vh;
    overflow-y: auto;
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

  .settings-divider {
    height: 1px;
    background: var(--border-color);
    margin: 0;
  }

  .section-heading {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .stacked-row {
    align-items: stretch;
    flex-direction: column;
  }

  .setting-copy {
    flex: 1 1 auto;
    min-width: 0;
  }

  .setting-label {
    color: var(--text-primary);
    font-size: 12px;
    font-weight: 500;
    margin-bottom: 2px;
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

  .interval-select {
    flex: 0 0 auto;
    height: 26px;
    padding: 0 6px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 11px;
    -webkit-appearance: none;
    appearance: none;
  }

  .interval-select:focus {
    outline: none;
    border-color: var(--accent-purple);
  }

  .full-width-select {
    width: 100%;
  }

  .about-section {
    gap: 4px;
  }

  .about-section .section-heading {
    margin-bottom: 4px;
  }

  .about-row {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  .about-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--accent-purple);
  }

  .about-version {
    font-size: 11px;
    color: var(--text-secondary);
    font-family: ui-monospace, "SF Mono", monospace;
  }

  .about-desc {
    font-size: 11px;
    color: var(--text-secondary);
  }

  .about-copy {
    font-size: 10px;
    color: var(--text-secondary);
    opacity: 0.5;
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

  .dev-success {
    padding: 10px 12px 0;
    color: var(--accent-green);
    font-size: 11px;
  }
</style>
