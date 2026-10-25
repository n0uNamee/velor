import { ArrowRight, Check, LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ImageRef, Profile, ProfileInput } from '../types'
import { Loading } from './Primitives'
import { UploadField } from './UploadField'

export function ProfileScreen({ profile, busy, onSave, onCancel }: { profile: Profile | null; busy: boolean; onSave: (input: ProfileInput) => Promise<boolean>; onCancel: () => void }) {
  const [text, setText] = useState(profile?.style_text ?? '')
  const [images, setImages] = useState<ImageRef[]>(profile?.images ?? [])
  const [uploading, setUploading] = useState({ wardrobe: false, reference: false })
  const [saved, setSaved] = useState(false)
  const addImage = (image: ImageRef) => setImages(previous => [...previous, image])
  const removeImage = (id: string) => setImages(previous => previous.filter(i => i.id !== id))
  async function submit(e: FormEvent) { e.preventDefault(); if (await onSave({ style_text: text.trim(), images })) setSaved(true) }
  const disabled = busy || uploading.wardrobe || uploading.reference
  return <main className="profile-layout page-enter">
    <aside className="profile-intro">
      <span className="eyebrow">ВАШ ЛИЧНЫЙ СТИЛЬ</span>
      <h1>Начнём<br />с <em>вас.</em></h1>
      <p>Хороший образ начинается с понимания того, что вам близко.</p>
      <ol className="intro-steps"><li><span>01</span><div><strong>Расскажите о себе</strong><small>Предпочтения, силуэты, привычки</small></div></li><li><span>02</span><div><strong>Покажите свой гардероб</strong><small>Вещи, с которыми хотите сочетать новое</small></div></li><li><span>03</span><div><strong>Добавьте вдохновение</strong><small>Образы, которые хочется примерить</small></div></li></ol>
      <div className="privacy-note"><LockKeyhole size={17} strokeWidth={1.4} /><p>Фотографии хранятся на локальном сервере VÉLOR. Внешним моделям они не отправляются.</p></div>
      <span className="intro-signature" aria-hidden>V.</span>
    </aside>
    <form className="profile-form" onSubmit={e => void submit(e)}>
      <div className="section-heading"><span className="eyebrow">ПРОФИЛЬ</span><span className="subtle">{profile ? 'Можно изменить в любой момент' : 'Один раз — для всех будущих образов'}</span></div>
      <label className="text-label" htmlFor="style-text">Что вам нравится носить?</label>
      <textarea id="style-text" value={text} onChange={e => { setText(e.target.value); setSaved(false) }} rows={5} placeholder="Люблю спокойные цвета, свободный крой и натуральные ткани. Не ношу яркие принты…" maxLength={6000} />
      <div className="suggestions">{['Минимализм', 'Свободный крой', 'Монохром', 'Натуральные ткани'].map(s => <button type="button" key={s} onClick={() => setText(t => `${t}${t.trim() ? ', ' : ''}${s.toLowerCase()}`)}>{s}<span>+</span></button>)}</div>
      <div className="form-divider" />
      <UploadField kind="wardrobe" title="Ваш гардероб" hint="Вещи, которые уже есть. Можно загрузить несколько фото." totalCount={images.length} images={images.filter(i => i.kind === 'wardrobe')} onAdd={addImage} onRemove={removeImage} onBusyChange={v => setUploading(p => ({ ...p, wardrobe: v }))} />
      <UploadField kind="reference" title="Вдохновение" hint="Референсы: образы, сочетания и детали, которые вам нравятся." totalCount={images.length} images={images.filter(i => i.kind === 'reference')} onAdd={addImage} onRemove={removeImage} onBusyChange={v => setUploading(p => ({ ...p, reference: v }))} />
      <div className="form-footer"><p>Профиль сохраняется отдельно от каждого запроса.</p><button className="button button-primary" type="submit" disabled={disabled || (!text.trim() && !images.length)}>{busy ? <Loading>Сохраняем</Loading> : saved ? <><Check size={16} />Сохранено</> : <>{profile ? 'Сохранить профиль' : 'Сохранить и продолжить'}<ArrowRight size={16} /></>}</button></div>
      {profile ? <button className="text-button" type="button" onClick={onCancel}>Вернуться к подборке</button> : null}
    </form>
  </main>
}
