// Settings > Agents > Agent defaults: the global values agents follow unless they override a section.

import { SettingsFrame, useConfigForm } from '../../settings/Frame'
import { Switch } from '../../../components/ui'
import { FileOutputFields, GenUIFields, IdleFields, ModelFields, OverrideCard, PermissionFields, SystemPromptFields } from '../../../components/SettingGroups'
import type { ConfigForm } from '../../../lib/types'

export function DefaultsSettings({ title }: { title: string }) {
  const { form, setForm, dirty, saving, save } = useConfigForm()
  const set = <K extends keyof ConfigForm['defaults']>(k: K, v: ConfigForm['defaults'][K]) =>
    setForm((f) => f && { ...f, defaults: { ...f.defaults, [k]: v } })
  const d = form?.defaults
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => form && save({ defaults: { ...form.defaults, custom_models: undefined } as any })}>
      {!form || !d ? <div class="skeleton" style={{ height: '320px', borderRadius: '20px' }} /> : (
        <>
          <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Agents follow these unless they turn on Override global for a section.</span>
          <OverrideCard title="Model"><ModelFields v={d} set={set} /></OverrideCard>
          <OverrideCard title="Permissions"><PermissionFields v={d} set={set} /></OverrideCard>
          <OverrideCard title="System prompt"><SystemPromptFields v={d} set={set} /></OverrideCard>
          <OverrideCard title="Sleep"><IdleFields v={d} set={set} /></OverrideCard>
          <OverrideCard title="Files from Claude"><FileOutputFields v={d} set={set} builtin={form.default_file_output_prompt} /></OverrideCard>
          <OverrideCard title="Interactive UI"><GenUIFields v={d} set={set} builtin={form.default_genui_prompt} widgetBuiltin={(k) => form.default_genui_widgets?.[k] || ''} /></OverrideCard>
          <div class="group-title">Chat display</div>
          <div class="group">
            <div class="row">
              <span class="label">Artifacts<span class="hint">A panel with every file and code block of the conversation, and long code shown as tappable cards.</span></span>
              <Switch on={d.artifacts ?? true} onChange={(v) => set('artifacts', v)} label="Artifacts" />
            </div>
          </div>
        </>
      )}
    </SettingsFrame>
  )
}
