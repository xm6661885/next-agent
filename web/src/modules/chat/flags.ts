// Effective Files / Memory switches for one assistant: global [files]/[memory] AND the assistant's own switch.

import { useEffect, useState } from 'preact/hooks'
import { chatVersion } from '../../lib/store'
import { chatApi, filesOn, memoryOn, type Assistant, type ChatConfig } from './api'

export function useAssistantFlags(assistantId: string) {
  const [state, setState] = useState<{ a: Assistant | null; cfg: ChatConfig | null }>({ a: null, cfg: null })
  useEffect(() => {
    let live = true
    Promise.all([chatApi.assistant(assistantId), chatApi.config()])
      .then(([a, cfg]) => { if (live) setState({ a, cfg }) }).catch(() => {})
    return () => { live = false }
  }, [assistantId, chatVersion.value])
  return { assistant: state.a, loaded: !!state.a && !!state.cfg, files: filesOn(state.cfg, state.a), memory: memoryOn(state.cfg, state.a) }
}
