import type { Page, Route } from '@playwright/test'
import type { Category, Gallery, ImageRef, Outfit, Product, Profile, RequestInput, RequestState, StyleBrief } from '../src/types'

// Explicit test fixtures. These are never substituted by the application runtime.
export const DEMO_MANNEQUIN = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#f2f2f0"/><text x="200" y="40" text-anchor="middle">DEMO · E2E</text><ellipse cx="200" cy="112" rx="27" ry="36" fill="#181818"/><path d="M164 155L236 155 267 307 235 321 226 525 205 525 200 360 194 525 173 525 166 321 133 307Z" fill="#242424"/></svg>')}`
const date = '2026-10-25T12:30:00Z'
const categoryList: Category[] = ['headwear', 'tops', 'bottoms', 'shoes', 'accessories']
const names: Record<Category, string> = { headwear: 'Шапка', tops: 'Джемпер', bottoms: 'Брюки', shoes: 'Ботинки', accessories: 'Шарф' }

export const demoProducts: Product[] = categoryList.flatMap((category, index) => [0, 1, ...(category === 'tops' ? [2] : [])].map(variant => ({
  id: `${category}-${variant}`,
  title: `${names[category]} DEMO ${variant + 1}`,
  category,
  source_id: index % 2 ? 'demo-source-b' : 'demo-source-a',
  source_url: 'https://example.com/demo-product',
  image_url: DEMO_MANNEQUIN,
  price_rub: 3000 + index * 1000 + variant * 100,
  price_note: 'Тестовая цена, не live предложение',
  sizes: ['M', 'L'],
  availability: 'unknown',
  verified_at: null,
  verification: 'demo',
  evidence: ['Explicit Playwright demo fixture'],
  is_demo: true,
})))

export function fixtureProfile(): Profile {
  return { id: 'profile-demo', style_text: 'Спокойный минимализм, свободный крой', images: [], created_at: date, updated_at: date }
}

interface FixtureOptions { profile?: Profile | null; failBoot?: boolean; telegram?: boolean }
export interface DemoContract {
  profile: Profile | null
  request: RequestState | null
  calls: { path: string; method: string; body: unknown; headers: Record<string, string> }[]
  uploads: { kind: string; hasFile: boolean; contentType: string }[]
  conflictNext: boolean
  requestsCreated: number
  styleCalls: number
  replacements: { old_product_id: string; new_product_id: string; expected_revision: number }[]
  pollReads: number
}

export async function installDemoContract(page: Page, options: FixtureOptions = {}): Promise<DemoContract> {
  const state: DemoContract = {
    profile: options.profile === undefined ? fixtureProfile() : options.profile,
    request: null, calls: [], uploads: [], conflictNext: false,
    requestsCreated: 0, styleCalls: 0, replacements: [], pollReads: 0,
  }
  let uploadIndex = 0
  let pendingPolls = 0
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({ contentType: 'text/javascript', body: '/* Explicit E2E Telegram mock: no real Telegram SDK session. */' }))
  if (options.telegram) await page.addInitScript(() => {
    window.Telegram = { WebApp: { initData: 'e2e-signed-demo-payload', ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {} } }
  })

  const makeBrief = (input: RequestInput): StyleBrief => ({
    schema_version: '1.0', id: `brief-${state.requestsCreated}`, profile_id: state.profile?.id ?? 'profile-demo',
    original_profile_text: state.profile?.style_text ?? '', original_request_text: input.text,
    images: [...(state.profile?.images ?? []), ...(input.images ?? [])], categories: categoryList,
    search_queries: ['DEMO search only'], constraints: [], preferences: [], exclusions: [],
    budget_rub: input.budget_rub ?? null, sizes: input.sizes ?? null, city: input.city ?? null,
    unknowns: ['Наличие не проверено: тестовые данные'], mode: 'demo',
  })
  const gallery = (): Gallery => ({ outfits: state.request?.outfits.filter(outfit => outfit.saved) ?? [], products: demoProducts })
  const makeOutfits = (): Outfit[] => [1, 2, 3, 4].map(index => ({
    id: `outfit-${index}`, request_id: state.request!.id, title: `DEMO образ ${index}`,
    product_ids: categoryList.map(category => demoProducts.find(product => product.category === category && !state.request!.excluded_product_ids.includes(product.id))!.id),
    revision: 1, render_revision: null, render_status: 'pending', render_url: null, saved: false,
    explanation: 'Тестовая комбинация из отобранного каталога.', render_disclaimer: 'DEMO · схематичная визуализация, не виртуальная примерка.',
  }))

  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const body = req.headers()['content-type']?.includes('application/json') ? req.postDataJSON() : null
    state.calls.push({ path, method, body, headers: req.headers() })
    if (options.failBoot && ['/api/health', '/api/profile', '/api/gallery'].includes(path)) return json(route, { detail: 'offline fixture' }, 503)
    if (path === '/api/health') return json(route, { status: 'ok', mode: 'demo', environment: 'development', providers: { brief: 'demo', search: 'demo', render: 'demo' }, search_workers: 3 })
    if (path === '/api/profile' && method === 'GET') return json(route, state.profile)
    if (path === '/api/profile' && method === 'PUT') {
      state.profile = { ...fixtureProfile(), style_text: body.style_text, images: body.images, updated_at: date }
      return json(route, state.profile)
    }
    if (path === '/api/gallery') return json(route, gallery())
    if (path === '/api/uploads' && method === 'POST') {
      const multipart = req.postDataBuffer()?.toString('latin1') ?? ''
      const kind = multipart.match(/name="kind"\r\n\r\n(wardrobe|reference)/)?.[1] ?? ''
      state.uploads.push({ kind, hasFile: multipart.includes('filename="demo-test.png"'), contentType: req.headers()['content-type'] ?? '' })
      const image: ImageRef = { id: `demo-upload-${++uploadIndex}`, kind: kind === 'wardrobe' ? 'wardrobe' : 'reference', url: `/api/uploads/demo-upload-${uploadIndex}`, local_path: null, mime_type: 'image/png' }
      return json(route, image)
    }
    if (path.startsWith('/api/uploads/') && method === 'GET') return route.fulfill({ contentType: 'image/png', body: demoUpload.buffer })
    if (path === '/api/requests' && method === 'POST') {
      const input = body as RequestInput
      ++state.requestsCreated
      state.pollReads = 0
      state.request = {
        id: `request-${state.requestsCreated}`, profile_id: state.profile?.id ?? 'profile-demo', text: input.text,
        status: 'searching', brief: makeBrief(input),
        catalog: { schema_version: '1.0', products: [], sources: [
          { source_id: 'demo-source-a', name: 'DEMO источник A', state: 'searching', found: 0, detail: 'Тестовый поиск' },
          { source_id: 'demo-source-b', name: 'DEMO источник B', state: 'queued', found: 0, detail: null },
        ], warnings: ['DEMO: тестовые карточки, наличие не проверено.'] },
        excluded_product_ids: [], outfits: [], created_at: date, error: null,
      }
      return json(route, state.request)
    }
    if (path === `/api/requests/${state.request?.id}` && method === 'GET') {
      ++state.pollReads
      if (state.request!.status === 'searching') {
        if (state.pollReads >= 2) {
          state.request!.status = 'selection'
          state.request!.catalog.products = demoProducts
          state.request!.catalog.sources = state.request!.catalog.sources.map(source => ({ ...source, state: 'complete', found: 5 }))
        } else state.request!.catalog.sources[0].state = 'verifying'
      }
      if (state.request!.status === 'styling' || state.request!.outfits.some(outfit => outfit.render_status === 'pending')) {
        if (pendingPolls > 0) --pendingPolls
        else {
          state.request!.status = 'ready'
          state.request!.outfits = state.request!.outfits.map(outfit => ({ ...outfit, render_revision: outfit.revision, render_status: 'ready', render_url: DEMO_MANNEQUIN }))
        }
      }
      return json(route, state.request)
    }
    const deletion = path.match(/^\/api\/requests\/([^/]+)\/products\/([^/]+)$/)
    if (deletion && method === 'DELETE' && state.request) {
      state.request.excluded_product_ids.push(deletion[2])
      return json(route, state.request)
    }
    if (path.endsWith('/style') && method === 'POST' && state.request) {
      ++state.styleCalls
      state.request.status = 'styling'
      state.request.outfits = makeOutfits()
      pendingPolls = 0
      return json(route, state.request)
    }
    const outfitPath = path.match(/^\/api\/requests\/([^/]+)\/outfits\/([^/]+)(\/save)?$/)
    if (outfitPath && state.request) {
      const outfit = state.request.outfits.find(item => item.id === outfitPath[2])!
      if (state.conflictNext) {
        state.conflictNext = false
        ++outfit.revision
        outfit.render_revision = outfit.revision
        return json(route, { detail: 'stale revision' }, 409)
      }
      if (body.expected_revision !== outfit.revision) return json(route, { detail: 'stale revision' }, 409)
      if (outfitPath[3] && method === 'POST') { outfit.saved = true; return json(route, outfit) }
      if (method === 'PATCH') {
        state.replacements.push(body)
        const oldProduct = demoProducts.find(product => product.id === body.old_product_id)
        const newProduct = demoProducts.find(product => product.id === body.new_product_id)
        if (!oldProduct || !newProduct || oldProduct.category !== newProduct.category || state.request.excluded_product_ids.includes(newProduct.id)) return json(route, { detail: 'invalid replacement' }, 422)
        outfit.product_ids = outfit.product_ids.map(id => id === body.old_product_id ? body.new_product_id : id)
        ++outfit.revision
        outfit.saved = false
        outfit.render_status = 'pending'
        pendingPolls = 2
        return json(route, outfit)
      }
    }
    return json(route, { detail: `Unhandled demo fixture path: ${method} ${path}` }, 404)
  })
  return state
}

/** A generated 1px PNG; no personal file or external transfer. */
export const demoUpload = {
  name: 'demo-test.png', mimeType: 'image/png',
  buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lHkAAAAASUVORK5CYII=', 'base64'),
}
