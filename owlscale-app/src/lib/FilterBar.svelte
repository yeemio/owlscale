<script lang="ts">
  import type { TaskFilter } from '../types'

  export let filter: TaskFilter = { text: '', status: '' }
</script>

<div class="filter-bar">
  <input
    class="filter-input"
    type="text"
    placeholder="Filter tasks…"
    bind:value={filter.text}
  />
  <select class="filter-select" bind:value={filter.status}>
    <option value="">All</option>
    <option value="returned">Review</option>
    <option value="dispatched">Working</option>
    <option value="in_progress">In Progress</option>
    <option value="draft">Draft</option>
    <option value="accepted">Done</option>
    <option value="rejected">Rejected</option>
  </select>
</div>

<style>
  .filter-bar {
    display: flex;
    gap: 6px;
    padding: 6px 12px;
  }

  .filter-input {
    flex: 1 1 auto;
    min-width: 0;
    height: 26px;
    padding: 0 8px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 11px;
  }

  .filter-input::placeholder {
    color: var(--text-secondary);
  }

  .filter-input:focus {
    outline: none;
    border-color: var(--accent-purple);
  }

  .filter-select {
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

  .filter-select:focus {
    outline: none;
    border-color: var(--accent-purple);
  }
</style>
