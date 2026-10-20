async page => {
  await page.evaluate(() => {closeDrawer();goPane('boards');BD_VIEW={kind:'all',filter:'active',q:'',limit:80};renderBoards();});
  const result={};
  await page.getByRole('combobox',{name:'方向类型',exact:true}).selectOption('industry');
  result.industry=await page.evaluate(()=>bdRows().map(r=>({id:r.id,type:r.type})));
  await page.getByRole('combobox',{name:'方向类型',exact:true}).selectOption('theme');
  result.themes=await page.evaluate(()=>bdRows().map(r=>({id:r.id,type:r.type})));
  result.ime=await page.evaluate(async()=>{
    const input=document.getElementById('bd-search');input.focus();
    input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
    input.value='农产品';input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'农产品'}));
    const during=document.getElementById('bd-search')===input;
    input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'农产品'}));
    const atEnd=document.getElementById('bd-search')===input;
    input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false,data:'农产品'}));
    await new Promise(resolve=>setTimeout(resolve,30));
    return {during,atEnd,value:document.getElementById('bd-search').value,ids:bdRows().map(r=>r.id)};
  });
  await page.getByRole('textbox',{name:'搜索动态方向',exact:true}).fill('知识产权保护');
  result.search=await page.evaluate(()=>({view:BD_VIEW,ids:bdRows().map(r=>r.id)}));
  await page.locator('[data-bd-id]').first().click();
  await page.locator('#board-dynamics-detail').waitFor();
  result.detail=await page.evaluate(()=>({dynamic:!!document.getElementById('board-dynamics-detail'),chart:!!document.getElementById('ms-board-chart'),members:document.getElementById('dr-b').innerText.includes('同花顺确认主板成员'),evidence:document.querySelector('#board-dynamics-detail pre').textContent}));
  await page.evaluate(()=>{closeDrawer();BD_VIEW={kind:'all',filter:'active',q:'',limit:80};renderBoards();});
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出当前结果 CSV',exact:true}).click();
  const download=await downloadPromise;
  await download.saveAs('output/playwright/board_dynamics_20261016/boards.csv');
  result.export=await page.evaluate(()=>({generation:DATA.ui_generation,ids:bdRows().map(r=>r.id),source:bdModel().source_at}));
  // Exercise every status selector against the frozen backend result.
  result.filters=await page.evaluate(()=>{const out={};for(const [key] of BD_FILTERS){out[key]=bdRows(key).map(r=>r.id);}return out;});
  await page.setViewportSize({width:1440,height:1100});
  await page.screenshot({path:'output/playwright/board_dynamics_20261016/desktop.png',scale:'css'});
  await page.setViewportSize({width:430,height:932});
  result.mobile=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,tableScroll:document.querySelector('#board-center .tw').scrollWidth}));
  await page.screenshot({path:'output/playwright/board_dynamics_20261016/mobile.png',scale:'css'});
  await page.setViewportSize({width:1440,height:1100});
  return result;
}
