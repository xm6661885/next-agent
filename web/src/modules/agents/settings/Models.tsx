// Settings > Agents > Models and pricing: shared custom model IDs (saved at once) and per-model token prices.

import { useEffect, useState } from 'preact/hooks'
import { toast, toastError } from '../../../lib/store'
import { saveCustomModels } from '../../../components/ModelPicker'
import { IconPlus, IconTrash } from '../../../components/icons'
import { SettingsFrame, useConfigForm } from '../../settings/Frame'
import type { ConfigForm, Price } from '../../../lib/types'

const PRICE_FIELDS: [keyof Price, string][] = [['input', 'Input'], ['output', 'Output'], ['cache_write', 'Cache write'], ['cache_read', 'Cache read']]
interface PriceRow { key: string; model: string; price: Record<keyof Price, string> }
const toRows = (p: ConfigForm['pricing']): PriceRow[] => Object.entries(p).map(([model, v], i) => ({
  key: `${i}-${model}`, model, price: Object.fromEntries(PRICE_FIELDS.map(([k]) => [k, String(v[k] ?? 0)])) as Record<keyof Price, string>,
}))

export function ModelsSettings({ title }: { title: string }) {
  const { form, setForm, saving, save } = useConfigForm()
  const [rows, setRows] = useState<PriceRow[]>([])
  const [orig, setOrig] = useState('')
  const [newModel, setNewModel] = useState('')
  useEffect(() => { if (form) { const r = toRows(form.pricing); setRows(r); setOrig(JSON.stringify(r.map((x) => [x.model, x.price]))) } }, [form?.pricing])
  const dirty = JSON.stringify(rows.map((x) => [x.model, x.price])) !== orig

  const setModels = async (list: string[]) => {
    try {
      const saved = await saveCustomModels(list)
      setForm((f) => f && { ...f, defaults: { ...f.defaults, custom_models: saved } })
    } catch (e) { toastError(e) }
  }
  const addModel = () => {
    const m = newModel.trim()
    if (!m || !form) return
    if (!form.defaults.custom_models.includes(m)) setModels([...form.defaults.custom_models, m])
    setNewModel('')
  }
  const onSave = () => {
    const pricing: ConfigForm['pricing'] = {}
    for (const r of rows) {
      const m = r.model.trim()
      if (!m) continue
      if (pricing[m]) return toast(`Pricing for ${m} is listed twice`, 'error')
      const p = {} as Price
      for (const [k, label] of PRICE_FIELDS) {
        const n = Number(r.price[k] || 0)
        if (!Number.isFinite(n) || n < 0) return toast(`${label} price for ${m} must be a number of at least 0`, 'error')
        p[k] = n
      }
      pricing[m] = p
    }
    save({ pricing })
  }
  const d = form?.defaults
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={onSave}>
      {!d ? <div class="skeleton" style={{ height: '240px', borderRadius: '20px' }} /> : (
        <>
          <div class="group-title" style={{ marginTop: 0 }}>Custom models</div>
          <div class="group">
            <div class="field">
              <span class="fhint" style={{ marginTop: 0 }}>Extra Claude model IDs shown in every agent model picker. Saved right away.</span>
              {d.custom_models.length > 0 && (
                <div class="model-chips" style={{ marginTop: '10px' }}>
                  {d.custom_models.map((m) => (
                    <span class="chip removable" key={m}><span class="mono">{m}</span>
                      <button type="button" aria-label={`Remove ${m}`} onClick={() => setModels(d.custom_models.filter((x) => x !== m))}><IconTrash width={14} height={14} /></button>
                    </span>
                  ))}
                </div>
              )}
              <form class="model-custom" onSubmit={(e) => { e.preventDefault(); addModel() }}>
                <input class="input mono" value={newModel} placeholder="claude-opus-5-5[1m]" autocapitalize="off" spellcheck={false}
                  onInput={(e) => setNewModel((e.target as HTMLInputElement).value)} />
                <button type="submit" class="btn small" disabled={!newModel.trim()}><IconPlus width={16} height={16} /> Add</button>
              </form>
            </div>
          </div>
          <div class="group-title">Pricing</div>
          <div class="group">
            <div class="field">
              <span class="fhint" style={{ marginTop: 0 }}>USD per million tokens. Models listed here use these prices for the cost shown in chats;
                other models keep the cost reported by Claude Code. Match by model ID, with or without a suffix like [1m].</span>
              {rows.map((r) => (
                <div class="price-row" key={r.key}>
                  <div class="price-head">
                    <input class="input mono" value={r.model} placeholder="Model ID" autocapitalize="off" spellcheck={false}
                      onInput={(e) => setRows(rows.map((x) => x.key === r.key ? { ...x, model: (e.target as HTMLInputElement).value } : x))} />
                    <button type="button" class="icon-btn" aria-label="Remove price" onClick={() => setRows(rows.filter((x) => x.key !== r.key))}><IconTrash width={18} height={18} /></button>
                  </div>
                  <div class="price-grid">
                    {PRICE_FIELDS.map(([k, label]) => (
                      <label key={k}><span>{label}</span>
                        <input class="input" type="number" inputMode="decimal" min={0} step="any" value={r.price[k]}
                          onInput={(e) => setRows(rows.map((x) => x.key === r.key ? { ...x, price: { ...x.price, [k]: (e.target as HTMLInputElement).value } } : x))} />
                      </label>
                    ))}
                  </div>
                </div>
              ))}
              <button type="button" class="btn small" style={{ marginTop: '12px' }}
                onClick={() => setRows([...rows, { key: `n${Date.now()}`, model: '', price: { input: '', output: '', cache_write: '', cache_read: '' } }])}>
                <IconPlus width={16} height={16} /> Add model price
              </button>
            </div>
          </div>
        </>
      )}
    </SettingsFrame>
  )
}
