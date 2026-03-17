# owlscale Architecture — Source of Truth

> Version: 0.2.0-design
> Last updated: 2026-03-17

---

## 1. 核心设计哲学

owlscale 解决一个具体问题：**当多个 AI agent 协作完成一个项目时，整个过程应当是结构化的、可追溯的、会话无关的。**

三个关键词：
- **结构化**：每个任务有标准的上下文包（Context Packet）和交付包（Return Packet）
- **可追溯**：所有操作有状态机追踪和日志，谁做了什么、什么时候、结果如何
- **会话无关**：agent 的身份和任务状态不依赖于某次对话，重启后可无缝恢复

owlscale 不是通信系统，不是任务调度器。它是**协议层 + 状态追踪层**，人仍然是触发者，但流程是标准的。

---

## 2. 项目隔离模型

每个项目有且只有一个 `.owlscale/` 目录，通过向上遍历父目录定位：

```
my-project/
  .owlscale/
    state.json      # 该项目所有任务的状态索引
    roster.json     # 该项目注册的 agent
    agents/         # 每个 agent 的身份上下文文件
    packets/        # Context Packets（任务说明）
    returns/        # Return Packets（交付结果）
    log/            # 操作日志
    config.toml     # 项目级配置
```

**不同项目的状态完全独立**。agent 的 ID（如 `cc-opus`）在不同项目中可以代表同一个 AI 实例，但它的任务列表、历史记录、roster 配置都是该项目私有的。

---

## 3. Agent 身份模型（核心设计）

### 3.1 问题

AI agent 是无状态的会话系统。每次启动一个新的 Claude Code / Copilot 窗口，它不知道：
- 自己在这个项目里叫什么
- 有哪些任务等待处理
- 该怎么行事

### 3.2 解决方案：Agent Context File

每个注册的 agent 在 `.owlscale/agents/<agent-id>.md` 有一个**身份上下文文件**，它是：
- 自动生成和维护的（owlscale 在 dispatch/return/accept/reject 后自动刷新）
- 会话无关的（关机重启不影响）
- 给 AI 读的（格式直接面向 LLM prompt）

### 3.3 Agent Context File 格式

```markdown
# owlscale Agent Context: copilot-opus
Project: my-project
Path: /Users/yeemio/AI/my-project
Role: executor
As of: 2026-03-17T16:00:00+08:00

## 你是谁

你是 copilot-opus，这个项目的 executor agent。
你的职责是：按照 Context Packet 的要求实现代码，写 Return Packet，运行 owlscale return。

## 当前待处理任务

| task-id | goal | packet |
|---------|------|--------|
| 2026-03-17-feat-auth | Add JWT authentication | .owlscale/packets/2026-03-17-feat-auth.md |

## 工作流程

1. 读取你的任务：`.owlscale/packets/<task-id>.md`
2. 运行 `owlscale claim <task-id>`（开始工作）
3. 完成后写 `.owlscale/returns/<task-id>.md`
4. 运行 `owlscale return <task-id>`

## 行为约束

- 只处理分配给 copilot-opus 的任务
- 不修改 .owlscale/state.json 和 roster.json
- 每个任务完成必须写 Return Packet，不能空着提交
- 遇到 scope 外的问题：写入 Return Packet 的 Remaining Risks，不擅自扩展
```

### 3.4 启动协议

当用户对一个 AI agent 说「你是 copilot-opus」时，agent 执行：

```
1. 读取 .owlscale/agents/copilot-opus.md
2. 知道自己的角色、待处理任务、行为规则
3. 开始处理第一个待处理任务
```

这是会话恢复的完整协议。用户不需要重新解释项目背景，不需要重新分配任务，agent 自己定位。

---

## 4. 简化的交互模型

### 4.1 项目所有者（人）的操作

**初始化（一次性）：**
```bash
cd my-project
owlscale init --name "My Project"
owlscale roster add cc-opus --name "Claude Code" --role coordinator
owlscale roster add copilot-opus --name "Copilot" --role executor
```

**日常任务分配：**
```bash
owlscale pack <task-id> --goal "..."   # 创建任务
owlscale dispatch <task-id> <agent>    # 分配（自动刷新 agent context）
owlscale accept/reject <task-id>       # 验收（自动刷新 agent context）
```

**查看状态：**
```bash
owlscale status
owlscale log
```

### 4.2 Agent 的操作

**启动新会话时（人告诉 agent）：**
> 「你是 copilot-opus，读取 .owlscale/agents/copilot-opus.md」

**Agent 自己执行：**
```bash
owlscale claim <task-id>     # 声明开始
# ... 做工作 ...
owlscale return <task-id>    # 提交结果
```

owlscale 的复杂命令（validate/lint/diff/stats/prune 等）是**管理员工具**，不是 agent 日常操作。

---

## 5. 自动刷新机制

每次以下操作后，owlscale 自动刷新相关 agent 的 context file：

| 操作 | 刷新哪些 agent |
|------|---------------|
| `dispatch <id> <agent>` | 刷新 assignee 的 context |
| `return <id>` | 刷新 coordinator 的 context |
| `accept <id>` | 刷新 assignee 的 context |
| `reject <id>` | 刷新 assignee 的 context |

这样 agent context file 始终反映最新的任务状态。

---

## 6. 版本路线图

### v0.1.0（已发布）
- 核心状态机：pack/dispatch/claim/return/accept/reject
- Roster 管理、日志、导出、lint、prune、diff、stats、route、git 集成
- 零外部依赖

### v0.2.0（当前开发目标）
- **`owlscale/identity.py`**：agent context file 生成与自动刷新
- **`owlscale init` 增强**：项目名称配置，初始化时自动生成 agent context
- **`owlscale whoami <agent-id>`**：打印某 agent 的完整上下文（用于粘贴到新会话）
- **dispatch/return/accept/reject 自动刷新**：状态变更后 context file 同步更新

### v0.3.0
- `search/tag/timeline/repair/config/snapshot` 等工效模块 promote 到公开版
- 完善项目级 config.toml

### v0.4.0（智能层）
- flywheel + hub：本地模型作为路由决策 + 训练数据管线

---

## 7. 设计约束

- **零外部依赖**：owlscale 核心永远不引入第三方库
- **文件优先**：所有状态是人类可读的文件，不用数据库，不用服务
- **agent 无感知**：owlscale 不假设 agent 的具体实现，任何能读文件的 AI 都可以接入
- **单向信息流**：pack → dispatch → return → accept，不走回头路（reject 除外）
