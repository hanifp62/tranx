import fs from 'node:fs';
import zlib from 'node:zlib';
import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

function createTinyPngBuffer(): Buffer {
  // Valid 1x1 white PNG
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64'
  );
}

function createFlatePdfBuffer(englishParagraph: string): Buffer {
  const escaped = englishParagraph.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
  const contentStream = `BT /F1 12 Tf 72 720 Td (${escaped}) Tj ET`;
  const deflated = zlib.deflateSync(Buffer.from(contentStream, 'latin1'));
  const head = Buffer.from(
    `%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n` +
      `2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n` +
      `3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n` +
      `4 0 obj\n<< /Length ${deflated.length} /Filter /FlateDecode >>\nstream\n`,
    'latin1'
  );
  const tail = Buffer.from(`\nendstream\nendobj\n%%EOF\n`, 'latin1');
  return Buffer.concat([head, deflated, tail]);
}

test.describe('tranX v3 Full Click-Through, Multilingual Matrix, Direct Engine & Accessibility Gate', () => {
  test('Desktop 1280x800: Terang & Gelap, 9-pair Bidirectional + Auto-Detect Matrix, 4 modes, IME guard, Pin+Undo, Glossary, Settings & Axe AA', async ({
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

    // 2. Verify Desktop geometry: K/Bilah mode sits BELOW K/Composer & 56px optical top rail aligns sidebar + header
    const composerBox = await page.locator('.composer-slot').boundingBox();
    const modeBarBox = await page.locator('.mode-bar-slot').boundingBox();
    expect(composerBox).not.toBeNull();
    expect(modeBarBox).not.toBeNull();
    expect(modeBarBox!.y).toBeGreaterThan(composerBox!.y);
    const sidebarTopBox = await page.locator('.sidebar-top-row').boundingBox();
    const stageHeaderBox = await page.locator('.stage-header').boundingBox();
    expect(sidebarTopBox).not.toBeNull();
    expect(stageHeaderBox).not.toBeNull();
    expect(Math.abs(sidebarTopBox!.height - stageHeaderBox!.height)).toBeLessThanOrEqual(2);
    const desktopOverflow1280 = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth
    );
    expect(desktopOverflow1280).toBe(false);

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

    // 5. Verify live Auto-Detection (ID, EN, JA) + Japanese IME composition guard vs real Enter submit
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Deteksi bahasa' })
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Indonesia' })
    ).toBeVisible();

    const textarea = page.locator('textarea.composer-textarea');
    await textarea.fill('Selamat pagi, bagaimana kabar hari ini?');
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Deteksi · Indonesia' })
    ).toBeVisible();

    await textarea.fill('Good morning, what are we reading today?');
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Deteksi · Inggris' })
    ).toBeVisible();

    await textarea.fill('千早は小さく笑った。');
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Deteksi · Jepang' })
    ).toBeVisible();

    await textarea.dispatchEvent('keydown', {
      key: 'Enter',
      isComposing: true,
      keyCode: 229,
    });
    await expect(page.locator('textarea.composer-textarea')).toHaveValue('千早は小さく笑った。');

    // Real Enter sends turn and renders Charter prose + NameChip
    await textarea.press('Enter');
    await expect(page.locator('.assistant-prose').first()).toContainText('Chihaya');
    await expect(page.getByRole('button', { name: '千早 \u2192 Chihaya' })).toBeVisible();
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_desktop_terang.png',
    });

    // 6. Verify Voice Dictation (Dikte suara) inside K/Composer
    await page.getByRole('button', { name: 'Dikte suara' }).click();
    await expect(page.locator('textarea.composer-textarea')).toHaveValue(/千早/, {
      timeout: 4000,
    });
    await page.locator('textarea.composer-textarea').fill('');

    // 7. Verify Full Bidirectional Pairs (ID->JA, Swap JA->ID, EN->ID, ID->EN, EN->JA, Auto->EN)
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Indonesia' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Jepang' }).click();
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Indonesia' })
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Jepang' })
    ).toBeVisible();

    // Send Indonesia -> Jepang turn
    await page
      .locator('textarea.composer-textarea')
      .fill('Chihaya tersenyum tenang di bawah atap.');
    await page.locator('textarea.composer-textarea').press('Enter');
    await expect(page.locator('.assistant-prose').last()).toContainText('千早');

    // Swap button flips Indonesia -> Jepang into Jepang -> Indonesia
    await page.getByRole('button', { name: 'Tukar bahasa' }).click();
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Jepang' })
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Indonesia' })
    ).toBeVisible();

    // Inggris -> Indonesia (en-id)
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Inggris' }).click();
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Inggris' })
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Indonesia' })
    ).toBeVisible();

    // Swap into Indonesia -> Inggris (id-en)
    await page.getByRole('button', { name: 'Tukar bahasa' }).click();
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Indonesia' })
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Inggris' })
    ).toBeVisible();

    // Inggris -> Jepang (en-ja)
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Inggris' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Jepang' }).click();
    await expect(
      page.getByRole('button', { name: 'Bahasa sumber: Inggris' })
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Jepang' })
    ).toBeVisible();

    // Deteksi bahasa -> Inggris (auto-en)
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Deteksi bahasa' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Inggris' }).click();
    await expect(
      page.getByRole('button', { name: 'Bahasa tujuan: Inggris' })
    ).toBeVisible();

    // 8. Verify True Mode Page Switching (zero Teks bubble / textarea overlap) + Mode Gambar
    await page.getByRole('tab', { name: 'Gambar' }).click();
    await expect(page.locator('textarea.composer-textarea')).toHaveCount(0);
    await expect(page.locator('.user-bubble')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Pilih gambar' })).toBeVisible();

    await page.getByRole('tab', { name: 'Dokumen' }).click();
    await expect(page.locator('textarea.composer-textarea')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Pilih berkas' })).toBeVisible();

    // Clicking Lainnya and then clicking outside dismisses popover cleanly without overlapping Search
    await page.getByRole('button', { name: 'Lainnya' }).click();
    await expect(page.getByRole('menuitem', { name: 'Berkas saya' })).toBeVisible();
    await page.locator('.popover-dismiss-backdrop').click({ position: { x: 640, y: 200 } });
    await expect(page.getByRole('menuitem', { name: 'Berkas saya' })).toHaveCount(0);

    await page.getByRole('tab', { name: 'Gambar' }).click();
    await page.locator('input[type="file"][accept*="image/png"]').setInputFiles({
      name: 'panel-manga.png',
      mimeType: 'image/png',
      buffer: createTinyPngBuffer(),
    });
    await page.getByRole('button', { name: 'Terjemahkan gambar' }).click();
    await expect(page.getByRole('tab', { name: 'Berdampingan' })).toBeVisible();
    await page.getByRole('tab', { name: 'Hamparan gambar' }).click();
    await expect(page.locator('canvas')).toBeVisible();

    // 9. Verify Mode Dokumen: arsip.rar stays visible with Galat reason, .srt uploads & opens Baca berdampingan
    await page.getByRole('tab', { name: 'Dokumen' }).click();
    await expect(page.locator('textarea.composer-textarea')).toHaveCount(0);
    const docInput = page.locator('input[type="file"][accept*=".epub"]');
    await docInput.setInputFiles({
      name: 'arsip.rar',
      mimeType: 'application/vnd.rar',
      buffer: Buffer.from('Rar!'),
    });
    await expect(page.getByText(/Format \.rar tidak didukung/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Terjemahkan dokumen' })).toBeDisabled();
    await page.getByRole('button', { name: 'Hapus lampiran arsip.rar' }).click();

    await docInput.setInputFiles({
      name: 'bab-03.srt',
      mimeType: 'text/plain',
      buffer: Buffer.from('1\n00:00:01,000 --> 00:00:03,000\n千早は走った。\n'),
    });
    await page.getByRole('button', { name: 'Terjemahkan dokumen' }).click();
    await expect(page.getByRole('button', { name: 'Baca berdampingan' })).toBeVisible();
    await page.getByRole('button', { name: 'Baca berdampingan' }).click();
    await expect(page.getByRole('button', { name: 'Kembali ke percakapan' })).toBeVisible();
    await page.getByRole('button', { name: 'Kembali ke percakapan' }).click();

    // 10. Verify Mode Link switches directly to dedicated Link page + Ebook Reader + Bab berikutnya + Daftar bab + Situs Terjemahan + auto-translated Google Translate URL (and zero Alat Web & HP)
    await page.getByRole('tab', { name: 'Link' }).click();
    await expect(page.locator('textarea.composer-textarea')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Alat Web & HP|Web & Mobile tools/i })).toHaveCount(0);
    await page.getByPlaceholder(/https:\/\//).fill('https://www.aozora.gr.jp/cards/1.html');
    await page.getByRole('button', { name: 'Terjemahkan halaman' }).click();
    await expect(page.getByText(/Ebook terdeteksi/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Buka situs terjemahan' })).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Buka halaman terjemahan penuh' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).click();
    // Mode is currently auto-en from Step 7 -> heading renders in English first, then switch to auto-id inside /web
    await expect(page.getByRole('heading', { name: 'Chapter 1: Rain at Rashomon' })).toBeVisible();
    await page.getByLabel('Pasangan bahasa').selectOption('auto-id');
    await expect(page.getByRole('heading', { name: 'Bab 1: Hujan di Rashomon' })).toBeVisible();
    // Verify Desktop /web 3-zone topbar stays single-row (<= 64px) and zero horizontal overflow!
    const desktopWebTopbar = await page.locator('.web-viewer-topbar').boundingBox();
    expect(desktopWebTopbar).not.toBeNull();
    expect(desktopWebTopbar!.height).toBeLessThanOrEqual(66);
    const webOverflow1280 = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth
    );
    expect(webOverflow1280).toBe(false);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_desktop_web_reader_1280.png',
    });
    // Toggle Berdampingan (bilingual) -> verify TRUE 2-column side-by-side layout on Desktop (>= 1024px)!
    await page.getByRole('button', { name: 'Berdampingan' }).click();
    await expect(page.getByText('千早は小さく笑った。')).toBeVisible();
    const biSrcBox = await page.locator('.bilingual-pair-card .bilingual-pair-src').first().boundingBox();
    const biDstBox = await page.locator('.bilingual-pair-card .novel-reader-para').first().boundingBox();
    expect(biSrcBox).not.toBeNull();
    expect(biDstBox).not.toBeNull();
    expect(biDstBox!.x).toBeGreaterThan(biSrcBox!.x + 200);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_desktop_web_bilingual_1280.png',
    });
    // Click Bab berikutnya -> navigates directly to Chapter 2 without re-entering any URL
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Bab berikutnya/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 2: Lentera di Kyoto' })).toBeVisible();
    await expect(page.getByText(/Anda berada di bab terakhir yang tersedia/)).toBeVisible();
    // Open Daftar bab modal -> jump back to Bab 1
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Daftar bab/ }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: /Bab 1: Hujan di Rashomon/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 1: Hujan di Rashomon' })).toBeVisible();
    // Switch to Situs Terjemahan via "Buka web terjemahan otomatis" -> stays strictly inside the SAME app tab (0 new tabs!)
    const pagesBeforeAutoSite = page.context().pages().length;
    await page.getByRole('button', { name: 'Buka web terjemahan otomatis' }).click();
    await expect(page).toHaveURL(/view=site/);
    expect(page.context().pages().length).toBe(pagesBeforeAutoSite);
    await expect(page.locator('iframe[title="Pembaca Halaman Terjemahan"]')).toBeVisible();
    await expect(page.getByRole('button', { name: /Alat Web & HP|Web & Mobile tools/i })).toHaveCount(0);
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
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

    // Switch UI Language to English and back via Undo (first return to empty Baru page)
    await page.getByRole('button', { name: 'Baru' }).click();
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

  test('Direct Spark Engine (/?e2e=1&direct=1): Zero "Failed to fetch" when Cloud Functions is unreachable, Link + standalone URL in Teks + reverse glossary', async ({
    page,
  }) => {
    // Simulate Firebase Spark plan: /v1/healthz returns 404 Not Found
    await page.route('**/v1/healthz', async (route) => {
      await route.fulfill({ status: 404, body: 'Not Found' });
    });

    // Simulate real-world external CORS proxies timing out/failing so ALL HTML + TOC must succeed via r.jina.ai X-Return-Format: html!
    await page.route('https://api.allorigins.win/raw**', async (route) => {
      await route.fulfill({ status: 504, body: 'Gateway Timeout' });
    });

    // CORS-enabled Jina Reader mock matching REAL r.jina.ai X-Return-Format: html + X-With-Links-Summary: true JSON schema!
    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      const hdrs = route.request().headers();
      const hasNoCache = hdrs['x-no-cache'] === 'true';

      if (reqUrl.includes('kakuyomu.jp/works/2912051604668493030/episodes/101')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Episode 1: Best Way to Skip School',
              description: 'Short meta description that must NOT replace full episode HTML prose.',
              url: 'https://kakuyomu.jp/works/2912051604668493030/episodes/101',
              finalUrl: 'https://kakuyomu.jp/works/2912051604668493030/episodes/101',
              html: `<!doctype html><html><head><title>Episode 1: Best Way to Skip School</title></head><body><div class="widget-episodeBody"><p>Morning rain tapped softly against the classroom window.</p><p>She opened her notebook and read the letter from Tokyo.</p></div><a id="contentMain-readNextEpisode" href="/works/2912051604668493030/episodes/102">次のエピソード Episode 2</a></body></html>`,
              links: {
                '次のエピソード Episode 2':
                  'https://kakuyomu.jp/works/2912051604668493030/episodes/102',
              },
            },
          }),
        });
        return;
      }
      if (reqUrl.includes('kakuyomu.jp/works/2912051604668493030/episodes/102')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Episode 2: After School Confession',
              url: 'https://kakuyomu.jp/works/2912051604668493030/episodes/102',
              finalUrl: 'https://kakuyomu.jp/works/2912051604668493030/episodes/102',
              html: `<!doctype html><html><head><title>Episode 2: After School Confession</title></head><body><div class="widget-episodeBody"><p>Lantern light swayed quietly across the wet stone alley.</p></div><a id="contentMain-readPreviousEpisode" href="/works/2912051604668493030/episodes/101#end">前のエピソード</a><a id="contentMain-readNextEpisode" href="/works/2912051604668493030/episodes/103">次のエピソード</a></body></html>`,
              links: {
                '前のエピソード': 'https://kakuyomu.jp/works/2912051604668493030/episodes/101#end',
                '次のエピソード': 'https://kakuyomu.jp/works/2912051604668493030/episodes/103',
              },
            },
          }),
        });
        return;
      }
      if (reqUrl.includes('kakuyomu.jp/works/2912051604668493030/episodes/103')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Episode 3: Tatsuya Secret Effort',
              url: 'https://kakuyomu.jp/works/2912051604668493030/episodes/103',
              finalUrl: 'https://kakuyomu.jp/works/2912051604668493030/episodes/103',
              html: `<!doctype html><html><head><title>Episode 3: Tatsuya Secret Effort</title></head><body><div class="widget-episodeBody"><p>Chihaya stood quietly under the wooden gate while listening to the rain.</p></div><a id="contentMain-readPreviousEpisode" href="/works/2912051604668493030/episodes/102#end">前のエピソード</a></body></html>`,
              links: {
                '前のエピソード': 'https://kakuyomu.jp/works/2912051604668493030/episodes/102#end',
              },
            },
          }),
        });
        return;
      }
      if (reqUrl.includes('kakuyomu.jp/works/2912051604668493030')) {
        // Simulate real-world stale Jina tracker cache when X-No-Cache is not sent!
        if (!hasNoCache) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            headers: { 'Access-Control-Allow-Origin': '*' },
            body: JSON.stringify({
              code: 200,
              data: {
                title: 'https://penta.a.one.impact-ad.jp/psm/1.0/actualizar',
                finalUrl: 'https://penta.a.one.impact-ad.jp/psm/1.0/actualizar',
                content: 'A 1x1 image, likely be a tacker probe',
              },
            }),
          });
          return;
        }
        const nextData = JSON.stringify({
          props: {
            pageProps: {
              __APOLLO_STATE__: {
                'Work:2912051604668493030': {
                  title: 'Kyoto School Story',
                  tableOfContentsV2: [{ __ref: 'TableOfContentsChapter:' }],
                },
                'TableOfContentsChapter:': {
                  episodeUnions: [
                    { __ref: 'Episode:101' },
                    { __ref: 'Episode:102' },
                    { __ref: 'Episode:103' },
                  ],
                },
                'Episode:101': { title: 'Episode 1: Best Way to Skip School' },
                'Episode:102': { title: 'Episode 2: After School Confession' },
                'Episode:103': { title: 'Episode 3: Tatsuya Secret Effort' },
              },
            },
          },
        });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Kyoto School Story - Kakuyomu',
              url: 'https://kakuyomu.jp/works/2912051604668493030',
              finalUrl: 'https://kakuyomu.jp/works/2912051604668493030',
              html: `<!doctype html><html><head><title>Kyoto School Story - Kakuyomu</title><script id="__NEXT_DATA__" type="application/json">${nextData}</script></head><body><h1>Kyoto School Story</h1><p>A school romance novel in Kyoto.</p></body></html>`,
              links: {
                '1話目から読む': 'https://kakuyomu.jp/works/2912051604668493030/episodes/101',
              },
            },
          }),
        });
        return;
      }
      const isCh2 = reqUrl.includes('2.html');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({
          code: 200,
          data: isCh2
            ? {
                title: 'Chapter 2: The Lanterns of Kyoto',
                url: 'https://www.aozora.gr.jp/cards/2.html',
                finalUrl: 'https://www.aozora.gr.jp/cards/2.html',
                html: `<!doctype html><html><head><title>Chapter 2: The Lanterns of Kyoto</title></head><body><h1>Chapter 2: The Lanterns of Kyoto</h1><p>Lantern light swayed quietly across the wet stone alley.</p><nav><a rel="prev" href="/cards/1.html">Previous Chapter</a></nav></body></html>`,
                links: { 'Previous Chapter': 'https://www.aozora.gr.jp/cards/1.html' },
              }
            : {
                title: 'The Rainy Gate of Kyoto',
                url: 'https://www.aozora.gr.jp/cards/1.html',
                finalUrl: 'https://www.aozora.gr.jp/cards/1.html',
                html: `<!doctype html><html><head><title>The Rainy Gate of Kyoto</title><script>window.__xss=91234;</script></head><body onload="window.__xss=91234"><h1>The Rainy Gate of Kyoto</h1><p>Chihaya stood quietly under the wooden gate while listening to the rain.</p><p>「…………」</p><p>She opened her notebook and read the letter from Tokyo.</p><nav><a rel="next" href="/cards/2.html" onclick="window.__xss=91234">Next Chapter</a></nav></body></html>`,
                links: { 'Next Chapter': 'https://www.aozora.gr.jp/cards/2.html' },
              },
        }),
      });
    });

    // CORS-enabled Google GTX mock supporting both batched POST and GET while preserving [[E0]] & [[#0]] markers
    let gtxRequestCount = 0;
    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
      gtxRequestCount += 1;
      const reqUrl = new URL(route.request().url());
      const tl = reqUrl.searchParams.get('tl') || 'id';
      const postParams = new URLSearchParams(route.request().postData() || '');
      const q = postParams.get('q') || reqUrl.searchParams.get('q') || '';
      const lines = q.split('\n');
      const translatedLines = lines.map((line) => {
        if (tl === 'ja') {
          return line
            .replace(/berjalan pelan di stasiun/gi, '駅を静かに歩いた')
            .replace(/The Rainy Gate of Kyoto/gi, '京都の雨の門');
        }
        if (tl === 'en') {
          return line.replace(/Selamat pagi/gi, 'Good morning');
        }
        return line
          .replace(/Episode 1: Best Way to Skip School/gi, 'Bab 1: Cara Terbaik Bolos Sekolah')
          .replace(/Episode 2: After School Confession/gi, 'Bab 2: Pengakuan Sepulang Sekolah')
          .replace(/Episode 3: Tatsuya Secret Effort/gi, 'Bab 3: Usaha Rahasia Tatsuya')
          .replace(/Kyoto School Story/gi, 'Kisah Sekolah Kyoto')
          .replace(
            /Morning rain tapped softly against the classroom window/gi,
            'Hujan pagi mengetuk lembut jendela ruang kelas'
          )
          .replace(/Chapter 2: The Lanterns of Kyoto/gi, 'Bab 2: Lentera di Kyoto')
          .replace(
            /Lantern light swayed quietly across the wet stone alley/gi,
            'Cahaya lentera ``Shobomaru" bergoyang tenang di sepanjang gang batu basah'
          )
          .replace(/Next Chapter/gi, 'Bab berikutnya')
          .replace(/Previous Chapter/gi, 'Bab sebelumnya')
          .replace(/おはようございます。?/g, 'Selamat pagi')
          .replace(/The Rainy Gate of Kyoto/gi, 'Gerbang Hujan di Kyoto')
          .replace(
            /stood quietly under the wooden gate while listening to the rain/gi,
            'berdiri tenang di bawah gerbang kayu sambil mendengarkan hujan'
          )
          .replace(
            /She opened her notebook and read the letter from Tokyo/gi,
            'Ia membuka buku catatannya dan membaca surat dari Tokyo'
          );
      });
      const segments = translatedLines.map((t, idx) => [
        idx < translatedLines.length - 1 ? `${t}\n` : t,
        lines[idx] || '',
      ]);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify([segments, null, 'en']),
      });
    });

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/?e2e=1&direct=1');

    // 1. Mode Link with bare URL (no https:// prefix) -> zero "Failed to fetch", auto-detects Ebook + Next Chapter
    await page.getByRole('tab', { name: 'Link' }).click();
    await page.getByPlaceholder(/https:\/\//).fill('www.aozora.gr.jp/cards/1.html');
    await page.getByRole('button', { name: 'Terjemahkan halaman' }).click();

    await expect(page.getByRole('main').getByText('Gerbang Hujan di Kyoto')).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi/)).toBeVisible();
    await expect(page.getByText(/Failed to fetch/i)).toHaveCount(0);

    // Open full translated Ebook reader (/web Mode Ebook)
    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).click();
    await expect(page.getByRole('heading', { name: 'Gerbang Hujan di Kyoto' })).toBeVisible();

    // Switch to Situs Terjemahan -> verify real HTML translated, <script> stripped, and <a href> rewritten to /web?url=...&view=site
    await page.getByRole('button', { name: 'Situs Terjemahan' }).click();
    const readerFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(readerFrame.locator('h1')).toContainText('Gerbang Hujan di Kyoto');
    await expect(readerFrame.locator('script')).toHaveCount(0);
    const rewrittenNextHref = await readerFrame.locator('a').first().getAttribute('href');
    expect(rewrittenNextHref || '').toContain('/web?url=');
    expect(rewrittenNextHref || '').toContain('view=site');
    expect(
      await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)
    ).toBeUndefined();

    // Click Bab berikutnya from Ebook dock -> translates Chapter 2 automatically
    await page.getByRole('button', { name: 'Mode Ebook' }).click();
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Bab berikutnya/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 2: Lentera di Kyoto' })).toBeVisible();
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 1a. Real Kakuyomu Ebook Auto-TOC Enrichment (even when external CORS proxies time out!):
    // Opening episode 103 auto-fetches /works/2912051604668493030 TOC via Jina X-No-Cache HTML (3/3),
    // translates chapter titles, allows jumping to Chapter 1 ("Baca dari Bab 1"), advancing Chapter 1 -> Chapter 2,
    // AND clicking Next inside Situs Terjemahan keeps page 2 translated in auto-id (NEVER reverts to source language!)
    await page.getByRole('tab', { name: 'Link' }).click();
    await page
      .getByPlaceholder(/https:\/\//)
      .fill('https://kakuyomu.jp/works/2912051604668493030/episodes/103');
    await page.getByRole('button', { name: 'Terjemahkan halaman' }).click();
    await expect(page.getByText(/Ebook terdeteksi · 3 \/ 3/)).toBeVisible();

    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).last().click();
    await expect(page.getByRole('heading', { name: 'Bab 3: Usaha Rahasia Tatsuya' })).toBeVisible();
    await expect(page.getByText(/Anda berada di bab terakhir yang tersedia \(3 \/ 3\)/)).toBeVisible();
    await page.locator('.ebook-next-card').getByRole('button', { name: 'Baca dari Bab 1' }).click();
    await expect(page.getByRole('heading', { name: 'Bab 1: Cara Terbaik Bolos Sekolah' })).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi · 1 \/ 3/)).toBeVisible();
    // Ensure full HTML episode body prose is rendered (never replaced by 1-line meta description!)
    await expect(page.locator('.novel-reader-body')).toContainText(
      'Hujan pagi mengetuk lembut jendela ruang kelas'
    );
    await expect(page.locator('.novel-reader-body')).toContainText(
      'Ia membuka buku catatannya dan membaca surat dari Tokyo'
    );
    await expect(page.locator('.novel-reader-body')).not.toContainText('Short meta description');
    // Switch to Situs Terjemahan on Episode 1 -> click rewritten Next Episode link inside iframe -> Episode 2 stays translated!
    await page.getByRole('button', { name: 'Situs Terjemahan' }).click();
    const kakuSiteFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(kakuSiteFrame.locator('body')).toContainText(
      'Hujan pagi mengetuk lembut jendela ruang kelas'
    );
    const kakuNextInSite = await kakuSiteFrame.locator('a').first().getAttribute('href');
    expect(kakuNextInSite || '').toContain('/web?url=');
    expect(kakuNextInSite || '').toContain('episodes%2F102');
    expect(kakuNextInSite || '').toContain('mode=auto-id');
    expect(kakuNextInSite || '').toContain('view=site');
    await kakuSiteFrame.locator('a').first().click();
    await expect(page).toHaveURL(/episodes%2F102.*view=site|view=site.*episodes%2F102/);
    await expect(kakuSiteFrame.locator('body')).toContainText(
      'Cahaya lentera "Shobomaru" bergoyang tenang di sepanjang gang batu basah'
    );
    await expect(kakuSiteFrame.locator('body')).not.toContainText('``Shobomaru"');
    await page.getByRole('button', { name: 'Mode Ebook' }).click();
    await expect(page.getByRole('heading', { name: 'Bab 2: Pengakuan Sepulang Sekolah' })).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi · 2 \/ 3/)).toBeVisible();
    await expect(page.locator('.ebook-reading-progress-fill')).toBeAttached();
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 1a-ii. Kakuyomu Work/TOC URL -> auto-detected as Ebook TOC with "Lanjutkan baca (2 / 3)" AND "Mulai baca Bab 1"
    await page.goto('/web?url=https%3A%2F%2Fkakuyomu.jp%2Fworks%2F2912051604668493030&mode=auto-id&view=reader');
    await expect(page.getByText(/Daftar isi Ebook/)).toBeVisible();
    await expect(
      page.locator('.ebook-toc-hero').getByRole('button', { name: /Lanjutkan baca \(2 \/ 3\)/ })
    ).toBeVisible();
    await page.locator('.ebook-toc-hero').getByRole('button', { name: /Mulai baca Bab 1/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 1: Cara Terbaik Bolos Sekolah' })).toBeVisible();
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 1b. Extension-less URL shortcuts: /r/<url> and PWA /share?text=... auto-route straight into /web
    await page.goto('/r/https://www.aozora.gr.jp/cards/1.html');
    await expect(page).toHaveURL(/\/web\?url=/);
    await expect(page.getByRole('heading', { name: 'Gerbang Hujan di Kyoto' })).toBeVisible();

    await page.goto('/share?text=Baca%20novel%20https%3A%2F%2Fwww.aozora.gr.jp%2Fcards%2F1.html');
    await expect(page).toHaveURL(/\/web\?url=/);
    await expect(page.getByRole('heading', { name: 'Gerbang Hujan di Kyoto' })).toBeVisible();
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 1c. Strict Target-Language Guarantee on Deteksi -> Indonesia (auto-id):
    // Indonesian paragraphs stay verbatim Indonesian while English and Japanese in the SAME prompt become Indonesian!
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('tab', { name: 'Teks' }).click();
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Deteksi bahasa' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Indonesia' }).click();
    await page
      .locator('textarea.composer-textarea')
      .fill(
        'Ini kalimat bahasa Indonesia yang tetap harus bahasa Indonesia.\n\nThe Rainy Gate of Kyoto\n\nおはようございます'
      );
    await page.locator('textarea.composer-textarea').press('Enter');
    const mixedOut = page.locator('.assistant-prose').first();
    await expect(mixedOut).toContainText(
      'Ini kalimat bahasa Indonesia yang tetap harus bahasa Indonesia.'
    );
    await expect(mixedOut).toContainText('Gerbang Hujan di Kyoto');
    await expect(mixedOut).toContainText('Selamat pagi');

    // 1d. L1/L2 Paragraph Translation Cache: repeating an identical phrase uses 0 extra GTX network calls!
    const gtxCallsBeforeRepeat = gtxRequestCount;
    await page.locator('textarea.composer-textarea').fill('おはようございます');
    await page.locator('textarea.composer-textarea').press('Enter');
    await expect(page.locator('.assistant-prose').last()).toContainText('Selamat pagi');
    expect(gtxRequestCount).toBe(gtxCallsBeforeRepeat);

    // 2. Standalone URL pasted directly inside Mode Teks -> auto-routed to Link reader cleanly
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('tab', { name: 'Teks' }).click();
    await page
      .locator('textarea.composer-textarea')
      .fill('https://www.aozora.gr.jp/cards/1.html');
    await page.locator('textarea.composer-textarea').press('Enter');
    await expect(
      page.getByRole('button', { name: 'Buka halaman terjemahan penuh' })
    ).toBeVisible();
    await expect(page.getByText(/Failed to fetch/i)).toHaveCount(0);

    // 3. Reverse Glossary Shield in Direct Mode: Indonesia -> Jepang restores locked kanji 千早 from "Chihaya"
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('tab', { name: 'Teks' }).click();
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Indonesia' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Jepang' }).click();
    await page
      .locator('textarea.composer-textarea')
      .fill('Chihaya berjalan pelan di stasiun.');
    await page.locator('textarea.composer-textarea').press('Enter');
    await expect(page.locator('.assistant-prose').first()).toContainText('千早');
    await expect(page.locator('.assistant-prose').first()).toContainText('駅を静かに歩いた');

    // 4. Real pdfjs-dist PDF extraction & translation in Direct Spark Mode (zero Blaze needed)
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Inggris' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Indonesia' }).click();
    await page.getByRole('tab', { name: 'Dokumen' }).click();
    const directDocInput = page.locator('input[type="file"][accept*=".epub"]');
    await directDocInput.setInputFiles({
      name: 'naskah-kyoto.pdf',
      mimeType: 'application/pdf',
      buffer: createFlatePdfBuffer(
        'She opened her notebook and read the letter from Tokyo.'
      ),
    });
    await page.getByRole('button', { name: 'Terjemahkan dokumen' }).click();
    await expect(page.getByRole('button', { name: 'Baca berdampingan' })).toBeVisible();
    await expect(page.getByRole('main')).toContainText(
      'Ia membuka buku catatannya dan membaca surat dari Tokyo'
    );
    await page.getByRole('button', { name: 'Baca berdampingan' }).click();
    await expect(page.getByRole('main')).toContainText(
      'She opened her notebook and read the letter from Tokyo.'
    );
    await expect(page.getByRole('main')).toContainText(
      'Ia membuka buku catatannya dan membaca surat dari Tokyo.'
    );
    await page.getByRole('button', { name: 'Kembali ke percakapan' }).click();

    // 5. Native .ass subtitle parsing + valid .ass and genuine OOXML .docx export in Direct Spark Mode
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('tab', { name: 'Dokumen' }).click();
    const assSample = [
      '[Script Info]',
      'Title: Kyoto Episode 1',
      'ScriptType: v4.00+',
      '',
      '[Events]',
      'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
      'Dialogue: 0,0:00:01.00,0:00:04.00,Default,Chihaya,0,0,0,,{\\an8}The Rainy Gate of Kyoto',
      '',
    ].join('\n');
    await directDocInput.setInputFiles({
      name: 'episode-01.ass',
      mimeType: 'text/plain',
      buffer: Buffer.from(assSample, 'utf-8'),
    });
    await page.getByRole('button', { name: 'Terjemahkan dokumen' }).click();
    await expect(page.getByRole('button', { name: 'Baca berdampingan' })).toBeVisible();

    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Berkas saya' }).click();
    await expect(page.getByRole('main').getByText('episode-01.ass')).toBeVisible();

    const assDlPromise = page.waitForEvent('download');
    await page.getByRole('main').getByRole('button', { name: '.ass', exact: true }).first().click();
    const assDl = await assDlPromise;
    expect(assDl.suggestedFilename()).toBe('episode-01.ass');
    const assOutText = fs.readFileSync((await assDl.path())!, 'utf-8');
    expect(assOutText).toContain('[Events]');
    expect(assOutText).toContain('Dialogue: 0,0:00:01.00,0:00:04.00,Default,Chihaya,0,0,0,,{\\an8}Gerbang Hujan di Kyoto');

    const docxDlPromise = page.waitForEvent('download');
    await page.getByRole('main').getByRole('button', { name: '.docx', exact: true }).first().click();
    const docxDl = await docxDlPromise;
    expect(docxDl.suggestedFilename()).toBe('episode-01.docx');
    const docxBytes = fs.readFileSync((await docxDl.path())!);
    expect(docxBytes[0]).toBe(0x50);
    expect(docxBytes[1]).toBe(0x4b);
    expect(docxBytes.toString('latin1')).toContain('word/document.xml');
    expect(docxBytes.toString('utf-8')).toContain('Gerbang Hujan di Kyoto');

    // 6. Real Zero-Key Browser Image OCR via tesseract.js WASM (no Gemini API key needed!)
    await page.getByRole('button', { name: 'Kembali ke ruang baca' }).click();
    await page.getByRole('tab', { name: 'Gambar' }).click();
    const renderedPngBase64 = await page.evaluate(() => {
      const c = document.createElement('canvas');
      c.width = 720;
      c.height = 180;
      const ctx = c.getContext('2d')!;
      ctx.fillStyle = '#FFFFFF';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.fillStyle = '#000000';
      ctx.font = 'bold 40px Arial, sans-serif';
      ctx.fillText('The Rainy Gate of Kyoto', 36, 108);
      return c.toDataURL('image/png').split(',')[1];
    });
    await page.locator('input[type="file"][accept*="image/png"]').setInputFiles({
      name: 'ocr-banner.png',
      mimeType: 'image/png',
      buffer: Buffer.from(renderedPngBase64, 'base64'),
    });
    await page.getByRole('button', { name: 'Terjemahkan gambar' }).click();
    await expect(page.getByRole('tab', { name: 'Berdampingan' })).toBeVisible({
      timeout: 25000,
    });
    await expect(page.getByRole('main')).toContainText('Gerbang Hujan di Kyoto');
    await expect(page.getByText(/simpan kunci API Gemini/i)).toHaveCount(0);
  });

  test('Tablet 820x1180 & Mobile 390x844: Zero horizontal overflow, unclipped split language bar, >= 44px tap targets, Mode bar ABOVE Composer, Laci & Bottom Sheets', async ({
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

    // Verify split language bar fits inside 390px mobile header cleanly
    const langBarBox = await page.locator('.lang-pair-bar').boundingBox();
    expect(langBarBox).not.toBeNull();
    expect(langBarBox!.x + langBarBox!.width).toBeLessThanOrEqual(346);

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

    // Verify Mobile Laci (320px leaving >= 56px scrim tap area) & Bottom Sheets (K/Lembar bawah)
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_390.png',
    });
    const menuBtn = page.getByRole('button', { name: 'Menu', exact: true });
    await menuBtn.click();
    await expect(menuBtn).toHaveAttribute('aria-expanded', 'true');
    await expect
      .poll(async () => {
        const box = await page.locator('aside.sidebar').boundingBox();
        return box ? box.x : -999;
      })
      .toBeGreaterThanOrEqual(-1);
    const sidebarBox = await page.locator('aside.sidebar').boundingBox();
    expect(sidebarBox!.width).toBeLessThanOrEqual(334);
    const bodyLocked = await page.evaluate(() => document.body.style.overflow === 'hidden');
    expect(bodyLocked).toBe(true);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_drawer_390.png',
    });

    // Tapping "Lainnya" inside mobile hamburger drawer opens a native Mobile Bottom Sheet (NOT desktop popover)
    await page.getByRole('button', { name: 'Lainnya' }).click();
    const moreSheet = page.getByRole('dialog', { name: 'Lainnya' });
    await expect(moreSheet).toBeVisible();
    await expect(moreSheet.getByRole('button', { name: 'Berkas saya' })).toBeVisible();
    await expect(moreSheet.getByRole('button', { name: 'Daftar nama' })).toBeVisible();
    await expect(moreSheet.getByRole('button', { name: 'Pintasan keyboard' })).toBeVisible();
    // Stacked Escape dismisses sheet first while keeping drawer open
    await page.keyboard.press('Escape');
    await expect(moreSheet).toHaveCount(0);
    await expect(menuBtn).toHaveAttribute('aria-expanded', 'true');

    // Tapping Account row inside mobile drawer opens Mobile Account Bottom Sheet & selecting Setelan closes drawer cleanly
    await page.locator('.account-row-btn').click();
    const accountSheet = page.locator('.bottom-sheet[role="dialog"]');
    await expect(accountSheet).toBeVisible();
    await accountSheet.getByRole('button', { name: /Setelan/ }).click();
    await expect(menuBtn).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('button', { name: 'Gelap' }).click();
    await page.keyboard.press('Escape');
    await expect(page.locator('html')).toHaveAttribute('data-tranx-v3', 'Gelap');

    // History row bottom sheet + stacked Escape dismissal unlocks body scroll
    await menuBtn.click();
    await page
      .getByRole('button', { name: /Menu riwayat Bab 1: Hujan di Gerbang Rashomon/i })
      .click();
    await expect(page.getByRole('button', { name: 'Lepas sematan' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Lepas sematan' })).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(menuBtn).toHaveAttribute('aria-expanded', 'false');
    const bodyUnlocked = await page.evaluate(() => document.body.style.overflow !== 'hidden');
    expect(bodyUnlocked).toBe(true);

    // Mobile Source & Target Language Bottom Sheets (H13) + Swap button
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await expect(page.getByRole('dialog', { name: 'Bahasa sumber' })).toBeVisible();
    await page
      .getByRole('dialog', { name: 'Bahasa sumber' })
      .getByRole('button', { name: 'Indonesia' })
      .click();

    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await expect(page.getByRole('dialog', { name: 'Bahasa tujuan' })).toBeVisible();
    await page
      .getByRole('dialog', { name: 'Bahasa tujuan' })
      .getByRole('button', { name: 'Jepang' })
      .click();

    await expect(page.getByRole('button', { name: 'Bahasa sumber: Indonesia' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bahasa tujuan: Jepang' })).toBeVisible();

    await page.getByRole('button', { name: 'Tukar bahasa' }).click();
    await expect(page.getByRole('button', { name: 'Bahasa sumber: Jepang' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bahasa tujuan: Indonesia' })).toBeVisible();

    // 3. Mobile 390x844 /web Reader Overhaul (in Dark Mode via real in-app navigation!): single-row topbar (<= 72px), single-row chapter dock (<= 76px), Hamburger Reader Bottom Sheet, WCAG AA & zero iframe clipping
    await page.getByRole('tab', { name: 'Link' }).click();
    await page.getByPlaceholder(/https:\/\//).fill('https://www.aozora.gr.jp/cards/1.html');
    await page.getByRole('button', { name: 'Terjemahkan halaman' }).click();
    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-tranx-v3', 'Gelap');
    await expect(page.getByRole('heading', { name: 'Bab 1: Hujan di Rashomon' })).toBeVisible();

    const webMobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth
    );
    expect(webMobileOverflow).toBe(false);

    const readerTopbarBox = await page.locator('.web-viewer-topbar.is-mobile').boundingBox();
    expect(readerTopbarBox).not.toBeNull();
    expect(readerTopbarBox!.height).toBeLessThanOrEqual(72);

    const chapterDockBox = await page.locator('.novel-chapter-dock').boundingBox();
    expect(chapterDockBox).not.toBeNull();
    expect(chapterDockBox!.height).toBeLessThanOrEqual(76);

    // All 3 chapter dock buttons sit on a single horizontal row (never wrapping onto 2nd line)
    const dockBtns = page.locator('.novel-chapter-dock-inner.is-mobile > button');
    expect(await dockBtns.count()).toBe(3);
    const [b0, b1, b2] = [
      await dockBtns.nth(0).boundingBox(),
      await dockBtns.nth(1).boundingBox(),
      await dockBtns.nth(2).boundingBox(),
    ];
    expect(Math.abs(b0!.y - b1!.y)).toBeLessThanOrEqual(4);
    expect(Math.abs(b1!.y - b2!.y)).toBeLessThanOrEqual(4);

    // Axe WCAG 2.2 AA on Mobile /web Reader in Dark Mode
    const axeWebDark = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();
    expect(axeWebDark.violations).toEqual([]);

    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_web_reader_390.png',
    });

    // Open Mobile Reader Hamburger Bottom Sheet -> verify all controls + Axe AA in Dark Mode
    const readerMenuBtn = page.getByRole('button', { name: 'Menu pembaca' });
    await readerMenuBtn.click();
    const readerSheet = page.getByRole('dialog', { name: 'Menu pembaca' });
    await expect(readerSheet).toBeVisible();
    await expect(readerSheet.getByLabel('Pasangan bahasa')).toBeVisible();
    await expect(readerSheet.getByRole('button', { name: 'Berdampingan' })).toBeVisible();
    await expect(readerSheet.getByRole('button', { name: 'Situs asli' })).toBeVisible();
    await expect(readerSheet.getByRole('button', { name: /Daftar bab/ })).toBeVisible();
    await expect(readerSheet.getByRole('button', { name: 'Daftar nama' })).toBeVisible();

    const axeWebSheet = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();
    expect(axeWebSheet.violations).toEqual([]);

    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_web_sheet_390.png',
    });

    // Switch to Situs Terjemahan from the bottom sheet -> verify translated iframe fits mobile viewport cleanly
    await readerSheet.getByRole('button', { name: 'Situs Terjemahan' }).click();
    await expect(readerSheet).toHaveCount(0);
    await expect(page.locator('iframe[title="Pembaca Halaman Terjemahan"]')).toBeVisible();
    const siteMobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth
    );
    expect(siteMobileOverflow).toBe(false);

    // 4. Verify Kakuyomu-style 980px desktop HTML inside Direct Engine Situs Terjemahan reflows cleanly to 390px mobile without right-edge clipping
    await page.route('**/v1/healthz', async (route) => {
      await route.fulfill({ status: 404, body: 'Not Found' });
    });
    await page.route('https://api.allorigins.win/raw**', async (route) => {
      await route.fulfill({ status: 504, body: 'Gateway Timeout' });
    });
    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
      const reqUrl = new URL(route.request().url());
      const postParams = new URLSearchParams(route.request().postData() || '');
      const q = postParams.get('q') || reqUrl.searchParams.get('q') || '';
      const lines = q.split('\n');
      const translatedLines = lines.map((line) =>
        line.replace(/杉澤達也の知られざる努力/g, 'Upaya Tatsuya Sugisawa yang tidak diketahui')
      );
      const segments = translatedLines.map((t, idx) => [
        idx < translatedLines.length - 1 ? `${t}\n` : t,
        lines[idx] || '',
      ]);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify([segments, null, 'ja']),
      });
    });
    await page.route('https://r.jina.ai/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({
          code: 200,
          data: {
            title: 'Cerita pendek: 杉澤達也の知られざる努力',
            url: 'https://kakuyomu.jp/works/9990001/episodes/60',
            finalUrl: 'https://kakuyomu.jp/works/9990001/episodes/60',
            html: `<!doctype html><html><head><meta name="viewport" content="width=1024"><title>Cerita pendek: 杉澤達也の知られざる努力</title><style>#contentMain{width:980px;margin-left:180px;} .widget-episodeTitle{white-space:nowrap;font-size:32px;}</style></head><body><div id="contentMain"><h1 class="widget-episodeTitle">Cerita pendek: 杉澤達也の知られざる努力</h1><div class="widget-episodeBody"><p>Kamis siang saat istirahat berakhir.</p></div></div><a id="contentMain-readPreviousEpisode" href="/works/9990001/episodes/59">前のエピソード</a><a id="contentMain-readNextEpisode" href="/works/9990001/episodes/61">次のエピソード</a></body></html>`,
            links: {
              '前のエピソード': 'https://kakuyomu.jp/works/9990001/episodes/59',
              '次のエピソード': 'https://kakuyomu.jp/works/9990001/episodes/61',
            },
          },
        }),
      });
    });
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fkakuyomu.jp%2Fworks%2F9990001%2Fepisodes%2F60&mode=auto-id&view=site'
    );
    const siteIframe = page.locator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(siteIframe).toBeVisible({ timeout: 15000 });
    const srcDocHtml = await siteIframe.getAttribute('srcdoc');
    expect(srcDocHtml || '').toContain('width=device-width, initial-scale=1.0');
    expect(srcDocHtml || '').not.toContain('width=1024');
    expect(srcDocHtml || '').toContain('Upaya Tatsuya Sugisawa yang tidak diketahui');
    const iframeFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    const headingBox = await iframeFrame.locator('.widget-episodeTitle').boundingBox();
    expect(headingBox).not.toBeNull();
    expect(headingBox!.x + headingBox!.width).toBeLessThanOrEqual(390);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_web_site_390.png',
    });

    // 5. Regression Test for Blank Site Mode on Mobile: WordPress body.has-sidebar / .no-sidebar + .preloader curtain + .fade-in opacity:0 MUST render visible translated content!
    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      if (reqUrl.includes('wp-novel-mobile.example.com')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Bab 1: Legenda Danau',
              url: 'https://wp-novel-mobile.example.com/bab-1/',
              finalUrl: 'https://wp-novel-mobile.example.com/bab-1/',
              html: `<!doctype html><html><head><title>Bab 1: Legenda Danau</title><style>.preloader{position:fixed;inset:0;background:#fff;z-index:99999;} .fade-in{opacity:0;}</style></head><body class="post-template-default single right-sidebar has-sidebar no-sidebar"><div class="preloader">Loading...</div><div id="page" class="site-wrapper has-sidebar"><main id="main"><article class="entry-content fade-in"><h1>Cerita pendek: 杉澤達也の知られざる努力</h1><p>Pada suatu pagi berkabut di tepi danau tenang, seorang pengelana membuka buku catatannya.</p><p>Angin berembus pelan membawa aroma pinus dari lereng bukit utara.</p></article></main></div></body></html>`,
              links: {
                'Bab 2': 'https://wp-novel-mobile.example.com/bab-2/',
              },
            },
          }),
        });
        return;
      }
      await route.fallback();
    });
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fwp-novel-mobile.example.com%2Fbab-1%2F&mode=auto-id&view=site'
    );
    const wpIframe = page.locator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(wpIframe).toBeVisible({ timeout: 15000 });
    const wpFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(wpFrame.locator('.preloader')).toHaveCount(0);
    await expect(wpFrame.getByText(/Upaya Tatsuya Sugisawa yang tidak diketahui/)).toBeVisible();
    await expect(wpFrame.getByText(/seorang pengelana membuka buku catatannya/)).toBeVisible();
    const wpBodyVisible = await wpFrame.locator('body').evaluate((el) => {
      const st = getComputedStyle(el);
      return st.display !== 'none' && st.visibility !== 'hidden' && Number(st.opacity) > 0.5;
    });
    expect(wpBodyVisible).toBe(true);
    const wpArticleOpacity = await wpFrame.locator('article.fade-in').evaluate((el) => {
      return Number(getComputedStyle(el).opacity);
    });
    expect(wpArticleOpacity).toBeGreaterThanOrEqual(0.95);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_wp_site_390.png',
    });

    // 6. Regression Test for AWS CloudFront 403 ERROR in Site Mode + 429 Dual-Endpoint Failover (clients5.google.com) + Multi-User Request Budget!
    let primaryGtxHits = 0;
    let altClients5Hits = 0;
    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
      const postParams = new URLSearchParams(route.request().postData() || '');
      const q = postParams.get('q') || '';
      if (q.includes('CloudFrontTestProse')) {
        primaryGtxHits += 1;
        // Simulate upstream 429 throttle under 10 concurrent users -> must fail over cleanly to clients5.google.com!
        await route.fulfill({
          status: 429,
          headers: { 'Retry-After': '1', 'Access-Control-Allow-Origin': '*' },
          body: 'Too Many Requests',
        });
        return;
      }
      await route.fallback();
    });
    await page.route('https://clients5.google.com/translate_a/t**', async (route) => {
      altClients5Hits += 1;
      const postParams = new URLSearchParams(route.request().postData() || '');
      const q = postParams.get('q') || '';
      const out = q
        .replace(/CloudFrontTestProse: A traveler walked through Kyoto\./g, 'Prosa Uji: Seorang pengelana berjalan melintasi Kyoto.')
        .replace(/Chapter 1: Mist Over the Bridge/g, 'Bab 1: Kabut di Atas Jembatan');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify([[out, 'en']]),
      });
    });
    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      const hdrs = route.request().headers();
      if (reqUrl.includes('cf-novel.example.com/ch/1')) {
        if (hdrs['x-return-format'] === 'html') {
          // Simulate AWS CloudFront 403 ERROR page on raw HTML fetch!
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            headers: { 'Access-Control-Allow-Origin': '*' },
            body: JSON.stringify({
              code: 200,
              data: {
                title: 'ERROR: The request could not be satisfied',
                url: 'https://cf-novel.example.com/ch/1',
                html: '<!doctype html><html><head><title>ERROR: The request could not be satisfied</title></head><body><h1>403 ERROR</h1><h2>The request could not be satisfied.</h2><p>Request blocked. We can\'t connect to the server for this app or website at this time.</p><hr><pre>Generated by cloudfront (CloudFront)\nRequest ID: vcv4F6ULQ1</pre></body></html>',
              },
            }),
          });
          return;
        }
        // Jina Rendered Markdown rescues the real 7-chapter novel cleanly!
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Chapter 1: Mist Over the Bridge',
              url: 'https://cf-novel.example.com/ch/1',
              content:
                '# Chapter 1: Mist Over the Bridge\n\nCloudFrontTestProse: A traveler walked through Kyoto.\n\nLanterns glowed along the river bank.',
              links: {
                'Chapter 1': 'https://cf-novel.example.com/ch/1',
                'Chapter 2': 'https://cf-novel.example.com/ch/2',
                'Chapter 3': 'https://cf-novel.example.com/ch/3',
                'Chapter 4': 'https://cf-novel.example.com/ch/4',
                'Chapter 5': 'https://cf-novel.example.com/ch/5',
                'Chapter 6': 'https://cf-novel.example.com/ch/6',
                'Chapter 7': 'https://cf-novel.example.com/ch/7',
              },
            },
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fcf-novel.example.com%2Fch%2F1&mode=auto-id&view=site'
    );
    const cfIframe = page.locator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(cfIframe).toBeVisible({ timeout: 15000 });
    const cfFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    // Must NEVER display CloudFront 403 error page! Must show real translated chapter via clients5 failover!
    await expect(cfFrame.locator('body')).not.toContainText(/403 ERROR|403 KESALAHAN|Generated by cloudfront/i);
    await expect(cfFrame.locator('body')).toContainText('Prosa Uji: Seorang pengelana berjalan melintasi Kyoto.');
    expect(primaryGtxHits).toBeGreaterThanOrEqual(1);
    expect(altClients5Hits).toBeGreaterThanOrEqual(1);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_cf_site_rescue_390.png',
    });
  });

  test('Claude-BugHunter Security & Complete Menu Readiness Gate: XSS/javascript: URI/SSRF defense + all remaining menus (Cari, Ganti nama, Hapus, Pintasan, Bantuan, Pelajari, Berkas export, Kamus merge, Cadangan JSON)', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => consoleErrors.push(err.message));

    await page.setViewportSize({ width: 1280, height: 800 });

    // 1. Security: /web?url=javascript:alert(91234) must NEVER render <a href="javascript:..."> or execute script
    await page.goto('/web?e2e=1&url=javascript%3Awindow.__xss%3D91234');
    await expect(page.getByText('Tidak dapat diterjemahkan langsung')).toBeVisible();
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
    const xssAfterJsUrl = await page.evaluate(
      () => (window as unknown as { __xss?: number }).__xss
    );
    expect(xssAfterJsUrl).toBeUndefined();

    // 2. Security: /web?url=http://169.254.169.254/latest/meta-data/ SSRF metadata block
    await page.goto('/web?e2e=1&url=http%3A%2F%2F169.254.169.254%2Flatest%2Fmeta-data%2F');
    await expect(page.getByText(/Alamat jaringan internal atau privat ditolak/i)).toBeVisible();
    await expect(page.locator('a[href*="169.254.169.254"]')).toHaveCount(0);

    // 3. Security: Valid /web Situs Terjemahan isolates iframe without allow-same-origin and has zero javascript: links
    await page.goto('/web?e2e=1&url=https%3A%2F%2Fwww.aozora.gr.jp%2Fcards%2F1.html&view=site');
    const iframeSandbox = await page
      .locator('iframe[title="Pembaca Halaman Terjemahan"]')
      .getAttribute('sandbox');
    expect(iframeSandbox || '').not.toContain('allow-same-origin');
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 4. Security: Stored/DOM XSS canary in chat, Ganti nama, and Glossary surface stays inert text
    const canary = '<script>window.__xss=91234</script><img src=x onerror="window.__xss=91234">';
    await page.locator('textarea.composer-textarea').fill(canary);
    await page.locator('textarea.composer-textarea').press('Enter');
    await expect(page.getByRole('main')).toContainText('<script>window.__xss=91234</script>');
    expect(
      await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)
    ).toBeUndefined();

    // 4b. Security (hunt-file-upload): Spoofed SVG/HTML magic-byte uploads disguised as .png and .pdf rejected
    await page.getByRole('tab', { name: 'Gambar' }).click();
    await page.locator('input[type="file"][accept*="image/png"]').setInputFiles({
      name: 'spoofed-svg.png',
      mimeType: 'image/png',
      buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" onload="window.__xss=91234"/>'),
    });
    await expect(
      page.getByText(/Isi biner berkas bukan gambar PNG, JPG, atau WEBP yang sah/i)
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Terjemahkan gambar' })).toBeDisabled();
    await page.getByRole('button', { name: 'Hapus lampiran spoofed-svg.png' }).click();

    await page.getByRole('tab', { name: 'Dokumen' }).click();
    await page.locator('input[type="file"][accept*=".epub"]').setInputFiles({
      name: 'spoofed-html.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('<html><script>window.__xss=91234</script></html>'),
    });
    await expect(
      page.getByText(/Isi biner berkas bukan dokumen PDF yang sah/i)
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Terjemahkan dokumen' })).toBeDisabled();
    await page.getByRole('button', { name: 'Hapus lampiran spoofed-html.pdf' }).click();
    await page.getByRole('tab', { name: 'Teks' }).click();

    // 5. Menu readiness: Sidebar Cari, Lipat panel samping + Menu expand, Ganti nama, Hapus
    await page.getByRole('button', { name: 'Cari' }).click();
    const searchInput = page.getByPlaceholder('Cari judul atau isi bacaan...');
    await searchInput.fill('Kyoto');
    await expect(
      page.getByRole('button', { name: 'Catatan Dialog Stasiun Kyoto', exact: true })
    ).toBeVisible();
    await searchInput.fill('zzz-tidak-ada-999');
    await expect(
      page.getByText('Tidak ada percakapan yang cocok dengan kata kunci tersebut.')
    ).toBeVisible();
    await searchInput.fill('');

    await page
      .getByRole('button', { name: /Menu riwayat Catatan Dialog Stasiun Kyoto/i })
      .click();
    await page.getByRole('menuitem', { name: 'Ganti nama' }).click();
    const renameInput = page.getByRole('dialog').locator('input.field-input');
    await renameInput.fill('Catatan Stasiun Kyoto Baru');
    await page.getByRole('dialog').getByRole('button', { name: 'Simpan' }).click();
    await expect(
      page.getByRole('button', { name: 'Catatan Stasiun Kyoto Baru', exact: true })
    ).toBeVisible();

    await page
      .getByRole('button', { name: /Menu riwayat Catatan Stasiun Kyoto Baru/i })
      .click();
    await page.getByRole('menuitem', { name: 'Hapus' }).click();
    await expect(
      page.getByRole('button', { name: 'Catatan Stasiun Kyoto Baru', exact: true })
    ).toHaveCount(0);

    await page.getByRole('button', { name: 'Lipat panel samping' }).click();
    await page.getByRole('button', { name: 'Menu', exact: true }).click();

    // 6. Menu readiness: Lainnya -> Pintasan keyboard, Berkas saya (upload + .txt/.html download), Daftar nama (Buat judul + Gabungkan judul)
    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Pintasan keyboard' }).click();
    await expect(page.getByRole('heading', { name: 'Pintasan keyboard' })).toBeVisible();
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Berkas saya' }).click();
    await page.getByRole('button', { name: 'Terjemahkan dokumen pertama' }).click();
    await page.locator('input[type="file"][accept*=".epub"]').setInputFiles({
      name: 'adegan-01.srt',
      mimeType: 'text/plain',
      buffer: Buffer.from('1\n00:00:01,000 --> 00:00:03,000\n千早は走った。\n'),
    });
    await page.getByRole('button', { name: 'Terjemahkan dokumen' }).click();
    await expect(page.getByRole('button', { name: 'Baca berdampingan' })).toBeVisible();

    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Berkas saya' }).click();
    await expect(page.getByRole('main').getByText('adegan-01.srt')).toBeVisible();
    const txtDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '.txt' }).click();
    const txtDownload = await txtDownloadPromise;
    expect(txtDownload.suggestedFilename()).toContain('.txt');

    await page.getByRole('button', { name: 'Lainnya' }).click();
    await page.getByRole('menuitem', { name: 'Daftar nama' }).click();
    await page
      .getByPlaceholder('Contoh: Rashomon atau Bab Manga...')
      .fill('Seri Kyoto Musim Hujan');
    await page.getByRole('button', { name: 'Buat judul' }).click();
    await page.getByPlaceholder('Contoh: 鴉羽').fill('美咲');
    await page.getByPlaceholder('Contoh: Karasuba').first().fill('Misaki');
    await page.getByRole('button', { name: 'Kunci ejaan nama' }).click();
    await expect(page.getByText('美咲')).toBeVisible();

    await page
      .getByLabel('Pilih judul tujuan penggabungan')
      .selectOption({ label: 'Rashomon' });
    await page.getByRole('button', { name: 'Gabungkan judul' }).click();
    await expect(page.getByText(/entri digabungkan ke judul tujuan/)).toBeVisible();
    await expect(page.getByText('美咲')).toBeVisible();
    await page.getByRole('button', { name: 'Kembali ke ruang baca' }).click();

    // 7. Menu readiness: Account menu -> Bantuan, Pelajari lebih lanjut, Setelan -> Data -> Unduh cadangan JSON
    await page.locator('.account-row-btn').click();
    await page.getByRole('menuitem', { name: 'Bantuan' }).click();
    await expect(page.getByRole('heading', { name: 'Bantuan' })).toBeVisible();
    await page.keyboard.press('Escape');

    await page.locator('.account-row-btn').click();
    await page.getByRole('menuitem', { name: 'Pelajari lebih lanjut' }).click();
    await expect(page.getByRole('heading', { name: 'Pelajari lebih lanjut' })).toBeVisible();
    await page.keyboard.press('Escape');

    await page.locator('.account-row-btn').click();
    await page.getByRole('menuitem', { name: /Setelan/ }).click();
    await page.getByRole('tab', { name: 'Data' }).click();
    const backupDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Unduh cadangan JSON' }).click();
    const backupDownload = await backupDownloadPromise;
    expect(backupDownload.suggestedFilename()).toMatch(/^tranx-backup-.*\.json$/);
    const backupPath = await backupDownload.path();
    expect(backupPath).not.toBeNull();
    await page.keyboard.press('Escape');

    // 8. Verify Baru preserves manually chosen language pair (Indonesia -> Jepang)
    await page.getByRole('button', { name: 'Baru' }).click();
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Indonesia' }).click();
    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await page.getByRole('menuitemradio', { name: 'Jepang' }).click();
    await page.getByRole('button', { name: 'Baru' }).click();
    await expect(page.getByRole('button', { name: 'Bahasa sumber: Indonesia' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bahasa tujuan: Jepang' })).toBeVisible();

    expect(consoleErrors).toEqual([]);
  });

  test('Universal Multi-Site Link Engine (Syosetu, RoyalRoad, Aozora Shift_JIS, NovelBin <select>+<br>, Wikipedia/WordPress, & Cloudflare honest fallback)', async ({
    page,
  }) => {
    await page.route('**/v1/healthz', async (route) => {
      await route.fulfill({ status: 404, body: 'Not Found' });
    });
    await page.route('https://api.allorigins.win/raw**', async (route) => {
      await route.fulfill({ status: 504, body: 'Gateway Timeout' });
    });
    await page.route('https://api.codetabs.com/**', async (route) => {
      await route.fulfill({ status: 504, body: 'Gateway Timeout' });
    });

    // Simulate real-world behavior discovered during live probing across 6 non-Kakuyomu ecosystems
    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      const hdrs = route.request().headers();
      const isHtmlMode = hdrs['x-return-format'] === 'html';

      // 1. Syosetu / Narou Episode 1 & 2: Jina HTML returns EMPTY html="", Rendered Markdown returns full Japanese prose!
      if (reqUrl.includes('ncode.syosetu.com/n9669bk/1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify(
            isHtmlMode
              ? { code: 200, data: { title: '', html: '', url: 'https://ncode.syosetu.com/n9669bk/1/' } }
              : {
                  code: 200,
                  data: {
                    title: 'Mushoku Tensei - Prologue',
                    url: 'https://ncode.syosetu.com/n9669bk/1/',
                    content:
                      'I am a 34-year-old jobless recluse.\n\nA bright flash appeared right before the truck hit.',
                    links: {
                      '次へ': 'https://ncode.syosetu.com/n9669bk/2/',
                      '目次': 'https://ncode.syosetu.com/n9669bk/',
                    },
                  },
                }
          ),
        });
        return;
      }
      if (reqUrl.includes('ncode.syosetu.com/n9669bk/2')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify(
            isHtmlMode
              ? { code: 200, data: { title: '', html: '', url: 'https://ncode.syosetu.com/n9669bk/2/' } }
              : {
                  code: 200,
                  data: {
                    title: 'Mushoku Tensei - Chapter 2: A New World',
                    url: 'https://ncode.syosetu.com/n9669bk/2/',
                    content: 'When I opened my eyes, I was staring at a wooden ceiling.',
                    links: { '前へ': 'https://ncode.syosetu.com/n9669bk/1/' },
                  },
                }
          ),
        });
        return;
      }
      if (reqUrl.includes('ncode.syosetu.com/n9669bk')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Mushoku Tensei',
              url: 'https://ncode.syosetu.com/n9669bk/',
              html: `<!doctype html><html><head><title>Mushoku Tensei</title></head><body><div class="p-eplist"><a href="/n9669bk/1/">Prologue</a><a href="/n9669bk/2/">Chapter 2: A New World</a></div></body></html>`,
              links: {
                Prologue: 'https://ncode.syosetu.com/n9669bk/1/',
                'Chapter 2: A New World': 'https://ncode.syosetu.com/n9669bk/2/',
              },
            },
          }),
        });
        return;
      }

      // 2. RoyalRoad Chapter: Jina HTML returns Cloudflare "Just a moment...", Rendered Markdown returns full chapter!
      if (reqUrl.includes('royalroad.com/fiction/21220/mother-of-learning/chapter/301778')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify(
            isHtmlMode
              ? {
                  code: 200,
                  data: {
                    title: 'Just a moment...',
                    html: '<html><head><title>Just a moment...</title></head><body>Enable JavaScript and cookies to continue</body></html>',
                  },
                }
              : {
                  code: 200,
                  data: {
                    title: '1. Good Morning Brother - Mother of Learning',
                    url: 'https://www.royalroad.com/fiction/21220/mother-of-learning/chapter/301778/1-good-morning-brother',
                    content:
                      '**Chapter 001****Good Morning Brother**\n\nZorian opened his eyes and heard _MORNING_ shouted loudly.',
                    links: {
                      'Next Chapter':
                        'https://www.royalroad.com/fiction/21220/mother-of-learning/chapter/301780/2-life-and-times',
                    },
                  },
                }
          ),
        });
        return;
      }
      if (reqUrl.includes('royalroad.com/fiction/21220/mother-of-learning')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Just a moment...',
              html: '<html><head><title>Just a moment...</title></head><body>Enable JavaScript and cookies to continue</body></html>',
            },
          }),
        });
        return;
      }

      // 3. Aozora Bunko: Jina HTML returns Shift_JIS mojibake (\uFFFD), Rendered Markdown returns clean UTF-8!
      if (reqUrl.includes('aozora.gr.jp/cards/000879/files/127_15260.html')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify(
            isHtmlMode
              ? {
                  code: 200,
                  data: {
                    title: '\uFFFDH\uFFFDV\uFFFD',
                    html: '<html><body><div class="main_text">\uFFFD\uFFFD\uFFFD\uFFFD</div></body></html>',
                  },
                }
              : {
                  code: 200,
                  data: {
                    title: 'Rashomon',
                    url: 'https://www.aozora.gr.jp/cards/000879/files/127_15260.html',
                    content: 'One evening a servant waited for the rain to stop under the Rashomon gate.',
                  },
                }
          ),
        });
        return;
      }

      // 4. NovelBin / Generic Novel site using <select> chapter dropdown + <br> line breaks inside #chr-content!
      if (reqUrl.includes('novelbin.com/b/kyoto-chronicles/chapter-1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Kyoto Chronicles &#8220;Chapter 1&#8221; &#124; NovelBin',
              url: 'https://novelbin.com/b/kyoto-chronicles/chapter-1',
              html: `<!doctype html><html><head><title>Kyoto Chronicles &#8220;Chapter 1&#8221; &#124; NovelBin</title></head><body>
                <select id="chapter-select">
                  <option value="/b/kyoto-chronicles/chapter-1" selected>Chapter 1: Departure</option>
                  <option value="/b/kyoto-chronicles/chapter-2">Chapter 2: Crossing the Bridge</option>
                  <option value="/b/kyoto-chronicles/chapter-3">Chapter 3: Lantern Night</option>
                </select>
                <div id="chr-content">First snow fell softly on the temple roof.<br><br>Second line whispered across the courtyard.<br>Third line closed the chapter.</div>
              </body></html>`,
            },
          }),
        });
        return;
      }

      // 5. Wikipedia non-novel article: infobox + sup.reference clutter + sidebar "Next" link must NOT trigger Ebook badge!
      if (reqUrl.includes('en.wikipedia.org/wiki/Rashomon_(short_story)')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Rashomon (short story) &#124; Wikipedia',
              url: 'https://en.wikipedia.org/wiki/Rashomon_(short_story)',
              html: `<!doctype html><html><head><title>Rashomon (short story) - Wikipedia</title></head><body>
                <aside><a href="/wiki/Next_article">Next</a></aside>
                <div id="mw-content-text"><div class="mw-parser-output">
                  <table class="infobox"><tr><td>INFOBOX_NOISE_1915</td></tr></table>
                  <p>Rashomon is a famous short story by Ryunosuke Akutagawa.<sup class="reference">[1]</sup></p>
                  <p>It depicts an encounter beneath the ruined southern gate of Kyoto.</p>
                  <a href="/wiki/Kyoto">Kyoto</a>
                </div></div>
              </body></html>`,
            },
          }),
        });
        return;
      }

      // 6. Hard Cloudflare-blocked site (both HTML and MD return Cloudflare challenge)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({
          code: 200,
          data: {
            title: 'Just a moment...',
            html: '<html><head><title>Just a moment...</title></head><body>Verify you are human</body></html>',
            content: 'Just a moment... Enable JavaScript and cookies to continue',
          },
        }),
      });
    });

    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
      const reqUrl = new URL(route.request().url());
      const postParams = new URLSearchParams(route.request().postData() || '');
      const q = postParams.get('q') || reqUrl.searchParams.get('q') || '';
      const lines = q.split('\n').map((line) =>
        line
          .replace(/Mushoku Tensei - Prologue/gi, 'Mushoku Tensei - Prolog')
          .replace(/Mushoku Tensei - Chapter 2: A New World/gi, 'Mushoku Tensei - Bab 2: Dunia Baru')
          .replace(/I am a 34-year-old jobless recluse\./gi, 'Aku adalah penyendiri pengangguran berusia 34 tahun.')
          .replace(
            /A bright flash appeared right before the truck hit\./gi,
            'Kilatan cahaya terang muncul tepat sebelum truk menabrak.'
          )
          .replace(
            /When I opened my eyes, I was staring at a wooden ceiling\./gi,
            'Saat aku membuka mata, aku menatap langit-langit kayu.'
          )
          .replace(/1\. Good Morning Brother - Mother of Learning/gi, '1. Selamat Pagi Kakak - Mother of Learning')
          .replace(/Chapter 001 Good Morning Brother/gi, 'Bab 001 Selamat Pagi Kakak')
          .replace(
            /Zorian opened his eyes and heard MORNING shouted loudly\./gi,
            'Zorian membuka matanya dan mendengar PAGI diteriakkan keras.'
          )
          .replace(
            /One evening a servant waited for the rain to stop under the Rashomon gate\./gi,
            'Suatu sore seorang pelayan menunggu hujan reda di bawah gerbang Rashomon.'
          )
          .replace(/Kyoto Chronicles ["\u201C]Chapter 1["\u201D] \| NovelBin/gi, 'Kronik Kyoto "Bab 1" | NovelBin')
          .replace(/First snow fell softly on the temple roof\./gi, 'Salju pertama turun lembut di atap kuil.')
          .replace(
            /Second line whispered across the courtyard\./gi,
            'Baris kedua berbisik melintasi halaman.'
          )
          .replace(/Third line closed the chapter\./gi, 'Baris ketiga menutup bab ini.')
          .replace(
            /Rashomon is a famous short story by Ryunosuke Akutagawa\./gi,
            'Rashomon adalah cerita pendek terkenal karya Ryunosuke Akutagawa.'
          )
          .replace(
            /It depicts an encounter beneath the ruined southern gate of Kyoto\./gi,
            'Kisah ini menggambarkan pertemuan di bawah gerbang selatan Kyoto yang runtuh.'
          )
      );
      const segments = lines.map((t, idx) => [idx < lines.length - 1 ? `${t}\n` : t, t]);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify([segments, null, 'en']),
      });
    });

    await page.setViewportSize({ width: 1280, height: 800 });

    // A. Syosetu episode (empty HTML -> auto-rescued by Jina Rendered Markdown + TOC 1/2 + Next chapter!)
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fncode.syosetu.com%2Fn9669bk%2F1%2F&mode=auto-id&view=reader'
    );
    await expect(page.getByRole('heading', { name: 'Mushoku Tensei - Prolog' })).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi · 1 \/ 2/)).toBeVisible();
    await expect(page.locator('.novel-reader-body')).toContainText(
      'Aku adalah penyendiri pengangguran berusia 34 tahun.'
    );
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Bab berikutnya/ }).click();
    await expect(page.getByRole('heading', { name: 'Mushoku Tensei - Bab 2: Dunia Baru' })).toBeVisible();
    await expect(page.locator('.novel-reader-body')).toContainText(
      'Saat aku membuka mata, aku menatap langit-langit kayu.'
    );

    // B. RoyalRoad chapter (Cloudflare HTML -> auto-rescued by Jina Rendered Markdown + clean inline markdown stripping + Situs Terjemahan safe fallback!)
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fwww.royalroad.com%2Ffiction%2F21220%2Fmother-of-learning%2Fchapter%2F301778%2F1-good-morning-brother&mode=auto-id&view=reader'
    );
    await expect(
      page.getByRole('heading', { name: '1. Selamat Pagi Kakak - Mother of Learning' })
    ).toBeVisible();
    await expect(page.locator('.novel-reader-body')).toContainText('Bab 001 Selamat Pagi Kakak');
    await expect(page.locator('.novel-reader-body')).not.toContainText('**');
    await expect(page.locator('.novel-reader-body')).not.toContainText('_MORNING_');
    await expect(page.getByText(/Ebook terdeteksi/)).toBeVisible();
    await page.getByRole('button', { name: 'Situs Terjemahan' }).click();
    const rrFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(rrFrame.locator('body')).toContainText('Zorian membuka matanya');
    await expect(rrFrame.locator('body')).not.toContainText('Just a moment');

    // C. Aozora Bunko (Shift_JIS mojibake HTML -> auto-rescued by clean UTF-8 Rendered Markdown!)
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fwww.aozora.gr.jp%2Fcards%2F000879%2Ffiles%2F127_15260.html&mode=auto-id&view=reader'
    );
    await expect(page.locator('.novel-reader-body')).toContainText(
      'Suatu sore seorang pelayan menunggu hujan reda di bawah gerbang Rashomon.'
    );
    await expect(page.locator('.novel-reader-body')).not.toContainText('\uFFFD');

    // D. NovelBin (<select> chapter dropdown -> 1/3 chapters + HTML entity decoded title + <br> lines split into 3 separate paragraphs!)
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fnovelbin.com%2Fb%2Fkyoto-chronicles%2Fchapter-1&mode=auto-id&view=reader'
    );
    await expect(page.getByRole('heading', { name: 'Kronik Kyoto "Bab 1" | NovelBin' })).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi · 1 \/ 3/)).toBeVisible();
    await expect(page.locator('.novel-reader-para')).toHaveCount(3);
    await expect(page.locator('.novel-reader-para').nth(0)).toContainText('Salju pertama');
    await expect(page.locator('.novel-reader-para').nth(1)).toContainText('Baris kedua');
    await expect(page.locator('.novel-reader-para').nth(2)).toContainText('Baris ketiga');

    // E. Wikipedia non-novel article (strips infobox & [1] ref, decodes HTML entity, NO false Ebook badge, rewrites internal links in Situs Terjemahan!)
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FRashomon_(short_story)&mode=auto-id&view=reader'
    );
    await expect(page.locator('.novel-reader-body')).toContainText(
      'Rashomon adalah cerita pendek terkenal karya Ryunosuke Akutagawa.'
    );
    await expect(page.locator('.novel-reader-body')).not.toContainText('INFOBOX_NOISE_1915');
    await expect(page.locator('.novel-reader-body')).not.toContainText('[1]');
    await expect(page.getByText(/Ebook terdeteksi/)).toHaveCount(0);
    await page.getByRole('button', { name: 'Situs Terjemahan' }).click();
    const wikiFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(wikiFrame.locator('body')).toContainText(
      'Rashomon adalah cerita pendek terkenal karya Ryunosuke Akutagawa.'
    );
    const wikiLinkHref = await wikiFrame.locator('a[href*="Kyoto"]').first().getAttribute('href');
    expect(wikiLinkHref || '').toContain('/web?url=');
    expect(wikiLinkHref || '').toContain('view=site');

    // F. Hard Cloudflare anti-bot site -> honest Indonesian error + Buka situs asli button (NEVER renders "Just a moment..." as article!)
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fblocked-novel.example%2Fch%2F1&mode=auto-id&view=reader'
    );
    await expect(page.getByText('Tidak dapat diterjemahkan langsung')).toBeVisible();
    await expect(page.getByText(/verifikasi keamanan \/ anti-bot \(Cloudflare/i)).toBeVisible();
    await expect(page.getByRole('link', { name: 'Buka situs asli' })).toBeVisible();
  });

  test('All-Chapters Mode-Locked Translation (92 Kakuyomu chapters ID & EN) + Full Standalone PWA Manifest & Install App Notification', async ({
    page,
  }) => {
    await page.route('**/v1/healthz', async (route) => {
      await route.fulfill({ status: 404, body: 'Not Found' });
    });

    // Build a realistic 92-episode Kakuyomu __NEXT_DATA__ work (exceeds old 60/80 caps!)
    const episodeCount = 92;
    const apollo: Record<string, unknown> = {
      'Work:999001': {
        title: '京都学園物語',
        tableOfContentsV2: [{ __ref: 'TableOfContentsChapter:1' }],
      },
      'TableOfContentsChapter:1': {
        episodeUnions: Array.from({ length: episodeCount }, (_, i) => ({
          __ref: `Episode:${1001 + i}`,
        })),
      },
    };
    for (let i = 1; i <= episodeCount; i += 1) {
      apollo[`Episode:${1000 + i}`] = {
        title: `第${i}話 学園の日記`,
      };
    }
    const nextData92 = JSON.stringify({
      props: { pageProps: { __APOLLO_STATE__: apollo } },
    });

    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      if (reqUrl.includes('kakuyomu.jp/works/999001/episodes/1060')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: '第60話 学園の日記 - 京都学園物語',
              url: 'https://kakuyomu.jp/works/999001/episodes/1060',
              html: `<!doctype html><html><head><title>第60話 学園の日記</title></head><body><div class="widget-episodeBody"><p>午後の教室に風が吹いた。</p><p>チャイムが鳴り響いた。</p></div></body></html>`,
            },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({
          code: 200,
          data: {
            title: '京都学園物語 - カクヨム',
            url: 'https://kakuyomu.jp/works/999001',
            html: `<!doctype html><html><head><title>京都学園物語</title><script id="__NEXT_DATA__" type="application/json">${nextData92}</script></head><body><h1>京都学園物語</h1><p>紹介文</p></body></html>`,
          },
        }),
      });
    });

    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
      const reqUrl = new URL(route.request().url());
      const tl = reqUrl.searchParams.get('tl') || 'id';
      const postParams = new URLSearchParams(route.request().postData() || '');
      const q = postParams.get('q') || reqUrl.searchParams.get('q') || '';
      const lines = q.split('\n').map((line) => {
        if (tl === 'en') {
          return line
            .replace(/京都学園物語/g, 'Kyoto Academy Story')
            .replace(/第(\d+)話 学園の日記/g, 'Chapter $1: Academy Diary')
            .replace(/午後の教室に風が吹いた。/g, 'A breeze blew through the afternoon classroom.')
            .replace(/チャイムが鳴り響いた。/g, 'The school bell echoed.');
        }
        return line
          .replace(/京都学園物語/g, 'Kisah Akademi Kyoto')
          .replace(/第(\d+)話 学園の日記/g, 'Bab $1: Catatan Akademi')
          .replace(/午後の教室に風が吹いた。/g, 'Angin bertiup di ruang kelas sore.')
          .replace(/チャイムが鳴り響いた。/g, 'Bel sekolah berbunyi nyaring.');
      });
      const segments = lines.map((t, idx) => [idx < lines.length - 1 ? `${t}\n` : t, t]);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify([segments, null, 'ja']),
      });
    });

    await page.setViewportSize({ width: 1280, height: 800 });

    // 1. Open Episode 60 of 92 in auto-id -> ALL 92 chapters (including #1, #60, AND #92!) + seriesTitle MUST be Indonesian!
    await page.goto(
      '/web?e2e=1&direct=1&url=https%3A%2F%2Fkakuyomu.jp%2Fworks%2F999001%2Fepisodes%2F1060&mode=auto-id&view=reader'
    );
    await expect(page.getByText(/Ebook terdeteksi · 60 \/ 92/)).toBeVisible();
    await expect(page.getByText('Kisah Akademi Kyoto').first()).toBeVisible();
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Daftar bab/ }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: /Kisah Akademi Kyoto \(92\)/ })).toBeVisible();
    await expect(dialog.locator('.chapter-list-item')).toHaveCount(92);
    await expect(dialog.locator('.chapter-list-item').nth(0)).toContainText('Bab 1: Catatan Akademi');
    await expect(dialog.locator('.chapter-list-item').nth(59)).toContainText('Bab 60: Catatan Akademi');
    await expect(dialog.locator('.chapter-list-item').nth(91)).toContainText('Bab 92: Catatan Akademi');
    // Verify ZERO untranslated Japanese chapter titles remain across ALL 92 items!
    await expect
      .poll(
        () =>
          dialog
            .locator('.chapter-list-item')
            .evaluateAll((els) => els.filter((el) => /第\d+話/.test(el.textContent || '')).length),
        { timeout: 15000 }
      )
      .toBe(0);
    await dialog.getByRole('button', { name: 'Tutup' }).click();

    // 2. Switch target mode to auto-en -> ALL 92 chapters + seriesTitle immediately re-translate to English (ZERO stale Indonesian!)
    await page.getByLabel('Pasangan bahasa').selectOption('auto-en');
    await expect(page.getByText('Kyoto Academy Story').first()).toBeVisible();
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Daftar bab/ }).click();
    await expect(dialog.getByRole('heading', { name: /Kyoto Academy Story \(92\)/ })).toBeVisible();
    await expect(dialog.locator('.chapter-list-item').nth(0)).toContainText('Chapter 1: Academy Diary');
    await expect(dialog.locator('.chapter-list-item').nth(59)).toContainText('Chapter 60: Academy Diary');
    await expect(dialog.locator('.chapter-list-item').nth(91)).toContainText('Chapter 92: Academy Diary');
    await expect
      .poll(
        () =>
          dialog
            .locator('.chapter-list-item')
            .evaluateAll((els) => els.filter((el) => /Bab \d+:/.test(el.textContent || '')).length),
        { timeout: 15000 }
      )
      .toBe(0);
    await dialog.getByRole('button', { name: 'Tutup' }).click();

    // 3. Verify complete standalone PWA Manifest + icons + screenshots served by production build!
    const manifestResp = await page.request.get('/manifest.webmanifest');
    expect(manifestResp.status()).toBe(200);
    const manifest = await manifestResp.json();
    expect(manifest.id).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.start_url).toBe('/');
    expect(manifest.icons.some((i: { sizes: string; purpose: string }) => i.sizes === '192x192' && i.purpose === 'any')).toBe(true);
    expect(manifest.icons.some((i: { sizes: string; purpose: string }) => i.sizes === '512x512' && i.purpose === 'maskable')).toBe(true);
    expect(manifest.screenshots?.length).toBeGreaterThanOrEqual(2);
    expect((await page.request.get('/screenshots/desktop-wide.png')).status()).toBe(200);
    expect((await page.request.get('/screenshots/mobile-narrow.png')).status()).toBe(200);
    expect(manifest.shortcuts?.length).toBeGreaterThanOrEqual(3);

    // 4. Verify persistent Install App button (no notification banner):
    //    - On Desktop Chromium when Chrome suppresses beforeinstallprompt (e.g. already installed "Open in app"), button stays HIDDEN (no fake guide popup!)
    //    - The moment beforeinstallprompt fires (uninstalled / reinstallable), button appears & 1-click triggers native prompt() directly!
    //    - Once accepted, button disappears immediately & stays hidden after reload; if uninstalled later & beforeinstallprompt fires again, it reappears!
    await page.goto('/?e2e=1');
    await expect(page.getByRole('heading', { name: 'Mau baca apa hari ini?' })).toBeVisible();
    await expect(page.locator('.pwa-install-banner')).toHaveCount(0);

    const headerInstallBtn = page.locator('.stage-header').getByRole('button', { name: 'Pasang aplikasi' });
    // Before beforeinstallprompt on Desktop Chromium -> hidden (matches Chrome "Open in app" state)
    await expect(headerInstallBtn).toHaveCount(0);

    // Browser fires native beforeinstallprompt -> header & account Install buttons appear immediately!
    await page.evaluate(() => {
      const ev = new Event('beforeinstallprompt', { cancelable: true }) as Event & {
        prompt?: () => Promise<void>;
        userChoice?: Promise<{ outcome: 'accepted'; platform: string }>;
      };
      (window as unknown as { __pwaPromptCalled?: boolean }).__pwaPromptCalled = false;
      ev.prompt = async () => {
        (window as unknown as { __pwaPromptCalled?: boolean }).__pwaPromptCalled = true;
      };
      ev.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
      window.dispatchEvent(ev);
    });

    await expect(headerInstallBtn).toBeVisible();
    await page.locator('.account-row-btn').click();
    await expect(page.getByRole('menuitem', { name: 'Pasang aplikasi' })).toBeVisible();
    await page.keyboard.press('Escape');

    // Axe WCAG 2.2 AA check with Install App button visible in header
    const axeInstall = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();
    expect(axeInstall.violations).toEqual([]);

    // 1-click direct native install (NO guide modal shown!) -> invokes prompt() & hides button once accepted!
    await headerInstallBtn.click();
    const promptInvoked = await page.evaluate(
      () => (window as unknown as { __pwaPromptCalled?: boolean }).__pwaPromptCalled
    );
    expect(promptInvoked).toBe(true);
    await expect(page.getByRole('heading', { name: 'Cara memasang aplikasi tranX' })).toHaveCount(0);
    await expect(headerInstallBtn).toHaveCount(0);
    await expect(page.getByText('tranX berhasil dipasang sebagai aplikasi!')).toBeVisible();

    // Reloading on an already-installed device keeps the Install App button hidden (header & Account menu!)
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Mau baca apa hari ini?' })).toBeVisible();
    await expect(headerInstallBtn).toHaveCount(0);
    await page.locator('.account-row-btn').click();
    await expect(page.getByRole('menuitem', { name: 'Pasang aplikasi' })).toHaveCount(0);
    await page.keyboard.press('Escape');

    // If later uninstalled and browser fires beforeinstallprompt again -> Install App button reappears!
    await page.evaluate(() => {
      const ev = new Event('beforeinstallprompt', { cancelable: true }) as Event & {
        prompt?: () => Promise<void>;
        userChoice?: Promise<{ outcome: 'dismissed'; platform: string }>;
      };
      ev.prompt = async () => {};
      ev.userChoice = Promise.resolve({ outcome: 'dismissed', platform: 'web' });
      window.dispatchEvent(ev);
    });
    await expect(headerInstallBtn).toBeVisible();

    // 5. Verify Android mobile 390px reinstall recovery: stale legacy v1 installed flag is auto-cleared, and OS getInstalledRelatedApps()=[] restores BOTH mobile header & hamburger drawer install buttons!
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'userAgent', {
        configurable: true,
        value:
          'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36',
      });
    });
    await page.evaluate(() => {
      window.localStorage.setItem('tranx_pwa_installed_device_v1', '1');
      window.localStorage.setItem(
        'tranx_pwa_installed_v2',
        JSON.stringify({ installedAt: Date.now() - 60_000 })
      );
      (window as unknown as { __tranxMockRelatedApps?: boolean }).__tranxMockRelatedApps = true;
      Object.defineProperty(navigator, 'getInstalledRelatedApps', {
        configurable: true,
        value: async () => [],
      });
    });
    await page.reload();
    await page.evaluate(() => {
      (window as unknown as { __tranxMockRelatedApps?: boolean }).__tranxMockRelatedApps = true;
      Object.defineProperty(navigator, 'getInstalledRelatedApps', {
        configurable: true,
        value: async () => [],
      });
      window.dispatchEvent(new Event('focus'));
    });
    const mobileHeaderInstall = page
      .locator('.stage-header')
      .getByRole('button', { name: 'Pasang aplikasi' });
    await expect(mobileHeaderInstall).toBeVisible();
    const legacyRemoved = await page.evaluate(
      () => window.localStorage.getItem('tranx_pwa_installed_device_v1') === null
    );
    expect(legacyRemoved).toBe(true);
    // Open mobile hamburger drawer -> labeled "Pasang aplikasi" button is clearly visible too!
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    await expect(page.locator('aside.sidebar').getByRole('button', { name: 'Pasang aplikasi' })).toBeVisible();
    // Simulate OS confirming installed again -> BOTH buttons disappear immediately on focus!
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'getInstalledRelatedApps', {
        configurable: true,
        value: async () => [{ platform: 'webapp', url: 'https://tranx-hanif-id.web.app/manifest.webmanifest' }],
      });
      window.dispatchEvent(new Event('focus'));
    });
    await expect(mobileHeaderInstall).toHaveCount(0);
    await expect(page.locator('aside.sidebar').getByRole('button', { name: 'Pasang aplikasi' })).toHaveCount(0);
  });

  test('Pass-14 Regression: Self-heal poisoned 403 IndexedDB cache, Kakuyomu 7->84 episode_sidebar expansion, mutated GTX markers & untranslated mop-up retry', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.route('**/v1/healthz', async (route) => {
      await route.fulfill({ status: 404, body: 'Not Found' });
    });

    const workId = '2912051604668493030';
    const ep1Url = `https://kakuyomu.jp/works/${workId}/episodes/1001`;
    const workUrl = `https://kakuyomu.jp/works/${workId}`;
    const totalEps = 84;

    // 1. Pre-seed poisoned IndexedDB cache (403 ERROR article + 403 KESALAHAN translation + partial 7-chapter TOC)
    await page.goto('/?e2e=1&direct=1');
    await page.evaluate(
      async ({ epUrl, tocUrl }) => {
        await new Promise<void>((resolve, reject) => {
          const req = indexedDB.open('tranx_perf_cache_v1', 2);
          req.onupgradeneeded = () => {
            const db = req.result;
            ['paras', 'articles', 'tocs'].forEach((n) => {
              if (!db.objectStoreNames.contains(n)) {
                const s = db.createObjectStore(n, { keyPath: 'k' });
                s.createIndex('t', 't', { unique: false });
              }
            });
          };
          req.onsuccess = () => {
            const db = req.result;
            const tx = db.transaction(['articles', 'tocs'], 'readwrite');
            const now = Date.now();
            tx.objectStore('articles').put({
              k: `art::${epUrl}`,
              t: now,
              v: {
                url: epUrl,
                host: 'kakuyomu.jp',
                titleId: 't_novel_kakuyomu_2912051604668493030',
                titleSrc: 'ERROR: The request could not be satisfied',
                srcParas: ['403 ERROR', 'The request could not be satisfied.'],
                detectedSource: 'en',
                novelNav: { isNovel: true, tocUrl, totalChapters: 7 },
                htmlFetchAttempted: true,
              },
            });
            tx.objectStore('articles').put({
              k: `tr::${epUrl}::auto-id`,
              t: now,
              v: {
                heading: 'KESALAHAN: Permintaan tidak dapat dipenuhi',
                paras: ['403 KESALAHAN', 'Permintaan itu tidak dapat dipenuhi.'],
              },
            });
            tx.objectStore('tocs').put({
              k: `toc::${tocUrl}`,
              t: now,
              v: {
                seriesTitle: 'ERROR: The request could not be satisfied',
                tocUrl,
                chapters: Array.from({ length: 7 }, (_, i) => ({
                  title: `第${i + 1}話 仮タイトル`,
                  url: `https://kakuyomu.jp/works/2912051604668493030/episodes/${1001 + i}`,
                })),
              },
            });
            tx.oncomplete = () => {
              db.close();
              resolve();
            };
            tx.onerror = () => reject(tx.error);
          };
          req.onerror = () => reject(req.error);
        });
      },
      { epUrl: ep1Url, tocUrl: workUrl }
    );

    // 2. Mock Jina: cached ep1 returns CloudFront 403, X-No-Cache retry returns real prose; work page returns ONLY 7 links (no __NEXT_DATA__); /episode_sidebar returns ALL 84 episodes!
    let ep1NoCacheRetries = 0;
    let sidebarFetches = 0;
    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      const hdrs = route.request().headers();
      const hasNoCache = hdrs['x-no-cache'] === 'true';

      if (reqUrl.includes('/episode_sidebar')) {
        sidebarFetches += 1;
        const sidebarItems = Array.from({ length: totalEps }, (_, i) => {
          const n = i + 1;
          return `<li><a href="/works/${workId}/episodes/${1000 + n}"><span>第${n}話 放課後の約束</span><time>2026年7月24日</time></a></li>`;
        }).join('');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: '',
              url: `${ep1Url}/episode_sidebar`,
              finalUrl: `${ep1Url}/episode_sidebar`,
              html: `<!doctype html><html><body><ol>${sidebarItems}</ol></body></html>`,
            },
          }),
        });
        return;
      }

      if (reqUrl.includes(`/episodes/1001`)) {
        if (!hasNoCache) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            headers: { 'Access-Control-Allow-Origin': '*' },
            body: JSON.stringify({
              code: 200,
              data: {
                title: 'ERROR: The request could not be satisfied',
                url: ep1Url,
                finalUrl: ep1Url,
                html: '<!doctype html><html><head><title>ERROR: The request could not be satisfied</title></head><body><h1>403 ERROR</h1><h2>The request could not be satisfied.</h2><p>Generated by cloudfront (CloudFront)</p></body></html>',
              },
            }),
          });
          return;
        }
        ep1NoCacheRetries += 1;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: '第1話 学校を休む最高の方法 - 放課後の嘘告物語 - カクヨム',
              url: ep1Url,
              finalUrl: ep1Url,
              html: `<!doctype html><html lang="ja"><head><title>第1話 学校を休む最高の方法</title></head><body><main><h1 class="widget-episodeTitle">第1話 学校を休む最高の方法</h1><div class="widget-episodeBody"><p>朝の光が静かな教室の窓を照らしていた。</p><p>彼は机の上の手紙をそっと開いた。</p></div></main></body></html>`,
            },
          }),
        });
        return;
      }

      // Collapsed Kakuyomu work page: ONLY 7 visible links & NO __NEXT_DATA__!
      const sevenLinksHtml = Array.from(
        { length: 7 },
        (_, i) =>
          `<a href="/works/${workId}/episodes/${1001 + i}">第${i + 1}話 放課後の約束</a>`
      ).join('');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({
          code: 200,
          data: {
            title: '放課後の嘘告物語 - カクヨム',
            url: workUrl,
            finalUrl: workUrl,
            html: `<!doctype html><html><head><title>放課後の嘘告物語 - カクヨム</title></head><body><h1>放課後の嘘告物語</h1><div>${sevenLinksHtml}</div></body></html>`,
          },
        }),
      });
    });

    // 3. Mock GTX with real-world chaos: fullwidth mutated markers (【#2】, [#5]) + 1st attempt leaves 第42話 untranslated to prove mop-up retry!
    let ep42DroppedOnce = false;
    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
      const postParams = new URLSearchParams(route.request().postData() || '');
      const reqUrl = new URL(route.request().url());
      const q = postParams.get('q') || reqUrl.searchParams.get('q') || '';
      const lines = q.split('\n');
      const translatedLines = lines.map((line, idx) => {
        // Simulate first-pass untranslated glitch on Episode 42
        if (line.includes('第42話') && !ep42DroppedOnce) {
          ep42DroppedOnce = true;
          return line;
        }
        let out = line
          .replace(/第(\d+)話\s*放課後の約束/g, 'Bab $1: Janji Sepulang Sekolah')
          .replace(/第1話\s*学校を休む最高の方法/g, 'Bab 1: Cara Terbaik Istirahat dari Sekolah')
          .replace(/放課後の嘘告物語/g, 'Kisah Pengakuan Bohong Sepulang Sekolah')
          .replace(
            /朝の光が静かな教室の窓を照らしていた。?/g,
            'Cahaya pagi menyinari jendela ruang kelas yang tenang.'
          )
          .replace(
            /彼は机の上の手紙をそっと開いた。?/g,
            'Ia membuka surat di atas meja dengan perlahan.'
          );
        // Simulate Google Translate mutating marker brackets into fullwidth 【#k】 / [#k]
        if (idx === 2) out = out.replace(/\[\[#(\d+)\]\]/, '【#$1】');
        if (idx === 5) out = out.replace(/\[\[#(\d+)\]\]/, '[#$1]');
        return out;
      });
      const segments = translatedLines.map((t, idx) => [
        idx < translatedLines.length - 1 ? `${t}\n` : t,
        lines[idx] || '',
      ]);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify([segments, null, 'ja']),
      });
    });

    // 4. Open Episode 1 in Site view directly on mobile 390px -> must self-heal 403, expand 7->84 via episode_sidebar, & translate 100%!
    await page.goto(
      `/web?e2e=1&direct=1&url=${encodeURIComponent(ep1Url)}&mode=auto-id&view=site`
    );

    // Dock must show 1 / 84 (NOT 1 / 7!)
    await expect(page.locator('.novel-chapter-dock')).toContainText('1 / 84', { timeout: 15000 });
    expect(ep1NoCacheRetries).toBeGreaterThanOrEqual(1);
    expect(sidebarFetches).toBeGreaterThanOrEqual(1);

    // Site iframe must show REAL translated prose and ZERO 403 KESALAHAN!
    const siteFrame = page.frameLocator('iframe[title="Pembaca Halaman Terjemahan"]');
    await expect(siteFrame.locator('body')).toContainText('Cara Terbaik Istirahat dari Sekolah');
    await expect(siteFrame.locator('body')).toContainText(
      'Cahaya pagi menyinari jendela ruang kelas yang tenang.'
    );
    await expect(siteFrame.locator('body')).not.toContainText('403 KESALAHAN');
    await expect(siteFrame.locator('body')).not.toContainText('Permintaan itu tidak dapat dipenuhi');

    // Open Chapter Modal -> must show ALL 84 chapters, ZERO error title, and 100% Indonesian including #1, #42 (retried!), and #84!
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Daftar bab/ }).click();
    const dlg = page.getByRole('dialog');
    await expect(dlg).toBeVisible();
    await expect(dlg).toContainText('(84)');
    await expect(dlg).not.toContainText('KESALAHAN');
    await expect(dlg.getByRole('button', { name: /Bab 1: Janji Sepulang Sekolah/ })).toBeVisible({
      timeout: 15000,
    });
    await expect(dlg.getByRole('button', { name: /Bab 42: Janji Sepulang Sekolah/ })).toBeVisible({
      timeout: 15000,
    });
    await expect(dlg.getByRole('button', { name: /Bab 84: Janji Sepulang Sekolah/ })).toBeVisible({
      timeout: 15000,
    });
    // Zero untranslated Japanese chapter titles across ALL 84 rows!
    const remainingJpChapters = await dlg
      .locator('.chapter-list-item')
      .evaluateAll((els) => els.filter((el) => /[\u3040-\u30ff\u3400-\u9fff]/.test(el.textContent || '')).length);
    expect(remainingJpChapters).toBe(0);
    await page.screenshot({
      path: '/Users/hanifpriyambodo/.gemini/antigravity/brain/1c9f5dd7-3454-423b-a588-20da84f6271e/qa_mobile_kakuyomu_84ch_rescue_390.png',
    });
  });
});
