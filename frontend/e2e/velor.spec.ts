import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { demoUpload, fixtureProfile, installDemoContract } from './demo-contract'
import type { DemoContract } from './demo-contract'

const runtimeErrors = new WeakMap<Page, string[]>()
test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  runtimeErrors.set(page, errors)
  page.on('pageerror', error => errors.push(error.message))
})
test.afterEach(async ({ page }) => {
  expect(runtimeErrors.get(page) ?? []).toEqual([])
  await expect(page.locator('vite-error-overlay')).toHaveCount(0)
})

async function createSelection(page: Page, state: DemoContract, withPhoto = false) {
  await page.getByLabel('Какой образ ищем?').fill('Осенняя прогулка по Москве, спокойные цвета')
  if (withPhoto) {
    await page.getByLabel('Референсы к запросу', { exact: true }).setInputFiles(demoUpload)
    await expect.poll(() => state.uploads.length).toBeGreaterThan(0)
  }
  await page.getByRole('button', { name: /Найти вещи/ }).click()
  await expect(page.getByText('DEMO источник A', { exact: true })).toBeVisible()
  await expect.poll(() => state.request?.status).toBe('selection')
  await expect(page.locator('.product-card').first()).toBeVisible()
}

async function createGallery(page: Page, state: DemoContract) {
  await createSelection(page, state)
  await page.getByRole('button', { name: /AI.?стилист|Собрать образы/i }).click()
  await expect.poll(() => state.request?.status).toBe('ready')
  await expect(page.locator('.outfit-card')).toHaveCount(4)
}

async function openEditor(page: Page, state: DemoContract) {
  await createGallery(page, state)
  await page.locator('.outfit-card').first().locator('.outfit-cover').click()
  await expect(page.locator('.editor-screen')).toBeVisible()
  await expect(page.locator('.outfit-render')).toBeVisible()
}

test('onboarding persists text and real multipart wardrobe/reference images; request photos remain separate', async ({ page }) => {
  const state = await installDemoContract(page, { profile: null })
  await page.goto('/')
  await expect(page).toHaveTitle(/VÉLOR/)
  await page.getByLabel('Что вам нравится носить?').fill('Мой постоянный профиль: свободный крой и графит')
  await page.getByLabel('Ваш гардероб', { exact: true }).setInputFiles(demoUpload)
  await page.getByLabel('Вдохновение', { exact: true }).setInputFiles(demoUpload)
  await expect.poll(() => state.uploads.length).toBe(2)
  await expect(page.getByRole('img', { name: 'Ваш гардероб, фото 1', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Сохранить и продолжить/ }).click()
  await expect(page.getByLabel('Какой образ ищем?')).toBeVisible()
  expect(state.profile?.style_text).toContain('Мой постоянный профиль')
  expect(state.profile?.images.map(image => image.kind).sort()).toEqual(['reference', 'wardrobe'])
  expect(state.uploads.every(upload => upload.hasFile && upload.contentType.startsWith('multipart/form-data; boundary='))).toBe(true)
  await page.reload()
  await expect(page.getByLabel('Какой образ ищем?')).toBeVisible()
  await expect(page.getByText('Мой постоянный профиль: свободный крой и графит', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  const restoredPhoto = page.getByRole('img', { name: 'Ваш гардероб, фото 1', exact: true })
  await expect(restoredPhoto).toBeVisible()
  await expect(restoredPhoto).toHaveAttribute('src', /^blob:/)
  await expect.poll(() => state.calls.filter(call => call.path.startsWith('/api/uploads/') && call.method === 'GET').length).toBeGreaterThanOrEqual(2)
  expect(state.calls.filter(call => call.path.startsWith('/api/uploads/') && call.method === 'GET').every(call => call.headers['x-dev-user'] === 'demo')).toBe(true)
  await page.getByRole('button', { name: 'Вернуться к подборке', exact: true }).click()
  await createSelection(page, state, true)
  const requestCall = state.calls.find(call => call.path === '/api/requests' && call.method === 'POST')!
  expect(requestCall.body).toMatchObject({ images: [{ kind: 'reference' }] })
  expect(state.profile?.images).toHaveLength(2)
  expect(state.request?.brief.images).toHaveLength(3)
})

test('search reports source progress, categories and request-only removal; stylist never starts automatically', async ({ page }) => {
  const state = await installDemoContract(page)
  await page.goto('/')
  await createSelection(page, state)
  expect(state.pollReads).toBeGreaterThanOrEqual(2)
  expect(state.calls.find(call => call.path === '/api/profile')?.headers['x-dev-user']).toBe('demo')
  expect(state.styleCalls).toBe(0)
  expect(state.request?.outfits).toEqual([])
  await expect(page.locator('.outfit-render')).toHaveCount(0)
  await page.getByRole('button', { name: /^Голова/ }).click()
  await expect(page.locator('.product-card')).toHaveCount(2)
  const card = page.locator('.product-card').filter({ hasText: 'Шапка DEMO 1' })
  await card.getByRole('button', { name: /Убрать|Удалить/ }).click()
  await expect(card).toHaveCount(0)
  expect(state.request?.excluded_product_ids).toEqual(['headwear-0'])
  expect(state.profile?.images).toEqual([])
  expect(state.styleCalls).toBe(0)
  await page.getByRole('button', { name: /AI.?стилист|Собрать образы/i }).click()
  await expect(page.locator('.outfit-card')).toHaveCount(4)
  expect(state.styleCalls).toBe(1)
  expect(state.request?.outfits.every(outfit => !outfit.product_ids.includes('headwear-0'))).toBe(true)
  const grid = page.locator('.outfit-grid')
  await expect(grid).toBeVisible()
  expect(await grid.evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(2)
  await page.getByRole('button', { name: 'Новая подборка', exact: true }).click()
  await createSelection(page, state)
  expect(state.requestsCreated).toBe(2)
  expect(state.request?.excluded_product_ids).toEqual([])
  await expect(page.locator('.product-card').filter({ hasText: 'Шапка DEMO 1' })).toBeVisible()
  expect(state.styleCalls).toBe(1)
})

test('editor replaces one actual catalog item with revision guard, hides stale render, saves to gallery', async ({ page }) => {
  const state = await installDemoContract(page)
  await page.goto('/')
  await openEditor(page, state)
  const topCard = page.locator('.editor-screen').locator('.editor-item').filter({ hasText: 'Джемпер DEMO 1' })
  await topCard.getByRole('button', { name: /Заменить/ }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('Ботинки DEMO 2', { exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: /Джемпер DEMO 2/ }).click()
  await expect.poll(() => state.replacements.length).toBe(1)
  expect(state.replacements[0]).toEqual({ old_product_id: 'tops-0', new_product_id: 'tops-1', expected_revision: 1 })
  await expect(page.locator('.outfit-render')).toHaveCount(0)
  await expect(page.locator('.editor-screen').getByText('Джемпер DEMO 2', { exact: true })).toBeVisible()
  await expect(page.locator('.outfit-render')).toBeVisible()
  await page.getByRole('button', { name: /Сохранить.*галере|Сохранить образ/i }).click()
  await expect.poll(() => state.request?.outfits[0].saved).toBe(true)
  const save = state.calls.find(call => call.path.endsWith('/outfit-1/save'))!
  expect(save.body).toEqual({ expected_revision: 2 })
  await expect(page.locator('.outfit-card').first()).toBeVisible()
  await page.screenshot({ path: '/tmp/velor-e2e-gallery-desktop.png', fullPage: true, animations: 'disabled' })
})

test('409 refreshes current outfit and leaves the editor actionable without repeating the mutation', async ({ page }) => {
  const state = await installDemoContract(page)
  await page.goto('/')
  await openEditor(page, state)
  state.conflictNext = true
  const readsBefore = state.pollReads
  await page.getByRole('button', { name: /Сохранить.*галере|Сохранить образ/i }).click()
  await expect(page.getByText(/Образ уже изменился/)).toBeVisible()
  await expect.poll(() => state.pollReads).toBeGreaterThan(readsBefore)
  expect(state.calls.filter(call => call.path.endsWith('/outfit-1/save'))).toHaveLength(1)
  await expect(page.getByRole('button', { name: /Сохранить.*галере|Сохранить образ/i })).toBeEnabled()
  await page.getByRole('button', { name: /Сохранить.*галере|Сохранить образ/i }).click()
  await expect.poll(() => state.request?.outfits[0].saved).toBe(true)
  expect(state.calls.filter(call => call.path.endsWith('/outfit-1/save')).at(-1)?.body).toEqual({ expected_revision: 2 })
})

test('failed backend remains an explicit error and never becomes a fake demo catalog', async ({ page }) => {
  const state = await installDemoContract(page, { failBoot: true })
  await page.goto('/')
  await expect(page.getByText(/Сервис пока недоступен/)).toBeVisible()
  await expect(page.locator('.product-card')).toHaveCount(0)
  await expect(page.locator('.outfit-render')).toHaveCount(0)
  expect(state.styleCalls).toBe(0)
  expect(state.requestsCreated).toBe(0)
})

test('Telegram initData is sent only as authorization and takes precedence over development identity', async ({ page }) => {
  const state = await installDemoContract(page, { telegram: true, profile: { ...fixtureProfile(), images: [{ id: 'private-reference', kind: 'reference', url: '/api/uploads/private-reference', local_path: null, mime_type: 'image/png' }] } })
  await page.goto('/')
  await expect(page.getByLabel('Какой образ ищем?')).toBeVisible()
  const profileRead = state.calls.find(call => call.path === '/api/profile')!
  expect(profileRead.headers.authorization).toBe('tma e2e-signed-demo-payload')
  expect(profileRead.headers['x-dev-user']).toBeUndefined()
  expect(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))).not.toContain('e2e-signed-demo-payload')
  await expect(page.getByText('e2e-signed-demo-payload')).toHaveCount(0)
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  const privatePhoto = page.getByRole('img', { name: 'Вдохновение, фото 1', exact: true })
  await expect(privatePhoto).toBeVisible()
  await expect(privatePhoto).toHaveAttribute('src', /^blob:/)
  const imageRead = state.calls.find(call => call.path === '/api/uploads/private-reference' && call.method === 'GET')!
  expect(imageRead.headers.authorization).toBe('tma e2e-signed-demo-payload')
  expect(imageRead.headers['x-dev-user']).toBeUndefined()
})

test('mobile core path stacks editor cleanly and keeps controls accessible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await installDemoContract(page)
  const consoleErrors: string[] = []
  page.on('pageerror', error => consoleErrors.push(error.message))
  await page.goto('/')
  await openEditor(page, state)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('button', { name: /Сохранить.*галере|Сохранить образ/i })).toBeVisible()
  expect(consoleErrors).toEqual([])
  await page.screenshot({ path: '/tmp/velor-e2e-editor-mobile.png', fullPage: true, animations: 'disabled' })
})
