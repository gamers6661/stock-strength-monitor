process.env.TEMP='D:/Temp/stock-monitor';process.env.TMP='D:/Temp/stock-monitor';
const fs=require('fs'),path=require('path');
const {chromium}=require('D:/_tools/stock-monitor/playwright/node_modules/playwright');
(async()=>{
 const mode=process.argv.includes('--live')?'live':'candidate';
 const browser=await chromium.launch({headless:true,executablePath:'D:/_tools/stock-monitor/browsers/chromium-1208/chrome-win64/chrome.exe'});
 const page=await browser.newPage({viewport:{width:1500,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 try {
  await page.goto('http://127.0.0.1:8848/dashboard.html',{waitUntil:'domcontentloaded',timeout:60000});
  await page.getByRole('button',{name:'个股',exact:true}).click();
  const model=mode==='candidate'?JSON.parse(fs.readFileSync('cache/stock_selection_v3/candidate-latest.json','utf8')):null;
  await page.evaluate(async m=>{if(!m)m=await(await fetch('/__stock_selection',{cache:'no-store'})).json();DATA.stock_selection=m;SS_LIVE=m;ssRender();},model);
  const state=await page.evaluate(()=>({version:ssModel().version,hash:ssModel().implementation_hash,result:ssModel().result_version,
    visible:ssRows().length,source:ssModel().source_at}));
  if(!state.version.endsWith('20261021.3'))throw Error('wrong candidate/live rule version '+state.version);
  const code=await page.evaluate(()=>ssRows()[0].code);
  await page.locator('tr[data-strength-id="'+code+'"]').click();
  await page.locator('#k-cv').waitFor({state:'visible'});
  await page.waitForFunction(()=>MS_CHART&&MS_CHART.bars.length>=26);
  const detail=await page.locator('#ss-detail').innerText();
  for(const word of ['盘中确认','连续守稳','整理奖励','判断标准与依据',state.result])if(!detail.includes(word))throw Error('missing detail evidence '+word);
  const chart=await page.evaluate(()=>{
    const cv=document.querySelector('#k-cv'),analysis=document.querySelector('.ss-analysis'),pixels=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
    let red=0,green=0;for(let i=0;i<pixels.length;i+=4){if(pixels[i]>160&&pixels[i+1]<110&&pixels[i+2]<110)red++;if(pixels[i]<70&&pixels[i+1]>100&&pixels[i+2]<150)green++;}
    const original=msDrawCandles;window.drawn=[];
    msDrawCandles=function(cv,b,p,n){drawn.push({count:n,first:b.slice(-n)[0].date,last:b.at(-1).date});return original(cv,b,p,n);};
    return {beforeAnalysis:!!(cv.compareDocumentPosition(analysis)&Node.DOCUMENT_POSITION_FOLLOWING),red,green,bars:MS_CHART.bars.length};
  });
  if(!chart.beforeAnalysis||!chart.red||!chart.green)throw Error('candlestick rendering/order failed');
  for(const n of ['20','40','60'])await page.getByRole('combobox',{name:'K线显示区间'}).selectOption(n);
  const ranges=await page.evaluate(()=>drawn);
  if(ranges.map(x=>x.count).join()!=='20,40,60')throw Error('range handler not exercised');
  await page.screenshot({path:'output/playwright/stock-selection-v3-repair-'+mode+'-detail.png'});
  await page.getByRole('button',{name:'×',exact:true}).click();
  const rows=await page.evaluate(()=>{
    MS_VIEW.stocks.selectionScope='all';MS_VIEW.stocks.q='';ssRender();
    const colors=Array.from(document.querySelectorAll('.ss-change')).map(e=>({value:parseFloat(e.textContent),color:getComputedStyle(e).color})).filter(x=>Number.isFinite(x.value));
    let csv;const download=downloadMSCSV;downloadMSCSV=t=>csv=t;try{ssCSV();}finally{downloadMSCSV=download;}
    const ids=ssRows().map(r=>r.code),lines=csv.trim().split('\r\n');
    return {colors:colors.every(x=>x.value>0?x.color==='rgb(218, 70, 75)':x.value<0?x.color==='rgb(21, 150, 108)':true),
      hasUp:colors.some(x=>x.value>0),hasDown:colors.some(x=>x.value<0),csvMatches:lines.slice(1).map(l=>l.match(/^"(\d+)"/)[1]).join()===ids.join(),
      csvVersions:lines.slice(1).every(l=>l.includes(ssModel().result_version)),count:ids.length};
  });
  if(!rows.colors||!rows.hasUp||!rows.hasDown||!rows.csvMatches||!rows.csvVersions)throw Error('list color or CSV mismatch');
  const report={mode,state,code,chart,ranges,rows,errors};
  if(errors.length)throw Error('page errors '+errors.join());
  fs.writeFileSync('research/stock_selection_v3_fix_20261021/browser_'+mode+'.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 } finally {await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
