<script lang="ts">
  import type { AgentInfo } from '../types'

  export let agent: AgentInfo
  export let active: boolean = false

  const roleColor: Record<AgentInfo['role'], string> = {
    coordinator: 'var(--accent-purple)',
    executor: 'var(--accent-green)',
    hub: 'var(--accent-yellow)',
  }
</script>

<div class="agent-card" title={`${agent.name} (${agent.role})`}>
  <span
    class="agent-dot"
    class:dot-active={active}
    style:background-color={roleColor[agent.role]}
    style:opacity={active ? '1' : '0.5'}
  ></span>
  <span class="agent-name">{agent.name}</span>
  <span class="agent-role">{agent.role}</span>
</div>

<style>
  .agent-card {
    height: 32px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 12px;
    transition: background-color 120ms ease;
  }

  .agent-card:hover {
    background: var(--bg-secondary);
  }

  .agent-dot {
    width: 8px;
    height: 8px;
    flex: 0 0 8px;
    border-radius: 999px;
  }

  .agent-name {
    flex: 1 1 auto;
    min-width: 0;
    color: var(--text-primary);
    font-size: 13px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .agent-role {
    flex: 0 0 auto;
    font-size: 11px;
    color: var(--text-secondary);
    text-transform: lowercase;
  }
</style>
