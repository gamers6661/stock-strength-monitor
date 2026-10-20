/* Official index chart only. Existing board strength and member sections stay intact. */
(function(){
 var renderBoard=showBoardById;
 showBoardById=function(id){
  renderBoard(id);
  var b=boardById(id),data=b&&b.index_chart;
  if(!b||!data)return;
  var bars=data.bars||[],hasOHLC=bars.length>=5;
  var card=document.createElement('section');card.className='card';card.id='ms-board-chart';
  card.innerHTML='<div class="ms-card-head"><h3>60日指数K线</h3><span class="cd">'+esc(data.code||'')+'</span></div>'
   +(hasOHLC?'<canvas id="k-cv" class="chart detail-chart" style="height:310px"></canvas>':'<p class="ms-muted">'+esc(data.reason||'暂无可用指数K线')+'</p>')
   +'<p class="ms-muted">'+esc(data.source||'同花顺指数')+(data.asof?' · 完成日线截至 '+esc(data.asof):'')
   +(hasOHLC?' · MA5 / MA10 / MA20 · 成交量':'')+'</p>'
   +(hasOHLC&&data.reason?'<p class="ms-muted">'+esc(data.reason)+'</p>':'')
   +(hasOHLC&&data.current_price?'<p class="ms-muted">虚线为指数报价 · '+esc(data.current_at)+'；未补成日K。</p>':'');
  var host=document.getElementById('dr-b');
  if(!host)return;
  host.insertBefore(card,host.firstChild);
  MS_CHART=null;
  if(hasOHLC){
   var cv=card.querySelector('canvas');
   MS_CHART={bars:bars,price:data.current_price};
   var tools=document.createElement('div');tools.className='ms-chart-tools';
   tools.innerHTML='<label>显示区间 <select aria-label="K线显示区间" onchange="msChartRange(Number(this.value))"><option value="60">60日</option><option value="40">40日</option><option value="20">20日</option></select></label><span id="k-readout">移到K线上查看日期、OHLC与成交量</span>';
   card.insertBefore(tools,cv);
   msDrawCandles(cv,bars,data.current_price,60);
   var latest=bars[bars.length-1],readout=card.querySelector('#k-readout');
   if(readout)readout.textContent='最新日K '+latest.date+' · 开 '+fmt(latest.open,2)+' 高 '+fmt(latest.high,2)+' 低 '+fmt(latest.low,2)+' 收 '+fmt(latest.close,2)+' · 成交量 '+volumeWan(latest.volume);
  }
 };
})();

/* Compact member records omit classification. Resolve from this same frozen stock pool. */
(function(){
 var affiliation=msAffiliation;
 msAffiliation=function(row,key){
  if(key!=='members')return affiliation(row,key);
  var stock=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).find(function(s){return s.code===row.code;})||{};
  function first(value){return Array.isArray(value)?value.filter(Boolean)[0]:value;}
  var industry=first(row.industry_detail)||first(stock.industry_detail)||first(stock.primary_industry)
    ||first(row.industry)||first(stock.industry)||'行业待核对';
  return affiliation(Object.assign({},row,{industry_detail:industry}),key);
 };
})();
