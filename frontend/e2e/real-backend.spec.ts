import { expect, test } from '@playwright/test'
import type { Gallery, Health, Outfit, Product, Profile, RequestState } from '../src/types'

test.skip(process.env.VELOR_E2E_REAL_BACKEND !== '1', 'Opt-in only: needs an isolated local demo backend with temporary storage.')

test('real isolated demo backend: uploads, selection, explicit stylist, mannequin, replacement and persistent gallery', async ({ page, request: http }) => {
  test.setTimeout(90_000)
  const devAuth = { 'X-Dev-User': 'demo' }
  const errors: string[] = []
  const consoleErrors: string[] = []
  const networkFailures: string[] = []
  const stylePosts: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('requestfailed', req => { if (!req.failure()?.errorText.includes('ERR_ABORTED')) networkFailures.push(`${req.method()} ${new URL(req.url()).pathname}: ${req.failure()?.errorText}`) })
  page.on('request', req => { if (req.method() === 'POST' && new URL(req.url()).pathname.endsWith('/style')) stylePosts.push(req.url()) })
  // Only the external Telegram SDK is stubbed. All /api traffic reaches FastAPI.
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({ contentType: 'text/javascript', body: '/* Local integration run outside a Telegram session. */' }))

  const healthResponse = await http.get('/api/health')
  expect(healthResponse.ok(), 'Vite must proxy to the isolated backend on port8001').toBe(true)
  const health = await healthResponse.json() as Health & { provider_budget?: { calls: number; limit_usd: number } }
  expect(health.mode).toBe('demo')
  expect(health.environment).toBe('test')
  expect(health.search_workers).toBe(3)
  expect(health.provider_budget?.calls).toBe(0)
  expect(health.provider_budget?.limit_usd).toBe(0)

  const readState = async (id: string) => {
    const response = await http.get(`/api/requests/${encodeURIComponent(id)}`, { headers: devAuth })
    expect(response.ok()).toBe(true)
    return response.json() as Promise<RequestState>
  }
  const responseFor = (path: string, method: string) => page.waitForResponse(response => new URL(response.url()).pathname === path && response.request().method() === method)
  const loadedImage = async () => {
    await expect(page.locator('.editor-screen .outfit-render')).toBeVisible()
    await expect.poll(() => page.locator('.editor-screen .outfit-render').evaluate(element => {
      const image = element as HTMLImageElement
      return image.complete && image.naturalWidth > 0
    })).toBe(true)
  }

  await page.setViewportSize({ width: 1536, height: 1024 })
  await page.goto('/')
  await expect(page).toHaveTitle(/VÉLOR/)
  // A repeated opt-in run edits only this isolated dev user's temporary profile.
  await expect(page.locator('#request-text, #style-text')).toBeVisible()
  if (await page.getByLabel('Какой образ ищем?').isVisible()) await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(page.getByLabel('Что вам нравится носить?')).toBeVisible()
  const profileText = `Локальный E2E ${Date.now()}: графит, свободный крой, спокойный минимализм.`
  await page.getByLabel('Что вам нравится носить?').fill(profileText)
  const pngBase64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 64; canvas.height = 64
    const context = canvas.getContext('2d')!
    context.fillStyle = '#dedede'; context.fillRect(0, 0, 64, 64)
    context.fillStyle = '#242424'; context.fillRect(18, 12, 28, 40)
    return canvas.toDataURL('image/png').split(',')[1]
  })
  const uploadResponse = responseFor('/api/uploads', 'POST')
  await page.getByLabel('Ваш гардероб', { exact: true }).setInputFiles({ name: 'generated-local-e2e.png', mimeType: 'image/png', buffer: Buffer.from(pngBase64, 'base64') })
  const uploaded = await uploadResponse
  expect(uploaded.ok()).toBe(true)
  const upload = await uploaded.json() as Profile['images'][number]
  expect(upload.local_path).toBeNull()
  expect(upload.url).toMatch(/^\/api\/uploads\//)
  const profileSave = responseFor('/api/profile', 'PUT')
  await page.getByRole('button', { name: /Сохранить и продолжить|Сохранить профиль/ }).click()
  const profileResponse = await profileSave
  expect(profileResponse.ok()).toBe(true)
  const profile = await profileResponse.json() as Profile
  expect(profile.style_text).toBe(profileText)
  expect(profile.images.some(image => image.id === upload.id)).toBe(true)

  await page.getByLabel('Какой образ ищем?').fill('Демо образ для осенней прогулки по Москве. Спокойные нейтральные цвета.')
  const createdResponse = responseFor('/api/requests', 'POST')
  await page.getByRole('button', { name: /Найти вещи/ }).click()
  const created = await createdResponse
  expect(created.ok()).toBe(true)
  const initial = await created.json() as RequestState
  expect(initial.outfits).toEqual([])
  expect(initial.brief.mode).toBe('demo')
  expect(initial.status).toBe('searching')
  await expect(page.getByRole('button', { name: /Поиск по источникам|Результаты поиска/ })).toBeVisible()
  await expect.poll(async () => (await readState(initial.id)).status).toBe('selection')
  await expect(page.locator('.product-card').first()).toBeVisible()
  let current = await readState(initial.id)
  expect(current.catalog.sources.length).toBeGreaterThan(0)
  expect(current.catalog.products.length).toBeGreaterThan(0)
  expect(current.catalog.products.every(product => product.is_demo && product.verification === 'demo')).toBe(true)
  expect(current.outfits).toEqual([])
  expect(stylePosts).toHaveLength(0)
  await expect(page.locator('.outfit-render')).toHaveCount(0)

  const removal = current.catalog.products.find(product => current.catalog.products.filter(item => item.category === product.category).length > 1)!
  expect(removal).toBeTruthy()
  const removeResponse = responseFor(`/api/requests/${initial.id}/products/${removal.id}`, 'DELETE')
  await page.locator(`.product-card[data-product-id="${removal.id}"]`).getByRole('button', { name: /Убрать/ }).click()
  expect((await removeResponse).ok()).toBe(true)
  current = await readState(initial.id)
  expect(current.excluded_product_ids).toContain(removal.id)
  expect(current.outfits).toEqual([])
  const stylistResponse = responseFor(`/api/requests/${initial.id}/style`, 'POST')
  await page.getByRole('button', { name: 'AI-стилист', exact: true }).click()
  expect((await stylistResponse).ok()).toBe(true)
  expect(stylePosts).toHaveLength(1)
  await expect.poll(async () => (await readState(initial.id)).status).toBe('ready')
  current = await readState(initial.id)
  expect(current.outfits.length).toBeGreaterThan(0)
  expect(current.outfits.every(outfit => !outfit.product_ids.includes(removal.id))).toBe(true)
  // Earlier opt-in runs may have saved snapshots in this temporary database.
  // The gallery must include this request, while retaining those older saves.
  for (const outfit of current.outfits) await expect(page.locator(`.outfit-card[data-outfit-id="${outfit.id}"]`)).toHaveCount(1)
  expect(await page.locator('.outfit-grid').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(2)
  const first = current.outfits[0]
  expect(first.render_status).toBe('ready')
  expect(first.render_revision).toBe(first.revision)
  expect(first.render_url).toMatch(/^data:image\/svg\+xml[;,]/)
  await page.locator(`.outfit-card[data-outfit-id="${first.id}"]`).locator('.outfit-cover').click()
  await loadedImage()
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0)
  await expect(page.getByText('Сочетание из выбранных вами вещей.', { exact: true })).toBeVisible()
  expect(await page.locator('.outfit-explanation').getAttribute('open')).toBeNull()
  const visualBox = await page.locator('.editor-visual').boundingBox()
  const itemsBox = await page.locator('.editor-items').boundingBox()
  expect(visualBox!.x).toBeLessThan(itemsBox!.x)
  await page.screenshot({ path: '/tmp/velor-real-editor-desktop.png', fullPage: false, animations: 'disabled' })

  const selectedIds = new Set(first.product_ids)
  let oldProduct: Product | undefined
  let newProduct: Product | undefined
  for (const product of current.catalog.products.filter(item => selectedIds.has(item.id))) {
    const candidate = current.catalog.products.find(item => item.category === product.category && item.id !== product.id && !selectedIds.has(item.id) && !current.excluded_product_ids.includes(item.id) && item.availability !== 'out_of_stock')
    if (candidate) { oldProduct = product; newProduct = candidate; break }
  }
  expect(oldProduct, 'The real demo catalog must offer a replacement within a selected category').toBeTruthy()
  expect(newProduct).toBeTruthy()
  await page.locator(`.editor-item[data-product-id="${oldProduct!.id}"]`).getByRole('button', { name: 'Заменить', exact: true }).click()
  const patchResponse = responseFor(`/api/requests/${initial.id}/outfits/${first.id}`, 'PATCH')
  const firstCandidate = page.getByRole('dialog').locator(`.replacement-card[data-product-id="${newProduct!.id}"]`)
  await expect(firstCandidate).toContainText(newProduct!.title)
  await firstCandidate.click()
  const patch = await patchResponse
  expect(patch.ok()).toBe(true)
  expect(patch.request().postDataJSON()).toEqual({ old_product_id: oldProduct!.id, new_product_id: newProduct!.id, expected_revision: first.revision })
  const revised = await patch.json() as Outfit
  expect(revised.revision).toBe(first.revision + 1)
  expect(revised.product_ids).toContain(newProduct!.id)
  expect(revised.product_ids).not.toContain(oldProduct!.id)
  expect(revised.product_ids.filter(id => id !== newProduct!.id)).toEqual(first.product_ids.filter(id => id !== oldProduct!.id))
  if (revised.render_status === 'pending') await expect(page.locator('.editor-screen .outfit-render')).toHaveCount(0)
  await expect.poll(async () => (await readState(initial.id)).outfits.find(outfit => outfit.id === first.id)?.render_status).toBe('ready')
  await loadedImage()
  const saveResponse = responseFor(`/api/requests/${initial.id}/outfits/${first.id}/save`, 'POST')
  await page.getByRole('button', { name: /Сохранить образ|Сохранить.*галере/ }).click()
  const saved = await saveResponse
  expect(saved.ok()).toBe(true)
  expect(saved.request().postDataJSON()).toEqual({ expected_revision: revised.revision })
  await expect(page.locator('.outfit-card').first()).toBeVisible()
  const galleryResponse = await http.get('/api/gallery', { headers: devAuth })
  expect(galleryResponse.ok()).toBe(true)
  const gallery = await galleryResponse.json() as Gallery
  expect(gallery.outfits.find(outfit => outfit.id === first.id)).toMatchObject({ saved: true, revision: revised.revision })
  await page.screenshot({ path: '/tmp/velor-real-gallery-desktop.png', fullPage: true, animations: 'disabled' })

  await page.reload()
  await expect(page.getByLabel('Какой образ ищем?')).toBeVisible()
  await page.getByRole('button', { name: 'Галерея', exact: true }).click()
  const savedCard = page.locator(`.outfit-card[data-outfit-id="${first.id}"]`)
  await expect(savedCard).toBeVisible()
  await savedCard.locator('.outfit-cover').click()
  await loadedImage()
  await expect(page.locator('.editor-screen .revision')).toContainText(String(revised.revision))
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const mobileVisual = await page.locator('.editor-visual').boundingBox()
  const mobileItems = await page.locator('.editor-items').boundingBox()
  expect(mobileVisual!.y).toBeLessThan(mobileItems!.y)
  await page.screenshot({ path: '/tmp/velor-real-editor-mobile.png', fullPage: true, animations: 'disabled' })

  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(page.getByLabel('Что вам нравится носить?')).toHaveValue(profileText)
  const persistedThumbnail = page.getByRole('img', { name: /Ваш гардероб, фото/ }).last()
  await expect(persistedThumbnail).toBeVisible()
  await expect(persistedThumbnail).toHaveAttribute('src', /^blob:/)
  expect(errors).toEqual([])
  expect(consoleErrors).toEqual([])
  expect(networkFailures).toEqual([])
  await expect(page.locator('vite-error-overlay')).toHaveCount(0)
  const finalHealth = await (await http.get('/api/health')).json() as typeof health
  expect(finalHealth.provider_budget?.calls).toBe(0)
})
