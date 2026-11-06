// The top level of Settings: one entry per module, in display order. To give another module a settings page, insert it here
// (Automations after Agents, Apps after Workflow) and add its sections to SECTIONS in registry.tsx with the same `module` key.
// Kept apart from registry.tsx so the settings frame can read module titles without importing every section component.

import type { JSX } from 'preact'
import { IconAgents, IconChat, IconLayers, IconSettings } from '../../components/icons'

export type Icon = (p: JSX.SVGAttributes<SVGSVGElement>) => JSX.Element
export interface SettingsModule { key: string; title: string; hint: string; icon: Icon }

export const MODULES: SettingsModule[] = [
  { key: 'chat', title: 'Chat', hint: 'Model providers, defaults, titles, files and memory, MCP servers', icon: IconChat },
  { key: 'agents', title: 'Agents', hint: 'Claude Code CLI, defaults, models, built-in tools, ACP', icon: IconAgents },
  { key: 'workflow', title: 'Workflow', hint: 'Run history, plugins, environment', icon: IconLayers },
  { key: 'general', title: 'General', hint: 'Account and API, config files', icon: IconSettings },
]

export const moduleOf = (key: string) => MODULES.find((m) => m.key === key)
