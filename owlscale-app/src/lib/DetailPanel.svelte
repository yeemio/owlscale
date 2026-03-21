<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import type { TaskInfo, TaskEvent, WorktreeInfo, AgentInfo, AgentPolicy } from '../types'

  export let task: TaskInfo | null
  export let worktrees: WorktreeInfo[] = []
  export let agents: AgentInfo[] = []
  export let agentPolicy: AgentPolicy | null = null

  let packetContent: string | null = null
  let returnContent: string | null = null
  let diffContent: string | null = null
  let diffExpanded = false
  let diffLoading = false
  let timeline: TaskEvent[] = []
  let accepting = false
  let rejecting = false
  let rejectDraft = false
  let rejectReason = ''
  let creatingReview = false
  let rebasingReview = false
  let attentionActionError: string | null = null
  let repairingWorktree = false

  const ATTENTION_META: Record<string, { msg: string; icon: string }> = {
    worktree_missing:       { icon: '⬡', msg: 'Coding worktree path is missing' },
    return_state_mismatch:  { icon: '⟳', msg: 'State sync mismatch — worktree still marked working' },
    ownership_drift:        { icon: '⚑', msg: 'Agent assignment drift detected' },
    stalled:                { icon: '⏱', msg: 'No activity for >30 min — may be stuck' },
    review_stale:           { icon: '⚠', msg: 'Base changed after review started' },
  }

  // D1: dispatch editor state
  let dispatchAssignee: string | null = null
  let dispatchWorktreeMode: 'create' | 'bind' = 'create'
  let dispatchBindWorktreeId: string | null = null
  let dispatching = false
  let dispatchError: string | null = null

  const badgeConfig: Record<string, { label: string; bg: string; fg: string }> = {
    returned: { label: '↩ REVIEW', bg: 'var(--accent-orange)', fg: 'var(--bg-primary)' },
    dispatched: { label: '⟳ WORKING', bg: '#636366', fg: 'var(--text-primary)' },
    in_progress: { label: '▶ IN PROG', bg: 'var(--accent-blue)', fg: 'var(--text-primary)' },
    accepted: { label: '✓ DONE', bg: 'var(--accent-green)', fg: 'var(--bg-primary)' },
    rejected: { label: '✗ REJECTED', bg: 'var(--accent-red)', fg: 'var(--text-primary)' },
    draft: { label: '○ DRAFT', bg: 'var(--bg-tertiary)', fg: 'var(--text-secondary)' },
  }

  $: badge = task ? (badgeConfig[task.status] ?? badgeConfig.draft) : badgeConfig.draft
  $: codingWorktree = task?.worktree_id
    ? worktrees.find(w => w.id === task!.worktree_id) ?? null
    : null
  $: reviewWorktree = task
    ? worktrees.find(w => w.id === `review-${task!.id}`) ?? null
    : null
  $: codingWorktrees = worktrees.filter(w => w.type === 'coding')
  $: attentionItems = task?.needs_attention ?? []

  // D1: derive override (assignee differs from workspace default agent)
  $: dispatchIsOverride = dispatchAssignee !== null &&
    agentPolicy?.default_execution_agent_id !== null &&
    agentPolicy?.default_execution_agent_id !== undefined &&
    dispatchAssignee !== agentPolicy.default_execution_agent_id

  let currentTaskId: string | null = null
  $: if (task?.id !== currentTaskId) {
    currentTaskId = task?.id ?? null
    // Reset dispatch editor on task switch
    dispatchAssignee = agentPolicy?.default_execution_agent_id ?? null
    dispatchWorktreeMode = task?.worktree_id ? 'bind' : 'create'
    dispatchBindWorktreeId = task?.worktree_id ?? null
    dispatchError = null
    rejectDraft = false
    rejectReason = ''

    if (currentTaskId) loadTaskDetails(currentTaskId)
    else { packetContent = null; returnContent = null; diffContent = null; diffExpanded = false; timeline = [] }
  }

  async function loadTaskDetails(taskId: string) {
    packetContent = null
    returnContent = null
    diffContent = null
    diffExpanded = false
    timeline = []

    try { packetContent = await invoke('get_task_packet', { taskId }) }
    catch { packetContent = null }

    try { returnContent = await invoke('get_return_packet', { taskId }) }
    catch { returnContent = null }

    try { timeline = await invoke('get_task_timeline', { taskId }) }
    catch { timeline = [] }

    diffLoading = true
    try { diffContent = await invoke('get_task_diff', { taskId }) }
    catch { diffContent = null }
    finally { diffLoading = false }
  }

  function computeDiffStats(diff: string): { added: number; removed: number; files: number } {
    let added = 0, removed = 0, files = 0
    for (const line of diff.split('\n')) {
      if (line.startsWith('+') && !line.startsWith('+++')) added++
      else if (line.startsWith('-') && !line.startsWith('---')) removed++
      else if (line.startsWith('diff ')) files++
    }
    return { added, removed, files }
  }

  function getDiffLineClass(line: string): string {
    if (line.startsWith('+') && !line.startsWith('+++')) return 'diff-add'
    if (line.startsWith('-') && !line.startsWith('---')) return 'diff-del'
    if (line.startsWith('@@')) return 'diff-hunk'
    if (line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('--- ') || line.startsWith('+++ ')) return 'diff-meta'
    return ''
  }

  $: diffStats = diffContent ? computeDiffStats(diffContent) : null
  $: diffLines = diffContent ? diffContent.split('\n') : []

  function formatTime(ts: string): string {
    try {
      const d = new Date(ts)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch { return ts }
  }

  function formatDate(ts: string): string {
    try {
      const d = new Date(ts)
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
    } catch { return '' }
  }

  const handleAccept = async () => {
    if (!task) return
    accepting = true
    try { await invoke('accept_task', { taskId: task.id }) }
    catch (e) { console.error('accept failed:', e) }
    finally { accepting = false }
  }

  const handleReject = async () => {
    if (!task) return
    rejecting = true
    try {
      await invoke('reject_task', {
        taskId: task.id,
        reason: rejectReason.trim() || null,
      })
      rejectDraft = false
      rejectReason = ''
    }
    catch (e) { console.error('reject failed:', e) }
    finally { rejecting = false }
  }

  function beginReject() {
    rejectDraft = true
  }

  function cancelReject() {
    rejectDraft = false
    rejectReason = ''
  }

  const handleOpenWorktree = async (worktreeId: string) => {
    try { await invoke('open_worktree', { worktreeId }) }
    catch (e) { console.error('open_worktree failed:', e) }
  }

  const handleCreateReviewWorktree = async () => {
    if (!task) return
    creatingReview = true
    try { await invoke('create_review_worktree', { taskId: task.id }) }
    catch (e) { console.error('create_review_worktree failed:', e) }
    finally { creatingReview = false }
  }

  const handleDispatch = async () => {
    if (!task || !dispatchAssignee) return
    dispatching = true
    dispatchError = null
    try {
      await invoke('dispatch_task', {
        taskId: task.id,
        agentId: dispatchAssignee,
        worktreeMode: dispatchWorktreeMode,
        worktreeId: dispatchWorktreeMode === 'bind' ? dispatchBindWorktreeId : null,
      })
    } catch (e) {
      dispatchError = typeof e === 'string' ? e : 'Dispatch failed'
      console.error('dispatch failed:', e)
    } finally {
      dispatching = false
    }
  }

  const handleManualRefresh = async () => {
    attentionActionError = null
    try { await invoke('manual_refresh') }
    catch (e) {
      attentionActionError = typeof e === 'string' ? e : 'Refresh failed'
      console.error('manual_refresh failed:', e)
    }
  }

  const handleRebaseReview = async () => {
    if (!task) return
    rebasingReview = true
    attentionActionError = null
    try { await invoke('rebase_review_worktree', { taskId: task.id }) }
    catch (e) {
      attentionActionError = typeof e === 'string' ? e : 'Rebase failed'
      console.error('rebase_review_worktree failed:', e)
    }
    finally { rebasingReview = false }
  }

  const handleRepairWorktree = async () => {
    if (!task) return
    repairingWorktree = true
    attentionActionError = null
    try { await invoke('repair_coding_worktree', { taskId: task.id }) }
    catch (e) {
      attentionActionError = typeof e === 'string' ? e : 'Repair failed'
      console.error('repair_coding_worktree failed:', e)
    }
    finally { repairingWorktree = false }
  }

  // Derive unique attention codes (strip 'needs_attention:' prefix)
  $: attentionCodes = [
    ...new Set([
      ...attentionItems.map(i => i.replace('needs_attention:', '')),
      ...(task?.review_stale ? ['review_stale'] : []),
    ])
  ]
</script>

{#if !task}
  <div class="empty-detail">
    <div class="empty-icon" aria-hidden="true">⬡</div>
    <div class="empty-text">Select a task to inspect</div>
    <div class="empty-hint">Click any task in the focus panel</div>
  </div>
{:else}
  <div class="inspector">
    <!-- Inspector header -->
    <header class="inspector-header">
      <span class="detail-badge" style:background={badge.bg} style:color={badge.fg}>{badge.label}</span>
      <h2 class="detail-title">{task.id}</h2>
    </header>

    <!-- Sticky action zone — S2 status-aware -->
    {#if task.status === 'returned'}
      <div class="action-zone">
        <!-- Primary: Accept full-width -->
        <button
          class="action-primary action-accept"
          on:click={handleAccept}
          disabled={accepting || rejecting}
        >
          {accepting ? '✓ Accepting…' : task.review_stale ? '✓ Ignore and Accept' : '✓ Accept Task'}
        </button>

        <!-- Secondary: Open worktrees side-by-side -->
        <div class="action-row-secondary">
          {#if reviewWorktree}
            {@const rwId = reviewWorktree.id}
            <button class="action-secondary" on:click={() => handleOpenWorktree(rwId)}>
              Open Review Worktree
            </button>
          {:else}
            <button class="action-secondary" on:click={handleCreateReviewWorktree} disabled={creatingReview}>
              {creatingReview ? 'Creating…' : 'Create Review Worktree'}
            </button>
          {/if}
          {#if codingWorktree}
            {@const cwId = codingWorktree.id}
            <button class="action-secondary" on:click={() => handleOpenWorktree(cwId)}>
              Open Coding Worktree
            </button>
          {/if}
        </div>

        <!-- Danger zone: Reject separated -->
        <div class="action-danger-row">
          {#if rejectDraft}
            <div class="reject-composer">
              <label class="editor-label" for="reject-reason">Reject reason</label>
              <textarea
                id="reject-reason"
                class="reject-textarea"
                bind:value={rejectReason}
                placeholder="Optional. Explain why this task is being rejected."
                rows="3"
              />
              <div class="reject-actions">
                <button class="action-secondary" on:click={cancelReject} disabled={rejecting}>
                  Cancel
                </button>
                <button
                  class="action-danger"
                  on:click={handleReject}
                  disabled={accepting || rejecting}
                >
                  {rejecting ? '… Rejecting' : 'Confirm Reject'}
                </button>
              </div>
            </div>
          {:else}
            <button
              class="action-danger"
              on:click={beginReject}
              disabled={accepting || rejecting}
            >
              ✗ Reject Task
            </button>
          {/if}
        </div>
      </div>

    {:else if task.status === 'draft'}
      <!-- D1: Inline dispatch editor -->
      <div class="action-zone dispatch-editor">

        <!-- 1. Assignee selector -->
        <div class="editor-field">
          <label class="editor-label" for="dispatch-assignee">Assignee</label>
          <div class="select-wrap">
            <select
              id="dispatch-assignee"
              class="editor-select"
              bind:value={dispatchAssignee}
            >
              <option value={null}>— choose agent —</option>
              {#each agents as agent (agent.id)}
                <option value={agent.id}>{agent.name} ({agent.id})</option>
              {/each}
            </select>
          </div>
          {#if dispatchIsOverride}
            <span class="override-tag-inline">OVERRIDE</span>
          {/if}
        </div>

        <!-- 2. Worktree mode -->
        <div class="editor-field">
          <div class="editor-label">Worktree</div>
          <div class="mode-toggle">
            <button
              class="mode-btn"
              class:active={dispatchWorktreeMode === 'create'}
              on:click={() => { dispatchWorktreeMode = 'create'; dispatchBindWorktreeId = null }}
            >
              Create default
            </button>
            <button
              class="mode-btn"
              class:active={dispatchWorktreeMode === 'bind'}
              on:click={() => dispatchWorktreeMode = 'bind'}
            >
              Bind existing
            </button>
          </div>

          {#if dispatchWorktreeMode === 'bind'}
            <div class="select-wrap" style="margin-top: 6px;">
              <select
                class="editor-select"
                bind:value={dispatchBindWorktreeId}
              >
                <option value={null}>— select worktree —</option>
                {#each codingWorktrees as wt (wt.id)}
                  <option value={wt.id}>{wt.branch}</option>
                {/each}
              </select>
            </div>
          {/if}
        </div>

        <!-- 3. Ownership preview -->
        <div class="ownership-preview">
          <div class="op-row">
            <span class="op-label">Workspace default</span>
            <span class="op-value">{agentPolicy?.default_execution_agent_id ?? '—'}</span>
          </div>
          <div class="op-row">
            <span class="op-label">This task</span>
            <span class="op-value">{dispatchAssignee ?? '—'}</span>
            {#if dispatchIsOverride}
              <span class="override-tag-inline">OVERRIDE</span>
            {/if}
          </div>
        </div>

        {#if dispatchError}
          <div class="dispatch-error">{dispatchError}</div>
        {/if}

        <!-- 4. Primary CTA -->
        <button
          class="action-primary action-dispatch"
          on:click={handleDispatch}
          disabled={!dispatchAssignee || dispatching || (dispatchWorktreeMode === 'bind' && !dispatchBindWorktreeId)}
        >
          {dispatching ? 'Dispatching…' : 'Dispatch Task →'}
        </button>
      </div>

    {:else if task.status === 'dispatched' || task.status === 'in_progress'}
      <div class="action-zone">
        {#if codingWorktree}
          {@const cwId = codingWorktree.id}
          <button class="action-secondary" on:click={() => handleOpenWorktree(cwId)}>
            Open Coding Worktree
          </button>
        {:else}
          <div class="action-hint">No coding worktree linked</div>
        {/if}
      </div>

    {/if}
    <!-- accepted / rejected: no action zone rendered -->

    {#if attentionCodes.length > 0}
      <section class="detail-section attention-section">
        <h3 class="section-title">Needs Attention</h3>
        <div class="attention-cards">
          {#each attentionCodes as code (code)}
            {@const meta = ATTENTION_META[code] ?? { icon: '!', msg: code }}
            <div class="attention-card">
              <div class="attention-card-msg">
                <span class="attention-icon">{meta.icon}</span>
                {meta.msg}
              </div>
              <div class="attention-card-actions">
                {#if code === 'worktree_missing'}
                  <button class="action-secondary" on:click={handleRepairWorktree} disabled={repairingWorktree}>
                    {repairingWorktree ? 'Repairing…' : 'Repair Worktree'}
                  </button>
                  <button class="action-secondary" on:click={handleManualRefresh}>Refresh</button>
                {:else if code === 'review_stale'}
                  <button class="action-secondary" on:click={handleRebaseReview} disabled={rebasingReview}>
                    {rebasingReview ? 'Rebasing…' : 'Rebase & Re-review'}
                  </button>
                {:else if code === 'stalled' || code === 'ownership_drift'}
                  {#if codingWorktree}
                    {@const cwId = codingWorktree.id}
                    <button class="action-secondary" on:click={() => handleOpenWorktree(cwId)}>Open Worktree</button>
                  {/if}
                  <button class="action-secondary" on:click={handleManualRefresh}>Refresh</button>
                {:else}
                  <button class="action-secondary" on:click={handleManualRefresh}>Refresh</button>
                {/if}
              </div>
            </div>
          {/each}
        </div>
        {#if attentionActionError}
          <div class="dispatch-error">{attentionActionError}</div>
        {/if}
      </section>
    {/if}

    <!-- Assignee -->
    {#if task.assignee}
      <div class="detail-meta">
        <span class="meta-label">Assignee</span>
        <span class="meta-value">{task.assignee}</span>
      </div>
    {/if}

    <!-- Goal -->
    {#if task.goal}
      <section class="detail-section">
        <h3 class="section-title">Goal</h3>
        <p class="detail-goal">{task.goal}</p>
      </section>
    {/if}

    {#if task.rejected_reason}
      <section class="detail-section">
        <h3 class="section-title">Reject Reason</h3>
        <p class="detail-goal">{task.rejected_reason}</p>
      </section>
    {/if}

    <!-- Worktree details (contextual) -->
    {#if codingWorktree && task.status !== 'draft'}
      <section class="detail-section">
        <h3 class="section-title">Coding Worktree</h3>
        <div class="worktree-card">
          <div class="worktree-meta">
            <div class="worktree-branch">{codingWorktree.branch}</div>
            <div class="worktree-path">{codingWorktree.path}</div>
          </div>
        </div>
      </section>
    {/if}

    {#if reviewWorktree && task.status === 'returned'}
      <section class="detail-section">
        <h3 class="section-title">Review Worktree</h3>
        <div class="worktree-card">
          <div class="worktree-meta">
            <div class="worktree-branch">{reviewWorktree.branch}</div>
            <div class="worktree-path">{reviewWorktree.path}</div>
          </div>
        </div>
      </section>
    {/if}

    <!-- Changes diff (returned / accepted / rejected + has coding worktree) -->
    {#if task.worktree_id && (task.status === 'returned' || task.status === 'accepted' || task.status === 'rejected')}
      <section class="detail-section">
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div class="diff-header" on:click={() => diffExpanded = !diffExpanded}>
          <h3 class="section-title">Changes</h3>
          <div class="diff-header-right">
            {#if diffLoading}
              <span class="diff-loading">loading…</span>
            {:else if diffStats && (diffStats.added > 0 || diffStats.removed > 0 || diffStats.files > 0)}
              <span class="diff-summary">
                {#if diffStats.files > 0}
                  <span class="diff-files">{diffStats.files}f</span>
                {/if}
                {#if diffStats.added > 0}
                  <span class="diff-stat-add">+{diffStats.added}</span>
                {/if}
                {#if diffStats.removed > 0}
                  <span class="diff-stat-del">−{diffStats.removed}</span>
                {/if}
              </span>
            {:else if !diffLoading}
              <span class="diff-empty-label">—</span>
            {/if}
            <span class="diff-toggle" aria-hidden="true">{diffExpanded ? '▲' : '▼'}</span>
          </div>
        </div>
        {#if diffExpanded}
          {#if !diffContent || diffContent.trim() === ''}
            <div class="diff-no-changes">No changes on this branch yet.</div>
          {:else}
            <div class="diff-viewer">
              {#each diffLines as line, i (i)}
                <div class="diff-line {getDiffLineClass(line)}">{line || '\u200b'}</div>
              {/each}
            </div>
          {/if}
        {/if}
      </section>
    {/if}

    <!-- Timeline -->
    {#if timeline.length > 0}
      <section class="detail-section">
        <h3 class="section-title">Timeline</h3>
        <div class="timeline">
          {#each timeline as event}
            <div class="timeline-event">
              <span class="tl-date">{formatDate(event.timestamp)}</span>
              <span class="tl-time">{formatTime(event.timestamp)}</span>
              <span class="tl-action">{event.action}</span>
              {#if event.detail}
                <span class="tl-detail">{event.detail}</span>
              {/if}
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <!-- Return Packet -->
    {#if returnContent}
      <section class="detail-section">
        <h3 class="section-title">Return Packet</h3>
        <pre class="detail-pre">{returnContent}</pre>
      </section>
    {/if}

    <!-- Context Packet -->
    {#if packetContent}
      <section class="detail-section">
        <h3 class="section-title">Context Packet</h3>
        <pre class="detail-pre">{packetContent}</pre>
      </section>
    {/if}
  </div>
{/if}

<style>
  .empty-detail {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 400px;
    gap: 8px;
    color: var(--text-secondary);
  }

  .empty-icon {
    font-size: 48px;
    color: var(--accent-purple);
    opacity: 0.3;
  }

  .empty-text {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  .empty-hint {
    font-size: 11px;
    color: var(--text-secondary);
    opacity: 0.6;
    text-align: center;
    max-width: 200px;
  }

  .inspector {
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow-y: auto;
    height: 100vh;
  }

  .inspector-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
  }

  .detail-badge {
    display: inline-flex;
    align-items: center;
    height: 20px;
    padding: 0 8px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.25px;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .detail-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    word-break: break-all;
  }

  /* ── S2: Action zone ───────────────────────────────────────── */
  .action-zone {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-primary);
    flex-shrink: 0;
  }

  .action-primary {
    width: 100%;
    height: 40px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    transition: filter 120ms ease;
  }

  .action-primary:hover:not(:disabled) {
    filter: brightness(0.88);
  }

  .action-primary:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .action-accept {
    background: var(--accent-green);
    color: var(--bg-primary);
  }

  .action-dispatch {
    background: var(--accent-blue);
    color: var(--bg-primary);
  }

  .action-row-secondary {
    display: flex;
    gap: 8px;
  }

  .action-secondary {
    flex: 1;
    height: 30px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    font-size: 11px;
    font-weight: 500;
    white-space: nowrap;
    transition: background-color 120ms ease;
  }

  .action-secondary:hover:not(:disabled) {
    background: var(--bg-secondary);
  }

  .action-secondary:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .action-danger-row {
    padding-top: 4px;
    border-top: 1px solid var(--border-color);
  }

  .reject-composer {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .reject-textarea {
    width: 100%;
    min-height: 72px;
    resize: vertical;
    padding: 8px 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    font-size: 12px;
    line-height: 1.4;
  }

  .reject-textarea:focus {
    outline: none;
    border-color: var(--accent-red);
  }

  .reject-actions {
    display: flex;
    gap: 8px;
  }

  .action-danger {
    width: 100%;
    height: 30px;
    border-radius: 6px;
    background: transparent;
    border: 1px solid var(--accent-red);
    color: var(--accent-red);
    font-size: 12px;
    font-weight: 600;
    transition: background-color 120ms ease;
  }

  .action-danger:hover:not(:disabled) {
    background: rgba(255, 69, 58, 0.1);
  }

  .action-danger:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .action-hint {
    font-size: 11px;
    color: var(--text-secondary);
    padding: 4px 0;
  }

  /* ── D1: Dispatch inline editor ────────────────────────────── */
  .dispatch-editor {
    gap: 12px;
  }

  .editor-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .editor-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  .select-wrap {
    position: relative;
  }

  .editor-select {
    width: 100%;
    height: 30px;
    padding: 0 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    font-size: 12px;
    appearance: none;
    cursor: pointer;
    transition: border-color 120ms ease;
  }

  .editor-select:focus {
    outline: none;
    border-color: var(--accent-purple);
  }

  .mode-toggle {
    display: flex;
    gap: 4px;
  }

  .mode-btn {
    flex: 1;
    height: 28px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-secondary);
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    transition: all 120ms ease;
  }

  .mode-btn.active {
    background: var(--accent-blue);
    color: var(--bg-primary);
    border-color: var(--accent-blue);
    font-weight: 600;
  }

  .ownership-preview {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .op-row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
  }

  .op-label {
    color: var(--text-secondary);
    min-width: 110px;
    font-size: 10px;
  }

  .op-value {
    color: var(--text-primary);
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 11px;
  }

  .override-tag-inline {
    display: inline-flex;
    align-items: center;
    height: 14px;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.3px;
    white-space: nowrap;
    background: rgba(255, 159, 10, 0.18);
    color: var(--accent-orange);
    border: 1px solid rgba(255, 159, 10, 0.35);
  }

  .dispatch-error {
    font-size: 11px;
    color: var(--accent-red);
    padding: 4px 6px;
    background: rgba(255, 69, 58, 0.08);
    border-radius: 4px;
    border: 1px solid rgba(255, 69, 58, 0.2);
  }

  /* ── Meta / sections ───────────────────────────────────────── */
  .detail-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 20px 0;
  }

  .attention-section {
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 16px;
  }

  .attention-cards {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 8px;
  }

  .attention-card {
    background: rgba(255, 159, 10, 0.06);
    border: 1px solid rgba(255, 159, 10, 0.2);
    border-radius: 8px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .attention-card-msg {
    font-size: 12px;
    color: var(--accent-orange);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .attention-icon {
    font-size: 13px;
    flex-shrink: 0;
  }

  .attention-card-actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .meta-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  .meta-value {
    font-size: 12px;
    color: var(--text-primary);
    background: var(--bg-tertiary);
    padding: 2px 8px;
    border-radius: 999px;
  }

  .detail-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 20px 0;
  }

  .section-title {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0;
  }

  .detail-goal {
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-primary);
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .worktree-card {
    padding: 10px 12px;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: var(--bg-secondary);
  }

  .worktree-meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .worktree-branch {
    font-size: 12px;
    color: var(--text-primary);
  }

  .worktree-path {
    font-size: 10px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .timeline {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .timeline-event {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    padding: 4px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .tl-date {
    color: var(--text-secondary);
    font-size: 10px;
    min-width: 44px;
  }

  .tl-time {
    color: var(--text-secondary);
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 10px;
    min-width: 64px;
  }

  .tl-action {
    color: var(--accent-purple);
    font-weight: 600;
    font-size: 10px;
    min-width: 64px;
  }

  .tl-detail {
    color: var(--text-secondary);
    font-size: 10px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* ── P1-A: Changes diff viewer ─────────────────────────────── */
  .diff-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    user-select: none;
    padding: 2px 0;
  }

  .diff-header-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .diff-summary {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-family: ui-monospace, "SF Mono", monospace;
  }

  .diff-files {
    color: var(--text-secondary);
    font-size: 10px;
  }

  .diff-stat-add {
    color: var(--accent-green);
    font-weight: 600;
  }

  .diff-stat-del {
    color: var(--accent-red);
    font-weight: 600;
  }

  .diff-loading,
  .diff-empty-label {
    font-size: 10px;
    color: var(--text-secondary);
  }

  .diff-toggle {
    font-size: 9px;
    color: var(--text-secondary);
  }

  .diff-no-changes {
    font-size: 11px;
    color: var(--text-secondary);
    padding: 8px 0 4px;
  }

  .diff-viewer {
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 10px;
    line-height: 1.4;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 8px 0;
    margin-top: 6px;
    max-height: 400px;
    overflow-y: auto;
    overflow-x: auto;
  }

  .diff-line {
    padding: 0 10px;
    white-space: pre;
    color: var(--text-secondary);
  }

  .diff-line.diff-add {
    background: rgba(48, 209, 88, 0.08);
    color: var(--accent-green);
  }

  .diff-line.diff-del {
    background: rgba(255, 69, 58, 0.08);
    color: var(--accent-red);
  }

  .diff-line.diff-hunk {
    color: var(--accent-blue);
    background: rgba(10, 132, 255, 0.06);
  }

  .diff-line.diff-meta {
    color: var(--text-secondary);
    opacity: 0.7;
  }

  .detail-pre {
    font-family: ui-monospace, "SF Mono", monospace;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 12px;
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 300px;
    overflow-y: auto;
  }
</style>
