<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { onMount } from 'svelte'
  import type { TaskEvent } from '../types'

  let events: TaskEvent[] = []
  let loading = false
  let error: string | null = null

  async function loadEvents() {
    loading = true
    error = null
    try {
      const raw = await invoke<TaskEvent[]>('get_task_timeline', { taskId: null })
      // Most recent first
      events = [...raw].reverse()
    } catch (e) {
      error = typeof e === 'string' ? e : 'Failed to load activity'
    } finally {
      loading = false
    }
  }

  onMount(loadEvents)

  function formatDate(ts: string): string {
    try {
      const d = new Date(ts)
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
    } catch { return '' }
  }

  function formatTime(ts: string): string {
    try {
      const d = new Date(ts)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch { return ts }
  }

  const actionColor: Record<string, string> = {
    PACK:     'var(--accent-purple)',
    DISPATCH: 'var(--accent-blue)',
    RETURN:   'var(--accent-orange)',
    ACCEPT:   'var(--accent-green)',
    REJECT:   'var(--accent-red)',
    RECONCILE:'var(--text-secondary)',
  }

  function colorForAction(action: string): string {
    const key = action.split(' ')[0].toUpperCase()
    return actionColor[key] ?? 'var(--text-secondary)'
  }
</script>

<div class="panel-root">
  <header class="panel-header">
    <div class="panel-title-row">
      <span class="panel-label">ACTIVITY</span>
      {#if events.length > 0}
        <span class="panel-count">{events.length}</span>
      {/if}
    </div>
    <button class="refresh-btn" on:click={loadEvents} disabled={loading} title="Reload activity">
      {loading ? '…' : '↻'}
    </button>
  </header>

  <div class="event-list">
    {#if loading && events.length === 0}
      <div class="loading-hint">Loading…</div>
    {:else if error}
      <div class="error-hint">{error}</div>
    {:else if events.length === 0}
      <div class="empty-state">
        <div class="empty-icon" aria-hidden="true">◉</div>
        <div class="empty-text">No activity yet</div>
        <div class="empty-hint">Events appear here as tasks move through the pipeline</div>
      </div>
    {:else}
      {#each events as event (event.timestamp + event.action + event.task_id)}
        <div class="event-row">
          <div class="event-time-col">
            <span class="event-date">{formatDate(event.timestamp)}</span>
            <span class="event-time">{formatTime(event.timestamp)}</span>
          </div>
          <div class="event-body">
            <span
              class="event-action"
              style:color={colorForAction(event.action)}
            >{event.action}</span>
            {#if event.task_id}
              <span class="event-task-id">{event.task_id}</span>
            {/if}
            {#if event.detail}
              <span class="event-detail">{event.detail}</span>
            {/if}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .panel-root {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .panel-header {
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .panel-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .panel-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: var(--text-secondary);
  }

  .panel-count {
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--bg-tertiary);
    padding: 1px 7px;
    border-radius: 999px;
  }

  .refresh-btn {
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

  .refresh-btn:hover:not(:disabled) {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  .refresh-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .event-list {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }

  .loading-hint,
  .error-hint {
    padding: 16px 20px;
    font-size: 12px;
    color: var(--text-secondary);
  }

  .error-hint {
    color: var(--accent-red);
  }

  .event-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 7px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    transition: background-color 120ms ease;
  }

  .event-row:hover {
    background: var(--bg-secondary);
  }

  .event-time-col {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    min-width: 72px;
    flex-shrink: 0;
    padding-top: 1px;
  }

  .event-date {
    font-size: 10px;
    color: var(--text-secondary);
    opacity: 0.6;
  }

  .event-time {
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 10px;
    color: var(--text-secondary);
  }

  .event-body {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    padding-top: 1px;
  }

  .event-action {
    font-size: 11px;
    font-weight: 600;
  }

  .event-task-id {
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 10px;
    color: var(--text-secondary);
    background: var(--bg-tertiary);
    padding: 1px 5px;
    border-radius: 3px;
  }

  .event-detail {
    font-size: 11px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 220px;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 200px;
    gap: 6px;
    color: var(--text-secondary);
  }

  .empty-icon {
    font-size: 32px;
    opacity: 0.25;
  }

  .empty-text {
    font-size: 13px;
    font-weight: 500;
  }

  .empty-hint {
    font-size: 11px;
    opacity: 0.6;
    text-align: center;
    max-width: 200px;
  }
</style>
