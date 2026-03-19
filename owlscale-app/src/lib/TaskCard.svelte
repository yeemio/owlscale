<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { slide } from 'svelte/transition'
  import type { TaskInfo } from '../types'

  export let task: TaskInfo

  let accepting = false
  let rejecting = false
  let dispatching = false
  let starting = false
  let returning = false
  let flashAccept = false
  let expanded = false
  let returnPacket = ''
  let returnError = ''
  let loadingReturn = false
  let returnSummary = ''
  let returnFilesChanged = ''
  let returnSubmitError = ''

  const badgeConfig: Record<
    TaskInfo['status'],
    { label: string; background: string; color: string }
  > = {
    returned: { label: 'REVIEW', background: 'var(--accent-orange)', color: 'var(--bg-primary)' },
    draft: { label: 'DRAFT', background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' },
    dispatched: { label: 'QUEUED', background: '#636366', color: 'var(--text-primary)' },
    in_progress: { label: 'IN PROG', background: 'var(--accent-blue)', color: 'var(--text-primary)' },
    accepted: { label: 'DONE', background: 'var(--accent-green)', color: 'var(--bg-primary)' },
    rejected: { label: 'REJECTED', background: 'var(--accent-red)', color: 'var(--text-primary)' },
  }

  $: badge = badgeConfig[task.status]
  $: if (task.status === 'in_progress' && !returnSummary) {
    returnSummary = task.goal ?? `Completed ${task.id}`
  }

  async function loadReturnPacket() {
    if (task.status !== 'returned' || returnPacket || loadingReturn) return
    loadingReturn = true
    returnError = ''
    try {
      returnPacket = await invoke<string>('get_return_packet', { taskId: task.id })
    } catch (e) {
      returnError = e instanceof Error ? e.message : String(e)
      console.error('get_return_packet failed:', e)
    } finally {
      loadingReturn = false
    }
  }

  function handleCardClick(e: MouseEvent) {
    if ((e.target as Element).closest('.task-actions')) return
    expanded = !expanded
    if (expanded) {
      loadReturnPacket().catch(console.error)
    }
  }

  const handleDispatch = async () => {
    dispatching = true
    try {
      await invoke('dispatch_task', { taskId: task.id, assignee: task.assignee })
    } catch (e) {
      console.error('dispatch_task failed:', e)
    } finally {
      dispatching = false
    }
  }

  const handleStart = async () => {
    starting = true
    try {
      await invoke('start_task', { taskId: task.id })
    } catch (e) {
      console.error('start_task failed:', e)
    } finally {
      starting = false
    }
  }

  const handleReturn = async () => {
    returnSubmitError = ''
    const filesChanged = returnFilesChanged
      .split(/[\n,]/)
      .map(value => value.trim())
      .filter(Boolean)
    if (!returnSummary.trim()) {
      returnSubmitError = 'Summary is required.'
      return
    }
    if (filesChanged.length === 0) {
      returnSubmitError = 'At least one changed file is required.'
      return
    }

    returning = true
    try {
      await invoke('return_task', {
        taskId: task.id,
        summary: returnSummary.trim(),
        filesChanged,
      })
      returnSubmitError = ''
    } catch (e) {
      returnSubmitError = e instanceof Error ? e.message : String(e)
      console.error('return_task failed:', e)
    } finally {
      returning = false
    }
  }

  const handleAccept = async () => {
    accepting = true
    try {
      await invoke('accept_task', { taskId: task.id })
      flashAccept = true
      setTimeout(() => {
        flashAccept = false
      }, 400)
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

  {#if task.status === 'draft'}
    <div class="task-actions">
      <button
        class="action-button dispatch-button"
        class:in-flight={dispatching}
        on:click|stopPropagation={handleDispatch}
        disabled={dispatching || !task.assignee}
      >
        {dispatching ? '…' : 'Dispatch'}
      </button>
    </div>
  {:else if task.status === 'dispatched'}
    <div class="task-actions">
      <button
        class="action-button start-button"
        class:in-flight={starting}
        on:click|stopPropagation={handleStart}
        disabled={starting}
      >
        {starting ? '…' : 'Start'}
      </button>
    </div>
  {:else if task.status === 'in_progress'}
    <div class="task-actions">
      <button
        class="action-button return-button"
        class:in-flight={returning}
        on:click|stopPropagation={() => {
          expanded = true
        }}
        disabled={returning}
      >
        Return…
      </button>
    </div>
  {:else if task.status === 'returned'}
    <div class="task-actions">
      <button
        class="action-button accept-button"
        class:in-flight={accepting}
        on:click|stopPropagation={handleAccept}
        disabled={accepting || rejecting}
      >
        {accepting ? '✓' : 'Accept'}
      </button>
      <button
        class="action-button reject-button"
        class:in-flight={rejecting}
        on:click|stopPropagation={handleReject}
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
      {#if task.status === 'returned'}
        <div class="detail-section">
          <div class="detail-label">Return Packet</div>
          {#if loadingReturn}
            <div class="detail-note">Loading return packet…</div>
          {:else if returnError}
            <div class="detail-error">{returnError}</div>
          {:else if returnPacket}
            <pre class="packet-preview">{returnPacket}</pre>
          {:else}
            <div class="detail-note">No return packet found.</div>
          {/if}
        </div>
      {:else if task.status === 'in_progress'}
        <div class="detail-section">
          <div class="detail-label">Return Summary</div>
          <input
            class="detail-input"
            bind:value={returnSummary}
            placeholder="What was completed?"
            on:click|stopPropagation
          />
          <div class="detail-label">Files Changed</div>
          <textarea
            class="detail-textarea"
            bind:value={returnFilesChanged}
            placeholder="src/lib.rs, README.md"
            rows="3"
            on:click|stopPropagation
          ></textarea>
          {#if returnSubmitError}
            <div class="detail-error">{returnSubmitError}</div>
          {/if}
          <button
            class="action-button return-submit-button"
            class:in-flight={returning}
            on:click|stopPropagation={handleReturn}
            disabled={returning}
          >
            {returning ? '…' : 'Mark Returned'}
          </button>
        </div>
      {/if}
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

  .task-goal,
  .task-id,
  .full-goal {
    color: var(--text-primary);
    font-size: 12px;
  }

  .task-goal,
  .task-id,
  .task-id-secondary {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .task-id-secondary {
    color: var(--text-secondary);
    font-size: 10px;
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

  .dispatch-button {
    background: var(--accent-purple);
    color: var(--text-primary);
  }

  .start-button {
    background: var(--accent-blue);
    color: var(--text-primary);
  }

  .return-button,
  .return-submit-button {
    background: var(--accent-orange);
    color: var(--bg-primary);
  }

  .dispatch-button:hover {
    filter: brightness(0.92);
  }

  .dispatch-button.in-flight {
    box-shadow: 0 0 8px rgba(124, 58, 237, 0.45);
  }

  .start-button:hover,
  .return-button:hover,
  .return-submit-button:hover {
    filter: brightness(0.92);
  }

  .start-button.in-flight {
    box-shadow: 0 0 8px rgba(10, 132, 255, 0.45);
  }

  .return-button.in-flight,
  .return-submit-button.in-flight {
    box-shadow: 0 0 8px rgba(255, 159, 10, 0.45);
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

  .expand-caret.open {
    transform: rotate(90deg);
  }

  .expand-detail {
    padding-top: 6px;
    border-top: 1px solid var(--border-color);
    margin-top: 4px;
  }

  .full-goal {
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
    font-family: ui-monospace, 'SF Mono', monospace;
    font-size: 10px;
    color: #636366;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .detail-section {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .detail-label {
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
  }

  .detail-note {
    color: var(--text-secondary);
    font-size: 11px;
  }

  .detail-error {
    color: var(--accent-red);
    font-size: 11px;
    white-space: pre-wrap;
  }

  .detail-input,
  .detail-textarea {
    width: 100%;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 11px;
    padding: 8px 10px;
  }

  .detail-textarea {
    resize: vertical;
    min-height: 72px;
  }

  .packet-preview {
    max-height: 180px;
    overflow: auto;
    margin: 0;
    padding: 8px;
    border-radius: 8px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 11px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: ui-monospace, 'SF Mono', monospace;
  }
</style>
