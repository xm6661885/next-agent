// Setting sections shared by global Settings and Agent settings. On an agent each section sits behind one
// "Override global" switch; while it is off the controls are disabled and show the global values.

import type { ComponentChildren } from 'preact'
import { useState } from 'preact/hooks'
import { Segmented, Switch } from './ui'
import { EffortSlider } from './EffortSlider'
import { ModelPicker } from './ModelPicker'
import { MODE_LABELS } from '../lib/util'
import { meta } from '../lib/store'
import type { Effective } from '../lib/types'

export type GroupValues = Effective
type Set = (k: keyof GroupValues, v: any) => void

interface SectionProps { v: GroupValues; set: Set; disabled?: boolean }

/** Group card with an optional override switch (agent pages only). */
export function OverrideCard({ title, override, onOverride, children }: {
  title: string; override?: boolean; onOverride?: (on: boolean) => void; children: ComponentChildren
}) {
  const agentMode = onOverride !== undefined
  return (
    <>
      <div class="group-title">{title}</div>
      <div class={`group ${agentMode && !override ? 'inherited' : ''}`}>
        {agentMode && (
          <div class="row">
            <span class="label">Override global<span class="hint">{override ? 'This agent uses its own values below.' : 'Following Settings. Turn on to customize.'}</span></span>
            <Switch on={!!override} onChange={onOverride!} label={`Override global ${title}`} />
          </div>
        )}
        <fieldset class="group-fields" disabled={agentMode && !override}>{children}</fieldset>
      </div>
    </>
  )
}

export function ModelFields({ v, set }: SectionProps) {
  return (
    <>
      <div class="field"><span class="flabel">Model</span>
        <ModelPicker value={v.model} onChange={(m) => set('model', m)} />
      </div>
      <div class="field"><span class="flabel">Effort</span>
        <EffortSlider value={v.effort} onChange={(x) => set('effort', x)} />
      </div>
      <div class="field"><span class="flabel">Fallback model</span>
        <ModelPicker value={v.fallback_model || ''} onChange={(m) => set('fallback_model', m)} noneLabel="None" />
        <span class="fhint">Used when the main model is overloaded.</span>
      </div>
      <div class="field"><span class="flabel">Extended thinking</span>
        <Segmented value={v.thinking} onChange={(x) => set('thinking', x)}
          options={[{ value: 'adaptive', label: 'Adaptive' }, { value: 'enabled', label: 'Budget' }, { value: 'disabled', label: 'Off' }]} />
        {v.thinking === 'enabled' && (
          <input class="input" style={{ marginTop: '10px' }} type="number" min={1024} step={1024} value={v.thinking_budget || 8000}
            onInput={(e) => set('thinking_budget', Number((e.target as HTMLInputElement).value))} />
        )}
      </div>
    </>
  )
}

export function PermissionFields({ v, set }: SectionProps) {
  const modes = meta.value?.permission_modes || Object.keys(MODE_LABELS)
  return (
    <div class="field"><span class="flabel">Permission mode</span>
      <select class="select" value={v.permission_mode} onChange={(e) => set('permission_mode', (e.target as HTMLSelectElement).value)}>
        {modes.map((m) => <option value={m}>{MODE_LABELS[m] || m}</option>)}
      </select>
      <span class="fhint">Ask before acting shows approval cards in the chat. You can switch modes inside any conversation.</span>
    </div>
  )
}

export function SystemPromptFields({ v, set }: SectionProps) {
  return (
    <div class="field"><span class="flabel">System prompt</span>
      <Segmented value={v.system_prompt_mode || 'preset'} onChange={(x) => set('system_prompt_mode', x as GroupValues['system_prompt_mode'])}
        options={[{ value: 'preset', label: 'Claude Code + append' }, { value: 'custom', label: 'Replace' }]} />
      <textarea class="textarea" style={{ marginTop: '10px' }} rows={4} value={v.system_prompt}
        placeholder={v.system_prompt_mode === 'custom' ? 'Full system prompt' : 'Extra instructions appended to the Claude Code prompt'}
        onInput={(e) => set('system_prompt', (e.target as HTMLTextAreaElement).value)} />
    </div>
  )
}

/** Switch plus an injected prompt that is edited only after tapping Edit. */
function PromptFields({ on, onToggle, label, hint, prompt, onPrompt, builtin, disabled }: {
  on: boolean; onToggle: (v: boolean) => void; label: string; hint: string
  prompt: string; onPrompt: (v: string) => void; builtin: string; disabled?: boolean
}) {
  const [editing, setEditing] = useState(false)
  return (
    <>
      <div class="row">
        <span class="label">{label}<span class="hint">{hint}</span></span>
        <Switch on={on} onChange={onToggle} label={label} disabled={disabled} />
      </div>
      {on && (
        <div class="field"><span class="flabel">Prompt</span>
          {editing && !disabled ? (
            <>
              <textarea class="textarea mono" rows={9} spellcheck={false} value={prompt || builtin}
                onInput={(e) => onPrompt((e.target as HTMLTextAreaElement).value)} />
              <div class="inline-actions">
                <button type="button" class="btn small ghost" onClick={() => onPrompt('')}>Reset to built-in</button>
                <button type="button" class="btn small" onClick={() => setEditing(false)}>Done</button>
              </div>
            </>
          ) : (
            <>
              <div class="prompt-preview">{prompt || builtin}</div>
              <div class="inline-actions">
                <span class="fhint" style={{ flex: 1, margin: 0 }}>{prompt && prompt !== builtin ? 'Custom prompt.' : 'Built-in prompt.'}</span>
                <button type="button" class="btn small" onClick={() => setEditing(true)}>Edit</button>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}

export function FileOutputFields({ v, set, disabled, builtin }: SectionProps & { builtin: string }) {
  return <PromptFields on={v.file_output} onToggle={(x) => set('file_output', x)} label="Share files in chat" disabled={disabled}
    hint="Teaches Claude to link images and files with Markdown, so they show up as previews and downloads."
    prompt={v.file_output_prompt} onPrompt={(x) => set('file_output_prompt', x)} builtin={builtin} />
}

export function GenUIFields({ v, set, disabled, builtin }: SectionProps & { builtin: string }) {
  return <PromptFields on={v.genui} onToggle={(x) => set('genui', x)} label="Generative UI in replies" disabled={disabled}
    hint="Claude can answer with live SVG diagrams, buttons, forms, sliders and charts."
    prompt={v.genui_prompt} onPrompt={(x) => set('genui_prompt', x)} builtin={builtin} />
}

export function IdleFields({ v, set }: SectionProps) {
  const mode = v.idle_mode || 'timer'
  return (
    <>
      <div class="field"><span class="flabel">Idle CLI processes</span>
        <Segmented value={mode} onChange={(x) => set('idle_mode', x as GroupValues['idle_mode'])}
          options={[{ value: 'timer', label: 'Timer' }, { value: 'adaptive', label: 'Adaptive' }, { value: 'never', label: 'Never sleep' }]} />
        <span class="fhint">{mode === 'adaptive'
          ? 'Keeps a CLI warm for the conversation you open, so the first message starts right away. Older idle conversations go to sleep.'
          : mode === 'never' ? 'Idle CLIs stay connected until you put them to sleep.'
          : 'Idle CLIs sleep after a set time. The conversation resumes on the next message.'} Sessions with running background tasks or scheduled jobs stay awake.</span>
      </div>
      {mode === 'timer' && (
        <label class="field"><span class="flabel">Sleep idle CLI after (minutes)</span>
          <input class="input" type="number" min={0} step={1} value={v.idle_timeout_min}
            onInput={(e) => set('idle_timeout_min', Number((e.target as HTMLInputElement).value))} />
          <span class="fhint">0 never sleeps.</span>
        </label>
      )}
      {mode === 'adaptive' && (
        <label class="field"><span class="flabel">Live CLIs kept warm</span>
          <input class="input" type="number" min={1} step={1} value={v.adaptive_keep ?? 1}
            onInput={(e) => set('adaptive_keep', Math.max(1, Number((e.target as HTMLInputElement).value)))} />
        </label>
      )}
    </>
  )
}
