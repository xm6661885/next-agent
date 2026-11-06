// Every settings section (the leaf pages), each owned by a module from modules.ts. Add a module's pages here; nothing else in settings needs to change.

import type { JSX } from 'preact'
import { IconImage, IconFile, IconPencilLine, IconAgents, IconAutomation, IconBolt, IconChat, IconCode, IconGlobe, IconLayers, IconLock, IconSettings, IconTerminal, IconTool } from '../../components/icons'
import { ClaudeCliSettings } from '../agents/settings/ClaudeCli'
import { DefaultsSettings } from '../agents/settings/Defaults'
import { ModelsSettings } from '../agents/settings/Models'
import { BuiltinMcpSettings } from '../agents/settings/BuiltinMcp'
import { MoreAgentsSettings } from '../more-agents/Settings'
import { ChatProviders, ChatDefaults, ChatTitles, ChatFiles, ChatMcp } from '../chat/settings'
import { AutomationsSettings } from '../automations/Settings'
import { WorkflowSettings } from '../workflow/settings'
import { AsrSettings } from '../asr/Settings'
import { ImagegenSettings } from '../imagegen/Settings'
import { IconMic } from '../../components/icons-apps'
import { GeneralSettings, RawFiles } from './General'
import { MODULES, type Icon } from './modules'

export { MODULES }
export interface Section { key: string; module: string; title: string; hint: string; icon: Icon; Component: (p: { title: string }) => JSX.Element }

export const SECTIONS: Section[] = [
  { key: 'chat-providers', module: 'chat', title: 'Model providers', hint: 'OpenAI and Anthropic format APIs and their models', icon: IconGlobe, Component: ChatProviders },
  { key: 'chat-defaults', module: 'chat', title: 'Chat defaults', hint: 'Default model, thinking, system prompt', icon: IconChat, Component: ChatDefaults },
  { key: 'chat-titles', module: 'chat', title: 'Titles', hint: 'Generate chat titles with a model', icon: IconPencilLine, Component: ChatTitles },
  { key: 'chat-files', module: 'chat', title: 'Files and memory', hint: 'Assistant files, attachments and memory', icon: IconFile, Component: ChatFiles },
  { key: 'chat-mcp', module: 'chat', title: 'MCP servers', hint: 'Tools available to chat assistants', icon: IconTool, Component: ChatMcp },
  { key: 'claude-cli', module: 'agents', title: 'Claude Code CLI', hint: 'CLI path, API, concurrency. Shared with Workflow', icon: IconTerminal, Component: ClaudeCliSettings },
  { key: 'agent-defaults', module: 'agents', title: 'Agent defaults', hint: 'Model, permissions, prompts, sleep', icon: IconAgents, Component: DefaultsSettings },
  { key: 'agent-models', module: 'agents', title: 'Models and pricing', hint: 'Custom model IDs and token prices', icon: IconCode, Component: ModelsSettings },
  { key: 'builtin-mcp', module: 'agents', title: 'Built-in tools', hint: 'Conversation history, agent collaboration', icon: IconBolt, Component: BuiltinMcpSettings },
  { key: 'more-agents', module: 'agents', title: 'More Agents', hint: 'External agents: ACP endpoints and Codex', icon: IconGlobe, Component: MoreAgentsSettings },
  { key: 'automations', module: 'automations', title: 'Tasks and webhooks', hint: 'Scripts directory, interpreters, webhook secret', icon: IconAutomation, Component: AutomationsSettings },
  { key: 'workflow', module: 'workflow', title: 'Workflow', hint: 'Run history, plugins, environment, API keys', icon: IconLayers, Component: WorkflowSettings },
  { key: 'asr', module: 'apps', title: 'Speech to text', hint: 'Transcription API, model, language, chunking', icon: IconMic, Component: AsrSettings },
  { key: 'imagegen', module: 'apps', title: 'Image generation', hint: 'Image API, models, reference mode, timeout', icon: IconImage, Component: ImagegenSettings },
  { key: 'general', module: 'general', title: 'Account and API', hint: 'External API key, sign out', icon: IconLock, Component: GeneralSettings },
  { key: 'raw', module: 'general', title: 'Config files', hint: 'Edit the TOML files directly', icon: IconSettings, Component: RawFiles },
]
