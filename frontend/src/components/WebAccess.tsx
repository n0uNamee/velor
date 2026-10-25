import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import { Loading } from './Primitives'

type AccessState = 'loading' | 'ready' | 'login' | 'offline'
interface Bootstrap { state: AccessState; error?: string }

// One bootstrap per page load also prevents a one-time fragment being redeemed
// twice by development StrictMode. Neither access code nor CSRF enters storage.
let bootstrapPromise: Promise<Bootstrap> | null = null
function bootstrap(): Promise<Bootstrap> {
  if (bootstrapPromise) return bootstrapPromise
  const fragment = new URLSearchParams(window.location.hash.slice(1))
  let accessCode = fragment.get('access')
  if (accessCode !== null) {
    fragment.delete('access')
    const rest = fragment.toString()
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${rest ? `#${rest}` : ''}`)
  }
  bootstrapPromise = (async () => {
    try {
      const health = await api.health()
      if (health.auth_status !== 'web') return { state: 'ready' }
      api.setWebSession(null)
      const current = await api.session()
      if (current.authenticated && current.csrf_token) {
        api.setWebSession(current.csrf_token)
        return { state: 'ready' }
      }
      if (accessCode) {
        try {
          const session = await api.login(accessCode)
          if (session.authenticated && session.csrf_token) {
            api.setWebSession(session.csrf_token)
            return { state: 'ready' }
          }
        } catch {
          return { state: 'login', error: 'Ссылка доступа устарела или код не принят. Введите код ещё раз.' }
        } finally {
          accessCode = null
        }
      }
      return { state: 'login' }
    } catch {
      return { state: 'offline', error: 'Не удалось связаться с VÉLOR. Попробуйте обновить страницу.' }
    }
  })()
  return bootstrapPromise
}

export function WebAccess({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AccessState>('loading')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    void bootstrap().then(result => {
      if (!active) return
      setState(result.state)
      setError(result.error ?? null)
    })
    const expired = () => {
      setState('login')
      setError('Сессия закончилась. Введите код доступа, чтобы продолжить.')
    }
    window.addEventListener('velor-session-expired', expired)
    return () => { active = false; window.removeEventListener('velor-session-expired', expired) }
  }, [])

  async function login(event: FormEvent) {
    event.preventDefault()
    if (busy || !code.trim()) return
    setBusy(true)
    setError(null)
    try {
      const session = await api.login(code.trim())
      if (!session.authenticated || !session.csrf_token) throw new Error('Session unavailable')
      api.setWebSession(session.csrf_token)
      setCode('')
      setState('ready')
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 429
        ? 'Слишком много попыток. Подождите немного и попробуйте снова.'
        : 'Код не принят или срок доступа закончился. Проверьте код и попробуйте снова.')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'ready') return children
  return <div className="app-shell">
    <header className="app-header"><div className="wordmark">VÉLOR<span>PERSONAL STYLE</span></div></header>
    <main className="boot-screen">
      {state === 'loading' ? <Loading>Открываем VÉLOR</Loading> : <form onSubmit={event => void login(event)} style={{ width: 'min(100%, 420px)', padding: '24px', textAlign: 'left' }}>
        <h1 style={{ fontFamily: 'Georgia, serif', fontSize: '36px', marginBottom: '16px' }}>Ваш личный стилист</h1>
        <p style={{ color: '#73766f', marginBottom: '24px', lineHeight: 1.6 }}>Введите временный код доступа, чтобы открыть свой профиль и подборки.</p>
        {state === 'login' ? <label style={{ display: 'grid', gap: '10px', marginBottom: '20px' }}>Код доступа<input type="password" name="code" autoComplete="one-time-code" value={code} onChange={event => setCode(event.target.value)} maxLength={128} required autoFocus disabled={busy} /></label> : null}
        {error ? <p role="alert" style={{ marginBottom: '16px', lineHeight: 1.5 }}>{error}</p> : null}
        {state === 'login' ? <button className="button button-primary" disabled={busy || !code.trim()} type="submit">{busy ? 'Входим…' : 'Войти в VÉLOR'}</button> : <button className="button button-primary" type="button" onClick={() => window.location.reload()}>Обновить страницу</button>}
      </form>}
    </main>
  </div>
}
