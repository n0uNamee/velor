import { ArrowRight, Check, Plus } from 'lucide-react'
import { useState } from 'react'
import type { Outfit, Product } from '../types'
import { DemoBadge, EmptyState, Loading } from './Primitives'
import { money } from '../lib/presentation'
import { OutfitRender } from './OutfitRender'

export function GalleryScreen({ outfits, savedOutfits, products, demo, styling, failure, opening, onOpen, onNew }: { outfits: Outfit[]; savedOutfits: Outfit[]; products: Product[]; demo: boolean; styling: boolean; failure: string | null; opening: boolean; onOpen: (outfit: Outfit) => void; onNew: () => void }) {
  const [savedOnly, setSavedOnly] = useState(false)
  const visible = savedOnly ? savedOutfits : outfits
  const productMap = new Map(products.map(p => [p.id, p]))
  return <main className="gallery-screen page-enter"><div className="page-heading"><div><span className="eyebrow">СОБРАНО ДЛЯ ВАС</span><h1>Ваши <em>образы.</em></h1><p>Всё сочетается. Последний штрих — за вами.</p></div><button className="button button-secondary" onClick={onNew}><Plus size={16} />Новая подборка</button></div>
    <div className="gallery-toolbar"><div className="line-tabs" role="group" aria-label="Фильтр галереи"><button className={!savedOnly ? 'active' : ''} onClick={() => setSavedOnly(false)}>Все образы <span>{outfits.length}</span></button><button className={savedOnly ? 'active' : ''} onClick={() => setSavedOnly(true)}>Сохранённые <span>{savedOutfits.length}</span></button></div>{demo ? <DemoBadge /> : null}</div>
    {failure ? <div className="inline-error" role="alert">{failure}</div> : null}
    {styling ? <div className="styling-message" role="status"><Loading>Стилист собирает сочетания из вашего отбора</Loading><p>Готовые образы появятся здесь. Можно оставаться на странице.</p></div> : null}
    {visible.length ? <div className="outfit-grid">{visible.map((outfit, i) => {
      const items = outfit.product_ids.map(id => productMap.get(id)).filter((p): p is Product => !!p)
      const knownTotal = items.length === outfit.product_ids.length && items.every(p => p.price_rub !== null)
      return <article className="outfit-card" data-outfit-id={outfit.id} key={outfit.id}><button className="outfit-cover" onClick={() => onOpen(outfit)} disabled={opening} aria-label={`Открыть ${outfit.title}`}><OutfitRender outfit={outfit} /><span className="look-index">LOOK {String(i + 1).padStart(2, '0')}</span>{outfit.saved ? <span className="saved-label"><Check size={12} />Сохранён</span> : null}{demo || items.some(p => p.is_demo) ? <span className="cover-demo"><DemoBadge /></span> : null}<span className="cover-open"><ArrowRight size={19} /></span></button><div className="outfit-caption"><div><h2>{outfit.title}</h2><p>{outfit.product_ids.length} вещей{knownTotal ? ` · ${money(items.reduce((sum, p) => sum + (p.price_rub ?? 0), 0))}` : ''}</p></div><button className="icon-button" onClick={() => onOpen(outfit)} disabled={opening} aria-label={`Редактировать ${outfit.title}`}><ArrowRight size={18} /></button></div></article>
    })}</div> : !styling ? <EmptyState title={savedOnly ? 'Здесь будут любимые образы' : 'Ваш первый образ впереди'} action={<button className="button button-primary" onClick={onNew}>Создать подборку<ArrowRight size={16} /></button>}>{savedOnly ? 'Откройте образ, внесите свои штрихи и нажмите «Сохранить образ».' : 'Начните с запроса, отберите вещи и запустите AI-стилиста.'}</EmptyState> : null}
  </main>
}
