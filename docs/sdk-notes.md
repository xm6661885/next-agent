# Claude Agent SDK for Python: research report

**Audited package:** `claude-agent-sdk 0.2.163`, the latest version returned by PyPI on 2026-10-03. Its wheel declares `Requires-Python: >=3.10` and bundles Claude Code CLI **2.1.286**. The local CLI you mentioned is **2.1.284**; setting `cli_path` selects that executable instead of the bundled one. The SDK describes the bundled CLI and `cli_path` in its [wheel metadata](`claude_agent_sdk-0.2.163.dist-info/METADATA`) and [options source](`claude_agent_sdk/types.py:2096`).

The extracted wheel source is the authority for Python types and implementation details below. Links to PyPI and official documentation are included for release and behavioral claims.

## 1. Version, Python, and CLI

- **PyPI:** `0.2.163`. The downloaded artifact is `claude_agent_sdk-0.2.163-py3-none-manylinux_2_17_x86_64.whl`.
- **Python:** 3.10 or newer.
- **CLI:** The package includes a platform-specific bundled executable. The wheel’s `_cli_version.py` reports `2.1.286`.
- **Override:** `ClaudeAgentOptions(cli_path=...)` accepts `str | Path | None`. `None` uses the bundled CLI; an explicit path uses that executable. For example:

  ```python
  ClaudeAgentOptions(cli_path="/home/you/.local/bin/claude")
  ```

That selects the supplied local CLI, version 2.1.284. It is two patch versions behind the wheel’s bundled CLI; the wheel does not promise that every bundled-CLI behavior is identical to an independently selected CLI version. See the [PyPI project page](https://pypi.org/project/claude-agent-sdk/) and [Python reference](https://docs.claude.com/en/docs/agent-sdk/python).

## 2. `ClaudeAgentOptions`: fields, types, defaults

This is the complete dataclass field list from the audited wheel’s [`types.py`](`claude_agent_sdk/types.py:1970`). Defaults below are Python constructor defaults. `default_factory` fields are shown by their resulting default value.

| Field | Type | Default |
|---|---|---:|
| `tools` | `list[str] \| ToolsPreset \| None` | `None` |
| `allowed_tools` | `list[str]` | `[]` |
| `system_prompt` | `str \| SystemPromptPreset \| SystemPromptCustom \| SystemPromptFile \| None` | `None` |
| `mcp_servers` | `dict[str, McpServerConfig] \| str \| Path` | `{}` |
| `strict_mcp_config` | `bool` | `False` |
| `permission_mode` | `PermissionMode \| None` | `None` |
| `continue_conversation` | `bool` | `False` |
| `resume` | `str \| None` | `None` |
| `session_id` | `str \| None` | `None` |
| `max_turns` | `int \| None` | `None` |
| `max_budget_usd` | `float \| None` | `None` |
| `disallowed_tools` | `list[str]` | `[]` |
| `model` | `str \| None` | `None` |
| `fallback_model` | `str \| None` | `None` |
| `betas` | `list[SdkBeta]` | `[]` |
| `permission_prompt_tool_name` | `str \| None` | `None` |
| `cwd` | `str \| Path \| None` | `None` |
| `cli_path` | `str \| Path \| None` | `None` |
| `settings` | `str \| None` | `None` |
| `add_dirs` | `list[str \| Path]` | `[]` |
| `env` | `dict[str, str]` | `{}` |
| `extra_args` | `dict[str, str \| None]` | `{}` |
| `max_buffer_size` | `int \| None` | `None` |
| `debug_stderr` | `Any` | `sys.stderr` *(deprecated; no longer read by transport)* |
| `stderr` | `Callable[[str], None] \| None` | `None` |
| `can_use_tool` | `CanUseTool \| None` | `None` |
| `hooks` | `dict[HookEvent, list[HookMatcher]] \| None` | `None` |
| `user` | `str \| None` | `None` |
| `include_partial_messages` | `bool` | `False` |
| `include_hook_events` | `bool` | `False` |
| `forward_subagent_text` | `bool` | `False` |
| `verbatim_prompts` | `bool` | `False` |
| `fork_session` | `bool` | `False` |
| `resume_session_at` | `str \| None` | `None` |
| `resume_drops_turn` | `str \| None` | `None` |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` |
| `setting_sources` | `list[SettingSource] \| None` | `None` |
| `skills` | `list[str] \| Literal["all"] \| None` | `None` |
| `sandbox` | `SandboxSettings \| None` | `None` |
| `plugins` | `list[SdkPluginConfig]` | `[]` |
| `max_thinking_tokens` | `int \| None` | `None` *(deprecated; use `thinking`)* |
| `thinking` | `ThinkingConfig \| None` | `None` |
| `effort` | `EffortLevel \| None` | `None` |
| `output_format` | `dict[str, Any] \| None` | `None` |
| `enable_file_checkpointing` | `bool` | `False` |
| `session_store` | `SessionStore \| None` | `None` |
| `session_store_flush` | `SessionStoreFlushMode` | `"batched"` |
| `load_timeout_ms` | `int` | `60_000` |
| `task_budget` | `TaskBudget \| None` | `None` |

Relevant type values and behavior:

- `PermissionMode` is `Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"]`.
- `SettingSource` is `Literal["user", "project", "local"]`. `None` loads normal filesystem settings; `[]` disables them. Include `"project"` if you want project `CLAUDE.md` files loaded.
- `EffortLevel` is `Literal["low", "medium", "high", "xhigh", "max"]`. The source describes `xhigh` as an Opus 4.7 level that falls back to `high` on other models.
- `ThinkingConfig` is a tagged union:
  - `{"type": "adaptive", "display"?: "summarized" | "omitted"}`
  - `{"type": "enabled", "budget_tokens": int, "display"?: "summarized" | "omitted"}`
  - `{"type": "disabled"}`
- System prompt forms:
  - Plain custom prompt: `system_prompt="..."`
  - Claude Code preset: `{"type": "preset", "preset": "claude_code"}`
  - Preset plus appended instructions: `{"type": "preset", "preset": "claude_code", "append": "..."}`
  - Custom prompt with snapshot option: `{"type": "custom", "prompt": "...", "snapshot": True}`
  - File form: `{"type": "file", "path": "..."}`
- `allowed_tools` pre-approves named tools; it does **not** limit tool availability. Use `tools` to choose the base built-in tool set and `disallowed_tools` to block tools.
- `max_turns` and `max_budget_usd` default to no explicit SDK limit. `ResultMessage` can report budget errors.
- `extra_args` maps CLI argument names without `--` to values; `None` represents a flag.
- `env` is merged into the subprocess environment. The SDK drops inherited `CLAUDECODE`, sets SDK-related variables, and applies `cwd` as `PWD`.
- `resume_session_at` truncates a resumed transcript at a UUID. `resume_drops_turn` optionally asks the CLI to validate that a discarded later range belongs to a specific user turn.
- `task_budget` is a token budget sent as API-side output configuration with a beta header; it is separate from `max_budget_usd`.

The [official Python reference’s options section](https://docs.claude.com/en/docs/agent-sdk/python) gives a readable subset and documents many of these options; the wheel source includes additional current fields such as `verbatim_prompts`, `resume_drops_turn`, session-store options, and task budgeting.

## 3. `ClaudeSDKClient`, input shape, and steering

### Methods

The audited [`client.py`](`claude_agent_sdk/client.py:93`) exposes these principal methods:

| Method | Signature / return |
|---|---|
| `connect` | `async def connect(self, prompt: str \| AsyncIterable[dict[str, Any]] \| None = None) -> None` |
| `query` | `async def query(self, prompt: str \| AsyncIterable[dict[str, Any]], session_id: str = "default") -> None` |
| `receive_messages` | `async def receive_messages(self) -> AsyncIterator[Message]` |
| `receive_response` | `async def receive_response(self) -> AsyncIterator[Message]` |
| `interrupt` | `async def interrupt(self) -> None` |
| `set_permission_mode` | `async def set_permission_mode(self, mode: PermissionMode) -> None` |
| `set_model` | `async def set_model(self, model: str \| None = None) -> None` |
| `rewind_files` | `async def rewind_files(self, user_message_id: str) -> None` |
| `get_mcp_status` | `async def get_mcp_status(self) -> McpStatusResponse` |
| `get_context_usage` | `async def get_context_usage(self) -> ContextUsageResponse` |
| `get_server_info` | `async def get_server_info(self) -> dict[str, Any] \| None` |
| `reconnect_mcp_server` | `async def reconnect_mcp_server(self, server_name: str) -> None` |
| `toggle_mcp_server` | `async def toggle_mcp_server(self, server_name: str, enabled: bool) -> None` |
| `stop_task` | `async def stop_task(self, task_id: str) -> None` |
| `disconnect` | `async def disconnect(self) -> None` |
| context-manager methods | `async def __aenter__(self) -> ClaudeSDKClient`; `async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool` |

`receive_response()` yields through and including the first `ResultMessage`; `receive_messages()` keeps reading until the stream ends. The [Python reference](https://docs.claude.com/en/docs/agent-sdk/python) lists the public client methods. `get_server_info()` returns the CLI initialize response (or `None` while initialization is unavailable); it is not a separate request.

### Wire message sent by `client.query()`

The source builds and writes this structure for a string prompt:

```python
message = {
    "type": "user",
    "message": {"role": "user", "content": prompt},
    "parent_tool_use_id": None,
    "session_id": session_id,
}
```

That code is in [`client.py`](`claude_agent_sdk/client.py:272`). An async-iterable prompt yields the same outer user-message shape; the SDK fills in `session_id` if it is absent.

### Calling `query()` during an active turn: queued, not steering

`client.query()` writes another user message to the connected CLI’s input stream. It does not call `interrupt()` or provide a distinct mid-turn steering API. The official [Streaming Input guide](https://docs.claude.com/en/docs/agent-sdk/streaming-vs-single-mode) describes queued messages as processing **sequentially**, with the ability to interrupt. So if a turn is running, treat another `query()` as a queued follow-up, not a reliable injection into the current model/tool loop.

For an immediate change of direction, interrupt, drain the interrupted turn, then send the replacement prompt. The official reference explicitly warns that `interrupt()` does **not** clear buffered messages: drain through the interrupted turn’s `ResultMessage` before reading the next response. It also documents interrupted results with `terminal_reason` such as `"aborted_streaming"` or `"aborted_tools"`. See the [interrupt example and buffer note](https://docs.claude.com/en/docs/agent-sdk/python) and the [streaming-input guide](https://docs.claude.com/en/docs/agent-sdk/streaming-vs-single-mode).

Example sequence:

```python
await client.interrupt()

async for message in client.receive_response():
    if isinstance(message, ResultMessage):
        break

await client.query("Stop the previous approach and do this instead...")
```

The SDK does not expose a `steer()` method or a query delivery-mode argument in this version.

### Message types and fields

Types are defined in [`types.py`](`claude_agent_sdk/types.py:1123`) and parsed in [`message_parser.py`](`claude_agent_sdk/_internal/message_parser.py`).

- `UserMessage`: `content: str | list[ContentBlock]`, `uuid`, `parent_tool_use_id`, `tool_use_result`, `origin`.
- `AssistantMessage`: `content: list[ContentBlock]`, `model`, `parent_tool_use_id`, `error`, `usage`, `message_id`, `stop_reason`, `session_id`, `uuid`.
- `SystemMessage`: `subtype: str`, `data: dict[str, Any]`. For `subtype == "init"`, `data` is the raw initialize metadata from the CLI, including fields such as tool names, slash commands, model, and other server/session information. Treat `data` as evolving raw protocol data rather than a fixed SDK schema.
- `ResultMessage`: `subtype`, `duration_ms`, `duration_api_ms`, `is_error`, `num_turns`, `session_id`, plus optional `stop_reason`, `total_cost_usd`, `usage`, `result`, `structured_output`, `model_usage`, `permission_denials`, `deferred_tool_use`, `errors`, `api_error_status`, `uuid`, `terminal_reason`, and `origin`.
- `StreamEvent`: `uuid`, `session_id`, raw `event: dict[str, Any]`, and optional `parent_tool_use_id`. Enable with `include_partial_messages=True`. Raw event deltas include text, thinking, and `input_json_delta` partial JSON updates; accumulate the event stream if you need the completed block.
- Other current message variants include `RateLimitEvent`, `ConversationResetMessage`, hook events, and task lifecycle messages. The `Message` union is broader in actual parsing than only assistant/user/result.

Content-block dataclasses include `TextBlock(text)`, `ThinkingBlock(thinking, signature)`, `ToolUseBlock(id, name, input)`, `ToolResultBlock(tool_use_id, content, is_error)`, and server-tool use/result blocks. Use `isinstance` checks on parsed blocks rather than expecting message content always to be plain text.

## 4. Sessions, transcripts, resume, and fork

The wheel exports these synchronous helpers:

```python
list_sessions(
    directory: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    include_worktrees: bool = True,
) -> list[SDKSessionInfo]

get_session_messages(
    session_id: str,
    directory: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[SessionMessage]
```

`SDKSessionInfo` includes `session_id`, `summary`, `last_modified`, `file_size`, `custom_title`, `first_prompt`, `git_branch`, `cwd`, `tag`, and `created_at`. `SessionMessage` contains `type` (`"user"` or `"assistant"`), `uuid`, `session_id`, raw `message`, and subagent-related parent identifiers where applicable. See the [Python session-helper reference](https://docs.claude.com/en/docs/agent-sdk/python) and [session guide](https://docs.claude.com/en/docs/agent-sdk/sessions).

Default local transcripts live at:

```text
~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
```

The project directory component is derived from the canonical working directory: resolve to a real path, normalize to Unicode NFC, then replace each non-ASCII-alphanumeric character with `-`. The audited SDK helper’s [`_sanitize_path`](`claude_agent_sdk/_internal/sessions.py:104`) truncates paths longer than 200 sanitized characters and adds a base-36 hash suffix. A `CLAUDE_CONFIG_DIR` override changes the root from `~/.claude`.

Each JSONL line is a transcript event/object. In practical terms, expect UUIDs, session IDs, timestamps, message role/content, tool-use and tool-result entries, and parent/branch metadata; don’t build a parser that assumes every line is an ordinary user or assistant turn. Subagents also have transcript files beneath the session’s `subagents/` directory.

Semantics:

- `ClaudeSDKClient` retains the current conversation while connected; consecutive `client.query()` calls continue that session.
- `continue_conversation=True` resumes the most recent session for the working directory.
- `resume="<session-id>"` resumes a specific session and is the appropriate choice when an app manages multiple conversations per user.
- `fork_session=True` is used with `resume` to create a new session ID based on the original history, leaving the original session intact.
- `resume_session_at="<uuid>"` lets the resume/fork start at a specific transcript entry.
- `continue_conversation` and `resume` are mutually exclusive. `session_id` has additional constraints and cannot normally be combined with either unless forking.

The official [sessions guide](https://docs.claude.com/en/docs/agent-sdk/sessions) describes fork as a new session based on copied history, not a mutation of the original. For durable multi-host sessions, the current wheel also supports `session_store`, which mirrors JSONL entries to an application-provided store; this is separate from the default on-disk transcript.

## 5. Permissions, user input, and `ExitPlanMode`

### `can_use_tool` and result dataclasses

The exact callback type is:

```python
CanUseTool = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResult],
]
```

The first argument is the tool name, the second its input, and the third a `ToolPermissionContext`. That context includes `signal` (currently `None`/reserved), `suggestions: list[PermissionUpdate]`, `tool_use_id`, and optional `agent_id`, `blocked_path`, `decision_reason`, `title`, `display_name`, and `description`.

The audited source defines:

```python
@dataclass
class PermissionResultAllow:
    behavior: Literal["allow"] = "allow"
    updated_input: dict[str, Any] | None = None
    updated_permissions: list[PermissionUpdate] | None = None

@dataclass
class PermissionResultDeny:
    behavior: Literal["deny"] = "deny"
    message: str = ""
    interrupt: bool = False
```

If `updated_input` is omitted, the SDK sends the original tool input. A deny can include a message Claude receives; `interrupt=True` requests interrupt behavior. Source: [`types.py`](`claude_agent_sdk/types.py:222`).

`can_use_tool` is called when permission evaluation reaches an ask/interactive decision. It is not a universal middleware for all tool calls: already allowed tools, permission modes, and settings allow rules can bypass it. For logic that must inspect every tool call, use `PreToolUse`. The [permissions guide](https://docs.claude.com/en/docs/agent-sdk/permissions) and [user-input guide](https://docs.claude.com/en/docs/agent-sdk/user-input) explain the evaluation order.

### “Always allow” / saved permission updates

The context’s `suggestions` are `PermissionUpdate` dataclasses. Echo the appropriate suggested updates in `updated_permissions` to persist an allow choice. Each update has:

- `type`: `"addRules"`, `"replaceRules"`, `"removeRules"`, `"setMode"`, `"addDirectories"`, or `"removeDirectories"`
- Optional `rules`, `behavior`, `mode`, `directories`, and `destination`
- `destination`: `"userSettings"`, `"projectSettings"`, `"localSettings"`, or `"session"`

A rule is `PermissionRuleValue(tool_name: str, rule_content: str | None = None)`. In the wire dictionary, its keys are `toolName` and `ruleContent`. A practical pattern from the official guide is to select the suggestions whose destination is `localSettings` and return:

```python
return PermissionResultAllow(
    updated_input=input_data,
    updated_permissions=[
        s for s in context.suggestions
        if s.destination == "localSettings"
    ],
)
```

### AskUserQuestion

`AskUserQuestion` reaches `can_use_tool` with `tool_name == "AskUserQuestion"` and an `input_data` containing a `questions` list. Each question contains `question`, `header`, `options` (label and description), and `multiSelect`. Return an allow result with the original `questions` plus `answers`, mapping the full question text to the selected label(s):

```python
return PermissionResultAllow(
    updated_input={
        "questions": input_data.get("questions", []),
        "answers": {
            "How should I format the output?": "Summary",
            "Which sections should I include?": ["Introduction", "Conclusion"],
        },
    }
)
```

Multi-select answers can be arrays of labels; the docs say they are also accepted as comma-joined strings. Do not omit `questions` from the returned `updated_input`. If you set a restrictive `tools` list, include `"AskUserQuestion"` for the model to ask clarifying questions. The [official user-input guide](https://docs.claude.com/en/docs/agent-sdk/user-input) has the question and answer format.

### ExitPlanMode

The Python reference lists `ExitPlanMode` as a tool, with input `{"plan": str}` and output `{"message": str, "approved": bool | None}`. It surfaces as a tool invocation, not merely text saying that the plan is ready. For a UI approval flow, recognize `tool_name == "ExitPlanMode"` in `can_use_tool`, display `input_data["plan"]`, and return the approval/denial decision. The tool shape is in the [Python reference](https://docs.claude.com/en/docs/agent-sdk/python#exitplanmode).

### Streaming and hook keepalive

The SDK’s control callbacks run over the CLI’s stdin/stdout control protocol. `ClaudeSDKClient` is the natural fit for a persistent interactive UI because it keeps the connection open across turns.

The current wheel’s `Query._has_bidirectional_needs()` explicitly treats SDK MCP servers, hooks, **and `can_use_tool`** as reasons to keep stdin open for control replies. This is the relevant implementation safeguard in [`_internal/query.py`](`claude_agent_sdk/_internal/query.py`). The official user-input guide still shows a dummy `PreToolUse` hook in an async-iterable `query()` example as a “Required workaround” to keep the stream open. That recipe is for the documented one-shot/stream-input pattern; for this persistent-agent backend, use `ClaudeSDKClient` and verify the behavior of the CLI selected by `cli_path`.

The callback may remain pending while waiting for a user decision; the official docs say execution stays paused until it returns. Build cancellation/timeouts and reconnect handling into the application’s approval wait path.

## 6. Image and file attachments

The supported image form is a user message whose `message.content` is a list containing text and an image block:

```python
{
    "type": "user",
    "message": {
        "role": "user",
        "content": [
            {"type": "text", "text": "Review this architecture diagram"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "<base64-encoded-bytes>",
                },
            },
        ],
    },
    "parent_tool_use_id": None,
}
```

The official [Streaming Input guide](https://docs.claude.com/en/docs/agent-sdk/streaming-vs-single-mode) uses this format and demonstrates reading bytes and base64-encoding them. `media_type` should match the image format, such as `image/png` or `image/jpeg`.

The wheel’s public `ContentBlock` union does not define a general-purpose file/document attachment block. For non-image files, use the CLI’s supported file/path workflow or provide extracted text; don’t assume that arbitrary file bytes can be inserted as an SDK content block. The `verbatim_prompts` option disables `@path` expansion and slash-command dispatch, so it changes path-based attachment behavior.

## 7. Other requested features

- **Hooks:** `hooks` maps hook names such as `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `Notification`, `SubagentStart`, and `PermissionRequest` to lists of `HookMatcher`. A matcher has `matcher`, `hooks`, and optional `timeout`. Hook callbacks are async; the current source notes that multiple matchers on the same event are dispatched concurrently. See [hooks documentation](https://docs.claude.com/en/docs/agent-sdk/hooks).
- **Custom tools:** define async Python handlers with `@tool`, register them using `create_sdk_mcp_server`, then pass the server in `mcp_servers`. Tool names are exposed as `mcp__<server>__<tool>`. See [custom tools](https://docs.claude.com/en/docs/agent-sdk/custom-tools).
- **External MCP:** `mcp_servers` accepts named stdio, SSE, HTTP, and SDK-server configurations, or a config path/JSON string. `get_mcp_status()` returns `{"mcpServers": [...]}`; reconnect/toggle methods are available. See [MCP docs](https://docs.claude.com/en/docs/agent-sdk/mcp).
- **Slash commands:** init/server metadata includes available commands; prompt delivery normally lets Claude Code interpret slash commands. `verbatim_prompts=True` disables slash-command dispatch.
- **Subagents:** `agents` is a mapping of names to `AgentDefinition` with fields including `description`, `prompt`, model, tools, skills, memory, MCP server references, max turns, and permission mode. By default, subagent text is not fully forwarded; set `forward_subagent_text=True` to include it. See [subagent docs](https://docs.claude.com/en/docs/agent-sdk/subagents).
- **Costs:** consume `ResultMessage.total_cost_usd`, `usage`, `model_usage`, `duration_ms`, and `num_turns`. `model_usage` provides per-model token and cost details. See [cost tracking](https://docs.claude.com/en/docs/agent-sdk/cost-tracking).
- **Todos:** Claude Code’s todo/task tools are CLI features. The SDK can expose/allow task-tracking tools; task lifecycle messages include `TaskStartedMessage`, `TaskProgressMessage`, `TaskNotificationMessage`, and `TaskUpdatedMessage`. See [todo tracking](https://docs.claude.com/en/docs/agent-sdk/todo-tracking).
- **System prompts:** preset-plus-append uses `{"type": "preset", "preset": "claude_code", "append": "..."}`. `SystemPromptPreset` also supports `snapshot` and `exclude_dynamic_sections` in current source. See [modifying system prompts](https://docs.claude.com/en/docs/agent-sdk/modifying-system-prompts).
- **File checkpointing:** set `enable_file_checkpointing=True`, and use `rewind_files(user_message_id)` with a user-message UUID. The client docs additionally require `extra_args={"replay-user-messages": None}` if you need replayed `UserMessage` objects with UUIDs in the output stream. See [checkpointing docs](https://docs.claude.com/en/docs/agent-sdk/file-checkpointing).

## 8. Operational gotchas and known issues

1. **Each client is a separate CLI subprocess.** The SDK does not provide a process-wide in-memory conversation shared across clients. Conversation continuity belongs to a connected client/session or to explicit transcript resume/fork. Persistent “agents” should own their own client and subprocess.

2. **Keep each client’s SDK operations in one async task/context.** The `ClaudeSDKClient` source itself warns against reusing an instance across different async runtime contexts. A repository issue reports silent hangs when a client is connected in one FastAPI/Starlette request task and used in another; its workaround is one dedicated worker task per session with `asyncio.Queue` bridges to request/WebSocket handlers. See [issue #576](https://github.com/anthropics/claude-agent-sdk-python/issues/576). This is directly relevant to the proposed FastAPI design.

3. **Do not treat `query()` as mid-turn steering.** It writes to the CLI input stream; documented streaming semantics are sequential queued messages. Use `interrupt()`, drain the interrupted result, then send a replacement message when immediate redirection is required.

4. **Drain after `ResultMessage` when background work may continue.** `receive_response()` stops at the parent result. Historical reports describe message-queue backpressure affecting SDK MCP/control messages when background subagent output continues after the consumer stops reading. See [issue #425](https://github.com/anthropics/claude-agent-sdk-python/issues/425). In a persistent UI, consider a long-lived message pump using `receive_messages()` and route events to the browser, rather than abandoning the stream at the parent result.

5. **Interrupt does not discard buffered output.** Drain the interrupted turn’s messages/result before associating later output with the next prompt. The official [Python reference](https://docs.claude.com/en/docs/agent-sdk/python) documents this explicitly.

6. **There are reported races/edge cases in the public issue tracker.** Examples include an `interrupt()` issued immediately after `query()` reportedly being ignored in some versions ([issue #1153](https://github.com/anthropics/claude-agent-sdk-python/issues/1153)), and background-task messages arriving after a parent result ([issue #788](https://github.com/anthropics/claude-agent-sdk-python/issues/788)). Treat these as reports to account for, not as proof that every current 0.2.163 + CLI 2.1.286 deployment reproduces them.

7. **Local transcript path encoding matters.** Ordinary paths are sanitized by replacing non-alphanumeric characters with hyphens. Long-path handling has a hash suffix; the SDK source notes potential long-path hash differences from CLI implementations. Avoid reproducing the path algorithm yourself if `list_sessions()` and `get_session_messages()` meet the need.

8. **Model and session state are mutable at runtime only through documented controls.** `set_model()` and `set_permission_mode()` send control requests. Updating the original `ClaudeAgentOptions` object after connect should not be assumed to reconfigure an active session.

### Primary references

- [Downloaded wheel metadata](`claude_agent_sdk-0.2.163.dist-info/METADATA`), [options and type definitions](`claude_agent_sdk/types.py:1970`), [client implementation](`claude_agent_sdk/client.py:93`), [session helpers](`claude_agent_sdk/_internal/sessions.py:680`), and [control/query implementation](`claude_agent_sdk/_internal/query.py`).
- [Official Python reference](https://docs.claude.com/en/docs/agent-sdk/python), [streaming input](https://docs.claude.com/en/docs/agent-sdk/streaming-vs-single-mode), [sessions](https://docs.claude.com/en/docs/agent-sdk/sessions), [permissions](https://docs.claude.com/en/docs/agent-sdk/permissions), and [user input](https://docs.claude.com/en/docs/agent-sdk/user-input).
- [Python SDK repository](https://github.com/anthropics/claude-agent-sdk-python) and its [issue tracker](https://github.com/anthropics/claude-agent-sdk-python/issues).
## 9. Verified locally (probe `scripts/probe_sdk.py`, SDK 0.2.163, bundled CLI 2.1.286, 2026-10-03)

- **Mid-turn `query()` IS steering.** A message written while a turn runs is injected at the next tool boundary
  (after the current tool result) and the model sees it within the same turn. Only one `ResultMessage` is emitted
  for the combined turn. It is not queued until the turn ends.
- With `extra_args={"replay-user-messages": None}` every user prompt is echoed back as a `UserMessage` with a `uuid`
  (string or list content, no `tool_result` blocks, `parent_tool_use_id=None`) at the moment the CLI consumes it.
  This is the "steer delivered" signal; consumption order is FIFO.
- Tool results arrive as `UserMessage` with `list[ToolResultBlock]`.
- `AskUserQuestion` goes through `can_use_tool`; returning
  `PermissionResultAllow(updated_input={"questions": q, "answers": {question_text: label}})` works. `suggestions` was `[]`.
- Background Bash produces `SystemMessage` subtypes `task_started` / `task_notification` (with `task_id`, `tool_use_id`,
  `description`, `status`). `SystemMessage(subtype="status")` is emitted frequently (`status: "requesting"`); ignore or map to a spinner.
- `SystemMessage(subtype="init")` is emitted at the start of **every** turn. Keys: `cwd, session_id, tools, mcp_servers, model,
  permissionMode, slash_commands, terminal_slash_commands, apiKeySource, claude_code_version, output_style, agents, skills, plugins, capabilities`.
- Session id stays the same across turns in one client.
- Memory: one connected CLI subprocess is ~190 MB RSS idle, ~220 MB after a few turns.
- Auth comes from `~/.claude/settings.json` `env` (e.g. ANTHROPIC_BASE_URL + token). `setting_sources` must include `"user"`
  or the CLI has no credentials. Leaving `model=None` uses the user default (`opus[1m]`).

## 10. Rewind by resume_session_at (verified)

Probe: `uv run python scripts/probe_rewind.py` on 2026-10-04, using the bundled CLI and a temporary cwd. It sent two
prompts (APPLE, BANANA), disconnected, then resumed at the `parentUuid` of the second user entry without
`fork_session`. The resumed answer to "Which words did I ask you to remember?" was **APPLE**. The resumed result kept
the same session ID (`9858dbb9-0dc7-42b0-b79e-bfdf9945d18d`); 8 new entries were appended to its existing JSONL
(29 to 37), and the new user entry's `parentUuid` equaled the saved parent
(`5acba032-37cb-43ac-96ec-2ba61ab31eec`). `get_session_messages` followed the newest branch and returned the
APPLE user message followed by the new question, without BANANA. The echoed UUID of the second user message was
`ad389c23-1c0c-4c92-ac3c-ce854df4b40f`, exactly matching its transcript entry UUID. The temporary cwd was removed.

The bundled CLI source constructs result `modelUsage` from cumulative session cost state (`nx()`), alongside
`total_cost_usd` from `Bg()`. Its schema text explicitly says `modelUsage` is cumulative and to read the latest result
instead of summing results. The existing per-process cost delta remains correct; a new CLI process starts a new delta
baseline.
