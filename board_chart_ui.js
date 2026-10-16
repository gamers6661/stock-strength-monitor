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
  }
 };
})();
