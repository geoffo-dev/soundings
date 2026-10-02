import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Branding (contract-phase4 §3.10–3.11) against the mock: the global profile
 * at /settings/branding (platform admins) with its live preview, uploads and
 * runtime application; a project's override in project settings.
 */

/** A 1×1 PNG. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

const rootVar = (page: Page, name: string) =>
  page.evaluate(
    (property) => getComputedStyle(document.documentElement).getPropertyValue(property).trim(),
    name,
  )

const previewVar = (page: Page, name: string) =>
  page
    .getByTestId('branding-preview')
    .first()
    .evaluate(
      (element, property) => getComputedStyle(element).getPropertyValue(property).trim(),
      name,
    )

test.describe('as a platform admin', () => {
  test.use({ signedInAs: USERS.priya })

  test('the page scrolls inside the app shell, never the whole document (K4-3)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/settings/branding')
    await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
    await expect(page.getByTestId('branding-preview').first()).toBeVisible()
    // Hidden radio and file inputs are absolutely positioned: they must belong to <main>.
    expect(
      await page.evaluate(
        () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
      ),
    ).toBe(0)
  })

  test('the preview follows the form before Save; Save re-themes the app', async ({ page }) => {
    await page.goto('/settings/branding')
    await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
    await expect(
      page
        .getByRole('navigation', { name: 'Settings sections' })
        .getByRole('link', { name: 'Branding' }),
    ).toHaveAttribute('aria-current', 'page')

    await page.getByLabel('App name').fill('Acme Ideas')
    await page.getByRole('button', { name: 'Brick (#b42318)' }).first().click()
    await page.getByRole('radio', { name: /IBM Plex Sans/ }).click()
    // Live: the preview has the new values, the app doesn't yet.
    await expect.poll(() => previewVar(page, '--brand-primary')).toBe('#b42318')
    await expect(page.getByTestId('branding-preview').first()).toContainText('Acme Ideas')
    expect(await rootVar(page, '--brand-primary')).toBe('#1d5fa8')
    await expect(page.getByText('Unsaved changes')).toBeVisible()

    const puts: unknown[] = []
    page.on('request', (request) => {
      if (request.method() === 'PUT' && request.url().endsWith('/admin/branding')) {
        puts.push(request.postDataJSON())
      }
    })
    await page.getByRole('button', { name: /Save branding/ }).click()
    await expect(page.getByText('Branding saved')).toBeVisible()
    expect(puts).toEqual([
      {
        app_name: 'Acme Ideas',
        primary_color: '#b42318',
        accent_color: null,
        font: 'ibm_plex_sans',
        email_footer: null,
        logo_asset_id: null,
        favicon_asset_id: null,
      },
    ])
    // The shell: colours, font, name in the sidebar and the tab title.
    await expect.poll(() => rootVar(page, '--brand-primary')).toBe('#b42318')
    expect(await rootVar(page, '--brand-font')).toBe('"IBM Plex Sans"')
    await expect(page.getByRole('complementary').first().getByText('Acme Ideas')).toBeVisible()
    await expect(page).toHaveTitle(/Acme Ideas$/)
  })

  test('leaving with unsaved changes asks first', async ({ page }) => {
    await page.goto('/settings/branding')
    await page.getByLabel('App name').fill('Acme Ideas')
    await page
      .getByRole('navigation', { name: 'Settings sections' })
      .getByRole('link', { name: 'Email' })
      .click()
    const dialog = page.getByRole('alertdialog', { name: 'Leave without saving?' })
    await expect(dialog).toContainText('Your changes to the branding haven’t been saved.')
    await dialog.getByRole('button', { name: 'Keep editing' }).click()
    await expect(page.getByLabel('App name')).toHaveValue('Acme Ideas')
  })

  test('colours are hex only, with contrast advice; invalid values never save', async ({
    page,
  }) => {
    await page.goto('/settings/branding')
    const primary = page.getByRole('textbox', { name: 'Primary colour', exact: true })
    await primary.fill('red; } body { display: none')
    await page.getByRole('button', { name: /Save branding/ }).click()
    await expect(primary).toBeFocused()
    await expect(primary).toHaveAccessibleDescription(/Use a hex colour/)
    // Mid-grey: neither white nor dark text reaches 4.5:1 on it.
    await primary.fill('#787878')
    await expect(page.getByTestId('branding-primary_color-advice')).toContainText('AA needs 4.5:1')
    await primary.fill('#1d5fa8')
    await expect(page.getByTestId('branding-primary_color-advice')).toContainText('meets AA')
  })

  test('a logo uploads as the raw file, shows as an image, and saves with the form', async ({
    page,
  }) => {
    await page.goto('/settings/branding')
    const logo = page.getByRole('group', { name: 'Logo' })
    const upload = page.waitForRequest(
      (request) => request.method() === 'POST' && request.url().includes('/admin/branding/assets'),
    )
    await logo.locator('input[type="file"]').setInputFiles({
      name: 'logo.png',
      mimeType: 'image/png',
      buffer: PNG,
    })
    const request = await upload
    expect(request.headers()['content-type']).toBe('image/png')
    expect(new URL(request.url()).searchParams.get('kind')).toBe('logo')
    await expect(logo.getByRole('img', { name: 'The logo you chose' })).toBeVisible()
    await expect(logo.getByText(/PNG · 1 × 1/)).toBeVisible()
    await page.getByRole('button', { name: /Save branding/ }).click()
    await expect(page.getByText('Branding saved')).toBeVisible()
    // Only ever an <img> (never inline SVG) in the shell too.
    await expect(page.locator('aside img[src^="/api/v1/branding/assets/"]').first()).toBeVisible()
  })

  test('files that aren’t PNG or SVG are refused with a reason', async ({ page }) => {
    await page.goto('/settings/branding')
    const favicon = page.getByRole('group', { name: 'Favicon' })
    await favicon.locator('input[type="file"]').setInputFiles({
      name: 'icon.gif',
      mimeType: 'image/gif',
      buffer: Buffer.from('GIF89a'),
    })
    await expect(favicon.getByRole('alert')).toHaveText('Choose a PNG or SVG file.')
    // An SVG with script: the API refuses it (here, the mock's allow-list).
    await favicon.locator('input[type="file"]').setInputFiles({
      name: 'icon.svg',
      mimeType: 'image/svg+xml',
      buffer: Buffer.from(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
      ),
    })
    await expect(favicon.getByRole('alert')).toContainText('That image can’t be used')
  })

  test('the branding page is axe-clean in both themes and works at 390 px', async ({ page }) => {
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme })
      await page.goto('/settings/branding')
      await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/settings/branding')
    await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  })

  test('a project’s branding override: only where it faces outward', async ({ page }) => {
    await page.goto('/p/sustainability/settings?tab=branding')
    const panel = page.getByRole('tabpanel', { name: 'Branding' })
    await expect(panel.getByRole('heading', { name: 'Branding', exact: true })).toBeVisible()
    await expect(panel.getByRole('textbox', { name: 'Primary colour', exact: true })).toHaveValue(
      '#2e7d4f',
    )
    // Previews of the public form and emails only (the app keeps the global branding).
    await expect(panel.getByRole('tab', { name: 'App' })).toHaveCount(0)
    await expect(panel.getByRole('tab', { name: 'Public form' })).toBeVisible()
    // Empty fields inherit the global branding, and say so.
    await expect(panel.getByText('From the global branding')).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Use the global one' })).toBeVisible()
    await panel.getByRole('button', { name: 'Use the global branding' }).click()
    const puts: unknown[] = []
    page.on('request', (request) => {
      if (
        request.method() === 'PUT' &&
        request.url().includes('/projects/sustainability/branding')
      ) {
        puts.push(request.postDataJSON())
      }
    })
    await panel.getByRole('button', { name: /Save branding/ }).click()
    await expect(page.getByText('Project branding saved')).toBeVisible()
    expect(puts).toEqual([
      {
        app_name: null,
        primary_color: null,
        accent_color: null,
        font: null,
        email_footer: null,
        logo_asset_id: null,
        favicon_asset_id: null,
      },
    ])
    expect(await seriousViolations(page)).toEqual([])
  })
})

test('anyone else gets the ordinary 404 for /settings/branding', async ({ page }) => {
  await page.goto('/settings/branding')
  await expect(
    page.getByRole('heading', { level: 1, name: 'We couldn’t find that page' }),
  ).toBeVisible()
  await expect(
    page
      .getByRole('navigation', { name: 'Settings sections' })
      .getByRole('link', { name: 'Branding' }),
  ).toHaveCount(0)
})
