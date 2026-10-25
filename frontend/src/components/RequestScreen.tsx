import { ArrowRight, SlidersHorizontal, Sparkles } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ImageRef, Profile, RequestInput } from '../types'
import { Loading } from './Primitives'
import { UploadField } from './UploadField'

export function RequestScreen({ profile, busy, onCreate, onEditProfile }: { profile: Profile; busy: boolean; onCreate: (input: RequestInput) => Promise<boolean>; onEditProfile: () => void }) {
  const [text, setText] = useState('')
  const [images, setImages] = useState<ImageRef[]>([])
  const [budget, setBudget] = useState('')
  const [city, setCity] = useState('')
  const [size, setSize] = useState('')
  const [details, setDetails] = useState(false)
  const [uploading, setUploading] = useState({ wardrobe: false, reference: false })
  async function submit(e: FormEvent) { e.preventDefault(); await onCreate({ text: text.trim(), images, budget_rub: budget ? Number(budget) : null, city: city.trim() || null, sizes: size.trim() ? { clothing: size.trim() } : null }) }
  const addImage = (image: ImageRef) => setImages(previous => [...previous, image])
  const removeImage = (id: string) => setImages(previous => previous.filter(i => i.id !== id))
  return <main className="request-layout page-enter">
    <div className="request-title"><span className="eyebrow">НОВАЯ ПОДБОРКА</span><h1>Для ваших<br /><em>планов.</em></h1><p>Опишите повод и настроение.<br />Вещи сначала выбираете вы.</p><div className="request-process"><span className="active">01&nbsp; Запрос</span><span>02&nbsp; Отбор вещей</span><span>03&nbsp; Образы</span></div></div>
    <form className="request-form" onSubmit={e => void submit(e)}>
      <label className="text-label" htmlFor="request-text">Какой образ ищем?</label>
      <textarea id="request-text" rows={5} value={text} onChange={e => setText(e.target.value)} placeholder="Например, образ для осенних прогулок по Москве. Хочу многослойность, удобную обувь и что-нибудь необычное…" maxLength={6000} />
      <div className="request-examples">{['На каждый день', 'В офис', 'Особенный вечер'].map(example => <button className="text-chip" key={example} type="button" onClick={() => setText(example)}>{example}<ArrowRight size={12} /></button>)}</div>
      <div className="profile-summary"><Sparkles size={17} strokeWidth={1.3} /><div><strong>Ваш профиль сохранён</strong><p>{profile.style_text || `В профиле ${profile.images.length} фото`}</p></div><button type="button" onClick={onEditProfile}>Изменить</button></div>
      <UploadField kind="wardrobe" title="Вещи для этого образа" hint="Добавьте то, с чем нужно сочетать подборку. Эти фото относятся только к запросу." totalCount={images.length} images={images.filter(i => i.kind === 'wardrobe')} onAdd={addImage} onRemove={removeImage} onBusyChange={v => setUploading(p => ({ ...p, wardrobe: v }))} />
      <UploadField kind="reference" title="Референсы к запросу" hint="Покажите настроение или желаемое сочетание." totalCount={images.length} images={images.filter(i => i.kind === 'reference')} onAdd={addImage} onRemove={removeImage} onBusyChange={v => setUploading(p => ({ ...p, reference: v }))} />
      <button type="button" className="details-toggle" onClick={() => setDetails(!details)} aria-expanded={details}><SlidersHorizontal size={15} />Бюджет, размер и город<span>{details ? '−' : '+'}</span></button>
      {details ? <div className="request-details"><label>Бюджет, ₽<input type="number" min="1" max="100000000" step="1" inputMode="numeric" placeholder="Не ограничен" value={budget} onChange={e => setBudget(e.target.value)} /></label><label>Размер<input placeholder="Например, M / 46" value={size} onChange={e => setSize(e.target.value)} maxLength={60} /></label><label>Город<input placeholder="Москва" value={city} onChange={e => setCity(e.target.value)} maxLength={100} /></label></div> : null}
      <div className="form-footer"><p>Сначала найдём вещи.<br />Стилист — после вашего отбора.</p><button className="button button-primary" type="submit" disabled={busy || uploading.wardrobe || uploading.reference || (!text.trim() && !images.length)}>{busy ? <Loading>Начинаем поиск</Loading> : <>Найти вещи<ArrowRight size={16} /></>}</button></div>
    </form>
  </main>
}
