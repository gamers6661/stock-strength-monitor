async (page) => {
  await page.waitForFunction(() => typeof setWorkMode === 'function' && typeof DATA === 'object');
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const state = async () => page.evaluate(() => {
    const button = document.querySelector('#work-switch button.on');
    const slider = document.querySelector('#work-switch .sl');
    const x = Number((slider.style.transform.match(/translateX\(([-\d.]+)px\)/)||[])[1]);
    return {mode: WORK_MODE, manual: WORK_MANUAL, selected: button.dataset.work,
      sliderX: x, expectedX: button.offsetLeft-3, width: Number.parseFloat(slider.style.width), expectedWidth: button.offsetWidth,
      closeVisible: document.querySelector('#ov-work-close').classList.contains('on'),
      date: DATA.close_strong_board.asof, count: DATA.close_strong_board.count,
      title: document.querySelector('#hero-h1').textContent};
  });
  const verify = async (label, expected) => {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const s = await state();
    if (s.selected !== expected || s.mode !== expected || Math.abs(s.sliderX-s.expectedX)>1 || Math.abs(s.width-s.expectedWidth)>1 || s.closeVisible !== (expected==='close')) throw new Error(label+': '+JSON.stringify(s));
    return {label,...s};
  };
  const results = [await verify('收盘后首次载入', 'close')];
  // 覆盖真实首帧竞态：分段按钮初始化后、RAF执行前由时段判断切换。
  await page.evaluate(() => {
    const original = document.querySelector('#work-switch');
    const test = original.cloneNode(true); test.id = 'seg-regression';
    test.querySelectorAll('button').forEach(b => b.classList.remove('on'));
    original.parentNode.appendChild(test); segInit(test);
    test.querySelector('[data-work="close"]').classList.add('on');
  });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  const race = await page.evaluate(() => {
    const el = document.querySelector('#seg-regression'), b=el.querySelector('button.on'), sl=el.querySelector('.sl');
    const ok=sl.style.transform==='translateX('+(b.offsetLeft-3)+'px)' && sl.style.width===b.offsetWidth+'px';
    el.remove(); return ok;
  });
  if(!race) throw new Error('首帧滑块竞态回归');
  await page.evaluate(() => { window.savedSessionNow=sessionNow; sessionNow=()=> '尾盘'; WORK_MANUAL=false; setWorkMode('live',false); });
  results.push(await verify('14:59盘中', 'live'));
  await page.evaluate(() => { sessionNow=()=> '已收盘'; refreshPageFreshness(); });
  results.push(await verify('跨收盘时点自动同步', 'close'));
  await page.getByRole('button', {name:'盘中监控',exact:true}).click();
  results.push(await verify('手动查看盘中', 'live'));
  await page.evaluate(() => refreshPageFreshness());
  results.push(await verify('手动选择保留', 'live'));
  await page.getByRole('button', {name:'收盘复盘',exact:true}).click();
  await page.setViewportSize({width:1100,height:800});
  results.push(await verify('缩放后按钮同步', 'close'));
  await page.evaluate(() => { sessionNow=()=> '集合竞价'; WORK_MANUAL=false; refreshPageFreshness(); });
  results.push(await verify('09:15自动切换盘中', 'live'));
  await page.evaluate(() => { sessionNow=window.savedSessionNow; WORK_MANUAL=false; setWorkMode(autoWorkMode(),false); refreshPageFreshness(); });
  await page.setViewportSize({width:1600,height:1000});
  results.push(await verify('恢复真实收盘页面', 'close'));
  await page.screenshot({path:'output/playwright/close-refresh-20261009.png'});
  if(errors.length) throw new Error(JSON.stringify(errors));
  return {results,initializationRaceFixed:race,pageErrors:errors};
}
