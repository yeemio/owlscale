<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { slide } from 'svelte/transition'
  import type { TaskInfo } from '../types'

  export let task: TaskInfo

  let accepting = false
  let rejecting = false
  let flashAccept = false
  let expanded = false

  const badgeConfig: Record<
    TaskInfo['status'],
    { label: string; background: string; color: string }
  > = {
    returned: { label: 'REVIEW', background: 'var(--accent-orange)', color: 'var(--bg-primary)' },
    dispatched: { label: 'WORKING', background: '#636366', color: 'var(--text-primary)' },
    in_progress: { label: 'IN PROG', background: 'var(--accent-blue)', color: 'var(--text-primary)' },
    accepted: { label: 'DONE', background: 'var(--accent-green)', color: 'var(--bg-primary)' },
    rejected: { label: 'REJECTED', background: 'var(--accent-red)', color: 'var(--text-primary)' },
    draft: { label: 'DRAFT', background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' },
  }

  $: badge = badgeConfig[task.status]

  function handleCardClick(e: MouseEvent) {
    if ((e.target as Element).closest('.task-actions')) return
    expanded = !expanded
  }

  const handleAccept = async () => {
    accepting = true
    try {
      await invoke('accept_task', { taskId: task.id })
      flashAccept = true
      setTimeout(() => { flashAccept = false }, 400)
    } catch (e) {
      console.error('accept_task failed:', e)
    } finally {
      accepting = false
    }
  }

  const handleReject = async () => {
    rejecting = true
    try {
      await invoke('reject_task', { taskId: task.id, reason: null })
    } catch (e) {
      console.error('reject_task failed:', e)
    } finally {
      rejecting = false
    }
  }
</script>

<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<!-- svelte-ignore a11y-click-events-have-key-events -->
<article
  class="task-card slide-in"
  class:flash-accept={flashAccept}
  title={task.goal ?? task.id}
  on:click={handleCardClick}
>
  <div class="expand-caret" class:open={expanded} aria-hidden="true">›</div>
  <div class="task-row">
    <span
      class="status-badge"
      style:background-color={badge.background}
      style:color={badge.color}
    >
      {badge.label}
    </span>
    <span class="assignee">{task.assignee ?? 'unassigned'}</span>
  </div>

  {#if task.goal}
    <div class="task-goal">{task.goal}</div>
    <div class="task-id-secondary">{task.id}</div>
  {:else}
    <div class="task-id">{task.id}</div>
  {/if}

  {#if task.status === 'returned'}
    <div class="task-actions">
      <button
        class="action-button accept-button"
        class:in-flight={accepting}
        on:click={handleAccept}
        disabled={accepting || rejecting}
      >
        {accepting ? '✓' : 'Accept'}
      </button>
      <button
        class="action-button reject-button"
        class:in-flight={rejecting}
        on:click={handleReject}
        disabled={accepting || rejecting}
      >
        {rejecting ? '…' : 'Reject'}
      </button>
    </div>
  {/if}

  {#if expanded}
    <div class="expand-detail" transition:slide={{ duration: 200 }}>
      <div class="full-goal">{task.goal ?? task.id}</div>
      <div class="meta-row">
        <span class="assignee-chip">{task.assignee ?? 'unassigned'}</span>
        <span class="task-id-full">{task.id}</span>
      </div>
    </div>
  {/if}
</article>

<style>
  .task-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-height: 52px;
    padding: 8px 12px;
    transition: background-color 0.3s ease;
    position: relative;
    cursor: pointer;
  }

  .task-card:hover {
    background: var(--bg-secondary);
  }

  .task-card.flash-accept {
    background: rgba(48, 209, 88, 0.15);
  }

  .task-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    min-height: 18px;
    padding: 0 8px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.25px;
    transition: background-color 0.25s ease, color 0.25s ease;
  }

  .assignee {
    flex: 0 1 auto;
    min-width: 0;
    font-size: 11px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .task-goal {
    color: var(--text-primary);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .task-id-secondary {
    color: var(--text-secondary);
    font-size: 10px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .task-id {
    color: var(--text-primary);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .task-actions {
    display: flex;
    gap: 8px;
  }

  .action-button {
    min-width: 64px;
    height: 24px;
    padding: 0 10px;
    border-radius: 6px;
    font-size: 11px;
    transition: filter 120ms ease, background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
  }

  .accept-button {
    background: var(--accent-green);
    color: var(--bg-primary);
  }

  .accept-button:hover {
    filter: brightness(0.9);
  }

  .accept-button.in-flight {
    box-shadow: 0 0 8px #30d158;
  }

  .reject-button.in-flight {
    border-color: #ff453a;
    box-shadow: 0 0 6px rgba(255, 69, 58, 0.5);
  }

  .reject-button {
    border: 1px solid var(--accent-red);
    color: var(--accent-red);
    background: transparent;
  }

  .reject-button:hover {
    background: rgba(255, 69, 58, 0.12);
    border-color: #e53e34;
    color: #ff6a61;
  }

  .expand-caret {
    position: absolute;
    top: 8px;
    right: 8px;
    font-size: 12px;
    color: var(--text-secondary);
    transition: transform 200ms ease;
    pointer-events: none;
  }

  .expand-caret.open { transform: rotate(90deg); }

  .expand-detail {
    padding-top: 6px;
    border-top: 1px solid var(--border-color);
    margin-top: 4px;
  }

  .full-goal {
    font-size: 12px;
    color: var(--text-primary);
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 160px;
    overflow-y: auto;
  }

  .meta-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
  }

  .assignee-chip {
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
  }

  .task-id-full {
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 10px;
    color: #636366;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
