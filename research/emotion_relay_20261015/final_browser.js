async (page) => {
 const result=await page.evaluate(async()=>{
  if(typeof ER_DIRECTION_EXPORT!=='function'||typeof ER_BOARD_REFERENCE!=='function')throw Error('Final scripts not published');
  const m=DATA.emotion_relay,p=m.promotion.find(p=>p.height===1),sum=m.promotion.reduce((n,p)=>n+p.expected,0);
  if(sum+m.promotion_height_pending!==m.yesterday_feedback.expected)throw Error('Promotion cohorts do not reconcile');
  const old=downloadMSCSV,lazy=DATA.ui_lazy;let csv='';
  try{DATA.ui_lazy=false;downloadMSCSV=text=>csv=text;await erBoardCSV();}finally{downloadMSCSV=old;DATA.ui_lazy=lazy;}
  if(!csv.includes('当前在板数')||!csv.includes(DATA.ui_generation))throw Error('Offline direction export broken');
  const status=await fetch('/__status').then(r=>r.json());
  if(status.phase!=='ready'||status.ui_generation!==DATA.ui_generation||status.code_emotion_relay_hash!==m.implementation_hash||status.snapshot_emotion_relay_hash!==m.implementation_hash)throw Error('Service/page/model do not match');
  return {generation:DATA.ui_generation,hash:m.implementation_hash,pid:status.pid,firstBoard:p.expected,heightPending:m.promotion_height_pending,yesterdaySealed:m.yesterday_feedback.expected,offlineExportRows:csv.trim().split('\n').length-1,cdDisplay:getComputedStyle(document.querySelector('.er-table .cd')).display};
 });
 if(result.cdDisplay!=='block')throw Error('Final candidate layout missing');
 await page.locator('#emotion-host [data-relay-code]').first().click();
 await page.locator('.er-stock-detail').waitFor();await page.locator('#dr-x').click();
 await page.getByRole('button',{name:'板块／题材',exact:true}).click();
 await page.locator('#board-center [data-direction-id]').first().locator('.ms-name-link').click();
 await page.locator('.er-board-detail').waitFor();
 if(!await page.locator('#ms-board-chart').count())throw Error('Index chart entry lost');
 result.referenceNotice=await page.locator('.er-index-reference').count();
 await page.locator('#dr-x').click();
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 await page.screenshot({path:'output/playwright/emotion-relay-final.png',fullPage:false});
 await page.setViewportSize({width:850,height:1000});
 await page.screenshot({path:'output/playwright/emotion-relay-narrow.png',fullPage:false});
 await page.setViewportSize({width:1440,height:1000});
 return result;
}
