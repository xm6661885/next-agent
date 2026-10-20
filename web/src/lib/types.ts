// Mirrors docs/protocol.md. Keep in sync with the backend.

export type SessionState = 'offline' | 'queued' | 'starting' | 'idle' | 'running' | 'interrupting'

export interface LastSession {
  id: string
  title: string
  updated_at: string
  preview: string
}

export interface AgentStatus {
  running: number
  live: number
  pending: number
  last_session: LastSession | null
}

export interface Agent {
  id: string
  name: string
  avatar: string
  description: string
  cwd: string
  model: string
  fallback_model: string
  effort: string
  thinking: string
  thinking_budget: number
  permission_mode: string
  system_prompt_mode: 'preset' | 'custom'
  system_prompt: string
  claude_md: 'inherit' | 'custom'
  setting_sources: string[]
  tools: string[]
  auto_memory: boolean
  allowed_tools: string[]
  disallowed_tools: string[]
  add_dirs: string[]
  max_turns: number
  max_budget_usd: number
  env: Record<string, string>
  mcp_servers: Record<string, unknown>
  agents: Record<string, unknown>
  enable_file_checkpointing: boolean
  file_output: boolean
  file_output_prompt: string
  genui: boolean
  genui_prompt: string
  genui_widgets: GenUIWidgets
  idle_mode: IdleMode
  idle_timeout_min: number
  adaptive_keep: number
  /** Home grouping: one of GET /api/groups, or '' for ungrouped. */
  group: string
  /** Groups whose fields this agent sets itself; the rest follow [defaults]. */
  override_groups: OverrideGroup[]
  extra_args: Record<string, string | null>
  created_at: string
  order: number
  status?: AgentStatus
  /** Read-only: every overridable field resolved against the defaults. */
  effective?: Effective
}

/** Per-widget switch and prompt; prompt '' = built-in. Keys: ask, chart, mermaid, mindmap, svg, html. */
export type GenUIWidgets = Record<string, { on: boolean; prompt: string }>

export type IdleMode = 'timer' | 'adaptive' | 'never'
export type OverrideGroup = 'model' | 'permissions' | 'system_prompt' | 'file_output' | 'genui' | 'idle'

export interface Effective {
  model: string; effort: string; fallback_model: string; thinking: 'adaptive' | 'enabled' | 'disabled'; thinking_budget: number
  permission_mode: string
  system_prompt_mode: 'preset' | 'custom'; system_prompt: string
  file_output: boolean; file_output_prompt: string; genui: boolean; genui_prompt: string; genui_widgets: GenUIWidgets
  idle_mode: IdleMode; idle_timeout_min: number; adaptive_keep: number
}

/** A file touched or shared in a conversation (GET /api/sessions/{sid}/artifacts). */
export interface Artifact {
  path: string; name: string; mime: string; is_image: boolean; exists: boolean; size: number | null
  sources: ('link' | 'write' | 'edit' | 'upload')[]; first_ts: string; last_ts: string; url: string
}

export interface Session {
  id: string
  agent_id: string
  sdk_session_id: string | null
  title: string
  preview: string
  created_at: string
  updated_at: string
  total_cost_usd: number
  turns: number
  fork_of: { session_id: string; at_uuid: string | null } | null
  imported: boolean
  /** Set on temporary sessions: the folder they run in. */
  cwd?: string
  overrides: { model: string | null; effort: string | null; permission_mode: string | null }
  context: { used: number; max: number; percent: number } | null
  state: SessionState
  pending: number
  /** A turn finished while no client had the chat open. */
  unread?: boolean
}

export interface SearchHit {
  session: Session
  /** Text around the first transcript match; empty for a title-only match. */
  snippet: string
}

export interface Attachment {
  id: string
  name: string
  mime: string
  size: number
  path: string
  url: string
  is_image: boolean
}

interface ItemBase {
  id: string
  ts?: string
  parent_tool_use_id?: string | null
}

export interface UserItem extends ItemBase {
  kind: 'user'
  text: string
  attachments: Attachment[]
  uuid: string | null
  pending: boolean
  /** Sent into a running turn and still waiting in the CLI queue (shown in the queue tray). */
  queued?: boolean
  client_id?: string
}

export interface TextItem extends ItemBase {
  kind: 'text'
  text: string
  streaming: boolean
}

export interface ThinkingItem extends ItemBase {
  kind: 'thinking'
  text: string
  streaming: boolean
  /** Live sessions only: set when the block stops. */
  duration_ms?: number
}

export interface ToolResult {
  content: string
  is_error: boolean
  images?: string[]
}

export interface ToolItem extends ItemBase {
  kind: 'tool'
  tool_use_id: string
  name: string
  input: Record<string, any>
  input_partial?: string
  streaming: boolean
  result: ToolResult | null
  /** Live sessions only: tool call to result, set with the result. */
  duration_ms?: number
}

export interface NoticeItem extends ItemBase {
  kind: 'notice'
  level: 'info' | 'warn' | 'error'
  text: string
}

export interface ResultItem extends ItemBase {
  kind: 'result'
  subtype: string
  is_error: boolean
  duration_ms: number
  num_turns: number
  cost_usd: number
  total_cost_usd: number
  usage?: Record<string, any>
  terminal_reason?: string | null
}

export type Item = UserItem | TextItem | ThinkingItem | ToolItem | NoticeItem | ResultItem

export interface QuestionOption { label: string; description?: string }
export interface Question { question: string; header?: string; options: QuestionOption[]; multiSelect?: boolean }

export interface PermissionRequest {
  id: string
  session_id: string
  kind: 'tool' | 'question' | 'plan'
  tool_name: string
  tool_use_id: string
  input: Record<string, any>
  title?: string
  description?: string
  decision_reason?: string
  blocked_path?: string | null
  suggestions: unknown[]
  created_at: string
}

export interface InitInfo {
  model?: string
  permission_mode?: string
  tools?: string[]
  slash_commands?: string[]
  mcp_servers?: { name: string; status: string }[]
  agents?: string[]
  skills?: string[]
  claude_code_version?: string
  cwd?: string
}

export interface TaskInfo {
  task_id: string
  kind?: 'task' | 'cron'
  tool_use_id?: string
  description: string
  status: string
  task_type?: string
  last_tool_name?: string
  summary?: string
  usage?: { total_tokens: number; tool_uses: number; duration_ms: number }
  cron?: string
  schedule?: string
  subagent_type?: string
  /** Agent tool call that owns this task (a shell started by a subagent); null for the main thread. */
  parent_tool_use_id?: string | null
  recurring?: boolean
  started_at?: string
  updated_at?: string
}

export interface Defaults {
  model: string
  effort: string
  fallback_model: string
  thinking: 'adaptive' | 'enabled' | 'disabled'
  thinking_budget: number
  permission_mode: string
  custom_models: string[]
  file_output: boolean
  file_output_prompt: string
  genui: boolean
  genui_prompt: string
  genui_widgets: GenUIWidgets
  system_prompt_mode: 'preset' | 'custom'
  system_prompt: string
  idle_mode: IdleMode
  idle_timeout_min: number
  adaptive_keep: number
  /** Client switch: Artifacts panel and code cards. */
  artifacts: boolean
}

export interface Meta {
  models: string[]
  efforts: string[]
  permission_modes: string[]
  version: string
  defaults: Defaults
  default_genui_widgets: Record<string, string>
}

export interface Price { input: number; output: number; cache_write: number; cache_read: number }

export interface ConfigForm {
  server: { host: string; port: number; max_concurrent: number; cli_path: string; api_key: string; anthropic_base_url: string; anthropic_api_key: string }
  defaults: Defaults
  pricing: Record<string, Price>
  default_file_output_prompt: string
  default_genui_prompt: string
  default_genui_widgets: Record<string, string>
}

export type Activity =
  | { kind: 'requesting' | 'compacting'; at: string }
  | { kind: 'retry'; at: string; attempt: number; max_retries: number; retry_delay_ms: number; error_status: number | null; error: string; no_response?: { waited_ms: number; retry_wait_ms: number } }
  | { kind: 'thinking_tokens'; at: string; estimated_tokens: number }

export interface DirEntry { name: string; path: string; git: boolean }

export interface DirListing {
  path: string
  parent: string | null
  home: string
  dirs: DirEntry[]
  recent: string[]
}

export interface Importable {
  sdk_session_id: string
  summary: string
  first_prompt: string
  last_modified: string | number
  git_branch?: string | null
}

/** One file of Claude Code memory. title/description/type come from frontmatter when present. */
export interface MemoryFile {
  path: string
  name: string
  size: number
  mtime: number
  title?: string
  description?: string
  type?: string
}

export interface MemoryListing {
  root: string
  global: MemoryFile | null
  projects: { id: string; cwd: string | null; mtime: number; files: MemoryFile[] }[]
}
