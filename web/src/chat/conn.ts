// One live connection per open chat. Applies server events to a reactive item list and
// resumes from the last seq after network drops or iOS backgrounding.

import { signal } from '@preact/signals'
import { authed, wsUrl } from '../lib/store'
import type { Activity, InitInfo, Item, PermissionRequest, Session, SessionState, TaskInfo } from '../lib/types'

export type ConnStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export class ChatConn {
  items = signal<Item[]>([])
  hasMore = signal(false)
  session = signal<Session | null>(null)
  state = signal<SessionState>('offline')
  queuePos = signal(0)
  perms = signal<PermissionRequest[]>([])
  init = signal<InitInfo | null>(null)
  tasks = signal<TaskInfo[]>([])
  conn = signal<ConnStatus>('connecting')
  loaded = signal(false)
  activity = signal<Activity | null>(null)

  private ws: WebSocket | null = null
  private seq = 0
  private retry = 0
  private timer: number | undefined
  private closed = false
  private index = new Map<string, number>()
  private outbox: any[] = []
  private pingTimer: number | undefined
  private lastMsgAt = 0
  private reqSeq = 0
  private waiters = new Map<string, (err: string | null) => void>()
  onError?: (msg: string) => void

  constructor(public sid: string) {
    this.connect()
    document.addEventListener('visibilitychange', this.wake)
    window.addEventListener('online', this.wake)
    window.addEventListener('pageshow', this.wake)
  }

  dispose() {
    this.closed = true
    clearTimeout(this.timer)
    clearInterval(this.pingTimer)
    document.removeEventListener('visibilitychange', this.wake)
    window.removeEventListener('online', this.wake)
    window.removeEventListener('pageshow', this.wake)
    this.ws?.close()
  }

  private wake = () => {
    if (this.closed || document.visibilityState !== 'visible') return
    // iOS can leave a dead socket in OPEN state after a long suspend; probe it.
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      if (Date.now() - this.lastMsgAt > 25000) this.forceReconnect()
      else this.raw({ type: 'ping' })
      return
    }
    this.retry = 0
    this.connect()
  }

  private forceReconnect() {
    const old = this.ws
    this.ws = null
    try { old?.close() } catch { /* ignore */ }
    this.retry = 0
    this.connect()
  }

  private connect() {
    if (this.closed) return
    if (this.ws && this.ws.readyState <= 1) return
    clearTimeout(this.timer)
    this.conn.value = this.loaded.value ? 'reconnecting' : 'connecting'
    const ws = new WebSocket(wsUrl(`/ws/sessions/${encodeURIComponent(this.sid)}`))
    this.ws = ws
    ws.onopen = () => {
      if (this.ws !== ws) return
      this.lastMsgAt = Date.now()
      ws.send(JSON.stringify({ type: 'resume', seq: this.seq || null }))
      clearInterval(this.pingTimer)
      this.pingTimer = window.setInterval(() => {
        if (Date.now() - this.lastMsgAt > 45000) this.forceReconnect()
        else this.raw({ type: 'ping' })
      }, 20000)
    }
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return
      this.lastMsgAt = Date.now()
      let msg: any
      try { msg = JSON.parse(ev.data) } catch { return }
      this.handle(msg)
    }
    ws.onclose = (ev) => {
      if (this.ws !== ws) return
      this.ws = null
      clearInterval(this.pingTimer)
      if (ev.code === 4401) { authed.value = false; this.conn.value = 'closed'; return }
      if (ev.code === 4404) { this.conn.value = 'closed'; this.onError?.('This conversation no longer exists.'); return }
      if (this.closed) return
      this.conn.value = 'reconnecting'
      this.retry = Math.min(this.retry + 1, 6)
      this.timer = window.setTimeout(() => this.connect(), Math.min(400 * 2 ** this.retry, 12000))
    }
  }

  private raw(m: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(m))
      return true
    }
    return false
  }

  /** Send a command; queued until the socket is open. Resolves with an error message or null. */
  send(m: Record<string, any>): Promise<string | null> {
    const req_id = `r${++this.reqSeq}`
    const msg = { ...m, req_id }
    return new Promise((resolve) => {
      this.waiters.set(req_id, resolve)
      // Commands without a reply resolve after a short grace period.
      setTimeout(() => { if (this.waiters.delete(req_id)) resolve(null) }, 4000)
      if (this.conn.value === 'open' && this.raw(msg)) return
      this.outbox.push(msg)
    })
  }

  private flush() {
    const q = this.outbox
    this.outbox = []
    for (const m of q) if (!this.raw(m)) this.outbox.push(m)
  }

  // ---------- event handling ----------

  private reindex(list: Item[]) {
    this.index.clear()
    list.forEach((it, i) => this.index.set(it.id, i))
  }

  private handle(msg: any) {
    if (typeof msg.seq === 'number') this.seq = Math.max(this.seq, msg.seq)
    switch (msg.type) {
      case 'snapshot': {
        // Keep optimistic local user items the server has not seen yet.
        const local = this.items.value.filter((it) => it.kind === 'user' && it.pending && (it as any)._local)
        const items: Item[] = msg.items || []
        const known = new Set(items.filter((i: any) => i.client_id).map((i: any) => i.client_id))
        const merged = [...items, ...local.filter((l: any) => !known.has(l.client_id))]
        this.reindex(merged)
        this.items.value = merged
        this.hasMore.value = !!msg.has_more
        if (msg.session) this.session.value = msg.session
        this.state.value = msg.state || 'offline'
        this.queuePos.value = msg.queue_position || 0
        this.perms.value = msg.permissions || []
        this.init.value = msg.init || null
        this.tasks.value = msg.tasks || []
        this.activity.value = msg.activity || null
        this.loaded.value = true
        this.conn.value = 'open'
        this.retry = 0
        this.flush()
        break
      }
      case 'item': this.upsert(msg.item); break
      case 'patch': this.patch(msg.id, msg.patch); break
      case 'delta': this.delta(msg.id, msg.field, msg.text); break
      case 'state':
        this.state.value = msg.state
        if (msg.state !== 'running' && msg.state !== 'interrupting') this.activity.value = null
        this.queuePos.value = msg.queue_position || 0
        if (this.conn.value !== 'open') { this.conn.value = 'open'; this.retry = 0; this.flush() }
        break
      case 'permission':
        this.perms.value = [...this.perms.value.filter((p) => p.id !== msg.request.id), msg.request]
        break
      case 'permission_resolved':
        this.perms.value = this.perms.value.filter((p) => p.id !== msg.id)
        break
      case 'session': this.session.value = msg.session; break
      case 'init': this.init.value = { ...(this.init.value || {}), ...msg, type: undefined, seq: undefined } as InitInfo; break
      case 'tasks': this.tasks.value = msg.tasks || []; break
      case 'activity': this.activity.value = msg.activity || null; break
      case 'truncate': this.truncate(msg.uuid); break
      case 'error': {
        const w = msg.req_id && this.waiters.get(msg.req_id)
        if (w) { this.waiters.delete(msg.req_id); w(msg.message) }
        else this.onError?.(msg.message)
        break
      }
      case 'pong':
        if (this.conn.value !== 'open' && this.loaded.value) { this.conn.value = 'open'; this.flush() }
        break
    }
    // Replays after resume arrive as ordinary events; the first one proves the socket is live.
    if (msg.type !== 'snapshot' && msg.type !== 'error' && this.loaded.value && this.conn.value !== 'open') {
      this.conn.value = 'open'
      this.retry = 0
      this.flush()
    }
  }

  private upsert(item: Item) {
    const list = this.items.value.slice()
    // Replace an optimistic local bubble with the server copy.
    if (item.kind === 'user' && (item as any).client_id) {
      const li = list.findIndex((x) => x.kind === 'user' && (x as any).client_id === (item as any).client_id && x.id !== item.id)
      if (li >= 0) list.splice(li, 1)
    }
    const i = list.findIndex((x) => x.id === item.id)
    if (i >= 0) list[i] = item
    else list.push(item)
    this.reindex(list)
    this.items.value = list
  }

  private patch(id: string, p: Record<string, any>) {
    const i = this.index.get(id)
    if (i === undefined) return
    const list = this.items.value.slice()
    list[i] = { ...list[i], ...p } as Item
    this.items.value = list
  }

  private delta(id: string, field: string, text: string) {
    const i = this.index.get(id)
    if (i === undefined) return
    const list = this.items.value.slice()
    const cur = list[i] as any
    list[i] = { ...cur, [field]: (cur[field] || '') + text }
    this.items.value = list
  }

  /** Drop a top-level user message and everything after it (edit and resend). */
  private truncate(uuid: string) {
    const i = this.items.value.findIndex((x) => x.kind === 'user' && !x.parent_tool_use_id && x.uuid === uuid)
    if (i < 0) return
    const list = this.items.value.slice(0, i)
    this.reindex(list)
    this.items.value = list
  }

  /** Optimistic bubble shown until the server echoes the item. */
  addLocalUser(client_id: string, text: string, attachments: any[]) {
    const item: any = { id: `local-${client_id}`, kind: 'user', text, attachments, uuid: null, pending: true, client_id, _local: true, ts: new Date().toISOString() }
    this.upsert(item)
  }

  removeLocal(client_id: string) {
    const list = this.items.value.filter((x) => !(x.kind === 'user' && (x as any)._local && (x as any).client_id === client_id))
    this.reindex(list)
    this.items.value = list
  }

  prependHistory(older: Item[], hasMore: boolean) {
    const ids = new Set(this.items.value.map((i) => i.id))
    const list = [...older.filter((i) => !ids.has(i.id)), ...this.items.value]
    this.reindex(list)
    this.items.value = list
    this.hasMore.value = hasMore
  }
}
