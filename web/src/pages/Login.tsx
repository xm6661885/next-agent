import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { authed } from '../lib/store'
import { Crab } from '../components/crab'
import { IconLock } from '../components/icons'

export function Login() {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [shake, setShake] = useState(0)
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => { setTimeout(() => ref.current?.focus(), 400) }, [])

  const submit = async (e: Event) => {
    e.preventDefault()
    if (!pw || busy) return
    setBusy(true)
    setErr('')
    try {
      await api.login(pw)
      authed.value = true
    } catch (ex: any) {
      setErr(ex.status === 429 ? 'Too many attempts. Try again in a few minutes.' : 'That password did not work.')
      setShake((s) => s + 1)
      setPw('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div class="page login enter-fade">
      <div class="login-blob b1" />
      <div class="login-blob b2" />
      <form class="login-card" onSubmit={submit}>
        <div class="login-crab crab-wave crab-walk">
          <Crab />
        </div>
        <h1 class="login-title">Welcome back</h1>
        <p class="login-sub">Your agents are waiting for you.</p>
        <div class={`login-field ${err ? 'err' : ''}`} key={shake} style={shake ? { animation: 'shake 0.45s' } : {}}>
          <IconLock />
          <input ref={ref} type="password" inputMode="numeric" autocomplete="current-password" placeholder="Password"
            value={pw} onInput={(e) => setPw((e.target as HTMLInputElement).value)} aria-label="Password" />
        </div>
        <div class="login-err" aria-live="polite">{err}</div>
        <button class="btn primary block login-btn" type="submit" disabled={!pw || busy}>
          {busy ? <span class="spinner" /> : 'Continue'}
        </button>
      </form>
    </div>
  )
}
