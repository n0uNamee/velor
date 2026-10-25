import { ImagePlus, LoaderCircle, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { ImageKind, ImageRef } from '../types'

interface Props {
  kind: ImageKind; images: ImageRef[]; title: string; hint: string;
  onAdd: (image: ImageRef) => void; onRemove: (id: string) => void;
  onBusyChange: (busy: boolean) => void; totalCount?: number
}
function PrivateThumbnail({ image, alt }: { image: ImageRef; alt: string }) {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    let localUrl: string | null = null
    void api.imageBlob(image.id, controller.signal).then(blob => {
      if (controller.signal.aborted) return
      localUrl = URL.createObjectURL(blob); setSrc(localUrl)
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => { controller.abort(); if (localUrl) URL.revokeObjectURL(localUrl) }
  }, [image.id])
  return src ? <img src={src} alt={alt} /> : <span className="private-image-status" role="img" aria-label={failed ? 'Фотография недоступна' : 'Загружаем фотографию'}>{failed ? '!' : <ImagePlus size={20} />}</span>
}
export function UploadField({ kind, images, title, hint, onAdd, onRemove, onBusyChange, totalCount = images.length }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const alive = useRef(true)
  const controller = useRef<AbortController | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [previews, setPreviews] = useState<Record<string, string>>({})
  const urls = useRef<string[]>([])
  useEffect(() => { alive.current = true; const localUrls = urls.current; return () => { alive.current = false; controller.current?.abort(); localUrls.forEach(URL.revokeObjectURL) } }, [])

  async function upload(files: FileList | File[] | null) {
    if (!files?.length || busy) return
    setBusy(true); setError(''); onBusyChange(true)
    controller.current = new AbortController()
    const errors: string[] = []
    const fileList = Array.from(files)
    if (fileList.length + totalCount > 24) errors.push('Можно добавить до 24 фото. Лишние файлы не загружены.')
    for (const file of fileList.slice(0, Math.max(0, 24 - totalCount))) {
      if (!alive.current) break
      try {
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Используйте JPEG, PNG или WebP.')
        if (file.size > 10 * 1024 * 1024) throw new Error('Максимальный размер фотографии — 10 МБ.')
        const ref = await api.upload(file, kind, controller.current.signal)
        if (!alive.current) break
        const preview = URL.createObjectURL(file); urls.current.push(preview)
        setPreviews(p => ({ ...p, [ref.id]: preview })); onAdd(ref)
      } catch (e) {
        if (controller.current.signal.aborted) break
        errors.push(`${file.name}: ${e instanceof Error ? e.message : 'Не удалось загрузить фото.'}`)
      }
    }
    if (alive.current) { setBusy(false); onBusyChange(false); setError(errors.join(' ')) }
    if (input.current) input.current.value = ''
  }
  return <div className="upload-section">
    <div className="field-heading"><h3>{title}</h3><span>Необязательно</span></div>
    <p className="field-hint">{hint}</p>
    <div className={`upload-drop ${dragging ? 'is-dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files) }}>
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={e => void upload(e.target.files)} aria-label={title} disabled={busy} />
      <button className="upload-button" type="button" onClick={() => input.current?.click()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={22} /> : <ImagePlus size={22} strokeWidth={1.3} />}<span>{busy ? 'Загружаем на локальный сервер…' : 'Добавить фотографии'}</span>{!busy ? <Plus size={16} /> : null}</button>
    </div>
    {images.length ? <div className="upload-previews">{images.map((image, i) => {
      const src = previews[image.id]
      return <div className="upload-thumb" key={image.id}>{src ? <img src={src} alt={`${title}, фото ${i + 1}`} /> : <PrivateThumbnail image={image} alt={`${title}, фото ${i + 1}`} />}<button type="button" onClick={() => onRemove(image.id)} aria-label={`Убрать фото ${i + 1} из ${title}`}><X size={13} /></button><span>{i + 1}</span></div>
    })}</div> : null}
    {error ? <p role="alert" className="field-error">{error}</p> : null}
  </div>
}
