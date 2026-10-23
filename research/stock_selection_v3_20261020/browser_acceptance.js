async (page) => {
  await page.getByRole('button',{name:'个股',exact:true}).click();
  await page.evaluate(async()=>{SS_LIVE=await (await fetch('/__stock_selection',{cache:'no-store'})).json();ssRender();});
  const auction=await page.evaluate(()=>{const original=sessionNow;try{sessionNow=()=> '竞价结束';renderStocks();msRender('stocks');return {v3:!!document.querySelector('[aria-label="个股强度榜单"]'),rows:msRows('stocks').map(r=>r.code).join()===ssRows().map(r=>r.code).join()};}finally{sessionNow=original;renderStocks();}});
  if(!auction.v3||!auction.rows)throw Error('auction takeover replaced V3');
  const initial=await page.evaluate(()=>({version:ssModel().version,result:ssModel().result_version,count:ssRows().length,
    ids:ssRows().map(r=>r.code),table:Array.from(document.querySelectorAll('#ms-stock-host tr[data-strength-id]')).map(r=>r.dataset.strengthId)}));
  if(initial.table.join()!=initial.ids.slice(0,100).join())throw Error('rendered order differs from backend/filter');
  await page.getByRole('combobox',{name:'个股强度排序'}).selectOption('price');
  const sorting=await page.evaluate(()=>{const m=ssModel(),rs=ssRows();return rs.every((r,i)=>!i||m.items[rs[i-1].code].dimensions.price>=m.items[r.code].dimensions.price);});
  if(!sorting)throw Error('price sorting');
  await page.getByRole('combobox',{name:'个股强度榜单'}).selectOption('all');
  await page.getByRole('combobox',{name:'板块支持'}).selectOption('板块支持');
  const filter=await page.evaluate(()=>ssRows().every(r=>ssModel().items[r.code].board.label==='板块支持'));
  if(!filter)throw Error('board filter');
  await page.getByRole('combobox',{name:'板块支持'}).selectOption('');
  const composition=await page.evaluate(async()=>{const input=document.querySelector('[aria-label="强势搜索"]');input.focus();
    input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));input.value='银行';
    input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'银行'}));ssRender();
    const survived=input.isConnected&&document.activeElement===input;
    input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'银行'}));
    await new Promise(r=>setTimeout(r,25));
    return {survived,query:MS_VIEW.stocks.q,count:ssRows().length,matched:ssRows().every(r=>(r.code+' '+r.name).includes('银行'))};
  });
  if(!composition.survived||composition.query!=='银行'||!composition.count||!composition.matched)throw Error('Chinese composition/filter');
  const csv=await page.evaluate(()=>{let text;const old=downloadMSCSV;downloadMSCSV=(t)=>text=t;try{ssCSV();}finally{downloadMSCSV=old;}
    const ids=ssRows().map(r=>r.code),lines=text.trim().split('\r\n');
    return {count:lines.length-1,ids,allHaveVersion:lines.slice(1).every(l=>l.includes(ssModel().result_version)),headers:lines[0]};
  });
  if(csv.count!==csv.ids.length||!csv.allHaveVersion)throw Error('CSV version/filter');
  await page.getByRole('textbox',{name:'强势搜索',exact:true}).fill('');
  await page.getByRole('combobox',{name:'个股强度榜单'}).selectOption('effective');
  await page.getByRole('combobox',{name:'个股强度排序'}).selectOption('score');
  const members=await page.evaluate(()=>{const m=ssModel(),c=ssRows()[0].code,b=msBoardCatalog().find(b=>b.type==='industry'&&b.member_codes.includes(c));
    const score=m.items[c].score;msOpenStocks(b.id,'trend',true);const rs=ssRows();
    const expected=b.member_codes.filter(code=>m.items[code]);const ok=ssView().selectionScope==='all'&&rs.length===expected.length&&rs.every(r=>expected.includes(r.code))&&ssModel().items[c].score===score;
    resetMSMemberView();MS_VIEW.stocks.selectionScope='effective';renderStocks();return {ok,count:rs.length};});
  if(!members.ok)throw Error('all-members navigation or score changed');
  const first=await page.evaluate(()=>ssRows()[0].code);
  await page.locator('#ms-stock-host tr[data-strength-id="'+first+'"]').click();
  await page.locator('#k-cv').waitFor({state:'visible'});
  await page.waitForFunction(()=>MS_CHART&&MS_CHART.bars.length>=26);
  const detail=await page.locator('#ss-detail').innerText();
  const currentVersion=await page.evaluate(()=>ssModel().result_version);
  if(!detail.includes(currentVersion)||!detail.includes('判断标准与依据'))throw Error('detail version/evidence');
  const chart=await page.evaluate(()=>{const chart=document.querySelector('#k-cv'),analysis=document.querySelector('.ss-analysis'),ctx=chart.getContext('2d');
    const pixels=ctx.getImageData(0,0,chart.width,chart.height).data;let red=0,green=0;
    for(let i=0;i<pixels.length;i+=4){if(pixels[i]>160&&pixels[i+1]<110&&pixels[i+2]<110)red++;if(pixels[i]<70&&pixels[i+1]>100&&pixels[i+2]<150)green++;}
    return {beforeAnalysis:!!(chart.compareDocumentPosition(analysis)&Node.DOCUMENT_POSITION_FOLLOWING),bars:MS_CHART.bars.length,red,green,last:MS_CHART.bars.at(-1).date};});
  if(!chart.beforeAnalysis||!chart.red||!chart.green)throw Error('candlesticks missing or evidence before chart');
  await page.getByRole('combobox',{name:'K线显示区间'}).selectOption('20');
  await page.getByRole('button',{name:'×',exact:true}).click();
  const colors=await page.evaluate(()=>{const m=ssModel();MS_VIEW.stocks.selectionScope='all';ssRender();const els=Array.from(document.querySelectorAll('#ms-stock-host .ss-change'));return els.filter(e=>e.textContent!=='—').map(e=>({value:parseFloat(e.textContent),color:getComputedStyle(e).color}));});
  if(!colors.some(x=>x.value>0)||!colors.some(x=>x.value<0)||!colors.every(x=>x.value>0?x.color==='rgb(218, 70, 75)':x.value<0?x.color==='rgb(21, 150, 108)':true))throw Error('red/green quote colors');
  await page.evaluate(()=>{MS_VIEW.stocks.selectionScope='effective';ssRender();});
  await page.screenshot({path:'output/playwright/stock-selection-v3-list.png',scale:'css'});
  return {auction,initial,sorting,filter,composition,csv,members,detailVersion:currentVersion,detailCode:first,chart,colors};
}
