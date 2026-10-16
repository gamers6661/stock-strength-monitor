async (page) => {
  await page.getByRole('button', { name: '个股', exact: true }).click();
  const results = [];
  async function compose(label, field, text) {
    const input = page.getByRole('textbox', { name: label, exact: true });
    const before = await input.evaluate((el, field) => {
      el.focus();
      window.__imeInput = el;
      el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
      el.value = 'dian';
      el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true, inputType: 'insertCompositionText', data: 'dian' }));
      msRender('stocks'); // The active page can also be rendered by a data refresh.
      return { connected: el.isConnected, focused: document.activeElement === el,
        composing: el._msComposing === true };
    }, field);
    if (!before.connected || !before.focused || !before.composing) throw Error('Composition destroyed input: ' + label);
    const ending = await input.evaluate((el, text) => {
      el.value = text;
      el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: text }));
      el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: false, inputType: 'insertText', data: text }));
      return el.isConnected;
    }, text);
    if (!ending) throw Error('Trailing input lost target: ' + label);
    await page.waitForFunction(({ label, field, text }) => {
      const el = document.querySelector('[aria-label="' + label + '"]');
      return el && el.value === text && MS_VIEW.stocks[field] === text && document.activeElement === el && !el._msEnding;
    }, { label, field, text });
    results.push({ label, text, original_node_survived_composition: true,
      survived_trailing_input: true, committed_filter_and_focus: true });
  }
  await compose('搜索板块题材', 'boardQuery', '电池');
  const directions = await page.locator('.ms-direction-options button').allTextContents();
  if (!directions.length || directions.some(name => !name.includes('电池'))) throw Error('Chinese board filter incorrect');
  await compose('搜索板块题材', 'boardQuery', '新能源');
  await compose('搜索板块题材', 'boardQuery', '电池');
  await page.getByRole('textbox', { name: '搜索板块题材', exact: true }).fill('AI');
  if (await page.getByRole('textbox', { name: '搜索板块题材', exact: true }).inputValue() !== 'AI') throw Error('ASCII input failed');
  await page.getByRole('textbox', { name: '搜索板块题材', exact: true }).fill('');
  await compose('强势搜索', 'q', '银行');
  await page.getByRole('textbox', { name: '强势搜索', exact: true }).fill('');
  await compose('搜索板块题材', 'boardQuery', '电池');
  const choice = page.locator('.ms-direction-options button').first();
  const name = await choice.textContent();
  await choice.click();
  const selection = await page.evaluate(() => ({ ids: MS_VIEW.stocks.industryIds.concat(MS_VIEW.stocks.themeIds),
    rows: msRows('stocks').length, valid: msRows('stocks').every(msMatchDirections),
    generation: DATA.ui_generation, implemented: typeof msSearchStart === 'function' }));
  if (!selection.ids.length || !selection.valid || !selection.implemented) throw Error('Board selection failed');
  await page.getByRole('button', { name: '清除方向', exact: true }).click();
  const clear = await page.evaluate(() => MS_VIEW.stocks.industryIds.length + MS_VIEW.stocks.themeIds.length === 0 && MS_VIEW.stocks.boardQuery === '');
  if (!clear) throw Error('Clear failed');
  await page.screenshot({ path: 'output/playwright/stock-ime-fixed.png', fullPage: false });
  return { results, directions, selected_name: name, selection, clear };
}
