<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import type { WorkspaceState, FocusMode } from '../types'
  import ReviewFocusView from './ReviewFocusView.svelte'
  import ExecutionFocusView from './ExecutionFocusView.svelte'
  import SetupFocusView from './SetupFocusView.svelte'

  export let state: WorkspaceState | null
  export let focusMode: FocusMode
  export let selectedTaskId: string | null = null

  const dispatch = createEventDispatcher<{ select: string }>()
</script>

<section class="focus-panel">
  {#if focusMode === 'review' && state}
    <ReviewFocusView {state} {selectedTaskId} on:select />
  {:else if focusMode === 'execution' && state}
    <ExecutionFocusView {state} {selectedTaskId} on:select />
  {:else}
    <SetupFocusView {state} />
  {/if}
</section>

<style>
  .focus-panel {
    height: 100vh;
    overflow-y: auto;
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
  }
</style>
