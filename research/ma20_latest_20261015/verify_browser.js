async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('http://127.0.0.1:8848/');
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();
 await page.locator('#ma-radar-host [data-ma-section="20"]').waitFor();
 const base=await page.evaluate(()=>({version:DATA.ma_trend.version,hash:DATA.ma_trend.implementation_hash,
   generation:DATA.ui_generation,source:DATA.ma_trend.source_at,counts:DATA.ma_trend.counts,
   defaults:{scope:MS_VIEW.radar.scope,phase:MS_VIEW.radar.phase},members:mtRows().length,
   total:(DATA.stocks||[]).length+(DATA.coverage_catalog||[]).length,
   params:DATA.ma_trend.parameters}));
 if(base.version!=='ma-trend-2026-10-15.1'||base.defaults.scope!=='all'||base.defaults.phase!==''||base.members!==base.total)throw Error('Radar defaults or all-members mismatch');
 if(!base.source.startsWith('2026-10-15'))throw Error('Today quote input not published');
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('20');
 const current20=await page.evaluate(()=>({rows:mtRows().map(r=>({code:r.code,status:r.ma_trend.status,platform:r.ma_trend.platform})),
    exitedShown:!!document.querySelector('#ma-radar-host [data-ma-section="20"] .ma-state')&&Array.from(document.querySelectorAll('#ma-radar-host [data-ma-section="20"] .ma-state')).some(e=>e.textContent==='已退出')}));
 if(current20.exitedShown||current20.rows.some(r=>r.status==='已退出'))throw Error('Historical exits mixed into current MA20');
 for(const r of current20.rows)if(!r.platform.latest_cycle||r.platform.retained_pct<20||r.platform.retained_atr<4)throw Error('MA20 admission mismatch '+r.code);
 const input=page.locator('#ma-radar-host [aria-label="搜索板块题材"]');
 const search=await input.evaluate(el=>({padding:getComputedStyle(el).paddingLeft,overlaidIcon:!!el.parentElement.querySelector('span'),width:el.offsetWidth}));
 if(search.overlaidIcon||parseFloat(search.padding)<14)throw Error('Search icon overlaps text');
 const ime=await input.evaluate(el=>{el.focus();el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='yi';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));mtRender();const kept=el.isConnected&&document.activeElement===el;el.value='医药';el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'医药'}));return kept;});
 await page.waitForFunction(()=>MS_VIEW.radar.boardQuery==='医药'&&!document.querySelector('#ma-radar-host [aria-label="搜索板块题材"]')._msEnding);
 if(!ime)throw Error('IME composing input lost');await page.locator('#ma-radar-host [aria-label="搜索板块题材"]').fill('');
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill('000993');
 const example=await page.evaluate(()=>{const r=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).find(r=>r.code==='000993');return {code:r.code,name:r.name,ma_trend:r.ma_trend,shown:mtRows().some(r=>r.code==='000993')};});
 if(example.shown){
   const tag=page.locator('#ma-radar-host [data-strength-id="000993"] [data-tip]').first();await tag.hover();
   await page.getByRole('tooltip').waitFor({state:'visible'});
   await page.screenshot({path:'output/playwright/ma20-latest-case.png',fullPage:false});
 }
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill('');
 await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('exited');
 if(!(await page.locator('#ma-radar-host [data-ma-section="20"]').innerText()).includes('历史退出 · MA20'))throw Error('History heading not explicit');
 await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('all');
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
 const colors=await page.locator('#ma-radar-host').evaluate(el=>{const up=el.querySelector('.pct-change.up'),down=el.querySelector('.pct-change.down');return {up:up&&getComputedStyle(up).color,down:down&&getComputedStyle(down).color};});
 if(colors.up!=='rgb(232, 39, 26)'||colors.down!=='rgb(18, 164, 92)')throw Error('Return colors wrong '+JSON.stringify(colors));
 await page.screenshot({path:'output/playwright/radar-all-defaults.png',fullPage:false});
 await page.getByRole('button',{name:'个股',exact:true}).click();
 const stockColor=await page.locator('#ms-stock-host .pct-change').first().evaluate(el=>({class:el.className,color:getComputedStyle(el).color}));
 if(stockColor.color!=='rgb(232, 39, 26)'&&stockColor.color!=='rgb(18, 164, 92)'&&stockColor.color!=='rgb(142, 142, 147)')throw Error('Stock colors missing');
 if(errors.length)throw Error(errors.join(' | '));
 return {base,current20,search,ime,example,colors,stockColor,errors};
}
