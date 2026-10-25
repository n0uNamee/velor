import { ImageOff } from 'lucide-react'
import { useState } from 'react'
import type { Outfit } from '../types'
import { Loading } from './Primitives'
import { safeImage } from '../lib/presentation'

function RenderImage({ src, title }: { src: string; title: string }) {
  const [failed, setFailed] = useState(false)
  return failed ? <div className="render-message"><ImageOff size={27} strokeWidth={1} /><p>Не удалось загрузить визуализацию.</p><span>Состав образа сохранён. Попробуйте обновить.</span></div> : <img className="outfit-render" src={src} alt={`Визуализация образа «${title}» на манекене`} referrerPolicy="no-referrer" onError={() => setFailed(true)} />
}
export function OutfitRender({ outfit }: { outfit: Outfit }) {
  const current = outfit.render_status === 'ready' && outfit.render_revision === outfit.revision
  const src = current ? safeImage(outfit.render_url) : undefined
  return src ? <RenderImage key={src} src={src} title={outfit.title} /> : <div className="render-message">{outfit.render_status === 'failed' ? <><ImageOff size={30} strokeWidth={1} /><p>Визуализация недоступна</p><span>Можно изменить состав или сохранить образ без неё.</span></> : outfit.render_status === 'pending' || outfit.render_revision !== outfit.revision ? <><Loading>Готовим визуализацию</Loading><span>Покажем только актуальную версию образа.</span></> : <><ImageOff size={30} strokeWidth={1} /><p>Для образа пока нет изображения</p></>}</div>
}
