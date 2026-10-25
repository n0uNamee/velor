import type { Category } from '../types'

export const categories: { id: Category; label: string }[] = [
  { id: 'headwear', label: 'Голова' }, { id: 'tops', label: 'Верх' },
  { id: 'bottoms', label: 'Низ' }, { id: 'shoes', label: 'Обувь' },
  { id: 'accessories', label: 'Аксессуары' },
]
export const categoryName = (category: Category) => categories.find(c => c.id === category)?.label ?? category
export const money = (price: number | null) => price === null ? 'Цена не указана' : `${new Intl.NumberFormat('ru-RU').format(price)} ₽`
export function safeImage(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  if (/^data:image\/(svg\+xml|png|jpeg|webp|gif)[;,]/i.test(url) || url.startsWith('/api/') || url.startsWith('blob:')) return url
  try { const parsed = new URL(url); return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? url : undefined } catch { return undefined }
}
