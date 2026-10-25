import { ArrowRight, Check, CircleAlert, Grid2X2, Plus, RefreshCw, UserRound, X } from 'lucide-react'
import { useLayoutEffect, useState } from 'react'
import { CatalogScreen } from './components/CatalogScreen'
import { EditorScreen } from './components/EditorScreen'
import { GalleryScreen } from './components/GalleryScreen'
import { ProfileScreen } from './components/ProfileScreen'
import { RequestScreen } from './components/RequestScreen'
import { DemoBadge, EmptyState, Loading } from './components/Primitives'
import { useVelor } from './hooks/useVelor'
import { WebAccess } from './components/WebAccess'
import { api, ApiError } from './api/client'
import type { Outfit, ProfileInput, RequestInput } from './types'

type View = 'new' | 'profile' | 'catalog' | 'gallery' | 'editor'

export default function App() {
  return <WebAccess><VelorApp /></WebAccess>
}

function VelorApp() {
  const velor = useVelor()
  const [view, setView] = useState<View>('new')
  const [editorId, setEditorId] = useState<string | null>(null)
  const [snapshotRevision, setSnapshotRevision] = useState<number | null>(null)
  const [juryBusy, setJuryBusy] = useState(false)
  const [juryError, setJuryError] = useState<string | null>(null)
  useLayoutEffect(() => { window.scrollTo(0, 0) }, [view, velor.booting, velor.profile?.id])
  async function saveProfile(input: ProfileInput) { const ok = await velor.saveProfile(input); if (ok) setView('new'); return ok }
  async function createRequest(input: RequestInput) { const ok = await velor.createRequest(input); if (ok) setView('catalog'); return ok }
  async function style() { if (await velor.style()) setView('gallery') }
  async function openJuryDemo() {
    if (juryBusy || velor.busy) return
    setJuryBusy(true)
    setJuryError(null)
    velor.clearError()
    try {
      const scenario = await api.juryDemo()
      await velor.reload()
      if (await velor.openRequest(scenario.id)) setView('catalog')
    } catch (caught) {
      setJuryError(caught instanceof ApiError ? caught.message : 'Не удалось открыть демо. Попробуйте ещё раз.')
    } finally {
      setJuryBusy(false)
    }
  }
  async function openOutfit(outfit: Outfit) {
    if (velor.request?.id !== outfit.request_id && !await velor.openRequest(outfit.request_id)) return
    setEditorId(outfit.id); setSnapshotRevision(outfit.saved ? outfit.revision : null); setView('editor')
  }
  const request = velor.request
  const currentOutfit = request?.outfits.find(o => o.id === editorId)
  const outfitMap = new Map(velor.gallery.outfits.map(o => [o.id, o]))
  request?.outfits.forEach(o => { const previous = outfitMap.get(o.id); if (!previous || previous.revision <= o.revision) outfitMap.set(o.id, o) })
  const products = new Map(velor.gallery.products.map(p => [p.id, p]))
  request?.catalog.products.forEach(p => products.set(p.id, p))
  const onboarding = !velor.profile && !velor.booting
  const demo = velor.health?.mode === 'demo' || request?.brief.mode === 'demo'
  const locked = velor.health?.auth_status === 'locked'
  const navView = onboarding ? 'profile' : view
  function navigate(next: View) { setView(next); velor.clearError(); if (next === 'gallery') void velor.refreshGallery() }
  return <div className="app-shell">
    <header className="app-header"><button className="wordmark" onClick={() => navigate('new')} aria-label="VÉLOR — главная">VÉLOR<span>PERSONAL STYLE</span></button><nav aria-label="Основная навигация"><button className={navView === 'new' || navView === 'catalog' ? 'active' : ''} onClick={() => navigate(request && view !== 'new' ? 'catalog' : 'new')}><Plus size={16} /><span>{request && view !== 'new' ? 'Подборка' : 'Новый запрос'}</span></button><button className={navView === 'gallery' || navView === 'editor' ? 'active' : ''} onClick={() => navigate('gallery')}><Grid2X2 size={15} /><span>Галерея</span></button><button className={navView === 'profile' ? 'active' : ''} onClick={() => navigate('profile')}><UserRound size={15} /><span>Профиль</span></button></nav><div className="runtime-status">{velor.health ? demo ? <DemoBadge /> : <span className="live-label">LIVE</span> : <span className="offline-label">{velor.booting ? 'Подключаемся' : 'Нет соединения'}</span>}</div></header>
    {demo ? <div className="runtime-banner"><span className="runtime-dot" /><span>Демо-режим <span className="banner-detail">· вещи и визуализации демонстрационные, наличие не подтверждено</span></span></div> : null}
    {locked ? <div className="app-notice" role="status"><CircleAlert size={18} /><p>Публичный вход VÉLOR открыт. Доступ к профилю и подборкам появится после подключения Telegram-бота.</p></div> : velor.error ? <div className="app-error" role="alert"><CircleAlert size={18} /><p>{velor.error}</p><button onClick={() => void velor.reload()} disabled={velor.booting || !!velor.busy}><RefreshCw size={14} />Обновить</button><button className="error-close" onClick={velor.clearError} aria-label="Закрыть сообщение об ошибке"><X size={16} /></button></div> : null}
    {velor.notice && !velor.error ? <div className="app-notice" role="status"><Check size={14} />{velor.notice}</div> : null}
    {juryError ? <div className="app-error" role="alert"><CircleAlert size={18} /><p>{juryError}</p><button className="error-close" onClick={() => setJuryError(null)} aria-label="Закрыть ошибку демо"><X size={16} /></button></div> : null}
    {velor.booting ? <main className="boot-screen"><span className="boot-wordmark">V.</span><Loading>Знакомимся с вашим стилем</Loading></main> : locked ? <main className="boot-screen"><EmptyState title="Подключаем Telegram">Публичный вход готов. Профиль и подборки пока закрыты; бот подключается. Личные данные и платные модели недоступны.</EmptyState></main> : view === 'gallery' ? <GalleryScreen outfits={[...outfitMap.values()]} savedOutfits={velor.gallery.outfits.filter(o => o.saved)} failure={request?.status === 'failed' ? request.error || 'Не удалось завершить подборку. Создайте новый запрос.' : null} products={[...products.values()]} demo={demo} styling={request?.status === 'styling'} opening={velor.busy === 'request'} onOpen={outfit => void openOutfit(outfit)} onNew={() => navigate('new')} /> : view === 'editor' && request && currentOutfit ? <EditorScreen key={currentOutfit.id} outfit={currentOutfit} snapshotRevision={snapshotRevision} request={request} busy={velor.busy} onReplace={velor.replaceProduct} onSave={velor.saveOutfit} onBack={() => navigate('gallery')} /> : (view === 'profile' || onboarding) ? <ProfileScreen key={velor.profile?.id ?? 'onboarding'} profile={velor.profile} busy={velor.busy === 'profile' || juryBusy} onSave={saveProfile} onCancel={() => navigate('new')} onJuryDemo={() => void openJuryDemo()} juryBusy={juryBusy} /> : view === 'catalog' && request ? <CatalogScreen request={request} busy={velor.busy} onRemove={velor.removeProduct} onStyle={() => void style()} onNew={() => navigate('new')} onGallery={() => navigate('gallery')} /> : velor.profile ? <RequestScreen key="new-request" catalogSource={velor.health?.catalog_source} profile={velor.profile} busy={velor.busy === 'request' || juryBusy} onCreate={createRequest} onEditProfile={() => navigate('profile')} onJuryDemo={() => void openJuryDemo()} juryBusy={juryBusy} /> : <main className="boot-screen"><p>Создайте профиль, чтобы начать.</p><button className="button button-primary" onClick={() => navigate('profile')}>К профилю<ArrowRight size={16} /></button></main>}
    <footer className="app-footer"><span>VÉLOR</span><p>Стиль начинается с вас.</p><span className="footer-note">Личный гардероб</span></footer>
  </div>
}
