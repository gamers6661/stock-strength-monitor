async page => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 if(await page.locator('#drawer.open').count())await page.locator('#dr-x').click();
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 const base=await page.evaluate(()=>({generation:DATA.ui_generation,ma:DATA.ma_trend.counts,pending:DATA.ma_trend.pending.length,phase:DATA.session}));
 const units=await page.evaluate(()=>({amount:yi(10000),small:yi(500),volume:volumeWan(1e8)}));
 if(units.amount!=='1.00亿元'||units.small!=='0.05亿元'||units.volume!=='10000.00万股')throw Error('Unit conversion failed '+JSON.stringify(units));
 const capText=await page.locator('#emotion-host').innerText();
 if(/封单\s+[\d.,]+万|成交\s+[\d.,]+万/.test(capText))throw Error('Wan units remain in limit-up pool');
 const ice=page.locator('[data-relay-code="000530"]').first();
 if(await ice.count()){
   const text=await ice.innerText();if(text.includes('新华传媒')||text.includes('伴生参照 百洋股份'))throw Error('False relation still displayed');
 }
 const cw=page.locator('[data-relay-code="002343"]').first();
 if(!await cw.innerText().then(t=>t.includes('新华传媒')&&t.includes('传媒')))throw Error('Media continuation not retained');
 await page.screenshot({path:'output/playwright/preopen-emotion.png',fullPage:false});
 const details=await page.evaluate(async()=>{
   const version=DATA.ui_generation,by={};for(const c of ['000530','002343','600825','001246','601091']){
     const r=await fetch('/__ui/detail?version='+version+'&kind=stock&id='+c).then(r=>r.json());if(r.version!==version)throw Error('Generation mismatch');by[c]=r.item;
   }
   return by;
 });
 const chartResults=[];
 for(const code of ['600825','001246','601091']){
   await page.evaluate(c=>showStock(c),code);
   await page.locator('#k-cv').waitFor({state:'visible'});
   await page.waitForFunction(()=>MS_CHART&&MS_CHART.bars&&MS_CHART.bars.length>0);
   const result=await page.evaluate(()=>({count:MS_CHART.bars.length,last:MS_CHART.bars.at(-1).date,allReal:MS_CHART.bars.every(b=>b.volume!==0),body:document.querySelector('#dr-b').innerText}));
   if(!result.count||!result.allReal)throw Error('Missing real candles '+code);
   if(code==='600825'&&(!result.body.includes('停牌标注')||result.last!=='2026-10-12'))throw Error('Suspended history missing');
   if(code==='001246'&&result.count>=20)throw Error('Short history was padded');
   const cv=page.locator('#k-cv');await cv.scrollIntoViewIfNeeded();const rect=await cv.boundingBox();await page.mouse.move(0,0);await page.mouse.move(rect.x+rect.width*.7,rect.y+100);
   const readout=await page.locator('#k-readout').innerText();if(!readout.includes('万股'))throw Error('Volume units missing '+readout);
   if(code==='600825')await page.screenshot({path:'output/playwright/preopen-suspension.png',fullPage:false});
   if(code==='001246')await page.screenshot({path:'output/playwright/preopen-short-history.png',fullPage:false});
   chartResults.push({code,count:result.count,last:result.last,readout});
   await page.locator('#dr-x').click();
 }
 const csv=await page.evaluate(async()=>{
   const response=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:DATA.ui_generation,codes:['000530','002343'],contexts:{view:'emotion'}})});
   if(!response.ok)throw Error('CSV export '+response.status);const text=await response.text();
   if(!text.includes('成交量(万股)')||!text.includes('成交额(亿元)')||!text.includes(DATA.ui_generation))throw Error('CSV units/generation mismatch');return {lines:text.trim().split('\n').length};
 });
 if(errors.length)throw Error(errors.join('\n'));
 return {base,units,charts:chartResults,csv,errors};
}
