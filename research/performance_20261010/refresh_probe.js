async (page) => {
  const base='http://127.0.0.1:8848';
  await page.unroute('**/__status');
  await page.goto(base+'/dashboard.html');
  await page.waitForFunction(()=>DATA.ui_lazy&&document.getElementById('update-state').textContent==='已同步');
  const status=await (await page.request.get(base+'/__status')).json();
  const previous=(await (await page.request.get(base+'/research/performance_20261010/retained_generations.json')).json()).previous;
  const result=await page.evaluate(async({previous,status})=>{
    const old=decodeDashboardPackage(await (await fetch('/__ui/summary?version='+previous)).json());
    DATA=old;PAGE_VERSION=0;UI_CACHE={};RENDERED={};renderOverview();
    goPane('stocks');STATE.q='电池';document.getElementById('q').value='电池';
    STATE.filters=defaultFilters();STATE.filters.scoreMin=40;STATE.sort.stocks={k:'change_pct',asc:true};STATE.limit=160;
    renderStocks();setWorkMode('live',true);await showStock('600241','industry:电池');
    document.querySelectorAll('#dr-b details').forEach(el=>el.open=true);
    document.getElementById('drawer').scrollTop=400;window.scrollTo(0,180);
    window.__refreshSentinel='keep-me';
    const before={state:JSON.stringify(STATE),mode:WORK_MODE,manual:WORK_MANUAL,stock:STOCK_VIEW,
      scroll:window.scrollY,drawer:document.getElementById('drawer').scrollTop,
      folds:document.querySelectorAll('#dr-b details[open]').length};
    watchDataVersion();
    for(let i=0;i<100&&(DATA.ui_generation!==status.ui_generation||UI_UPDATING);i++)await new Promise(r=>setTimeout(r,100));
    const after={state:JSON.stringify(STATE),mode:WORK_MODE,manual:WORK_MANUAL,stock:STOCK_VIEW,
      scroll:window.scrollY,drawer:document.getElementById('drawer').scrollTop,
      folds:document.querySelectorAll('#dr-b details[open]').length};
    const checks={version:DATA.ui_generation===status.ui_generation,documentPreserved:window.__refreshSentinel==='keep-me',
      state:before.state===after.state,mode:before.mode===after.mode&&before.manual===after.manual,
      scroll:before.scroll===after.scroll,drawerScroll:before.drawer===after.drawer,
      meaningfulScroll:before.drawer>0,folds:before.folds===after.folds,
      drawer:document.getElementById('drawer').classList.contains('open')&&UI_DRAWER.id==='600241',
      query:document.getElementById('q').value==='电池',
      sameVersionCache:Object.keys(UI_CACHE).every(k=>k.startsWith(status.ui_generation+'|'))};
    closeDrawer();goPane('boards');BC_SEARCH='电池';BC_FILTER='all';renderBoards();
    let input=document.getElementById('bc-search-boards');input.focus();
    input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
    // Re-load the other retained real generation to exercise the composition gate.
    const deferred=updateDashboardData({ui_generation:previous,data_version:1});
    await new Promise(r=>setTimeout(r,500));
    checks.imeDeferred=DATA.ui_generation===status.ui_generation&&document.activeElement===input;
    input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'电池'}));await deferred;
    checks.imeFocus=document.activeElement===document.getElementById('bc-search-boards');
    await updateDashboardData(status);
    return {checks,before,after};
  },{previous,status});
  const expired=await page.request.get(base+'/__ui/detail?version='+('0'.repeat(24))+'&kind=stock&id=600241');
  result.checksExpired=expired.status()===409;
  const foreign=await page.request.post(base+'/__ui/export',{headers:{Origin:'https://foreign.example'},data:{version:status.ui_generation,codes:['600241'],contexts:{}}});
  result.foreignRejected=foreign.status()===403;
  await page.screenshot({path:'D:/股票强势监测/research/performance_20261010/refresh_state.png',fullPage:false});
  return result;
}
