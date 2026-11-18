import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

function createTinyPngBuffer(): Buffer {
  // Valid 1x1 white PNG
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64'
  );
}

test.describe('tranX v3 Full Click-Through, Responsive & Accessibility Gate', () => {
  test('Desktop 1280x800: Terang & Gelap, 4 modes, IME guard, Pin+Undo, Glossary, Settings & Axe AA', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => consoleErrors.push(err.message));

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/?e2e=1');

    // 1. Verify greeting & empty stage
    await expect(page.getByRole('heading', { name: 'Mau baca apa hari ini?' })).toBeVisible();

    // 2. Verify Desktop geometry: K/Bilah mode sits BELOW K/Composer
    const composerBox = await page.locator('.composer-slot').boundingBox();
    const modeBarBox = await page.locator('.mode-bar-slot').boundingBox();
    expect(composerBox).not.toBeNull();
    expect(modeBarBox).not.toBeNull();
    expect(modeBarBox!.y).toBeGreaterThan(composerBox!.y);

    // 3. Verify WCAG AA Axe-Core on Terang
    const axeLight = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();
    expect(axeLight.violations).toEqual([]);

    // 4. Verify Disematkan strictly above Terbaru & Pin/Unpin + Undo Toast
    const pinnedSec = await page.locator('section[aria-label="Disematkan"]').boundingBox();
    const recentSec = await page.locator('section[aria-label="Terbaru"]').boundingBox();
    expect(pinnedSec!.y).toBeLessThan(recentSec!.y);

    await page
      .getByRole('button', { name: /Menu riwayat Catatan Dialog Stasiun Kyoto/i })
      .click();
    await page.getByRole('menuitem', { name: 'Sematkan' }).click();
    await expect(page.getByText('Percakapan disematkan ke atas')).toBeVisible();
    await page.getByRole('button', { name: 'Urungkan' }).click();

    // 5. Verify Japanese IME composition guard vs real Enter submit
    const textarea = page.locator('textarea.composer-textarea');
    await textarea.fill('千早は小さく笑った。');
    await textarea.dispatchEvent('keydown', {
      key: 'Enter',
      isComposing: true,
      keyCode: 229,
    });
    // Still on empty home because IME composition was active
    await expect(page.locator('textarea.composer-textarea')).toHaveValue('千早は小さく笑った。');

    // Real Enter sends turn and renders Charter prose + NameChip
    await textarea.press('Enter');
    await expect(page.locator('.assistant-prose').first()).toContainText('Chihaya');
    await expect(page.getByRole('button', { name: '千早 → Chihaya' })).toBeVisible();
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_desktop_terang.png',
    });

    // 6. Verify Voice Dictation (Dikte suara) inside K/Composer
    await page.getByRole('button', { name: 'Dikte suara' }).click();
    await expect(page.locator('textarea.composer-textarea')).toHaveValue(/千早/, {
      timeout: 4000,
    });

    // 7. Verify Target Language Pill (Jepang -> Inggris)
    await page.getByRole('button', { name: /Jepang → Indonesia/ }).click();
    await page.getByRole('menuitemradio', { name: 'Jepang → Inggris' }).click();
    await expect(page.getByRole('button', { name: /Jepang → Inggris/ })).toBeVisible();

    // 8. Verify Mode Gambar: Berdampingan & Hamparan gambar (<canvas>)
    await page.getByRole('tab', { name: 'Gambar' }).click();
    await page.locator('input[type="file"][accept*="image/png"]').setInputFiles({
      name: 'panel-manga.png',
      mimeType: 'image/png',
      buffer: createTinyPngBuffer(),
    });
    await page.getByRole('button', { name: 'Kirim' }).click();
    await expect(page.getByRole('tab', { name: 'Berdampingan' })).toBeVisible();
    await page.getByRole('tab', { name: 'Hamparan gambar' }).click();
    await expect(page.locator('canvas')).toBeVisible();

    // 9. Verify Mode Dokumen: arsip.rar stays visible with Galat reason, .srt uploads & opens Baca berdampingan
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('tab', { name: 'Dokumen' }).click();
    const docInput = page.locator('input[type="file"][accept*=".epub"]');
    await docInput.setInputFiles({
      name: 'arsip.rar',
      mimeType: 'application/vnd.rar',
      buffer: Buffer.from('Rar!'),
    });
    await expect(page.getByText(/Format \.rar tidak didukung/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Kirim' })).toBeDisabled();
    await page.getByRole('button', { name: 'Hapus lampiran arsip.rar' }).click();

    await docInput.setInputFiles({
      name: 'bab-03.srt',
      mimeType: 'text/plain',
      buffer: Buffer.from('1\n00:00:01,000 --> 00:00:03,000\n千早は走った。\n'),
    });
    await page.getByRole('button', { name: 'Kirim' }).click();
    await expect(page.getByRole('button', { name: 'Baca berdampingan' })).toBeVisible();
    await page.getByRole('button', { name: 'Baca berdampingan' }).click();
    await expect(page.getByRole('button', { name: 'Kembali ke percakapan' })).toBeVisible();
    await page.getByRole('button', { name: 'Kembali ke percakapan' }).click();

    // 10. Verify Mode Link + /web viewer
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('tab', { name: 'Link' }).click();
    await page.getByPlaceholder(/https:\/\//).fill('https://www.aozora.gr.jp/cards/1.html');
    await page.getByRole('button', { name: 'Terjemahkan halaman' }).click();
    await expect(
      page.getByRole('button', { name: 'Buka halaman terjemahan penuh' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).click();
    await expect(page.locator('iframe[title="Pembaca Halaman Terjemahan"]')).toBeVisible();
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 11. Verify Lainnya -> Berkas saya & Daftar nama (14-field glossary)
    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Berkas saya' }).click();
    await expect(page.getByRole('heading', { name: 'Berkas saya' })).toBeVisible();
    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Daftar nama' }).click();
    await expect(page.getByRole('heading', { name: 'Daftar nama' })).toBeVisible();
    await page.getByPlaceholder('Contoh: 鴉羽').fill('鴉羽');
    await page.getByPlaceholder('Contoh: Karasuba').first().fill('Karasuba');
    await page.getByRole('button', { name: 'Kunci ejaan nama' }).click();
    await expect(page.getByText('鴉羽')).toBeVisible();
    await page.getByRole('button', { name: 'Kembali ke ruang baca' }).click();

    // 12. Verify Setelan 4 tabs (Umum, Akun, Data, Lanjutan), Dark Mode (Gelap) + Axe AA, UI Lang switch + Undo, and Logout flow
    await page.locator('.account-row-btn').click();
    await page.getByRole('menuitem', { name: /Setelan/ }).click();
    await page.getByRole('button', { name: 'Gelap' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-tranx-v3', 'Gelap');

    await page.getByRole('tab', { name: 'Akun' }).click();
    await page.getByRole('button', { name: 'Buat kode pasangan' }).click();
    await expect(page.getByText('482915')).toBeVisible();

    await page.getByRole('tab', { name: 'Data' }).click();
    await page.getByRole('button', { name: 'Buat token Pintasan baru' }).click();
    await expect(page.getByText(/txi_/)).toBeVisible();

    await page.getByRole('tab', { name: 'Lanjutan' }).click();
    await page.getByRole('button', { name: 'Cek mesin sekarang' }).click();
    await expect(page.getByText(/gemini-2.5-flash-lite: Siap/)).toBeVisible();
    await page.keyboard.press('Escape');

    // Axe WCAG AA in Gelap mode
    const axeDark = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();
    expect(axeDark.violations).toEqual([]);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_desktop_gelap.png',
    });

    // Switch UI Language to English and back via Undo
    await page.locator('.account-row-btn').click();
    await page.getByRole('menuitem', { name: /Bahasa tampilan/ }).click();
    await expect(
      page.getByRole('heading', { name: 'What would you like to read today?' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Undo' }).click();
    await expect(page.getByRole('heading', { name: 'Mau baca apa hari ini?' })).toBeVisible();

    // Sign out dialog -> /masuk -> /masuk/kode
    await page.locator('.account-row-btn').click();
    await page.getByRole('menuitem', { name: 'Keluar' }).click();
    await expect(page.getByRole('heading', { name: 'Keluar dari tranX?' })).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Keluar' }).click();
    await expect(page.getByRole('button', { name: 'Masuk dengan Google' })).toBeVisible();
    await page.getByRole('button', { name: /kode pasangan 6 angka/ }).click();
    await page.getByLabel('Kode pasangan 6 angka').fill('482915');
    await page.getByRole('button', { name: 'Masuk dengan kode' }).click();
    await expect(page.getByRole('heading', { name: 'Mau baca apa hari ini?' })).toBeVisible();

    expect(consoleErrors).toEqual([]);
  });

  test('Tablet 820x1180 & Mobile 390x844: Zero horizontal overflow, >= 44px tap targets, Mode bar ABOVE Composer, Laci & Bottom Sheet', async ({
    page,
  }) => {
    // 1. Tablet 820x1180 check
    await page.setViewportSize({ width: 820, height: 1180 });
    await page.goto('/?e2e=1');
    const tabletOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth
    );
    expect(tabletOverflow).toBe(false);

    // 2. Mobile 390x844 check
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/?e2e=1');
    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth
    );
    expect(mobileOverflow).toBe(false);

    // Verify Mobile geometry: K/Bilah mode sits ABOVE K/Composer (Gemini Mobile ergonomics)
    const composerBox = await page.locator('.composer-slot').boundingBox();
    const modeBarBox = await page.locator('.mode-bar-slot').boundingBox();
    expect(modeBarBox!.y).toBeLessThan(composerBox!.y);

    const modeTrayClipped = await page
      .locator('.mode-tray')
      .evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(modeTrayClipped).toBe(false);

    // Verify >= 44x44px tap targets on mobile send & mic buttons
    const micBox = await page.getByRole('button', { name: 'Dikte suara' }).boundingBox();
    const sendBox = await page.getByRole('button', { name: 'Kirim' }).boundingBox();
    expect(micBox!.width).toBeGreaterThanOrEqual(44);
    expect(micBox!.height).toBeGreaterThanOrEqual(44);
    expect(sendBox!.width).toBeGreaterThanOrEqual(44);
    expect(sendBox!.height).toBeGreaterThanOrEqual(44);

    // Verify Mobile Laci (320px leaving >= 56px scrim tap area) & Bottom Sheet (K/Lembar bawah)
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_390.png',
    });
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    const sidebarBox = await page.locator('aside.sidebar').boundingBox();
    expect(sidebarBox!.width).toBeLessThanOrEqual(334);
    await page
      .getByRole('button', { name: /Menu riwayat Bab 1: Hujan di Gerbang Rashomon/i })
      .click();
    await expect(page.getByRole('button', { name: 'Lepas sematan' })).toBeVisible();
    await page.keyboard.press('Escape');

    // Mobile Target Language Bottom Sheet (H13)
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /Jepang → Indonesia/ }).click();
    await expect(page.getByRole('dialog', { name: 'Bahasa terjemahan' })).toBeVisible();
  });
});
