<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'
  import { createEventDispatcher, onMount } from 'svelte'

  export let show: boolean = false

  const dispatch = createEventDispatcher<{ close: void; created: string }>()

  let goal = ''
  let taskId = ''
  let taskIdManuallyEdited = false
  let creating = false
  let error: string | null = null
  let goalEl: HTMLTextAreaElement

  let suggestTimer: ReturnType<typeof setTimeout> | null = null

  // Debounce suggest_task_id when goal changes and user hasn't manually set taskId
  $: if (goal && !taskIdManuallyEdited) {
    if (suggestTimer) clearTimeout(suggestTimer)
    suggestTimer = setTimeout(async () => {
      try {
        const suggested = await invoke<string>('suggest_task_id', { goal })
        if (!taskIdManuallyEdited) taskId = suggested
      } catch {
        // silent — taskId stays as-is
      }
    }, 350)
  }

  $: if (!goal && !taskIdManuallyEdited) {
    taskId = ''
  }

  function onTaskIdInput() {
    taskIdManuallyEdited = true
  }

  async function handleCreate() {
    if (!goal.trim()) return
    creating = true
    error = null
    try {
      const finalId = await invoke<string>('create_task', {
        goal: goal.trim(),
        taskId: taskId.trim() || null,
      })
      dispatch('created', finalId)
    } catch (e) {
      const msg = typeof e === 'string' ? e : String(e)
      if (msg.startsWith('task_conflict:')) {
        error = 'A task with that ID already exists. Choose a different ID.'
      } else if (msg.startsWith('invalid_task_goal:')) {
        error = 'Goal cannot be empty.'
      } else if (msg.startsWith('invalid_task_id:')) {
        error = 'Task ID contains invalid characters.'
      } else {
        error = msg || 'Create failed. Try again.'
      }
    } finally {
      creating = false
    }
  }

  function handleCancel() {
    dispatch('close')
  }

  function resetForm() {
    goal = ''
    taskId = ''
    taskIdManuallyEdited = false
    creating = false
    error = null
    if (suggestTimer) { clearTimeout(suggestTimer); suggestTimer = null }
  }

  // Reset form each time sheet opens; focus textarea
  $: if (show) {
    resetForm()
    // defer focus until DOM updates
    setTimeout(() => goalEl?.focus(), 50)
  }

  function handleBackdrop(e: MouseEvent) {
    if ((e.target as HTMLElement).classList.contains('sheet-backdrop')) {
      dispatch('close')
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!show) return
    if (e.key === 'Escape') dispatch('close')
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') handleCreate()
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if show}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="sheet-backdrop" on:click={handleBackdrop}>
    <aside class="sheet" role="dialog" aria-modal="true" aria-label="Create Task">
      <header class="sheet-header">
        <span class="sheet-title">Create Task</span>
        <button class="close-btn" on:click={handleCancel} aria-label="Close">✕</button>
      </header>

      <div class="sheet-body">
        <p class="helper-text">
          Goal becomes the draft packet summary and the inspector starting point.
          Agent and worktree are chosen in Dispatch, not here.
        </p>

        <label class="field-label" for="goal-input">Goal <span class="required">*</span></label>
        <textarea
          id="goal-input"
          class="goal-input"
          bind:this={goalEl}
          bind:value={goal}
          placeholder="Describe what this task should accomplish…"
          rows={4}
          disabled={creating}
        ></textarea>

        <label class="field-label" for="taskid-input">Task ID</label>
        <input
          id="taskid-input"
          class="taskid-input"
          type="text"
          bind:value={taskId}
          on:input={onTaskIdInput}
          placeholder="auto-generated from goal"
          disabled={creating}
          spellcheck="false"
        />
        <p class="field-hint">Leave blank to auto-generate. You can edit after suggestion appears.</p>

        {#if error}
          <div class="inline-error" role="alert">{error}</div>
        {/if}
      </div>

      <footer class="sheet-footer">
        <button class="cancel-btn" on:click={handleCancel} disabled={creating}>Cancel</button>
        <button
          class="create-btn"
          on:click={handleCreate}
          disabled={!goal.trim() || creating}
        >
          {creating ? 'Creating…' : 'Create Draft'}
        </button>
      </footer>
    </aside>
  </div>
{/if}

<style>
  .sheet-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    z-index: 100;
    display: flex;
    justify-content: flex-end;
  }

  .sheet {
    width: 360px;
    height: 100%;
    background: var(--bg-primary);
    border-left: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    animation: slideIn 180ms ease;
    outline: none;
  }

  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to   { transform: translateX(0);    opacity: 1; }
  }

  .sheet-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 20px 14px;
    border-bottom: 1px solid var(--border-color);
  }

  .sheet-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .close-btn {
    font-size: 14px;
    color: var(--text-secondary);
    padding: 2px 6px;
    border-radius: 6px;
    transition: background 100ms;
  }

  .close-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }

  .sheet-body {
    flex: 1;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    overflow-y: auto;
  }

  .helper-text {
    font-size: 11px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin: 0 0 12px;
  }

  .field-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.3px;
    margin-top: 8px;
  }

  .required {
    color: var(--accent-red);
  }

  .goal-input {
    width: 100%;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    color: var(--text-primary);
    resize: vertical;
    font-family: inherit;
    line-height: 1.5;
    transition: border-color 120ms;
  }

  .goal-input:focus {
    outline: none;
    border-color: var(--accent-blue);
  }

  .goal-input:disabled {
    opacity: 0.6;
  }

  .taskid-input {
    width: 100%;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    color: var(--text-primary);
    font-family: ui-monospace, "SF Mono", monospace;
    transition: border-color 120ms;
  }

  .taskid-input:focus {
    outline: none;
    border-color: var(--accent-blue);
  }

  .taskid-input:disabled {
    opacity: 0.6;
  }

  .taskid-input::placeholder {
    font-family: inherit;
    color: var(--text-secondary);
  }

  .field-hint {
    font-size: 10px;
    color: var(--text-secondary);
    margin: 0;
    opacity: 0.8;
  }

  .inline-error {
    font-size: 11px;
    color: var(--accent-red);
    background: rgba(255, 69, 58, 0.08);
    border: 1px solid rgba(255, 69, 58, 0.2);
    border-radius: 6px;
    padding: 7px 10px;
    margin-top: 4px;
  }

  .sheet-footer {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 14px 20px;
    border-top: 1px solid var(--border-color);
  }

  .cancel-btn {
    flex: 0 0 auto;
    height: 34px;
    padding: 0 14px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    background: var(--bg-secondary);
    transition: background 100ms, color 100ms;
  }

  .cancel-btn:hover:not(:disabled) {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }

  .cancel-btn:disabled {
    opacity: 0.5;
  }

  .create-btn {
    flex: 1;
    height: 34px;
    border-radius: 8px;
    background: var(--accent-blue);
    color: var(--bg-primary);
    font-size: 12px;
    font-weight: 600;
    transition: filter 120ms;
  }

  .create-btn:hover:not(:disabled) {
    filter: brightness(0.9);
  }

  .create-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
</style>
