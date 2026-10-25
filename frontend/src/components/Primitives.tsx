import { ArrowUpRight, Check, LoaderCircle, Shirt } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Product } from '../types'
import { money, safeImage } from '../lib/presentation'
export function Loading({ children = 'Загружаем' }: { children?: ReactNode }) {
  return <span className="loading"><LoaderCircle size={16} className="spin" aria-hidden />{children}</span>
}
export function DemoBadge() { return <span className="demo-badge">DEMO</span> }
export function ProductImage({ product }: { product: Product }) {
  const [failed, setFailed] = useState(false)
  const src = safeImage(product.image_url)
  return <div className="product-image">{src && !failed ? <img src={src} alt={product.title} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} /> : <div className="image-fallback"><Shirt size={30} strokeWidth={1} /><span>Фото недоступно</span></div>}</div>
}
export function ProductFacts({ product, link = true }: { product: Product; link?: boolean }) {
  const validLink = /^https?:\/\//i.test(product.source_url)
  return <>
    <div className="product-meta"><span>{product.source_id}</span>{product.is_demo || product.verification === 'demo' ? <DemoBadge /> : product.verification === 'verified' ? <span className="verified"><Check size={11} />Проверено</span> : <span>Не проверено</span>}</div>
    <h3>{product.title}</h3>
    <div className="product-price">{money(product.price_rub)}</div>
    <p className="product-note">{product.is_demo ? 'Демо-позиция · наличие не подтверждено' : product.availability === 'in_stock' && product.verification === 'verified' ? 'В наличии по данным источника' : product.availability === 'out_of_stock' ? 'Нет в наличии' : 'Наличие уточняется'}{product.sizes.length ? ` · ${product.sizes.join(', ')}` : ''}</p>
    {product.price_note ? <p className="product-note">{product.price_note}</p> : null}
    {link && validLink ? <a className="source-link" href={product.source_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Источник <ArrowUpRight size={13} /></a> : null}
  </>
}
export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-mark" aria-hidden>V</div><h2>{title}</h2><p>{children}</p>{action}</div>
}
