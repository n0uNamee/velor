import { ArrowLeft, ArrowRight, Check, ChevronDown, Circle, LoaderCircle, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import type { Category, RequestState, SourceState } from '../types'
import { DemoBadge, EmptyState, Loading, ProductFacts, ProductImage } from './Primitives'
import { categories } from '../lib/presentation'

const sourceLabels: Record<SourceState, string> = { queued: 'В очереди', searching: 'Ищем вещи', verifying: 'Проверяем', complete: 'Завершено', inaccessible: 'Источник недоступен', unconfigured: 'Не подключён', failed: 'Ошибка источника' }
export function CatalogScreen({ request, busy, onRemove, onStyle, onNew, onGallery }: { request: RequestState; busy: string | null; onRemove: (id: string) => Promise<boolean>; onStyle: () => void; onNew: () => void; onGallery: () => void }) {
  const [category, setCategory] = useState<Category | 'all'>('all')
  const [showSources, setShowSources] = useState(true)
  const excluded = new Set(request.excluded_product_ids)
  const selected = request.catalog.products.filter(p => !excluded.has(p.id))
  const shown = selected.filter(p => category === 'all' || p.category === category)
  const searching = request.status === 'searching'
  const styling = request.status === 'styling'
  const complete = request.catalog.sources.filter(s => ['complete', 'inaccessible', 'unconfigured', 'failed'].includes(s.state)).length
  const demo = request.brief.mode === 'demo'
  return <main className="catalog-screen page-enter">
    <button className="back-link" onClick={onNew}><ArrowLeft size={15} />Новый запрос</button>
    <div className="page-heading"><div><span className="eyebrow">{searching ? 'ПОИСК ВЕЩЕЙ' : 'ВАШ ОТБОР'} {demo ? <DemoBadge /> : null}</span><h1>{searching ? 'Находим ваше.' : 'Оставьте лучшее.'}</h1><p className="request-quote">{request.text}</p></div><span className="step-number">01 <span>/ 03</span></span></div>
    <div className="search-status"><button className="source-toggle" onClick={() => setShowSources(!showSources)} aria-expanded={showSources}><span>{searching ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}{searching ? 'Поиск по источникам' : 'Результаты поиска'}<span className="source-count">{complete} / {request.catalog.sources.length}</span></span><ChevronDown size={16} className={!showSources ? 'collapsed' : ''} /></button>
      {showSources ? <div className="source-grid">{request.catalog.sources.length ? request.catalog.sources.map(source => <div className="source-row" key={source.source_id}><div className={`source-dot ${source.state}`} /><div><strong>{source.name}</strong><span>{sourceLabels[source.state]}{source.found ? ` · ${source.found} вещей` : ''}</span>{source.detail ? <small>{source.detail}</small> : null}</div></div>) : <p className="subtle">{searching ? 'Подготавливаем источники…' : 'Источники не предоставлены сервером.'}</p>}</div> : null}
    </div>
    {demo ? <p className="demo-note">Демонстрационный каталог. Цены и наличие не подтверждены live-поиском.</p> : null}
    {request.catalog.warnings.length ? <div className="catalog-warnings">{request.catalog.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div> : null}
    {request.error || request.status === 'failed' ? <div className="inline-error" role="alert">{request.error || 'Подборка не завершилась. Создайте новый запрос.'}</div> : null}
    <div className="catalog-toolbar"><div className="category-tabs" role="group" aria-label="Категории вещей"><button className={category === 'all' ? 'active' : ''} onClick={() => setCategory('all')}>Всё <span>{selected.length}</span></button>{categories.map(c => <button key={c.id} className={category === c.id ? 'active' : ''} onClick={() => setCategory(c.id)}>{c.label}<span>{selected.filter(p => p.category === c.id).length}</span></button>)}</div><span className="catalog-hint">Убирайте то, что вам не подходит</span></div>
    {shown.length ? <div className="product-grid">{shown.map(product => <article className="product-card" data-product-id={product.id} key={product.id}><div className="product-picture"><ProductImage product={product} /><button className="remove-product" disabled={!!busy || searching || styling} onClick={() => void onRemove(product.id)} aria-label={`Убрать ${product.title} — ${product.source_id}`} title="Убрать из этой подборки">{busy === `remove:${product.id}` ? <LoaderCircle className="spin" size={17} /> : <X size={17} />}</button></div><div className="product-info"><ProductFacts product={product} /></div></article>)}</div> : searching ? <div className="search-empty"><Loading>Источники подбирают вещи по вашему запросу</Loading><div className="skeleton-grid">{[0, 1, 2].map(i => <div className="skeleton" key={i} />)}</div></div> : <EmptyState title={category === 'all' ? 'В подборке пока пусто' : 'В этой категории нет вещей'} action={<button className="button button-secondary" onClick={onNew}>Уточнить запрос<ArrowRight size={15} /></button>}>{category === 'all' ? 'Попробуйте другой запрос или дождитесь подключения источников.' : 'Выберите другую категорию или создайте новую подборку.'}</EmptyState>}
    <div className="selection-bar"><div><strong>{selected.length} {selected.length === 1 ? 'вещь в отборе' : 'вещей в отборе'}</strong><p>{excluded.size ? `${excluded.size} исключено только из этого запроса. ` : ''}{searching ? 'Дождитесь завершения поиска.' : 'Следующий шаг — собрать из них образы.'}</p></div>{request.status === 'ready' && request.outfits.length ? <button className="button button-primary" onClick={onGallery}>Смотреть образы<ArrowRight size={16} /></button> : <button className="button button-primary" onClick={onStyle} disabled={!!busy || searching || styling || request.status === 'failed' || !selected.length}>{styling || busy === 'style' ? <Loading>Стилист собирает образы</Loading> : <><Sparkles size={16} />AI-стилист<ArrowRight size={16} /></>}</button>}</div>
    <p className="selection-note"><Circle size={6} fill="currentColor" />Образы появятся только после нажатия «AI-стилист».</p>
  </main>
}
