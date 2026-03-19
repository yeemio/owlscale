<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'

  const pickFolder = async () => {
    try {
      const dir = await invoke<string | null>('pick_workspace_dir')
      if (dir) {
        await invoke('set_workspace_dir', { path: dir })
      }
    } catch (e) {
      console.error('pick_workspace_dir failed:', e)
    }
  }
</script>

<div class="empty-state">
  <div class="empty-icon" aria-hidden="true">⬡</div>
  <div class="empty-title">No workspace</div>
  <div class="empty-subtitle">
    Open a project folder that already contains a
    <code class="inline-cmd">.owlscale/</code>
    workspace.
  </div>
  <button class="pick-link" type="button" on:click={pickFolder}>
    Open folder…
  </button>
</div>

<style>
  .empty-state {
    width: 320px;
    min-height: 280px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 20px 24px;
    background: var(--bg-primary);
  }

  .empty-icon {
    font-size: 40px;
    line-height: 1;
    color: var(--accent-purple);
    margin-bottom: 4px;
  }

  .empty-title {
    font-size: 15px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .empty-subtitle {
    font-size: 13px;
    color: var(--text-secondary);
    text-align: center;
  }

  .inline-cmd {
    display: inline-block;
    background: rgba(124, 58, 237, 0.18);
    color: var(--accent-purple);
    font-family: ui-monospace, 'SF Mono', monospace;
    font-size: 12px;
    padding: 1px 6px;
    border-radius: 4px;
  }

  .pick-link {
    margin-top: 4px;
    font-size: 12px;
    color: var(--text-secondary);
    border-radius: 4px;
    padding: 2px 6px;
    transition: color 120ms ease;
  }

  .pick-link:hover {
    color: var(--text-primary);
  }
</style>
