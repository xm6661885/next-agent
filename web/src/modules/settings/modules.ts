// The top level of Settings: one entry per module, in display order. To give another module a settings page, insert it here
// (Automations after Agents, Apps after Workflow) and add its sections to SECTIONS in registry.tsx with the same `module` key.
// Kept apart from registry.tsx so the settings frame can read module titles without importing every section component.

import type { JSX } from 'preact'
import { IconAgents, IconAutomation, IconChat, IconLayers, IconSettings } from '../../components/icons'
import { IconSparkle } from '../../components/icons-apps'

export type Icon = (p: JSX.SVGAttributes<SVGSVGElement>) => JSX.Element
export interface SettingsModule { key: string; title: string; hint: string; icon: Icon; /** Section key: the module has a single section, so its row opens that section directly. */ direct?: string }

export const MODULES: SettingsModule[] = [
  { key: 'chat', title: 'Chat', hint: 'Model providers, defaults, titles, files and memory, MCP servers', icon: IconChat },
  { key: 'agents', title: 'Agents', hint: 'Claude Code CLI, defaults, models, built-in tools, ACP', icon: IconAgents },
  { key: 'automations', title: 'Automations', hint: 'Scripts directory, interpreters, webhook secret', icon: IconAutomation, direct: 'automations' },
  { key: 'workflow', title: 'Workflow', hint: 'Run history, plugins, environment', icon: IconLayers, direct: 'workflow' },
  { key: 'apps', title: 'Apps', hint: 'Speech to text and image generation', icon: IconSparkle },
  { key: 'general', title: 'General', hint: 'Account and API, config files', icon: IconSettings },
]

export const moduleOf = (key: string) => MODULES.find((m) => m.key === key)
