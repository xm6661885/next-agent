// Agent detail: header with avatar, quick actions, and the session manager.

import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { agents, agentsVersion, liveSessions, sessionsVersion, toast, toastError } from '../lib/store'
import { back, entryKey, navigate, wide } from '../lib/router'
import { Avatar, Spark } from '../components/crab'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../components/ui'
import { IconCheck, IconChat, IconClose, IconEdit, IconFork, IconImport, IconMoon, IconMore, IconPlus, IconSearch, IconSettings, IconTrash } from '../components/icons'
import { fmtCost, haptic, relTime, shortPath } from '../lib/util'
import type { Agent, Importable, SearchHit, Session } from '../lib/types'

/** Last known conversation list per agent; also seeded by the home page before it opens a chat. */
export const sessionCache = new Map<string, Session[]>()

const PAGE = 5, MORE = 20
/** How many rows each history entry had revealed, so Back keeps the list as long as it was. */
const shownMemory = new Map<string, number>()

export function AgentPage({ agentId }: { agentId: string }) {
  const { scrolled, onScroll, ref: scrollRef } = useScrolled()
  const key = useRef(entryKey()).current
  const [agent, setAgent] = useState<Agent | null>(agents.value?.find((a) => a.id === agentId) || null)
  // Seed from the last visit so coming back shows the list at once instead of a skeleton.
  const [sessions, setSessionsState] = useState<Session[] | null>(sessionCache.get(agentId) || null)
  const setSessions = (v: Session[] | ((l: Session[] | null) => Session[])) => setSessionsState((prev) => {
    const next = typeof v === 'function' ? v(prev) : v
    sessionCache.set(agentId, next)
    return next
  })
  const [query, setQuery] = useState('')
  const [menuFor, setMenuFor] = useState<Session | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [limit, setLimitState] = useState(shownMemory.get(key) || PAGE)
  const setLimit = (n: number) => { shownMemory.set(key, n); setLimitState(n) }
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<Set<string> | null>(null)
  const [deleting, setDeleting] = useState(false)
  const sentinel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.agent(agentId).then(setAgent).catch((e) => { toastError(e); if (e.status === 404) back() })
  }, [agentId, agentsVersion.value])

  const loadSessions = () => api.sessions(agentId).then(setSessions).catch(toastError)
  useEffect(() => { loadSessions() }, [agentId, sessionsVersion.value])

  const live = liveSessions.value
  const merged = (sessions || []).map((s) => {
    const l = live[s.id]
    return l ? { ...s, state: l.state, pending: l.pending, title: l.title ?? s.title, preview: l.preview ?? s.preview, updated_at: l.updated_at ?? s.updated_at } : s
  })
  const q = query.trim()

  // Search titles and transcripts on the server, debounced. Results reuse the live state.
  useEffect(() => {
    if (!q) { setHits(null); setSearching(false); return }
    setSearching(true)
    let stale = false
    const t = setTimeout(() => {
      api.searchSessions(agentId, q).then((r) => { if (!stale) setHits(r) }).catch((e) => { if (!stale) toastError(e) })
        .finally(() => { if (!stale) setSearching(false) })
    }, 250)
    return () => { stale = true; clearTimeout(t) }
  }, [q, agentId, sessionsVersion.value])

  const byId = new Map(merged.map((s) => [s.id, s]))
  const snippets = new Map((hits || []).map((h) => [h.session.id, h.snippet]))
  const results = q ? (hits || []).map((h) => byId.get(h.session.id)).filter((s): s is Session => !!s) : merged
  const shown = q ? results : results.slice(0, limit)
  const hasMore = !q && results.length > limit

  // Once the list has been expanded, keep revealing rows as the end scrolls into view.
  useEffect(() => {
    const el = sentinel.current
    if (!el || !hasMore || limit === PAGE) return
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) setLimit(limit + MORE) }, { rootMargin: '240px' })
    io.observe(el)
    return () => io.disconnect()
  }, [hasMore, limit])

  const selecting = selected !== null
  const toggle = (id: string) => setSelected((cur) => {
    const n = new Set(cur || [])
    n.has(id) ? n.delete(id) : n.add(id)
    return n
  })
  const startSelect = (s: Session) => { setMenuFor(null); setSelected(new Set([s.id])) }
  const allShownSelected = selecting && shown.length > 0 && shown.every((s) => selected!.has(s.id))
  const toggleAll = () => setSelected(allShownSelected ? new Set() : new Set(shown.map((s) => s.id)))
  const removeSelected = async () => {
    const ids = [...(selected || [])]
    if (!ids.length) return
    const ok = await confirmDialog({
      title: `Delete ${ids.length} conversation${ids.length > 1 ? 's' : ''}?`,
      body: 'They will be removed from this list and their uploads deleted. The Claude Code transcripts on disk are kept.',
      confirm: 'Delete', danger: true,
    })
    if (!ok) return
    setDeleting(true)
    try {
      const r = await api.deleteSessions(ids)
      const gone = new Set(r.deleted)
      setSessions((l) => (l || []).filter((x) => !gone.has(x.id)))
      setHits((h) => h && h.filter((x) => !gone.has(x.session.id)))
      setSelected(null)
      toast(`Deleted ${gone.size} conversation${gone.size > 1 ? 's' : ''}`)
    } catch (e) { toastError(e) } finally { setDeleting(false) }
  }
  const totalCost = merged.reduce((n, s) => n + (s.total_cost_usd || 0), 0)
  const anyRunning = merged.some((s) => s.state === 'running')

  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try {
      const s = await api.createSession(agentId)
      navigate({ name: 'chat', agentId, sessionId: s.id })
    } catch (e) { toastError(e) } finally { setCreating(false) }
  }

  const rename = async (s: Session) => {
    setMenuFor(null)
    const t = await promptDialog({ title: 'Rename conversation', value: s.title, confirm: 'Rename' })
    if (t === null || !t.trim()) return
    try { await api.updateSession(s.id, { title: t.trim() }); loadSessions() } catch (e) { toastError(e) }
  }
  const fork = async (s: Session) => {
    setMenuFor(null)
    try {
      const n = await api.forkSession(s.id)
      toast('Forked conversation')
      navigate({ name: 'chat', agentId, sessionId: n.id })
    } catch (e) { toastError(e) }
  }
  const sleep = async (s: Session) => {
    setMenuFor(null)
    try {
      const n = await api.sleepSession(s.id)
      setSessions((l) => (l || []).map((x) => (x.id === n.id ? n : x)))
      toast('Conversation is now idle')
    } catch (e) { toastError(e) }
  }
  const remove = async (s: Session) => {
    setMenuFor(null)
    const ok = await confirmDialog({
      title: 'Delete conversation?',
      body: 'It will be removed from this list and its uploads deleted. The Claude Code transcript on disk is kept.',
      confirm: 'Delete', danger: true,
    })
    if (!ok) return
    try {
      await api.deleteSession(s.id)
      setSessions((l) => (l || []).filter((x) => x.id !== s.id))
      setHits((h) => h && h.filter((x) => x.session.id !== s.id))
    } catch (e) { toastError(e) }
  }

  return (
    <div class="page">
      {selecting ? (
        <TopBar scrolled
          left={<button class="icon-btn" aria-label="Cancel selection" onClick={() => setSelected(null)}><IconClose /></button>}
          right={<button class="btn ghost small" onClick={toggleAll}>{allShownSelected ? 'Select none' : 'Select all'}</button>}>
          <span class="topbar-center">{selected!.size ? `${selected!.size} selected` : 'Select conversations'}</span>
        </TopBar>
      ) : (
        <TopBar scrolled={scrolled}
          left={<BackButton label="Agents" onClick={() => wide.value ? navigate({ name: 'home' }) : back()} />}
          right={<button class="icon-btn" aria-label="Agent settings" onClick={() => navigate({ name: 'agent-settings', agentId })}><IconSettings /></button>}>
          {scrolled && agent && <span class="topbar-center fade-in">{agent.name}</span>}
        </TopBar>
      )}
      <div class={`page-scroll ${selecting ? 'with-select-bar' : ''}`} ref={scrollRef} onScroll={onScroll}>
        <div class="container">
          {agent ? (
            <div class="agent-hero rise">
              <Avatar agent={agent} size={84} busy={anyRunning} />
              <h1 class="serif">{agent.name}</h1>
              <div class="agent-hero-path">{shortPath(agent.cwd)}</div>
              {agent.description && <p class="agent-hero-desc">{agent.description}</p>}
              <div class="agent-hero-tags">
                <span class="mtag">{agent.model || 'Default model'}</span>
                {agent.effort && <span class="mtag">effort {agent.effort}</span>}
                <span class="mtag">{merged.length} chats</span>
                <span class="mtag">{fmtCost(totalCost)}</span>
              </div>
              <div class="agent-hero-actions">
                <button class="btn primary" onClick={newChat} disabled={creating}>
                  {creating ? <span class="spinner" /> : <IconPlus width={18} height={18} />} New chat
                </button>
                <button class="btn" onClick={() => setImportOpen(true)}><IconImport width={18} height={18} /> Import</button>
              </div>
            </div>
          ) : (
            <div class="agent-hero"><div class="skeleton" style={{ width: '84px', height: '84px', borderRadius: '26px' }} /></div>
          )}

          {merged.length > 0 && (
            <div class="search-box rise" style={{ '--i': 2 }}>
              <IconSearch />
              <input type="search" placeholder="Search conversations" aria-label="Search conversations" value={query}
                onInput={(e) => setQuery((e.target as HTMLInputElement).value)} />
              {searching ? <span class="spinner" /> : query && (
                <button class="search-clear" aria-label="Clear search" onClick={() => setQuery('')}><IconClose /></button>
              )}
            </div>
          )}

          <div class="group-title">{q ? (hits ? `${results.length} result${results.length === 1 ? '' : 's'}` : 'Searching') : 'Conversations'}</div>
          {sessions === null || (q && hits === null) ? (
            <div class="group">{[0, 1, 2].map((i) => <div key={i} class="row"><div class="skeleton" style={{ height: '36px', flex: 1 }} /></div>)}</div>
          ) : shown.length === 0 ? (
            <div class="empty rise" style={{ padding: '28px 20px' }}>
              <IconChat width={30} height={30} style={{ color: 'var(--text-3)' }} />
              <p style={{ margin: '8px 0 0' }}>{q ? 'Nothing matches.' : 'No conversations yet. Start one above.'}</p>
            </div>
          ) : (
            <div class="group">
              {shown.map((s, i) => (
                <SessionRow key={s.id} s={s} i={i} snippet={snippets.get(s.id)}
                  selected={selecting ? selected!.has(s.id) : undefined}
                  onOpen={() => selecting ? toggle(s.id) : navigate({ name: 'chat', agentId, sessionId: s.id })}
                  onMore={() => selecting ? toggle(s.id) : setMenuFor(s)} />
              ))}
            </div>
          )}
          {hasMore && (
            <div ref={sentinel} class="list-more">
              {limit === PAGE && (
                <button class="btn ghost small" onClick={() => setLimit(limit + MORE)}>
                  Show older ({results.length - limit})
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <Sheet open={!!menuFor} onClose={() => setMenuFor(null)} title={menuFor?.title || 'Conversation'}>
        {menuFor && (
          <div class="menu">
            <button onClick={() => rename(menuFor)}><IconEdit /> Rename</button>
            <button onClick={() => fork(menuFor)}><IconFork /> Fork into a new chat</button>
            {menuFor.state !== 'offline' && <button onClick={() => sleep(menuFor)}><IconMoon /> Put to sleep (idle)</button>}
            <button onClick={() => startSelect(menuFor)}><IconCheck /> Select multiple</button>
            <button class="danger" onClick={() => remove(menuFor)}><IconTrash /> Delete</button>
          </div>
        )}
      </Sheet>

      {selecting && (
        <div class="select-bar">
          <button class="btn danger" disabled={!selected!.size || deleting} onClick={removeSelected}>
            {deleting ? <span class="spinner" /> : <IconTrash width={18} height={18} />}
            Delete{selected!.size ? ` ${selected!.size}` : ''}
          </button>
        </div>
      )}

      <ImportSheet open={importOpen} agentId={agentId} onClose={() => setImportOpen(false)} onDone={loadSessions} />
    </div>
  )
}

function SessionRow({ s, i, snippet, selected, onOpen, onMore }: {
  s: Session; i: number; snippet?: string; selected?: boolean; onOpen: () => void; onMore: () => void
}) {
  const press = useRef<{ timer?: number; fired: boolean }>({ fired: false })
  const busy = s.state === 'running' || s.state === 'interrupting'
  const selecting = selected !== undefined
  // A long press opens the menu; swallow the click iOS still sends when the finger lifts.
  const startPress = () => {
    press.current.fired = false
    press.current.timer = window.setTimeout(() => { press.current.fired = true; haptic(); onMore() }, 550)
  }
  const cancelPress = () => clearTimeout(press.current.timer)
  const click = () => {
    if (press.current.fired) { press.current.fired = false; return }
    onOpen()
  }
  const hint = s.pending > 0 ? 'Waiting for your answer' : (snippet || s.preview || (s.turns ? `${s.turns} turns` : 'Empty'))
  return (
    <div class={`session-row rise ${selected ? 'selected' : ''}`} style={{ '--i': Math.min(i, 12) }}>
      <button class="row" onClick={click} aria-pressed={selecting ? selected : undefined}
        onContextMenu={(e) => { e.preventDefault(); onMore() }}
        onTouchStart={startPress} onTouchEnd={cancelPress} onTouchMove={cancelPress} onTouchCancel={cancelPress}>
        <span class="session-state">
          {selecting ? <span class={`check ${selected ? 'on' : ''}`} />
            : s.pending > 0 ? <span class="dot waiting" /> : busy ? <Spark size={16} /> : <span class={`dot ${s.state !== 'offline' ? 'live' : ''}`} />}
        </span>
        <span class="label">
          <span class="session-title">{s.title || 'New conversation'}</span>
          <span class="hint">{hint}</span>
        </span>
        <span class="session-meta">
          <span>{relTime(s.updated_at)}</span>
          {s.fork_of && <IconFork width={13} height={13} />}
        </span>
      </button>
      {!selecting && <button class="icon-btn session-more" aria-label="More" onClick={onMore}><IconMore /></button>}
    </div>
  )
}

function ImportSheet({ open, agentId, onClose, onDone }: { open: boolean; agentId: string; onClose: () => void; onDone: () => void }) {
  const [list, setList] = useState<Importable[] | null>(null)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setList(null)
    setSel(new Set())
    api.importable(agentId).then(setList).catch((e) => { toastError(e); setList([]) })
  }, [open])

  const toggle = (id: string) => {
    const n = new Set(sel)
    n.has(id) ? n.delete(id) : n.add(id)
    setSel(n)
  }
  const doImport = async () => {
    setBusy(true)
    try {
      await api.importSessions(agentId, [...sel])
      toast(`Imported ${sel.size} conversation${sel.size > 1 ? 's' : ''}`)
      onDone()
      onClose()
    } catch (e) { toastError(e) } finally { setBusy(false) }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Import from Claude Code"
      actions={<button class="btn primary small" disabled={!sel.size || busy} onClick={doImport}>Import{sel.size ? ` ${sel.size}` : ''}</button>}>
      <p class="sheet-note">Conversations started with the Claude Code CLI in this agent's folder. Importing lets you continue them here.</p>
      {list === null ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '30px' }}><Spark size={26} /></div>
      ) : list.length === 0 ? (
        <div class="empty" style={{ padding: '24px' }}>Nothing new to import.</div>
      ) : (
        <div class="group">
          {list.map((it) => (
            <button key={it.sdk_session_id} class="row" onClick={() => toggle(it.sdk_session_id)}>
              <span class={`check ${sel.has(it.sdk_session_id) ? 'on' : ''}`} />
              <span class="label">
                <span class="session-title">{it.summary || it.first_prompt || it.sdk_session_id}</span>
                <span class="hint">{relTime(it.last_modified)}{it.git_branch ? ` on ${it.git_branch}` : ''}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </Sheet>
  )
}
