async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('http://127.0.0.1:8848/');
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();
 await page.locator('#ma-radar-host [data-ma-section="10"]').waitFor();
 const base=await page.evaluate(()=>({version:DATA.ma_trend.version,hash:DATA.ma_trend.implementation_hash,generation:DATA.ui_generation,
   source:DATA.ma_trend.source_at,params:DATA.ma_trend.parameters}));
 if(base.version!=='ma-trend-2026-10-15.2'||!base.source.startsWith('2026-10-15'))throw Error('Wrong live revision/source');
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill('000995');
 const historical=await page.locator('#ma-radar-host').innerText();
 if(!historical.includes('历史启动 2026-09-21')||!historical.includes('2026-10-09')||!historical.includes('历史阶段'))throw Error('Historical wave still presented as current');
 await page.screenshot({path:'output/playwright/huangtai-historical-origin.png',fullPage:false});
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('10');
 if(await page.locator('#ma-radar-host [data-strength-id="000995"]').count())throw Error('Old HT wave remains in current MA10');
 await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('exited');
 if(!await page.locator('#ma-radar-host [data-strength-id="000995"]').count())throw Error('Historical exit cannot be queried');
 const cases=await page.evaluate(()=>['000995','002578','002811','600812','001318','000993'].map(c=>{const r=DATA.stocks.concat(DATA.coverage_catalog||[]).find(r=>r.code===c);return {code:c,name:r.name,ma_trend:r.ma_trend};}));
 const mf=cases.find(r=>r.code==='002578').ma_trend;
 if(!mf.last_exit||mf.last_exit.date!=='2026-09-08'||mf.last_exit.reason!=='MA10整理平台观察到期'||mf.origin.date!==mf.last_exit.origin.date)throw Error('Expiry still points to an unrelated wave');
 await page.getByRole('button',{name:'个股',exact:true}).click();
 await page.locator('#ms-stock-host [aria-label="强势搜索"]').fill('000995');
 if(!await page.locator('#ms-stock-host [data-strength-id="000995"]').count())throw Error('Complete membership lost');
 if(!(await page.locator('#ms-stock-host').innerText()).includes('历史阶段 · MA10承接整理'))throw Error('Stock history tag ambiguous');
 await page.getByRole('combobox',{name:'个股标签',exact:true}).selectOption('MA10承接整理');
 if(await page.locator('#ms-stock-host [data-strength-id="000995"]').count())throw Error('Stock current-stage filter includes old wave');
 await page.getByRole('combobox',{name:'个股标签',exact:true}).selectOption('');
 await page.locator('#ms-stock-host [data-strength-id="000995"]').click();
 await page.locator('.ma-trend-detail > summary').click();
 const details=await page.locator('.ma-trend-detail').innerText();
 if(!details.includes('历史波段起点 2026-09-21'))throw Error('Detail still calls historical origin current');
 if(errors.length)throw Error(errors.join(' | '));
 return {base,historical,cases,details,errors};
}
