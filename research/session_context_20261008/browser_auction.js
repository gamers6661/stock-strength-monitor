async page => {
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.clock.setFixedTime(new Date('2026-10-08T09:15:55+08:00'));
  await page.goto('http://127.0.0.1:8848/output/playwright/auction_0915.html');
  const first=await page.evaluate(()=>({phase:sessionNow(),mode:WORK_MODE,
    heading:document.getElementById('hero-h1').textContent,
    count:document.getElementById('work-auction-count').textContent,
    cards:document.querySelectorAll('#work-auction-list button').length,
    version:DATA.session_context.version}));
  await page.screenshot({path:'D:/股票强势监测/output/playwright/context-auction-0915.png',scale:'css'});
  await page.locator('#work-auction-list button').first().click();
  const detail=await page.locator('#session-context-detail').innerText();
  await page.screenshot({path:'D:/股票强势监测/output/playwright/context-auction-detail.png',scale:'css'});
  await page.clock.setFixedTime(new Date('2026-10-08T09:20:05+08:00'));
  await page.goto('http://127.0.0.1:8848/output/playwright/auction_0920.html');
  const middle=await page.locator('#work-auction-list button').first().innerText();
  await page.clock.setFixedTime(new Date('2026-10-08T09:26:08+08:00'));
  await page.goto('http://127.0.0.1:8848/output/playwright/auction_0926.html');
  const final=await page.locator('#work-auction-list button').first().innerText();
  // 9:15报价尚未到达时也切换；09:30不能沿用竞价资格。
  await page.clock.setFixedTime(new Date('2026-10-08T09:15:00+08:00'));
  const beforeQuote=await page.evaluate(()=>{DATA.session_context.auction_rows=[];
    setWorkMode(autoWorkMode(),false);
    return {mode:WORK_MODE,empty:document.getElementById('work-auction-list').innerText};});
  await page.clock.setFixedTime(new Date('2026-10-08T09:30:00+08:00'));
  const open=await page.evaluate(()=>{setWorkMode(autoWorkMode(),false);return {
    mode:WORK_MODE,auctionVisible:getComputedStyle(document.getElementById('work-auction-section')).display,
    auctionStillCurrent:DATA.stocks.some(s=>contextCurrent(s.session_context))};});
  return {first,detail,middle,final,beforeQuote,open,errors};
}
