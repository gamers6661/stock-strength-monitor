async page => {
  const center=page.locator('#board-center');
  const tag=center.locator('.bc-card .ui-tag').first();
  await tag.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await tag.hover();
  const hovered=await page.locator('#ui-note-tip').evaluate(e=>({hidden:e.hidden,text:e.textContent}));
  await tag.click();
  await page.waitForTimeout(300);
  const clicked=await page.locator('#ui-note-tip').evaluate(e=>({hidden:e.hidden,text:e.textContent}));
  return {hovered,clicked,description:await tag.getAttribute('aria-describedby')};
}
