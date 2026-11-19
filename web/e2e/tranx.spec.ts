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
    const autoSiteHref = await page
      .getByRole('link', { name: 'Buka web terjemahan otomatis' })
      .getAttribute('href');
    expect(autoSiteHref || '').toContain('www-aozora-gr-jp.translate.goog');
    expect(autoSiteHref || '').toContain('_x_tr_tl=en');
    await expect(
      page.getByRole('button', { name: 'Buka halaman terjemahan penuh' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).click();
    // Mode is currently auto-en from Step 7 -> heading renders in English first, then switch to auto-id inside /web
    await expect(page.getByRole('heading', { name: 'Chapter 1: Rain at Rashomon' })).toBeVisible();
    await page.getByLabel('Pasangan bahasa').selectOption('auto-id');
    await expect(page.getByRole('heading', { name: 'Bab 1: Hujan di Rashomon' })).toBeVisible();
    // Toggle Berdampingan (bilingual)
    await page.getByRole('button', { name: 'Berdampingan' }).click();
    await expect(page.getByText('千早は小さく笑った。')).toBeVisible();
    // Click Bab berikutnya -> navigates directly to Chapter 2 without re-entering any URL
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Bab berikutnya/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 2: Lentera di Kyoto' })).toBeVisible();
    await expect(page.getByText(/Anda berada di bab terakhir yang tersedia/)).toBeVisible();
    // Open Daftar bab modal -> jump back to Bab 1
    await page.locator('.novel-chapter-dock').getByRole('button', { name: /Daftar bab/ }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: /Bab 1: Hujan di Rashomon/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 1: Hujan di Rashomon' })).toBeVisible();
    // Switch to Situs Terjemahan (extension-less full translated website inside sandboxed iframe)
    await page.getByRole('button', { name: 'Situs Terjemahan' }).click();
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

    // CORS-enabled raw HTML proxy mock (tests real directEngine Kakuyomu TOC + episode Ebook reader, XSS stripping, and <a href> rewriting)
    await page.route('https://api.allorigins.win/raw**', async (route) => {
      const targetParam = new URL(route.request().url()).searchParams.get('url') || '';
      if (targetParam.includes('kakuyomu.jp/works/2912051604668493030/episodes/')) {
        // Real Kakuyomu episode HTML does NOT contain __NEXT_DATA__ TOC; tranX must auto-fetch /works/2912051604668493030!
        const isEp101 = targetParam.includes('episodes/101');
        const isEp102 = targetParam.includes('episodes/102');
        const html = isEp101
          ? `<!doctype html><html><head><title>Episode 1: Best Way to Skip School</title></head><body><h1>Episode 1: Best Way to Skip School</h1><p>Morning rain tapped softly against the classroom window.</p><a id="contentMain-readNextEpisode" href="/works/2912051604668493030/episodes/102">次のエピソード</a></body></html>`
          : isEp102
            ? `<!doctype html><html><head><title>Episode 2: After School Confession</title></head><body><h1>Episode 2: After School Confession</h1><p>Lantern light swayed quietly across the wet stone alley.</p><a id="contentMain-readPreviousEpisode" href="/works/2912051604668493030/episodes/101">前のエピソード</a><a id="contentMain-readNextEpisode" href="/works/2912051604668493030/episodes/103">次のエピソード</a></body></html>`
            : `<!doctype html><html><head><title>Episode 3: Tatsuya Secret Effort</title></head><body><h1>Episode 3: Tatsuya Secret Effort</h1><p>Chihaya stood quietly under the wooden gate while listening to the rain.</p><a id="contentMain-readPreviousEpisode" href="/works/2912051604668493030/episodes/102">前のエピソード</a></body></html>`;
        await route.fulfill({
          status: 200,
          contentType: 'text/html; charset=utf-8',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: html,
        });
        return;
      }
      if (targetParam.includes('kakuyomu.jp/works/2912051604668493030')) {
        const nextData = JSON.stringify({
          props: {
            pageProps: {
              __APOLLO_STATE__: {
                'Work:2912051604668493030': { title: 'Kyoto School Story' },
                'TableOfContentsChapter:1': {
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
          contentType: 'text/html; charset=utf-8',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: `<!doctype html><html><head><title>Kyoto School Story - Kakuyomu</title><script id="__NEXT_DATA__" type="application/json">${nextData}</script></head><body><h1>Kyoto School Story</h1><p>A school romance novel in Kyoto.</p></body></html>`,
        });
        return;
      }
      const isCh2 = targetParam.includes('2.html');
      const html = isCh2
        ? `<!doctype html><html><head><title>Chapter 2: The Lanterns of Kyoto</title></head><body><h1>Chapter 2: The Lanterns of Kyoto</h1><p>Lantern light swayed quietly across the wet stone alley.</p><nav><a rel="prev" href="/cards/1.html">Previous Chapter</a></nav></body></html>`
        : `<!doctype html><html><head><title>The Rainy Gate of Kyoto</title><script>window.__xss=91234;</script></head><body onload="window.__xss=91234"><h1>The Rainy Gate of Kyoto</h1><p>Chihaya stood quietly under the wooden gate while listening to the rain.</p><p>She opened her notebook and read the letter from Tokyo.</p><nav><a rel="next" href="/cards/2.html" onclick="window.__xss=91234">Next Chapter</a></nav></body></html>`;
      await route.fulfill({
        status: 200,
        contentType: 'text/html; charset=utf-8',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: html,
      });
    });

    // CORS-enabled Jina Reader mock matching real r.jina.ai JSON schema (including pure-punctuation line & Kakuyomu)
    await page.route('https://r.jina.ai/**', async (route) => {
      const reqUrl = route.request().url();
      if (reqUrl.includes('kakuyomu.jp/works/2912051604668493030/episodes/101')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Episode 1: Best Way to Skip School',
              content: 'Morning rain tapped softly against the classroom window.',
              url: 'https://kakuyomu.jp/works/2912051604668493030/episodes/101',
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
              content: 'Lantern light swayed quietly across the wet stone alley.',
              url: 'https://kakuyomu.jp/works/2912051604668493030/episodes/102',
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
              content:
                'Chihaya stood quietly under the wooden gate while listening to the rain.\n\n[前のエピソード](https://kakuyomu.jp/works/2912051604668493030/episodes/102)',
              url: 'https://kakuyomu.jp/works/2912051604668493030/episodes/103',
            },
          }),
        });
        return;
      }
      if (reqUrl.includes('kakuyomu.jp/works/2912051604668493030')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({
            code: 200,
            data: {
              title: 'Kyoto School Story - Kakuyomu',
              content:
                'A school romance novel in Kyoto.\n\n[最初から読む](https://kakuyomu.jp/works/2912051604668493030/episodes/101)\n[Episode 1: Best Way to Skip School](https://kakuyomu.jp/works/2912051604668493030/episodes/101)\n[Episode 2: After School Confession](https://kakuyomu.jp/works/2912051604668493030/episodes/102)\n[Episode 3: Tatsuya Secret Effort](https://kakuyomu.jp/works/2912051604668493030/episodes/103)',
              url: 'https://kakuyomu.jp/works/2912051604668493030',
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
                content:
                  'Lantern light swayed quietly across the wet stone alley.\n\n[Previous Chapter](https://www.aozora.gr.jp/cards/1.html)',
                url: 'https://www.aozora.gr.jp/cards/2.html',
              }
            : {
                title: 'The Rainy Gate of Kyoto',
                content:
                  'Chihaya stood quietly under the wooden gate while listening to the rain.\n\n「…………」\n\nShe opened her notebook and read the letter from Tokyo.\n\n[Next Chapter](https://www.aozora.gr.jp/cards/2.html)',
                url: 'https://www.aozora.gr.jp/cards/1.html',
              },
        }),
      });
    });

    // CORS-enabled Google GTX mock supporting both batched POST and GET while preserving [[E0]] & [[#0]] markers
    await page.route('https://translate.googleapis.com/translate_a/single**', async (route) => {
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
            'Cahaya lentera bergoyang tenang di sepanjang gang batu basah'
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

    // 1a. Real Kakuyomu Ebook Auto-TOC Enrichment:
    // Opening the LAST episode (103) auto-fetches /works/2912051604668493030 TOC (3/3), translates chapter titles,
    // allows jumping to Chapter 1 ("Baca dari Bab 1"), and advancing Chapter 1 -> Chapter 2 seamlessly!
    await page.getByRole('tab', { name: 'Link' }).click();
    await page
      .getByPlaceholder(/https:\/\//)
      .fill('https://kakuyomu.jp/works/2912051604668493030/episodes/103');
    await page.getByRole('button', { name: 'Terjemahkan halaman' }).click();
    await expect(page.getByText(/Ebook terdeteksi · 3 \/ 3/)).toBeVisible();
    const kakuAutoUrl = await page
      .getByRole('link', { name: 'Buka web terjemahan otomatis' })
      .last()
      .getAttribute('href');
    expect(kakuAutoUrl || '').toContain('kakuyomu-jp.translate.goog/works/2912051604668493030/episodes/103');
    expect(kakuAutoUrl || '').toContain('_x_tr_tl=id');

    await page.getByRole('button', { name: 'Buka halaman terjemahan penuh' }).last().click();
    await expect(page.getByRole('heading', { name: 'Bab 3: Usaha Rahasia Tatsuya' })).toBeVisible();
    await expect(page.getByText(/Anda berada di bab terakhir yang tersedia \(3 \/ 3\)/)).toBeVisible();
    await page.locator('.ebook-next-card').getByRole('button', { name: 'Baca dari Bab 1' }).click();
    await expect(page.getByRole('heading', { name: 'Bab 1: Cara Terbaik Bolos Sekolah' })).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi · 1 \/ 3/)).toBeVisible();
    // Advance Bab 1 -> Bab 2 using end-of-chapter Ebook continuation card without typing any URL
    await page.locator('.ebook-next-card').getByRole('button', { name: /Bab berikutnya/ }).click();
    await expect(page.getByRole('heading', { name: 'Bab 2: Pengakuan Sepulang Sekolah' })).toBeVisible();
    await expect(page.getByText(/Ebook terdeteksi · 2 \/ 3/)).toBeVisible();
    await page.getByRole('button', { name: 'Kembali' }).click();

    // 1a-ii. Kakuyomu Work/TOC URL -> auto-detected as Ebook TOC with "Mulai baca Bab 1"
    await page.goto('/web?url=https%3A%2F%2Fkakuyomu.jp%2Fworks%2F2912051604668493030&mode=auto-id&view=reader');
    await expect(page.getByText(/Daftar isi Ebook/)).toBeVisible();
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
    await page.keyboard.press('Escape');

    // Mobile Source & Target Language Bottom Sheets (H13) + Swap button
    await page.getByRole('button', { name: /Bahasa sumber:/ }).click();
    await expect(page.getByRole('dialog', { name: 'Bahasa sumber' })).toBeVisible();
    await page.getByRole('dialog', { name: 'Bahasa sumber' }).getByRole('button', { name: 'Indonesia' }).click();

    await page.getByRole('button', { name: /Bahasa tujuan:/ }).click();
    await expect(page.getByRole('dialog', { name: 'Bahasa tujuan' })).toBeVisible();
    await page.getByRole('dialog', { name: 'Bahasa tujuan' }).getByRole('button', { name: 'Jepang' }).click();

    await expect(page.getByRole('button', { name: 'Bahasa sumber: Indonesia' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bahasa tujuan: Jepang' })).toBeVisible();

    await page.getByRole('button', { name: 'Tukar bahasa' }).click();
    await expect(page.getByRole('button', { name: 'Bahasa sumber: Jepang' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bahasa tujuan: Indonesia' })).toBeVisible();
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
});
