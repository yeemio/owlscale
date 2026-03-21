<script lang="ts">
  import type { TaskInfo } from '../types'

  export let task: TaskInfo
  export let selected: boolean = false
  export let worktreeOwnerOverride: boolean = false
  export let reviewWorktreeReady: boolean = false
  export let codingWorktreeMissing: boolean = false
  export let showWorktreeSignals: boolean = false

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
  $: hasAttention = task.needs_attention.length > 0
</script>

<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<!-- svelte-ignore a11y-click-events-have-key-events -->
<article
  class="task-card slide-in"
  class:selected
  class:dimmed={task.status === 'accepted' || task.status === 'rejected'}
  on:click
>
  <!-- Row 1: status badge + assignee + override tag -->
  <div class="task-row">
    <span
      class="status-badge"
      style:background-color={badge.background}
      style:color={badge.color}
    >
      {badge.label}
    </span>
    <span class="assignee">{task.assignee ?? 'unassigned'}</span>
    {#if worktreeOwnerOverride}
      <span class="override-tag">OVERRIDE</span>
    {/if}
    {#if hasAttention}
      <span class="attention-tag">ATTN</span>
    {/if}
  </div>

  <!-- Row 2: goal summary -->
  <div class="task-goal">{task.goal ?? task.id}</div>

  <!-- Row 3: worktree signals (only in Review Focus for returned tasks) -->
  {#if showWorktreeSignals && task.status === 'returned'}
    <div class="wt-signals">
      <span class="wt-signal" class:signal-ok={reviewWorktreeReady} class:signal-warn={!reviewWorktreeReady}>
        {reviewWorktreeReady ? 'Review WT ✓' : 'Review WT needed'}
      </span>
      {#if codingWorktreeMissing}
        <span class="wt-signal signal-danger">Coding WT missing</span>
      {/if}
      {#if task.review_stale}
        <span class="wt-signal signal-danger">Base changed</span>
      {/if}
      {#if hasAttention}
        {#each task.needs_attention as issue (issue)}
          {#if issue !== 'needs_attention:review_stale'}
            <span class="wt-signal signal-danger">{issue.replace('needs_attention:', '')}</span>
          {/if}
        {/each}
      {/if}
    </div>
  {/if}
</article>

<style>
  .task-card {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 16px;
    cursor: pointer;
    transition: background-color 120ms ease;
    border-left: 2px solid transparent;
  }

  .task-card:hover {
    background: var(--bg-secondary);
  }

  .task-card.selected {
    background: var(--bg-secondary);
    border-left-color: var(--accent-purple);
  }

  .task-card.dimmed {
    opacity: 0.5;
  }

  .task-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: nowrap;
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    min-height: 16px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.25px;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .assignee {
    flex: 0 1 auto;
    min-width: 0;
    font-size: 10px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .override-tag {
    display: inline-flex;
    align-items: center;
    height: 14px;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.3px;
    white-space: nowrap;
    flex-shrink: 0;
    background: rgba(255, 159, 10, 0.18);
    color: var(--accent-orange);
    border: 1px solid rgba(255, 159, 10, 0.35);
  }

  .attention-tag {
    display: inline-flex;
    align-items: center;
    height: 14px;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.3px;
    white-space: nowrap;
    flex-shrink: 0;
    background: rgba(255, 69, 58, 0.18);
    color: var(--accent-red);
    border: 1px solid rgba(255, 69, 58, 0.35);
  }

  .task-goal {
    color: var(--text-primary);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* S4: worktree signals row */
  .wt-signals {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 2px;
  }

  .wt-signal {
    font-size: 9px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 3px;
    letter-spacing: 0.1px;
  }

  .signal-ok {
    background: rgba(48, 209, 88, 0.14);
    color: var(--accent-green);
  }

  .signal-warn {
    background: rgba(255, 159, 10, 0.14);
    color: var(--accent-orange);
  }

  .signal-danger {
    background: rgba(255, 69, 58, 0.14);
    color: var(--accent-red);
  }
</style>
