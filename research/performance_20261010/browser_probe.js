async (page) => {
  const base='http://127.0.0.1:8848';
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.addInitScript(()=>{
    const OriginalDate=Date,fixed=new OriginalDate('2026-10-10T10:00:00+08:00').getTime();
    class FrozenDate extends OriginalDate{constructor(...args){super(...(args.length?args:[fixed]));}static now(){return fixed;}}
    window.Date=FrozenDate;
  });
  await page.route('**/__status',route=>route.abort());
  async function fingerprint(){return await page.evaluate(()=>{
    const out={};STATE.q='';STATE.filters=defaultFilters();STATE.boardFilterId=null;
    STATE.sort.stocks={k:null,asc:false};STOCK_VIEW='all';
    const ids=()=>stockViewRows('all',true).map(s=>s.code).join(',');
    out.all=ids();
    Object.keys(STATEFN).forEach(k=>{STATE.filters=defaultFilters();STATE.filters.states=[k];out['state:'+k]=ids();});
    STATE.filters=defaultFilters();
    ['scoreMin','chgMin','intraMin','ret5Min','turnMin','vrMin','capMin','pos60Min','distMin'].forEach(k=>{
      STATE.filters=defaultFilters();STATE.filters[k]=({scoreMin:65,chgMin:3,intraMin:80,ret5Min:5,turnMin:3,vrMin:1.2,capMin:50,pos60Min:60,distMin:1})[k];out['range:'+k]=ids();
    });
    STATE.filters=defaultFilters();
    ['ret5','ret20','price','change_pct','turnover','float_mcap','stock_strength_score','strength_accel5_pp','vol_ratio5','position60'].forEach(k=>{
      [false,true].forEach(asc=>{STATE.sort.stocks={k:k,asc:asc};out['sort:'+k+':'+asc]=ids();});
    });
    STATE.sort.stocks={k:null,asc:false};
    boardCatalog().forEach(b=>{STATE.boardFilterId=b.id;out['board:'+b.id]=ids();});STATE.boardFilterId=null;
    ['电池','种植业与林业','600241','时代万恒','新华股份','000001','机器人'].forEach(q=>{STATE.q=q;out['search:'+q]=ids();});STATE.q='';
    out.stockTags=stockPoolRows().map(s=>[s.code,stockKeyStatus(s,quoteFreshAtClientNow(s),null),uiTrendPullbackTags(s)]);
    out.boardTags=boardCatalog().map(b=>[b.id,boardTrendTags(b)]);
    out.close=(DATA.close_strong_board.stocks||[]).map(s=>s.code);
    renderStocks();out.table=document.getElementById('tb-stocks').innerHTML;
    return out;
  });}
  async function csvHash(){return await page.evaluate(async()=>{
    STATE.q='';STATE.filters=defaultFilters();STATE.boardFilterId=null;STATE.sort.stocks={k:null,asc:false};
    let blob,oldURL=URL.createObjectURL,oldClick=HTMLAnchorElement.prototype.click;
    URL.createObjectURL=b=>{blob=b;return 'blob:probe';};HTMLAnchorElement.prototype.click=function(){};
    try{await exportCSV();}finally{URL.createObjectURL=oldURL;HTMLAnchorElement.prototype.click=oldClick;}
    let bytes=await blob.arrayBuffer();
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
    const text=await blob.text();return {hash,bytes:bytes.byteLength,lines:text.split('\n').length,columns:text.split('\n')[0].split(',').length};
  });}
  let t=Date.now();await page.goto(base+'/research/performance_20261010/baseline.html');await page.waitForFunction(()=>typeof stockViewRows==='function'&&DATA.stocks.length===3024);
  const oldLoad=Date.now()-t,old=await fingerprint(),oldCSV=await csvHash();
  t=Date.now();await page.goto(base+'/dashboard.html');await page.waitForFunction(()=>DATA.ui_lazy&&DATA.stocks.length===3024);
  const newLoad=Date.now()-t,next=await fingerprint();
  const mismatches=Object.keys(old).filter(k=>JSON.stringify(old[k])!==JSON.stringify(next[k]));
  t=Date.now();const newCSV=await csvHash();const csvMillis=Date.now()-t;
  const requests=[];page.on('request',r=>requests.push(r.url()));
  t=Date.now();const detail=await page.evaluate(async()=>{
    await showStock('600241');document.querySelectorAll('#dr-b details').forEach(e=>e.open=true);
    let row=stockPoolRows().find(s=>s.code==='600241');
    return {code:row.code,chart:!!row.k&&!!document.getElementById('k-cv'),themes:row.theme_relations.length,
      path:Array.isArray((row.intraday_path||{}).recent),text:document.getElementById('dr-b').innerText.includes('归属与数据来源')};
  });const detailMillis=Date.now()-t;
  const cached=await page.evaluate(async()=>{await showStock('600241');return Object.keys(UI_CACHE).length;});
  const board=await page.evaluate(async()=>{
    closeDrawer();await showBoardById('industry:电池');let b=boardById('industry:电池');
    return {members:b.members.length,fullNames:b.members.every(r=>!!r.name),text:document.getElementById('dr-b').innerText.includes('当前指数趋势')};
  });
  await page.screenshot({path:'D:/股票强势监测/research/performance_20261010/board_detail.png',fullPage:false});
  return {oldLoadMillis:oldLoad,newLoadMillis:newLoad,scenarios:Object.keys(old).length,mismatches,
    oldCSV,newCSV,csvEqual:oldCSV.hash===newCSV.hash,csvMillis,detail,detailMillis,cached,board,
    detailRequests:requests,externalRequests:requests.filter(u=>!u.startsWith(base)),errors};
}
