
var DATA = /*__DATA__*/null;

/* ── 渲染错误兜底 ──
   一个 JS 异常就会让某个页签整页空白，而控制台之外没有任何提示 ——
   用户只会看到"页面是空的"，无从判断是数据问题还是代码问题。
   这里把首次异常直接顶到页面顶端，并给出函数名与行号。 */
window.addEventListener('error',function(e){
  try{
    var bar=document.getElementById('__err');
    if(!bar){
      bar=document.createElement('div'); bar.id='__err';
      bar.style.cssText='position:fixed;left:0;right:0;top:0;z-index:9999;'
        +'background:#fff3f2;color:#a1201a;border-bottom:1px solid #f2c9c5;'
        +'font:12.5px/1.5 -apple-system,system-ui,sans-serif;padding:9px 16px';
      document.body.appendChild(bar);
    }
    if(!bar.dataset.once){
      bar.dataset.once='1';
      bar.innerHTML='<b>看板渲染出错</b>：'+esc(e.message||'未知错误')
        +'　<code style="opacity:.7">'+(e.filename||'').split('/').pop()
        +':'+(e.lineno||'?')+(e.colno?':'+e.colno:'')+'</code>'
        +'　<span style="cursor:pointer;text-decoration:underline" '
        +'onclick="this.parentNode.remove()">关闭</span>';
    }
  }catch(_){}
});

/* ═══════════════ 工具 ═══════════════ */
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function n(v,d){var x=Number(v);return isFinite(x)?x:(d===undefined?0:d);}
// boards/display_boards 是核对后的个股题材；concepts 是 F10 完整原始相关概念。
function displayBoards(s){return (s&&s.display_boards&&s.display_boards.length)
  ? s.display_boards : ((s&&s.boards)||[]);}
function displayConcepts(s){return (s&&s.concepts&&s.concepts.length)
  ? s.concepts : displayBoards(s);}
function fmt(v,d){var x=Number(v);if(!isFinite(x))return '—';return x.toFixed(d===undefined?2:d);}
function sgn(v,d){var x=Number(v);if(!isFinite(x))return '—';d=d===undefined?2:d;
  return (x>0?'+':'')+x.toFixed(d);}
function cls(v){var x=Number(v);return x>0?'up':(x<0?'down':'flat');}
function pct(v,d){return sgn(v,d)+'%';}
/* 成交额格式化：入参单位是万元（腾讯行情/我方估算都用万元）。
   原实现把"万元÷1e4=亿元"的结果又拿去和 1e4 比，于是阈值等于"≥1万亿元"、
   永远走不到亿元分支 —— 9.58 亿的成交额被显示成「9.6万」，
   相当于所有成交额少标了 4 个数量级。 */
function yi(wan){
  var w=n(wan), y=w/1e4;                 // 万元 → 亿元
  if(y>=100)return y.toFixed(0)+'亿';
  if(y>=1)return y.toFixed(2)+'亿';
  if(w>=1)return w.toFixed(0)+'万';
  return '—';
}

function scoreColor(v){v=Math.max(0,Math.min(100,n(v)));
  if(v>=80)return '#e8271a'; if(v>=68)return '#f08c00';
  if(v>=55)return '#0071e3'; if(v>=42)return '#5e5ce6'; return '#6e6e73';}
function hm(v){v=Math.max(0,Math.min(100,n(v)));
  var bg,tx;
  if(v>=75){bg='rgba(232,39,26,'+(0.15+(v-75)/25*0.32).toFixed(3)+')';tx='#c62216';}
  else if(v>=55){bg='rgba(0,113,227,'+(0.12+(v-55)/20*0.24).toFixed(3)+')';tx='#0071e3';}
  else if(v>=40){bg='rgba(0,0,0,.05)';tx='#6e6e73';}
  else{bg='rgba(18,164,92,'+(0.09+(40-v)/40*0.2).toFixed(3)+')';tx='#0e7a45';}
  return '<span class="hm" style="background:'+bg+';color:'+tx+'">'+fmt(v,0)+'</span>';}
function bar(v,kind){v=Math.max(0,Math.min(100,n(v)));
  return '<span class="bar'+(kind?' '+kind:'')+'"><i style="width:'+v+'%"></i></span>';}
function hmRaw(v,lo,hi){ /* 区间映射到 0-100 后上色 */
  var p=(n(v)-lo)/(hi-lo)*100; return hm(p);}

function tagHtml(t,ratio){
  var c='tag';
  if(ratio!==undefined&&ratio!==null){ if(n(ratio)>=70)c='tag hot'; else if(n(ratio)>=55)c='tag warm'; }
  return '<span class="'+c+'">'+esc(t)+'</span>';}

/* onclick 内联字符串转义 —— 题材名里可能出现括号、引号、空格，
   直接拼进 HTML 属性会把 onclick 语句截断（「柔性屏(折叠屏)」这类名字就会踩到） */
function jsq(s){return String(s==null?'':s).replace(/\\/g,'\\\\').replace(/'/g,"\\'")
  .replace(/"/g,'&quot;').replace(/</g,'&lt;');}

/* ── 板别 ──
   股票池已扩容到四板：沪主板/深主板（±10%）、创业板/科创板（±20%）。
   板别必须在每个视图都标出来 —— 混在一张榜里时不标注，用户会把
   20% 板涨 10% 当成主板涨停，评分的可比性也无从判断。 */
/* 池内板别顺序 = 快照里 board_mix 的键（只含实际纳入的板）。
   以前硬编码四板，收板后仍会渲染出两个数量为 0 的“创业板/科创板”筛选块。 */
function boardOrder(){var m=DATA.board_mix||{},ks=Object.keys(m);
  return ks.length?ks:['沪主板','深主板'];}
function bpill(s){
  if(!s)return '';
  var nm=s.board_name||s.board;          // 每日分析下发的是简写 board
  if(!nm)return '<span class="flat">—</span>';
  var k=s.board_type||k2type(nm);
  var lim=n(s.board_limit||(DATA.board_limit_by_name||{})[nm]||10);
  return '<span class="bd bd-'+esc(k)+'" title="'+esc(nm)+' · 涨跌幅限制 ±'+lim+'%">'
    +esc(nm)+'</span>';
}
/* 次新徽标单独给一个函数：它标的是"上市天数"这个状态，不是板别。
   放在名称旁边（和涨停/下行并列），板别则固定占一列，避免同一信息重复两次。 */
function npill(s){
  if(!n(s&&s.is_new))return '';
  return '<span class="bd bd-new" title="上市 '+(s.list_days==null?'—':n(s.list_days))
    +' 天（<'+n(DATA.new_stock_days||60)+' 天视为次新）· 涨跌幅限制按新股规则">次新</span>';
}
function k2type(name){
  return {'沪主板':'sh_main','深主板':'sz_main','创业板':'gem','科创板':'star'}[name]||'';
}

/* 次新统计披露：池内几只、真正打分几只、差集为什么没进榜。
   不写清楚的话，用户看到"池内次新 20 只"却只筛到 7 只，第一反应是筛选坏了。 */
function newStatHtml(){
  return gateHtml();
}
/* 距 MA20 的 ATR 倍数着色：绿=刚进趋势、蓝=健康区、橙=偏热、红=过热 */
function distAtrCls(v){
  v=n(v);
  if(v<0)return 'flat';
  if(v<0.5)return '';
  if(v<=2.5)return 'down';
  if(v<=3.5)return 'wa';
  return 'up';
}
/* V3 的 Risk Gate 硬门槛：不计权重，直接决定是否进候选池。
   把每条门槛的剔除数量摊开 —— 静默丢股票比丢错股票更糟。 */
function gateHtml(){
  var g=DATA.risk_gate; if(!g)return '';
  var d=g.dropped||{};
  var rows=[['上市交易日不足 '+n(g.min_trading_days),d.bars],
             ['当日无成交 / 停牌',d.notrade],
            ['无K线数据',d.nokline]];
  var body=rows.filter(function(x){return n(x[1])>0;})
    .map(function(x){return '　· '+x[0]+'：剔除 <b>'+n(x[1])+'</b> 只';}).join('<br>');
  return '<br><b style="color:var(--orange)">Risk Gate 硬门槛</b>'
    +'（不计权重，直接决定是否进候选池）：入池 '+n(g.pool_in)+' 只 → 通过 <b>'
    +n(g.passed)+'</b> 只'
     +(body?('<br>'+body):'')
     +'<br><span style="opacity:.8">历史成交额仅作参考，不设入榜门槛。</span>';
}

function toast(msg){
  var t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('on');
  clearTimeout(t._tm); t._tm=setTimeout(function(){t.classList.remove('on');},2600);}

/* ── 悬浮说明气泡 ──
   为什么不用 CSS ::after：气泡会被祖先的 overflow 裁掉。
   「距MA20(ATR)」在 .metric 里（overflow:hidden），表头提示在 .tw 里
   （overflow-x:auto，overflow-y 随之变 auto）—— 两处都会把气泡切掉，
   只剩最后一行露在卡片里，看起来就像说明文字漏成了正文。
   现在改成挂在 body 上的 fixed 层：脱离所有裁剪容器，并在视口内钳位。 */
var TIPBOX=null, TIPEL=null;
function tipBoxEl(){
  if(!TIPBOX){
    TIPBOX=document.createElement('div');
    TIPBOX.className='tipbox';
    TIPBOX.setAttribute('role','tooltip');
    document.body.appendChild(TIPBOX);
  }
  return TIPBOX;
}
/* 定位锚点：指标卡这类「标签在上、数值在下」的小卡片，锚到**卡片本身**。
   若锚在数值上，气泡会正好压在卡片自己的标签上 ——
   用户看到的就是「数值区被一段说明文字顶掉」。 */
function tipAnchor(el){
  return el.closest('.metric') || el;
}
/* 定位规则：默认放锚点上方；上方不够就翻到下方；水平居中并夹在视口内。
   （fixed 层只在位移计算里用 rect，不受任何祖先 transform 影响 —— 所以
   它必须挂在 body 上，挂在抽屉里的话抽屉的 translateX 会变成它的包含块。） */
function placeTip(el){
  if(!TIPBOX||!TIPEL)return;
  var r=tipAnchor(el).getBoundingClientRect(), b=TIPBOX.getBoundingClientRect();
  var vw=window.innerWidth, vh=window.innerHeight, GAP=9, PAD=10;
  var top=r.top-b.height-GAP;
  if(top<PAD) top=r.bottom+GAP;
  if(top+b.height>vh-PAD) top=Math.max(PAD, vh-b.height-PAD);
  var left=r.left+r.width/2-b.width/2;
  left=Math.min(Math.max(left,PAD), Math.max(PAD, vw-b.width-PAD));
  TIPBOX.style.left=Math.round(left)+'px';
  TIPBOX.style.top=Math.round(top)+'px';
}
function showTip(el){
  var txt=el.getAttribute('data-tip')||'';
  if(!txt)return;
  var box=tipBoxEl();
  box.textContent=txt;          // textContent：说明文字里出现 < > 也不会被当标签解析
  TIPEL=el;
  box.classList.add('on');
  placeTip(el);
}
function hideTip(){ if(TIPBOX)TIPBOX.classList.remove('on'); TIPEL=null; }
document.addEventListener('mouseover',function(e){
  var el=(e.target&&e.target.closest)?e.target.closest('.tip'):null;
  if(el){ if(el!==TIPEL)showTip(el); }
  else if(TIPEL)hideTip();
});
document.addEventListener('mouseout',function(e){
  var el=(e.target&&e.target.closest)?e.target.closest('.tip'):null;
  if(el && !(e.relatedTarget&&el.contains(e.relatedTarget)))hideTip();
});
/* 抽屉内部的滚动不会冒泡到 window，但捕获阶段能收到 —— 气泡跟随元素走 */
window.addEventListener('scroll',function(){ if(TIPEL)placeTip(TIPEL); },true);
window.addEventListener('resize',hideTip);

/* ═══════════════ 全局状态 ═══════════════ */
/* 筛选条件的默认值 —— **唯一真源**。
   这里曾经同时存在两份手写的默认对象（一份在 STATE 初始化里、一份在 clearFilters 里），
   新增「板别 / 次新」字段时只改了后一份，结果初始加载时 STATE.filters.boards 是
   undefined，activeFilterCount() 里 f.boards.length 直接抛 TypeError，
   个股页整页空白 —— 只在首次进入时复现，改完点一下"重置"反而正常，极难发现。
   现在两处都调这个工厂函数，不可能再漂移。 */
function defaultFilters(){
  return {themes:[],industries:[],boards:[],states:[],scoreMin:0,scoreMax:100,
    chgMin:-21,chgMax:21,intraMin:0,intraMax:100,ret5Min:-50,ret5Max:200,turnMin:0,turnMax:100,
    vrMin:0,vrMax:200,capMin:0,capMax:100000,
    fundMin:0,fundMax:100,pos60Min:0,pos60Max:100,
    distMin:-10,distMax:10};
}

var STATE={
  pane:'overview',
  period:'all',
  strategy:'trend',
  q:'',
  sort:{stocks:{k:null,asc:false},boards:{k:'score',asc:false},hold:{k:'score',asc:false}},
  limit:80,
  // 区间筛选一律用「下限~上限」成对出现，未改动时等于全域值（不参与计数）。
  // 之前没有资金分与60日位置的区间，用户想筛"资金流入前30%"只能靠状态标签猜。
  filters:defaultFilters(),
  cols:{board:true,industry:true,factors:true},
  // 状态标签多选逻辑：'and' 需同时满足（适合"低位+放量"这类叠加条件），
  // 'or' 任一满足（适合"首板或连板"这类并列条件）。
  // 旧版写死 every()，用户勾两三个标签就一只股票都筛不出来，误以为筛选坏了。
  stateMode:'and'
};
/* 注：PRESETS 统一在下方「个股页」段落定义一次即可。此前这里还有一份重复定义，
   后者覆盖前者、前一份变成死代码，改了一处不生效 —— 已删。 */

/* ═══════════════ 分段控制器 ═══════════════ */
function segInit(el,onChange){
  if(!el)return;
  var btns=[].slice.call(el.querySelectorAll('button')), sl=el.querySelector('.sl');
  function move(b){ if(!b||!sl)return; sl.style.width=b.offsetWidth+'px';
    sl.style.transform='translateX('+(b.offsetLeft-3)+'px)'; }
  var act=el.querySelector('button.on')||btns[0];
  requestAnimationFrame(function(){move(act);});
  el.addEventListener('click',function(e){
    var b=e.target.closest('button'); if(!b||!el.contains(b))return;
    btns.forEach(function(x){x.classList.remove('on');});
    b.classList.add('on'); move(b);
    // data-s 是策略切换器的键。**segInit 读不到这个键时会回退成空串**，
    // 而 setStrategy('') 会被兜底成 'trend' —— 表现为"滑块动了、页面什么都没变"。
    // 新增任何分段控制器，都必须在这里同步它的 data-* 键名，
    // 否则按钮看着是选中了，回调却一直收到空值。
    if(onChange)onChange(b.getAttribute('data-p')||b.getAttribute('data-k')
      ||b.getAttribute('data-f')||b.getAttribute('data-s')||b.getAttribute('data-work')||'');
  });
  window.addEventListener('resize',function(){move(el.querySelector('button.on')||btns[0]);});
}

/* ═══════════════ 策略切换（两套因子完全独立） ═══════════════ */
/* 当前策略。'trend'=波段趋势 V3，'ignition'=短线启动 V2。
   两套因子分、因子列、雷达、注释**分键存、二选一渲染**，绝不混用。 */
function strat(){ return 'trend'; }
function stratScore(s){ return s.stock_strength_percentile; }
function stratFactors(s){ return s.factors||{}; }
function stratCols(){
  var m=DATA.strategy_factors||{};
  var f=m[strat()]||m['trend']||[];
  return f.map(function(x){return [x[0], x[1]];});
}
function stratMeta(){
  var ls=DATA.strategies||[];
  for(var i=0;i<ls.length;i++) if(ls[i].key===strat()) return ls[i];
  return ls[0]||{key:'trend',name:'趋势与日线进攻强度 V3.8'};
}
function updateStratbar(){
  var el=document.getElementById('stratbar'); if(!el)return;
  var m=stratMeta();
  el.innerHTML='<span class="s-key">'+esc(m.short)+'</span>'
    +'<span class="s-model">'+esc(m.model)+'</span>'
    +'<span>'+esc(m.hook)+'</span>'
    +'<span>'+esc(m.hold)+'</span>';
}
function setStrategy(k, silent){
  k='trend';
  STATE.strategy=k;
  var seg=document.getElementById('seg-strategy');
  if(seg){ [].forEach.call(seg.querySelectorAll('button'),function(b){
    b.classList.toggle('on', b.getAttribute('data-s')===k);}); }
  updateStratbar();
  // 策略影响：个股榜、选股雷达、详情抽屉、CSV、总览强势股小榜
  RENDERED.stocks=false; RENDERED.radar=false; RENDERED.overview=false;
  if(!silent){
    goPane(STATE.pane);
    if(STATE.pane==='overview')renderOverview();   // goPane 不重渲染总览，这里补上
    toast('已切换：'+stratMeta().name);
  }
}

/* ═══════════════ 抽屉 ═══════════════ */
function openDrawer(title,sub,html,wide){
  document.getElementById('dr-t').innerHTML=title;
  document.getElementById('dr-s').innerHTML=sub||'';
  document.getElementById('dr-b').innerHTML=html;
  document.getElementById('dr-b').scrollTop=0;
  var d=document.getElementById('drawer');
  d.classList.toggle('wide',!!wide);
  d.classList.add('open');
  document.getElementById('scrim').classList.add('on');
}
function closeDrawer(){
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('scrim').classList.remove('on');
}

/* ═══════════════ 数据新鲜度 ═══════════════ */
function parseDT(s){
  s=String(s||''); var m=s.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if(!m)return null;
  return new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6]);
}
function sessionNow(){
  var d=new Date(), w=d.getDay(), t=d.getHours()*60+d.getMinutes();
  if(w===0||w===6)return '休市';
  if(t<9*60+15)return '盘前';
  if(t<9*60+25)return '集合竞价';
  if(t<9*60+30)return '竞价结束';
  if(t<=11*60+30)return '早盘';
  if(t<13*60)return '午间休市';
  if(t<=15*60)return t>=14*60+30?'尾盘':'午盘';
  return '已收盘';
}
function useCompletedClose(){
  return (DATA&&DATA.session==='非交易日')
    ||['盘前','已收盘','休市'].indexOf(sessionNow())>=0;
}
function savedBoundaryQuote(s,kind){
  var boundary=(DATA&&DATA.boundary_prices)||{},now=new Date();
  var today=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')
    +'-'+String(now.getDate()).padStart(2,'0');
  if(boundary.date!==today||!s)return null;
  var batch=boundary[kind]||{},q=(batch.prices||{})[String(s.code)];
  if(!q||!(Number(q.price)>0)||q.change_pct==null||!isFinite(Number(q.change_pct)))return null;
  return {price:Number(q.price),change:Number(q.change_pct),at:today+' '+batch.cutoff,
    sourceAt:q.source_at||'',capturedAt:batch.captured_at||'',
    kind:kind==='auction_final'?'竞价结束截至09:25':kind==='midday'?'午间截至11:30':'收盘报价截至15:00'};
}
function auctionDisplayQuote(s){
  if(['集合竞价','竞价结束'].indexOf(sessionNow())<0||!s)return null;
  var now=new Date(),today=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')
    +'-'+String(now.getDate()).padStart(2,'0');
  var final=savedBoundaryQuote(s,'auction_final');if(final)return final;
  var q=s.auction_observation||{},at=String(q.quote_at||''),minute=at.slice(11,16);
  if(at.slice(0,10)!==today||minute<'09:15'||minute>'09:25'
      ||!(Number(q.price)>0)||q.change_pct==null||!isFinite(Number(q.change_pct)))return null;
  return {price:Number(q.price),change:Number(q.change_pct),at:at,sourceAt:at,
    kind:now.getHours()*60+now.getMinutes()>=9*60+25?'竞价末价待确认':'集合竞价报价'};
}
function morningOpenBridgeQuote(s){
  if(sessionNow()!=='早盘'||quoteFreshAtClientNow(s))return null;
  var final=savedBoundaryQuote(s,'auction_final');if(final)return final;
  var q=s&&s.auction_observation||{},at=String(q.quote_at||''),now=new Date();
  var today=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')
    +'-'+String(now.getDate()).padStart(2,'0');
  if(at.slice(0,10)!==today||at.slice(11,16)<'09:15'||at.slice(11,16)>'09:25'
      ||!(Number(q.price)>0)||q.change_pct==null||!isFinite(Number(q.change_pct)))return null;
  return {price:Number(q.price),change:Number(q.change_pct),at:at,sourceAt:at,kind:'最近竞价参考'};
}
function morningReferenceQuote(s){
  if(!s)return null;
  var saved=savedBoundaryQuote(s,'midday');if(saved)return saved;
  var now=new Date(),today=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')
    +'-'+String(now.getDate()).padStart(2,'0');
  var sourceAt=String(s.intraday_quote_at||'');
  var sourceMinute=sourceAt.slice(11,16);
  var price=Number(s.price),high=Number(s.high),low=Number(s.low);
  var traded=Number(s.amount_wan)>0||Number(s.volume_shou)>0;
  if(sourceAt.slice(0,10)===today&&sourceMinute>='11:30'&&sourceMinute<'13:00'
      &&price>0&&high>=low&&low>0&&price>=low-.011&&price<=high+.011
      &&s.change_pct!=null&&isFinite(Number(s.change_pct))&&traded){
    return {price:price,change:Number(s.change_pct),at:today+' 11:30',
      sourceAt:sourceAt,kind:'午间截至11:30'};
  }
  var oldAt=String(s.last_valid_quote_at||s.intraday_quote_at||'');
  var oldPrice=Number(s.last_valid_price||s.price);
  var oldChange=s.last_valid_change_pct==null?s.change_pct:s.last_valid_change_pct;
  if(oldAt.slice(0,10)===today&&oldAt.slice(11,16)>='09:30'
      &&oldAt.slice(11,16)<='11:30'&&oldPrice>0&&oldChange!=null
      &&isFinite(Number(oldChange)))
    return {price:oldPrice,change:Number(oldChange),at:oldAt,
      sourceAt:oldAt,kind:'上午最后有效报价'};
  return null;
}
function lunchDisplayQuote(s){
  return sessionNow()==='午间休市'?morningReferenceQuote(s):null;
}
function afternoonBridgeQuote(s){
  var phase=sessionNow();
  return (phase==='午盘'||phase==='尾盘')&&!quoteFreshAtClientNow(s)
    ?morningReferenceQuote(s):null;
}
function closeDisplayQuote(s){
  if(!s)return null;
  var now=new Date(),today=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')
    +'-'+String(now.getDate()).padStart(2,'0');
  if(s.last_completed_date===today&&Number(s.last_completed_close)>0)
    return {price:Number(s.last_completed_close),change:s.last_completed_change_pct,
      at:today,kind:'正式收盘'};
  if(sessionNow()==='已收盘'&&DATA.session!=='非交易日'){
    var boundary=savedBoundaryQuote(s,'close');if(boundary)return boundary;
  }
  return Number(s.last_completed_close)>0?{price:Number(s.last_completed_close),
    change:s.last_completed_change_pct,at:s.last_completed_date||'',kind:'最近完成日收盘'}:null;
}
function quoteFreshAtClientNow(s){
  if(!s||s.intraday_quote_fresh!==true)return false;
  var at=parseDT(s.intraday_quote_at),now=new Date(Date.now());
  if(!at||at.getFullYear()!==now.getFullYear()||at.getMonth()!==now.getMonth()
     ||at.getDate()!==now.getDate())return false;
  var meta=(DATA&&DATA.intraday_model)||{};
  var age=(now.getTime()-at.getTime())/1000;
  var maxAge=Number(meta.max_quote_age_seconds),maxFuture=Number(meta.max_quote_future_seconds);
  if(!isFinite(maxAge)||maxAge<=0)maxAge=600;
  if(!isFinite(maxFuture)||maxFuture<0)maxFuture=90;
  return age<=maxAge&&age>=-maxFuture;
}
function currentCandidateQuoteUsable(s){
  var phase=sessionNow();
  if(['早盘','午盘','尾盘'].indexOf(phase)<0||!quoteFreshAtClientNow(s))return false;
  var at=parseDT(s.intraday_quote_at),minute=at.getHours()*60+at.getMinutes();
  return (minute>=9*60+30&&minute<=11*60+30)||(minute>=13*60&&minute<=15*60);
}
function currentCandidateActive(s,key){return !!(s&&s[key]===true&&currentCandidateQuoteUsable(s));}
function quoteStatusAtClientNow(s){
  var phase=sessionNow(),stamp=(s&&s.last_valid_quote_at)
    ||(s&&s.intraday_quote_fresh===true&&s.intraday_quote_at)||'';
  if(phase==='午间休市'){
    var lunch=lunchDisplayQuote(s);
    return lunch?lunch.kind+' · 盘中观察截至 '+(stamp||'未知'):'午间休市 · 上午报价待核对';
  }
  if(afternoonBridgeQuote(s))return '午后报价待更新 · 暂显11:30价格';
  var morningBridge=morningOpenBridgeQuote(s);
  if(morningBridge)return '开盘报价待更新 · 暂显'+morningBridge.kind+' '+morningBridge.sourceAt;
  if(phase==='盘前')return '盘前观察 · 最近有效 '+(stamp||'报价时间未知');
  if(phase==='集合竞价'||phase==='竞价结束'){
    var auction=auctionDisplayQuote(s);
    return auction?'竞价报价 '+auction.sourceAt+' · 盘中趋势待确认':
      '竞价报价未更新 · 上次有效 '+(stamp||'未知');
  }
  if(phase==='休市')return '非交易日 · 最近有效 '+(stamp||'报价时间未知');
  if(phase==='已收盘')return '收盘后对照 · 最后有效 '+(stamp||'报价不可判断')
    +(s&&s.intraday_quote_fresh===true&&!quoteFreshAtClientNow(s)?' · 报价已过期':'');
  if(s&&s.intraday_quote_fresh!==true)
    return (s.intraday_quote_status||'报价不可判断')+(stamp?' · 最后有效 '+stamp:'');
  return '报价已过期 · 最后有效 '+(stamp||'时间未知');
}
function freshness(){
  var im=(DATA&&DATA.intraday_model)||{};
  var stamp=DATA&&['集合竞价','竞价结束'].indexOf(DATA.session)>=0?im.auction_latest_quote_at:im.latest_valid_quote_at;
  if(!stamp){
    var rows=(DATA&&DATA.stocks||[]).concat(DATA&&DATA.coverage_catalog||[]);
    rows.forEach(function(s){if(s.intraday_quote_fresh===true&&s.intraday_quote_at
      &&(!stamp||s.intraday_quote_at>stamp))stamp=s.intraday_quote_at;});
  }
  var dt=parseDT(stamp); if(!dt)return null;
  return Math.max(0,Math.round((Date.now()-dt.getTime())/60000));
}
var LAST_CANDIDATE_WINDOW=null,LAST_RENDERED_PHASE=null;
function refreshPageFreshness(){
  var phase=sessionNow(),phaseChanged=LAST_RENDERED_PHASE!==null&&LAST_RENDERED_PHASE!==phase;
  LAST_RENDERED_PHASE=phase;
  renderFresh();
  if(!WORK_MANUAL&&WORK_MODE!==autoWorkMode())setWorkMode(autoWorkMode(),false);
  else if(WORK_MODE)renderWorkboard();
  var open=(DATA.stocks||[]).concat(DATA.coverage_catalog||[])
    .some(currentCandidateQuoteUsable);
  if(phaseChanged||(LAST_CANDIDATE_WINDOW!==null&&open!==LAST_CANDIDATE_WINDOW)){
    LAST_CANDIDATE_WINDOW=open;
    renderStocks();renderOverview();
  }else if(LAST_CANDIDATE_WINDOW===null)LAST_CANDIDATE_WINDOW=open;
}
function renderFresh(){
  var mins=freshness();
  var el=document.getElementById('fresh-txt'), dot=document.getElementById('fresh-dot');
  var im=(DATA&&DATA.intraday_model)||{}, auctionOnly=DATA&&['集合竞价','竞价结束'].indexOf(DATA.session)>=0;
  var stamp=(auctionOnly?im.auction_latest_quote_at:im.latest_valid_quote_at)||'';
  if(!stamp){
    (DATA&&DATA.stocks||[]).concat(DATA&&DATA.coverage_catalog||[]).forEach(function(s){
      if(s.intraday_quote_fresh===true&&s.intraday_quote_at&&(!stamp||s.intraday_quote_at>stamp))stamp=s.intraday_quote_at;});
  }
  if(location.protocol==='file:'){
    el.textContent='静态快照 · 行情截至 '+(stamp||'未知')+' · 不接收后台更新';
    dot.style.background='#8e8e93';dot.style.boxShadow='none';
    return;
  }
  var sess=sessionNow();
  var auctionFinal=(DATA.boundary_prices||{}).auction_final||{};
  var today=new Date(),todayKey=today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')
    +'-'+String(today.getDate()).padStart(2,'0');
  var finalReady=String((DATA.boundary_prices||{}).date||'')===todayKey&&Number(auctionFinal.count)>0;
  var liveOpen=String(im.latest_valid_quote_at||'').slice(0,10)===todayKey
    &&String(im.latest_valid_quote_at||'').slice(11,16)>='09:30'
    &&(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).some(quoteFreshAtClientNow);
  if(sess==='集合竞价'||sess==='竞价结束'){
    el.textContent=finalReady?'竞价结束 · 9:25参考 '+n(auctionFinal.count)+' 只 · 等待9:30开盘':
      (sess==='竞价结束'?'竞价结束 · 末价待确认':'集合竞价')+' · 报价 '+n(im.auction_quote_count)+' 只 · 源时间 '+(im.auction_latest_quote_at||'待更新');
    dot.style.background=finalReady||mins!=null&&mins<=10?'#12a45c':'#f08c00';dot.style.boxShadow='none';return;
  }
  if(sess==='早盘'&&!liveOpen){
    el.textContent='正式开盘 · 报价待更新'
      +(finalReady?' · 暂显9:25竞价参考':String(im.auction_latest_quote_at||'').slice(0,10)===todayKey?' · 暂显最近竞价参考':'');
    dot.style.background='#f08c00';dot.style.boxShadow='none';return;
  }
  if(mins===null){el.textContent='无有效逐股报价';dot.style.background='#f08c00';dot.style.boxShadow='none';return;}
  var stale = auctionOnly?(mins>10||['早盘','午盘','尾盘'].indexOf(sess)>=0):
    (sess==='早盘'||sess==='午盘'||sess==='尾盘')&&mins>10;
  var ageText=mins<1?'刚刚':mins+' 分钟前';
  var lunchSource='';
  if(sess==='午间休市')stockPoolRows().forEach(function(s){
    var q=lunchDisplayQuote(s);
    if(q&&q.kind==='午间截至11:30'&&q.sourceAt>lunchSource)lunchSource=q.sourceAt;
  });
  var lunchBatch=(DATA.boundary_prices||{}).midday;
  var closeBatch=(DATA.boundary_prices||{}).close;
  var closeReady=sess==='已收盘'&&closeBatch
    &&String(closeBatch.captured_at||'').slice(0,10)===String((DATA.boundary_prices||{}).date||'')
    &&parseDT(closeBatch.captured_at)&&parseDT(closeBatch.captured_at).toDateString()===new Date().toDateString();
  el.textContent = auctionOnly?'竞价报价 '+n(im.auction_quote_count)+' 只 · 截至 '+stamp
    +(['早盘','午盘','尾盘'].indexOf(sess)>=0?' · 等待盘中更新':''):
    sess==='午间休市'?'午间休市 · 上午交易截至 11:30 · 评分截至 '+stamp
      +(lunchSource?' · 源刷新 '+lunchSource.slice(11,16):'')
      +(lunchBatch?' · 抓取 '+String(lunchBatch.captured_at||'').slice(11,16):''):
    sess==='休市'?'非交易时段 · 最近行情截至 '+stamp:
    sess==='已收盘'?(closeReady?'收盘后 · 价格截至 15:00 · 源抓取 '+String(closeBatch.captured_at||'').slice(11,16)
      +' · 正式日线截至 '+((DATA.strength_model||{}).asof||'待更新'):
      '收盘后 · 定点收盘报价待更新 · 上次行情 '+stamp):
    sess==='午盘'&&String(stamp).slice(11,16)<'13:00'
      ?'午后开盘 · 等待新报价 · 暂显11:30价格':
    ageText+' · '+sess+' · 行情截至 '+stamp+(stale?' · 报价已过期':'');
  dot.style.background = stale ? '#f08c00' : (sess==='休市'||sess==='午间休市'||sess==='已收盘'||sess==='盘前'?'#8e8e93':'#12a45c');
  dot.style.boxShadow = stale ? '0 0 9px #f08c00' : 'none';
  if(location.protocol==='http:'||location.protocol==='https:'){
    fetch('/__status',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
      var loaded=DATA.scan_completed_at||DATA.generated_at;
      if(s.last_publish_ok===false)el.textContent+=' · 页面发布失败';
      else if(s.snapshot_generated_at&&loaded&&s.snapshot_generated_at>loaded)el.textContent+=' · 新版本待载入';
      else if(s.last_publish_ok===true&&s.snapshot_generated_at===loaded)el.textContent+=' · 服务已发布并载入';
    }).catch(function(){});
  }
}

/* ═══════════════ 主动刷新数据 ═══════════════
   看板数据是构建时**内联进 HTML** 的（DATA 常量），所以「刷新」不能只是重载页面
   —— 重载读到的还是同一份旧数据，用户会以为按钮坏了。真正的刷新是让本地服务
   重跑一次扫描、重建 dashboard.html，然后本页再重载。

   两条路径：
     · 服务在跑（http 打开）→ POST /__refresh 触发重扫，轮询 /__status 到结束再重载
     · 双击 html 本地打开（file://）→ 没有服务端可调用，直接提示怎么启动服务

   为什么要有冷却：连点会连续打东财/腾讯接口，触发风控后整段被封 20 分钟以上，
   所以服务端 60 秒内只接受一次请求，前端把剩余秒数如实告诉用户。 */
 var RF={busy:false,t0:0,poll:null,hard:null,warned:false,
          followBackground:false,versionChanged:false};
 var PAGE_VERSION=null;
function rfLabel(txt,busy){
  var b=document.getElementById('btn-refresh'); if(!b)return;
  var t=document.getElementById('rf-txt');
  if(t)t.textContent=txt;
  b.classList[busy?'add':'remove']('busy');
  b.disabled=!!busy;
}
 function rfDone(){
   RF.busy=false; RF.followBackground=false; RF.versionChanged=false;
   clearInterval(RF.poll); clearTimeout(RF.hard); rfLabel('刷新数据',false);
 }
 function rfPoll(){
   clearInterval(RF.poll);
   RF.poll=setInterval(function(){
     fetch('/__status',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
       var rf=(s&&s.refresh)||{}, sec=Math.round((Date.now()-RF.t0)/1000);
       if(PAGE_VERSION===null)PAGE_VERSION=s.data_version||null;
       if(s.data_version&&PAGE_VERSION&&s.data_version!==PAGE_VERSION){
         RF.versionChanged=true;
         PAGE_VERSION=s.data_version;
         rfLabel('载入中…',true);
         setTimeout(function(){ location.reload(); },300);
         return;
       }
       if(RF.followBackground){
         if(s.scan_active){
           rfLabel('后台刷新中 '+sec+'s',true);
           if(sec>180&&!RF.warned){
             RF.warned=true;
             toast('后台仍在获取行情与历史数据，完成后本页自动更新');
           }
           return;
         }
         if(s.last_scan_ok===false){
           var bgErr=s.last_scan_error||'数据源连接失败';
           rfDone(); toast('后台本轮未发布：'+bgErr);
           return;
         }
         rfLabel('载入中…',true);
         setTimeout(function(){ location.reload(); },300);
         return;
       }
       if(rf.running){
         rfLabel('刷新中 '+sec+'s',true);
        // 分类成员与概念指数映射由明确的分类更新命令维护；这里仅等待行情扫描。
        if(sec>180&&!RF.warned){
          RF.warned=true;
          toast('行情扫描仍在进行，完成后会自动载入新数据');
        }
        return;
      }
      if(rf.ok===false){
        rfDone();
        if(rf.reason==='not_ready'){
          toast(rf.error||'当前阶段没有可用的新行情；本轮保留上一份数据');
        } else {
          toast('刷新失败：'+(rf.error||'未知错误')+'（详情见 logs\\serve.log）');
        }
        return;
      }
       if(rf.finished_at && rf.finished_at*1000 >= RF.t0-1000){
         // 本轮跑完 → 重新载入拿到新数据。finished_at 是服务进程全局状态，
         // 必须确认它属于本次请求，不能拿上一次手动刷新时间误判。
         rfLabel('载入中…',true);
         setTimeout(function(){ location.reload(); },600);
         return;
      }
      if(sec>20){ rfDone(); toast('刷新状态异常，请稍后手动刷新页面'); }
    }).catch(function(){
      rfDone(); toast('与本地服务的连接中断了，请检查服务是否还在运行');
    });
  },2000);
  // 只停止"等待"，不是中断服务端扫描：扫完的数据照样会落盘，重载页面即可看到
  RF.hard=setTimeout(function(){
    if(RF.busy){ rfDone(); toast('等待超过 20 分钟已放弃跟踪 —— 数据跑完直接刷新页面即可'); }
  },1200000);
}
function refreshData(){
  if(RF.busy){ toast('正在刷新中，请等它跑完'); return; }
  if(location.protocol!=='http:'&&location.protocol!=='https:'){
    toast('当前是双击 html 本地打开，没有服务端可抓数据 —— 用「打开看板.bat」启动服务后再点这里');
    return;
  }
  RF.busy=true; RF.t0=Date.now(); RF.warned=false; rfLabel('刷新中…',true);
  fetch('/__refresh',{method:'POST',cache:'no-store'})
    .then(function(r){
      if(!r.ok)throw new Error('HTTP '+r.status);
      return r.json();
    })
     .then(function(j){
       if(j.status==='cooldown'){
         rfDone(); toast('刚刷新过，'+j.wait+' 秒后可再刷（避免触发数据源风控）'); return;
       }
       if(j.status==='busy'){
         RF.followBackground=true;
         rfLabel('后台刷新中…',true);
         toast('后台正在刷新，完成后本页会自动载入新数据');
       }
       rfPoll();                                 // started / busy 都进入轮询
    })
    .catch(function(e){
      rfDone(); toast('刷新请求失败：'+((e&&e.message)||e)+'（本地服务可能已停止）');
    });
 }

 /* 后台自动扫描完成后，已打开的页面也要拿到新版本。
    只读 /__status 的文件版本，不重复抓行情。 */
 function watchDataVersion(){
   if(location.protocol!=='http:'&&location.protocol!=='https:')return;
   fetch('/__status',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
     var v=s&&s.data_version;
     if(!v)return;
     if(PAGE_VERSION===null){PAGE_VERSION=v;return;}
     if(v!==PAGE_VERSION){
       if(RF.busy){RF.versionChanged=true;return;}
       PAGE_VERSION=v;
       toast('数据已更新，正在载入…');
       setTimeout(function(){location.reload();},300);
     }
   }).catch(function(){});
 }

/* ═══════════════ 页签 ═══════════════ */
var RENDERED={};
function goPane(p){
  STATE.pane=p;
  [].forEach.call(document.querySelectorAll('.pane'),function(x){x.classList.remove('on');});
  var el=document.getElementById('p-'+p); if(el)el.classList.add('on');
  [].forEach.call(document.querySelectorAll('#seg button'),function(b){
    b.classList.toggle('on',b.getAttribute('data-p')===p);});
  var sl=document.querySelector('#seg .sl');
  var ab=document.querySelector('#seg button.on');
  if(sl&&ab){sl.style.width=ab.offsetWidth+'px';sl.style.transform='translateX('+(ab.offsetLeft-3)+'px)';}
  window.scrollTo({top:0,behavior:'smooth'});
  if(!RENDERED[p]){
    RENDERED[p]=true;
    if(p==='stocks')renderStocks();
    if(p==='radar')renderRadar();
    if(p==='boards')renderBoards();
    if(p==='themes')renderThemesPage();
    if(p==='hold')renderHold();
  }
  setTimeout(auditSticky,90);
}

/* 表头位置自检（幂等，开销可忽略）
   .tw 有 overflow-x:auto，按 CSS 规范 overflow-y 随之变成 auto，于是 .tw 就成了表头的
   滚动容器 —— 表头 sticky 的偏移基准是 .tw 的顶部，不是导航栏。top 一旦写成非 0，
   浏览器会把表头往下钳制，正好盖住第一行（排名第一的股票整条看不见，且肉眼看不出是 bug）。
   这里兜一道：发现表头明显偏离容器顶部就整体退回静态表头。 */
function auditSticky(){
  var bad=false;
  [].forEach.call(document.querySelectorAll('.tw'),function(tw){
    if(bad||tw.scrollTop)return;
    var th=tw.querySelector('thead th'); if(!th)return;
    var off=th.getBoundingClientRect().top-tw.getBoundingClientRect().top;
    if(off>2&&off<200)bad=true;
  });
  if(bad&&!window.__stickyOff){
    window.__stickyOff=true;
    var s=document.createElement('style');
    s.textContent='thead th{position:static !important}';
    document.head.appendChild(s);
    if(window.console)console.warn('[看板] 表头 sticky 偏移异常，已退回静态表头（否则会遮住首行）');
  }
}

/* ═══════════════ 总览 ═══════════════ */
var WORK_MODE=null,WORK_MANUAL=false,TREND_LINE=5;
function setTrendLine(period){
  if([5,10,20].indexOf(period)<0||TREND_LINE===period)return;
  TREND_LINE=period;
  setWorkMode(WORK_MODE,false);
  var list=document.getElementById('work-trend-list');
  var reclaim=document.getElementById('work-trend-reclaim-list');
  if(list&&list.parentElement)list.parentElement.scrollTop=0;
  if(reclaim&&reclaim.parentElement)reclaim.parentElement.scrollTop=0;
}
function autoWorkMode(){
  var phase=sessionNow();
  if(DATA.session==='非交易日')return 'close';
  return ['早盘','午间休市','午盘','尾盘'].indexOf(phase)>=0?'live':'close';
}
function setWorkMode(mode,manual){
  WORK_MODE=mode==='live'?'live':'close';
  if(manual)WORK_MANUAL=true;
  var tabs=document.querySelectorAll('#work-switch button');
  tabs.forEach(function(b){b.classList.toggle('on',b.getAttribute('data-work')===WORK_MODE);});
  var chosen=document.querySelector('#work-switch button.on'),slider=document.querySelector('#work-switch .sl');
  if(chosen&&slider){slider.style.width=chosen.offsetWidth+'px';slider.style.transform='translateX('+(chosen.offsetLeft-3)+'px)';}
  document.getElementById('ov-work-live').classList.toggle('on',WORK_MODE==='live');
  document.getElementById('ov-work-close').classList.toggle('on',WORK_MODE==='close');
  document.getElementById('hero-h1').textContent=WORK_MODE==='live'?'进攻与再启动监测':'收盘进攻强势主榜';
  var cb=DATA.close_strong_board||{},trend=DATA['trend_ma'+TREND_LINE+'_observation']||{};
  document.getElementById('hero-p').textContent=WORK_MODE==='live'
    ?'暂态进攻A · 反包与整理突破 · 风险独立显示 · '+(trend.baseline_asof||'上一完成交易日')+' 趋势股近线观察'
    :'以 '+(cb.asof||'最近完成日')+' 正式日线和现有因子资格筛选；当前主榜 '+(cb.count||0)+' 只。';
  document.getElementById('work-note').textContent=(WORK_MANUAL?'手动切换':'按当前时段自动展示')
    +' · '+sessionNow()+' · 可随时切换';
  renderWorkboard();
}
function workQuoteCurrent(at){
  var dt=parseDT(at),now=new Date();
  return !!dt&&dt.toDateString()===now.toDateString()
    &&(now.getTime()-dt.getTime())/60000<=10;
}
function workRowOpen(code){return stockPoolRows().some(function(s){return s.code===code;});}
function workProfileTags(code,lookup){
  var row=lookup[String(code)]||{};
  var industry=row.primary_industry||(Array.isArray(row.industry)?row.industry[0]:row.industry)||'行业待核对';
  var concepts=displayBoards(row).filter(function(name,i,all){return name&&all.indexOf(name)===i;});
  var shown=concepts.slice(0,2);
  var html='<span class="work-observation-tags">'
    +'<span class="work-observation-tag industry" title="所属行业：'+esc(industry)+'">行业 · '+esc(industry)+'</span>';
  if(shown.length){
    html+=shown.map(function(name,i){return '<span class="work-observation-tag concept" title="同花顺概念：'+esc(name)+'">'
      +(i===0?'概念 · ':'')+esc(name)+'</span>';}).join('');
    if(concepts.length>shown.length)html+='<span class="work-observation-tag more" title="其余概念：'+esc(concepts.slice(shown.length).join(' · '))+'">+'
      +(concepts.length-shown.length)+'</span>';
  }else html+='<span class="work-observation-tag more">概念待核对</span>';
  return html+'</span>';
}
function ensureCloseBoardDisplay(){
  var close=DATA.close_strong_board||{},asof=close.asof;
  if(!asof||asof!==(DATA.strength_model||{}).asof)return;
  var stocks={};(DATA.stocks||[]).forEach(function(s){stocks[s.code]=s;});
  var boards={};(DATA.board_catalog||[]).forEach(function(b){boards[b.type+'|'+b.name]=b;});
  function peers(board,code){
    if(!board||board.asof!==asof)return null;
    var v=(board.members||[]).filter(function(m){return m.code!==code&&typeof m.change_pct==='number'&&isFinite(m.change_pct);})
      .map(function(m){return m.change_pct;});
    return v.length>=3?{change:Math.round(v.reduce(function(a,b){return a+b;},0)/v.length*100)/100,count:v.length}:null;
  }
  (close.stocks||[]).forEach(function(row){
    if(Object.prototype.hasOwnProperty.call(row,'today_change_pct'))return;
    var s=stocks[row.code];if(!s||s.signal_date!==asof)return;
    row.today_change_pct=s.signal_close>0&&s.last_close>0?Math.round((s.signal_close/s.last_close-1)*10000)/100:null;
    var industry=peers(boards['industry|'+s.primary_industry],row.code);
    row.industry=s.primary_industry;
    row.industry_peer_change_pct=industry?industry.change:null;
    row.industry_peer_count=industry?industry.count:0;
    var seen={};row.rising_concepts=[];
    (s.display_boards||s.boards||[]).forEach(function(name){
      if(typeof name!=='string'||seen[name])return;seen[name]=true;
      var p=peers(boards['theme|'+name],row.code);
      if(p&&p.change>0)row.rising_concepts.push({name:name,peer_change_pct:p.change,peer_count:p.count});
    });
    row.rising_concepts.sort(function(a,b){return b.peer_change_pct-a.peer_change_pct||a.name.localeCompare(b.name);});
    row.rising_concepts=row.rising_concepts.slice(0,3);
  });
}
function renderWorkboard(){
  if(!DATA)return;
  ensureCloseBoardDisplay();
  var close=DATA.close_strong_board||{},trend=DATA['trend_ma'+TREND_LINE+'_observation']||{},fresh=DATA.intraday_new_strength||{};
  var workLookup={};stockPoolRows().forEach(function(s){workLookup[String(s.code)]=s;});
  renderAttackMonitor(workLookup);
  var closeRows=close.stocks||[],rows=fresh.rows||[];
  var workPhase=sessionNow(),lunchRetained=workPhase==='午间休市';
  var afternoonWaiting=['午盘','尾盘'].indexOf(workPhase)>=0
    &&String((DATA.intraday_model||{}).latest_valid_quote_at||'').slice(11,16)<'13:00';
  var preserveMorning=lunchRetained||afternoonWaiting;
  var activeRows=rows.filter(function(s){return workQuoteCurrent(s.quote_at)
    &&['早盘','午盘','尾盘'].indexOf(workPhase)>=0;});
  var morningRows=preserveMorning?rows.filter(function(s){
    var at=parseDT(s.quote_at),now=new Date();
    return at&&at.toDateString()===now.toDateString()
      &&at.getHours()*60+at.getMinutes()<=11*60+30;
  }):[];
  document.getElementById('work-new-count').textContent=preserveMorning
    ?'上午留存 '+morningRows.length+' 只 · '+(afternoonWaiting?'午后待更新':'评分截至 '+esc((fresh.last_valid_quote_at||'').slice(11,16)||'未知'))
    :(activeRows.length===rows.length?rows.length+' 只'
      :'当前有效 '+activeRows.length+' / 留档 '+rows.length+' 只');
  var h='';
  rows.forEach(function(s){var usable=activeRows.indexOf(s)>=0,retained=morningRows.indexOf(s)>=0;
    var latest=retained?morningReferenceQuote(workLookup[String(s.code)]):null;
    var shownChange=latest?latest.change:s.change_pct;
    var status=usable?s.kind:
      retained?(afternoonWaiting?'午后待更新 · 上午留存 · ':'午间留存 · ')+s.kind:'报价已过期';
    h+='<button type="button" class="work-observation" onclick="showStock(\''+jsq(s.code)+'\')">'
      +'<span class="work-observation-top"><span class="work-observation-name">'+esc(s.name)
      +'<span class="work-observation-code">'+esc(s.code)+'</span></span>'
      +'<span class="work-observation-change '+(usable||retained?cls(shownChange):'flat')+'">'
      +(usable||retained?pct(shownChange,1):'—')+'</span></span>'
      +workProfileTags(s.code,workLookup)
      +'<span class="work-observation-bottom"><span>'+esc(status)+' · 评分 '+esc((s.quote_at||'').slice(11,16)||'时间未知')
      +(latest?' · 价格截至 '+esc(latest.at.slice(11,16))+' ¥'+fmt(latest.price,2):'')+'</span>'
      +'<span class="work-observation-metric">盘中分 '+fmt(s.intraday_score,1)
      +' · 超额 '+(s.relative_return_pct==null?'—':sgn(s.relative_return_pct,1)+' 点')+'</span></span></button>';
  });
  if(!rows.length)h='<div class="work-observation-empty">'+esc(fresh.reason||'当前没有有效盘中强势候选')+'</div>';
  document.getElementById('work-new-list').innerHTML=h;
  var phase=sessionNow(),normal=['早盘','午盘','尾盘'].indexOf(phase)>=0;
  var retained=['午间休市','已收盘','休市'].indexOf(phase)>=0||afternoonWaiting;
  var trendUsable=function(s){return afternoonWaiting||(!normal?retained:workQuoteCurrent(s.quote_at));};
  [5,10,20].forEach(function(period){
    var button=document.querySelector('[data-trend-line="'+period+'"]');
    var board=DATA['trend_ma'+period+'_observation']||{};
    var count=(board.main_rows||[]).filter(trendUsable).length
      +(board.reclaim_rows||[]).filter(trendUsable).length;
    if(button)button.setAttribute('aria-pressed',String(period===TREND_LINE));
    var countEl=document.getElementById('trend-tab-count-'+period);
    if(countEl)countEl.textContent=count?String(count):'';
  });
  var mainRows=(trend.main_rows||[]).filter(trendUsable);
  var reclaimRows=(trend.reclaim_rows||[]).filter(trendUsable);
  var pendingRows=(trend.pending_rows||[]);
  var pendingVisible=normal?pendingRows.filter(function(s){return workQuoteCurrent(s.quote_at);}):pendingRows;
  var expiredNote=normal?'':'（已过期）';
  var phaseNote=afternoonWaiting?' · 午后报价待更新，上午观察留存（已过期）':normal?'':
    retained?(trend.last_valid_quote_at?' · 最后有效盘中观察（已过期）':' · 当前无有效报价，等待下一正常交易时段核验')
      :' · 等待正常交易';
  document.getElementById('work-trend-heading').textContent='趋势观察 · MA'+TREND_LINE;
  document.getElementById('work-trend-count').textContent=mainRows.length+' 只贴线未破'
    +(pendingVisible.length?' · '+pendingVisible.length+' 只待核验':'');
  document.getElementById('work-trend-note').textContent=trend.baseline_asof
    ?'基于 '+trend.baseline_asof+' 完成日趋势 · 昨收站上 MA'+TREND_LINE+' · 日低低于昨收 · 现价距暂态 MA'+TREND_LINE+' ≤1%；仅近线观察，风险较少者优先'
    :(trend.reason||'等待上一完成交易日趋势数据');
  document.getElementById('work-trend-time').textContent=(trend.last_valid_quote_at||'暂无有效报价')+phaseNote;
  function trendTable(items,reclaim){
    var html='';
    items.forEach(function(s){
      var latest=preserveMorning?morningReferenceQuote(workLookup[String(s.code)]):null;
      var shownChange=latest?latest.change:s.change_pct;
      var detail=reclaim?'跌破后 '+(s.reclaim_minutes==null?'—':s.reclaim_minutes+' 分钟')+'收回'
        :'日低距线 '+sgn(s.low_distance_pct,2)+'%';
      var visibleRisk=(s.risk_flags||[]).filter(function(flag){return !/MA(?:5|10|20)/.test(flag);})[0];
      html+='<button type="button" class="work-observation" onclick="showStock(\''+jsq(s.code)+'\')">'
        +'<span class="work-observation-top"><span class="work-observation-name">'+esc(s.name)
        +'<span class="work-observation-code">'+esc(s.code)+'</span></span>'
        +'<span class="work-observation-change '+cls(shownChange)+'">'
        +(shownChange==null?'—':pct(shownChange,1))+'</span></span>'
        +workProfileTags(s.code,workLookup)
        +'<span class="work-observation-bottom"><span>'+(afternoonWaiting?'上午观察 · ':'')+esc(s.status)+' · '+esc(detail)
        +' · 观察 '+esc((s.quote_at||'').slice(11,16))
        +(latest?' · '+esc(latest.kind)+' ¥'+fmt(latest.price,2)
          +(latest.kind==='午间截至11:30'?'':(' · '+esc(latest.at.slice(11,16)))):'')
        +(visibleRisk?' · 风险 '+esc(visibleRisk):'')+'</span>'
        +'<span class="work-observation-metric">距 MA'+TREND_LINE+' +'+fmt(s.distance_pct,2)+'% · 盘中暂态 '+fmt(s.line_value||s['ma'+TREND_LINE],2)
        +' · 报价日前完成日 '+fmt(s.completed_day_ma,2)
        +(s.distance_atr==null?' · ATR待核验':' · '+fmt(s.distance_atr,2)+' ATR')+'</span></span></button>';
    });
    if(!items.length)html='<div class="work-observation-empty">'
      +(normal?'当前没有符合条件且报价有效的股票':retained
        ?(trend.last_valid_quote_at?'该阶段没有符合条件的留档候选':(trend.reason||'当前没有有效报价，等待下一正常交易时段核验'))
        :'等待正常交易报价')+'</div>';
    return html;
  }
  document.getElementById('work-trend-list').innerHTML=trendTable(mainRows,false);
  function pendingTable(items){
    if(!items.length)return '<div class="work-observation-empty">'+(normal?'当前没有待核验的均线观察':
      retained?(trend.last_valid_quote_at?'当前没有可保留的待核验记录':(trend.reason||'当前没有有效报价，等待下一正常交易时段核验')):
      '等待正常交易报价')+'</div>';
    return items.map(function(s){return '<button type="button" class="work-observation" onclick="showStock(\''+jsq(s.code)+'\')">'
      +'<span class="work-observation-top"><span class="work-observation-name">'+esc(s.name||s.code)
      +'<span class="work-observation-code">'+esc(s.code)+'</span></span><span>待核验</span></span>'
      +'<span class="work-observation-bottom"><span>'+esc(s.reason||'价格口径待核验')+' · '+esc((s.quote_at||'').slice(11,16))
      +(normal?'':' · 历史观察已过期')+'</span><span class="work-observation-metric">'+esc(s.line||('MA'+TREND_LINE))+'</span></span></button>';}).join('');
  }
  document.getElementById('work-trend-pending-list').innerHTML=pendingTable(pendingVisible);
  document.getElementById('work-trend-pending-count').textContent=pendingVisible.length+' 只';
  document.getElementById('work-trend-reclaim-title').textContent='15 分钟内收回 · '+reclaimRows.length+' 只';
  document.getElementById('work-trend-reclaim-list').innerHTML=trendTable(reclaimRows,true);
  document.getElementById('work-close-count').textContent=closeRows.length+' 只';
  document.getElementById('work-close-note').textContent=(close.today_pending?'今日正式收盘日线尚未生成，显示最近一次收盘名单。':(close.criterion||'按日线进攻强势资格筛选；近期变化单列。'))
    +' 判断日 '+(close.asof||'暂无');
  h='<thead><tr><th>#</th><th>股票</th><th>当日涨幅</th><th>所属行业板块</th><th>上涨的关联概念</th><th>日线分</th><th>趋势与风险</th></tr></thead><tbody>';
  closeRows.forEach(function(s,i){
    var concepts=(s.rising_concepts||[]).map(function(c){return '<span class="close-concept" title="剔除本股后，'+fmt(c.peer_count,0)+'只有效同伴的平均涨幅">'+esc(c.name)+' <b>'+pct(c.peer_change_pct,2)+'</b></span>';}).join('');
    h+='<tr'+(workRowOpen(s.code)?' class="clickable" onclick="showStock(\''+jsq(s.code)+'\')"':'')+'>'
      +'<td>'+(i+1)+'</td>'
      +'<td><span class="close-stock-name">'+esc(s.name)+'</span><span class="close-stock-code">'+esc(s.code)+'</span></td>'
      +'<td><span class="close-day '+cls(s.today_change_pct)+'">'+(s.today_change_pct==null?'—':pct(s.today_change_pct,2))+'</span>'
      +'<span class="close-cell-sub">正式收盘</span></td>'
      +'<td><span class="close-industry">'+esc(s.industry||'行业待确认')+'</span>'
      +'<span class="close-cell-sub">'+(s.industry_peer_change_pct==null?'同伴样本不足':'同伴 '+pct(s.industry_peer_change_pct,2))+'</span></td>'
      +'<td><div class="close-concepts">'+(concepts||'<span class="close-empty">关联概念暂无同伴上涨</span>')+'</div></td>'
      +'<td><span class="close-score">'+fmt(s.score,1)+'</span><span class="close-cell-sub">分位 '+fmt(s.percentile,0)+'</span></td>'
      +'<td><span class="close-status">'+esc(s.trend_stage||'趋势在线')+' · '+esc(s.motion||'近期变化未知')+'</span>'
      +(s.risk_notes&&s.risk_notes.length?'<span class="close-risk">'+esc(s.risk_notes.join('；'))+'</span>':'')+'</td></tr>';
  });
  if(!closeRows.length)h+='<tr><td colspan="7" class="flat">'+(close.asof?'该日没有符合现有因子资格的强势股':'正式收盘主榜尚未生成')+'</td></tr>';
  document.getElementById('work-close-table').innerHTML=h+'</tbody>';
}
function exportCloseBoard(){
  ensureCloseBoardDisplay();
  var board=DATA.close_strong_board||{},rows=board.stocks||[];
  function cell(x){return '"'+String(x==null?'':x).replace(/"/g,'""')+'"';}
  var lines=[['代码','名称','判断日','当日涨幅%','所属行业板块','行业同伴平均涨幅%','上涨的关联概念（剔除本股）','日线基础分','强度分位','5日涨幅%','20日涨幅%','趋势阶段','风险备注','模型版本'].map(cell).join(',')];
  rows.forEach(function(s){lines.push([s.code,s.name,board.asof,s.today_change_pct,s.industry,s.industry_peer_change_pct,(s.rising_concepts||[]).map(function(c){return c.name+' '+pct(c.peer_change_pct,2);}).join('；'),s.score,s.percentile,s.ret5,s.ret20,s.trend_stage,(s.risk_notes||[]).join('；'),board.factor_model_version].map(cell).join(','));});
  var a=document.createElement('a'),blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/csv;charset=utf-8'});
  a.href=URL.createObjectURL(blob);a.download='收盘强势主榜_'+(board.asof||'暂无')+'.csv';a.click();
  toast('已导出 '+rows.length+' 只收盘强势股');
}
function leadingBoardData(){
  var quoteAt=(DATA.intraday_model||{}).latest_valid_quote_at||DATA.quote_capture_at||'';
  var quoteDay=String(quoteAt).slice(0,10),byCode={};
  (DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(function(s){
    if(s.intraday_quote_fresh!==true||String(s.intraday_quote_at||'').slice(0,10)!==quoteDay
       ||s.change_pct==null||!isFinite(Number(s.change_pct)))return;
    byCode[s.code]=Number(s.change_pct);
  });
  var market=Object.keys(byCode).map(function(c){return byCode[c];});
  var marketAvg=market.length?market.reduce(function(a,b){return a+b;},0)/market.length:null;
  var rows=(DATA.board_catalog||[]).filter(function(b){return b.type==='theme';}).map(function(b){
    var codes=b.member_codes||[],values=codes.filter(function(c){return byCode[c]!==undefined;})
      .map(function(c){return byCode[c];});
    if(!values.length)return null;
    var avg=values.reduce(function(a,v){return a+v;},0)/values.length;
    var sorted=values.slice().sort(function(a,b){return a-b;}),mid=Math.floor(sorted.length/2);
    return {board:b,count:values.length,total:codes.length,avg:avg,
      median:sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2,
      up:values.filter(function(v){return v>0;}).length,
      upPct:values.filter(function(v){return v>0;}).length/values.length*100,
      excess:marketAvg==null?null:avg-marketAvg};
  }).filter(function(x){return x&&x.count>=10&&x.total>0&&x.count/x.total>=.8
      &&x.avg>0&&x.excess>0&&x.upPct>=50;});
  rows.sort(function(a,b){return b.avg-a.avg||b.upPct-a.upPct||b.median-a.median||a.board.name.localeCompare(b.board.name);});
  return {rows:rows,marketAvg:marketAvg,marketCount:market.length,quoteAt:quoteAt};
}
function renderOverview(){
  var b=(DATA&&DATA.breadth)||{}, o=(DATA&&DATA.outer)||{};
  var sess=DATA.session||sessionNow();

  /* — Hero 叙事 — */
  var boards=(DATA.board_catalog||[]).filter(function(x){return x.type==='theme'&&x.ranking_eligible===true;})
    .sort(function(a,b){return n(a.trend_rank,1e9)-n(b.trend_rank,1e9)||a.name.localeCompare(b.name);});
  var stocks=(DATA.stocks||[]).filter(function(s){return s.traded!==0;});
  var top=boards[0]||{}, t2=boards[1]||{}, t3=boards[2]||{};
  var names=[top.name,t2.name,t3.name].filter(Boolean);
  var heroP='';
  if(b.up||b.down){
    var bmx0=DATA.board_mix||{};
    var bt=Object.keys(bmx0).sort(function(a,b){return n(bmx0[b].n)-n(bmx0[a].n);})
      .map(function(k){return k+' '+n(bmx0[k].n);}).join(' / ');
    heroP = (DATA.pool_boards||['沪主板','深主板']).join('·')+' <b style="color:var(--txt)">'
      +n(DATA.pool_size)+'</b> 只标的中（'
      + (bt||'—') + '），'
      + '<span class="up">'+n(b.up)+'</span> 只上涨、<span class="down">'+n(b.down)+'</span> 只下跌，'
      + '涨停 <b style="color:var(--txt)">'+n(b.limit_up)+'</b> 只（<b>按各板涨跌幅限制分别判定</b>）。';
    if(names.length) heroP += ' 主板成员趋势靠前题材 <b style="color:var(--txt)">'+esc(names.join('、'))+'</b>。';
    if(sess==='集合竞价'||sess==='竞价结束'||sess==='盘前') heroP += ' <span style="color:var(--orange)">当前处于'+sess+'，量价数据尚未充分，仅供前瞻参考。</span>';
  }else{ heroP='等待数据 …'; }
  document.getElementById('hero-p').innerHTML=heroP;

  if(!WORK_MODE)WORK_MODE=autoWorkMode();
  setWorkMode(WORK_MODE,false);
  document.getElementById('nav-sub').textContent='题材轮动 · '
    +(DATA.pool_boards||['沪主板','深主板']).join('·')+' · '+n(DATA.pool_size)+' 只';

  /* — 时间戳带 — */
  var st=[];
  st.push('<span class="t">数据时间 <b>'+esc(DATA.generated_at||'—')+'</b></span>');
  st.push('<span class="t">阶段 <b>'+esc(sess)+'</b></span>');
  st.push('<span class="t">模式 <b>'+(DATA.mode==='full'?'全量':'增量')+'</b></span>');
  st.push('<span class="t">耗时 <b>'+n(DATA.elapsed)+'s</b></span>');
  st.push('<span class="t">资金口径 <b>'+esc(DATA.fund_source||'—')+'</b></span>');
  var cov=boards.filter(function(x){return x.fund_covered>0||x.fund_today_covered>0;}).length;
  st.push('<span class="t">题材资金覆盖 <b>'+cov+'/'+boards.length+'</b></span>');
  var sh=DATA.data_sources||{};
  function srcState(x){
    x=x||{}; if(x.status==='ok')return '实时';
    if(x.status==='cache')return '缓存';
    if(x.status==='stale_cache')return '短时缓存';
    if(x.status==='error')return '不可用';
    return '未探测';
  }
  st.push('<span class="t">数据源 <b>同花顺概念 '+srcState(sh.ths_concepts)
    +' · 腾讯行情 '+srcState(sh.tencent_quotes)
    +' · 东财资金 '+srcState(sh.eastmoney_fundflow)
    +' · 新浪当日资金 '+srcState(sh.sina_fundflow)+'</b></span>');
  document.getElementById('hero-stamp').innerHTML=st.join('');

  /* — 指标卡 — */
  var oc=o.composite;
  var upr=n(b.up_ratio);
  var M=[
    {l:'上涨家数',v:'<span class="up">'+n(b.up)+'</span>',s:'下跌 '+n(b.down)+' · 平盘 '+Math.max(0,n(b.flat)-n(b.no_trade))},
    {l:'市场温度',v:fmt(upr,1)+'<span style="font-size:1.1rem">%</span>',
     s:'上涨占比 · '+(upr>=60?'普涨格局':upr>=40?'结构分化':'普跌格局')},
    {l:'涨停家数',v:'<span class="up">'+n(b.limit_up)+'</span>',s:'各板限制分别判定（主板10% / 双创20%）'},
    {l:'尚未成交',v:(n(b.no_trade)>0?'<span class="flat">'+n(b.no_trade)+'</span>':'0'),
     s:'开盘初期未成交个股，已排除出榜单'},
    {l:'隔夜外围',v:(oc==null?'<span class="flat">—</span>':'<span class="'+(oc>0?'up':(oc<0?'down':'flat'))+'">'+sgn(oc,2)+'%</span>'),
     s:o.stale?'沿用 '+esc(o.asof||'')+' 的最近成功数据':(oc==null?'数据暂不可用':'道指 / 纳指 / 标普 / 费半 加权')},
    {l:'趋势在线',v:n((DATA.strength_model||{}).watch_count),s:'三线多头且收盘守住10日线'}
  ];
  if(o.indices){
    Object.keys(o.indices).forEach(function(k){
      var x=o.indices[k]; if(!x||x.change_pct===undefined)return;
      M.push({l:x.name||k,v:'<span class="'+cls(x.change_pct)+'">'+pct(x.change_pct)+'</span>',s:'隔夜收盘'});
    });
  }
  document.getElementById('ov-metrics').innerHTML=M.map(function(m,i){
    return '<div class="metric ani" style="animation-delay:'+(i*45)+'ms">'
      +'<div class="lbl">'+esc(m.l)+'</div><div class="val">'+m.v+'</div>'
      +'<div class="sub">'+m.s+'</div></div>';}).join('');

  var sm=DATA.strength_model||{};
  var strengthEntries=[['日线进攻强势',sm.persistent_strong_count,'完成日线实际涨幅与进攻速度'],
    ['日线近期增强',sm.recent_improving_count,'日线等长区间相对表现改善'],
    ['日线高位衰减',sm.high_fading_count,'日线20日涨幅仍靠前，近期相对转弱']];
  document.getElementById('ov-strength-entry').innerHTML=strengthEntries.map(function(x){
    return '<div class="metric clickable" onclick="goPane(\'stocks\');applyPreset(\''+jsq(x[0])+'\')">'
      +'<div class="lbl">'+esc(x[0])+'</div><div class="val">'+n(x[1])+'</div>'
      +'<div class="sub">'+esc(x[2])+'</div></div>';}).join('');

  /* 按主榜个股的真实分类计数；展示文案与筛选策略名称不能代替数据键。 */
  var axisStocks=DATA.stocks||[], axisCounts={};
  axisStocks.forEach(function(s){var k=s.axis_group||'情绪数据不足';axisCounts[k]=(axisCounts[k]||0)+1;});
  var axisCards=[
    {key:'情绪活跃·趋势在线',preset:'情绪活跃·趋势在线',label:'双轴共现',desc:'情绪活跃 · 日线趋势在线',tone:'both'},
    {key:'情绪活跃·趋势未在线',preset:'情绪活跃·趋势未在线',label:'情绪候选',desc:'情绪活跃 · 日线趋势未在线',tone:'emotion'},
    {key:'趋势在线·情绪平稳',preset:'日线趋势在线·情绪平稳',label:'趋势候选',desc:'日线趋势在线 · 情绪平稳',tone:'trend'},
    {key:'趋势未在线·情绪平稳',preset:'日线趋势未在线·情绪平稳',label:'结构未在线',desc:'日线趋势未在线 · 情绪平稳',tone:'quiet'}
  ];
  var axisClassified=axisCards.reduce(function(total,x){return total+(axisCounts[x.key]||0);},0);
  var axisUnverified=Math.max(0,axisStocks.length-axisClassified);
  var axisEmotion=DATA.market_emotion||{};
  var axisQuoteAt=(DATA.intraday_model||{}).latest_valid_quote_at||'';
  document.getElementById('ov-axis-sub').textContent='日线趋势截至 '+((DATA.strength_model||{}).asof||'—')
    +'；情绪为'+(axisEmotion.state==='离线未核验'?'旧报价未核验':axisEmotion.provisional?'盘中暂态':'收盘观察')
    +(axisQuoteAt?'（行情截至 '+axisQuoteAt+'）':'')
    +'。主榜有效样本 '+axisStocks.length+' 只，其中情绪活跃 '
    +((axisCounts['情绪活跃·趋势在线']||0)+(axisCounts['情绪活跃·趋势未在线']||0))+' 只、日线趋势在线 '
    +((axisCounts['情绪活跃·趋势在线']||0)+(axisCounts['趋势在线·情绪平稳']||0))+' 只。';
  document.getElementById('ov-axes').innerHTML=axisStocks.length?axisCards.map(function(x){
    var count=axisCounts[x.key]||0, share=(count/axisStocks.length*100).toFixed(1);
    return '<button type="button" class="axis-card '+x.tone+'" title="查看对应个股" onclick="goPane(\'stocks\');applyPreset(\''+jsq(x.preset)+'\')">'
      +'<span class="axis-card-head"><strong>'+esc(x.label)+'</strong><i>↗</i></span>'
      +'<span class="axis-card-main"><b>'+count+'</b><span>只 · '+share+'%</span></span>'
      +'<span class="axis-card-desc">'+esc(x.desc)+'</span>'
      +'<span class="axis-card-track"><i style="width:'+share+'%"></i></span></button>';}).join('')
    :'<div class="empty">当前没有可核验的主榜样本</div>';
  var axisUnknownEl=document.getElementById('ov-axis-unknown');
  axisUnknownEl.style.display=axisUnverified?'':'none';
  axisUnknownEl.textContent=axisUnverified?'另有 '+axisUnverified+' 只情绪或趋势未核验，未计入上方四类。':'';
  var me=DATA.market_emotion||{};
  function ep(v){return v==null?'—':pct(v,1);}
  function emotionStat(label,value,tone){return '<div class="emotion-stat"><small>'+label+'</small><b class="'+(tone||'')+'">'+value+'</b></div>';}
  document.getElementById('ov-market-emotion').innerHTML='<div class="emotion-market-head"><h3>主板交易情绪</h3><span>'
    +esc(me.state||'数据不足')+(me.state==='离线未核验'?' · 旧报价':me.provisional?' · 盘中暂态':' · 收盘观察')+'</span></div>'
    +'<div class="emotion-stats">'
    +emotionStat('有效成交',n(me.traded)+' / '+n(me.pool))
    +emotionStat(me.provisional?'当前涨停':'收盘涨停',n(me.limit_up),'up')
    +emotionStat('首板',n(me.first_board),'up')
    +emotionStat('连板',n(me.continued_board),'up')
    +emotionStat('触板未封',n(me.touched_unsealed),'wa')
    +emotionStat('跌停',n(me.limit_down),'down')+'</div>'
    +'<div class="emotion-follow">'
    +'<div class="emotion-follow-item"><strong>昨日涨停 · '+n(me.limit_up_yesterday)+' 只</strong><span>今日收益中位 '+ep(me.yesterday_limit_median_pct)
    +' · 高开中位 '+ep(me.yesterday_limit_gap_median_pct)+' · 开盘后收益中位 '+ep(me.yesterday_limit_intraday_median_pct)
    +' · 晋级率 '+ep(me.advance_pct)+'</span></div>'
    +'<div class="emotion-follow-item"><strong>昨日强势 · '+n(me.yesterday_strong_count)+' 只</strong><span>今日收益中位 '+ep(me.yesterday_strong_median_pct)
    +' · 观察是否延续完成日线趋势</span></div></div>'
    +'<p class="emotion-market-note">'+esc(me.scope||'')+'；停牌和无成交不入分母。涨停家数与上涨家数使用同一报价池。'
    +(me.provisional?'盘中数据尚待收盘确认。':'')+'不能据此推断封板时间或个股带动顺序。</p>';
  var extra=DATA.emotion_candidates||[];
  document.getElementById('ov-emotion-only-count').textContent=extra.length+' 只 · 趋势资格见个股详情';
  document.getElementById('ov-emotion-only').innerHTML=extra.length
    ? '<div class="emotion-extra-list">'+extra.map(function(s){
        return '<button type="button" class="emotion-extra-stock" onclick="showEmotionOnly(\''+jsq(s.code)+'\')">'
          +'<span><b>'+esc(s.name)+' <small style="display:inline">'+esc(s.code)+'</small></b><em class="'+cls(s.change_pct)+'">'+pct(s.change_pct,1)+'</em></span>'
          +'<small>'+esc(s.emotion_heat||'情绪待核验')+' · 主榜趋势资格未核验</small></button>';}).join('')
      +'</div>'
    : '<div class="empty">当前没有主榜外的情绪活跃观察样本</div>';

  /* 同一轮有效报价、同一主板样本计算题材等权涨幅和主板基准。 */
  var todayBoards=leadingBoardData();
  var boardTime=String(todayBoards.quoteAt||'').slice(0,16).replace('T',' ');
  document.getElementById('ov-board-note').innerHTML='同花顺概念 · 有效报价成员等权涨幅排序 · 主板等权 '
    +'<b class="'+cls(todayBoards.marketAvg)+'">'+pct(todayBoards.marketAvg,2)+'</b>'
    +'（'+n(todayBoards.marketCount)+' 只） · 报价截至 '+esc(boardTime||'未知')
    +' · 至少10只有效成员且覆盖≥80%；重叠题材分别展示。';
  document.getElementById('ov-boards').innerHTML=todayBoards.rows.slice(0,6).map(function(y,i){
    var x=y.board,cb='pickThemeByName(\''+jsq(x.name)+'\')';
    return '<div class="leader-card ani" role="button" tabindex="0" aria-label="筛选'+esc(x.name)+'成员" '
      +'style="animation-delay:'+(i*55)+'ms" onclick="'+cb+'" '
      +'onkeydown="if(event.target===this&&(event.key===\'Enter\'||event.key===\' \')){event.preventDefault();'+cb+'}">'
      +'<div class="leader-top"><span class="leader-rank">'+(i+1)+'</span>'
      +'<b class="leader-name" title="'+esc(x.name)+'">'+esc(x.name)+'</b><span class="leader-type">题材</span></div>'
      +'<div class="leader-main"><div><span class="leader-return-label">今日成员等权涨幅</span>'
      +'<strong class="leader-return '+cls(y.avg)+'">'+pct(y.avg,2)+'</strong></div>'
      +'<span class="leader-excess '+cls(y.excess)+'">跑赢主板 '+sgn(y.excess,2)+' 点</span></div>'
      +'<div class="leader-facts"><div class="leader-fact"><span>上涨成员</span><b>'+y.up+'/'+y.count+' · '+fmt(y.upPct,0)+'%</b></div>'
      +'<div class="leader-fact"><span>涨幅中位数</span><b class="'+cls(y.median)+'">'+pct(y.median,1)+'</b></div>'
      +'<div class="leader-fact"><span>报价覆盖</span><b>'+y.count+'/'+y.total+'</b></div></div>'
      +'<div class="leader-bottom"><span>日线趋势在线 '+fmt(x.trend_pct,0)+'% · 历史背景</span>'
      +'<button type="button" onclick="event.stopPropagation();showBoardById(\''+jsq(x.id)+'\')">查看成分明细 ↗</button></div>'
      +'</div>';}).join('')||'<div class="empty">当前没有达到成员数、报价覆盖和广度条件的领涨题材</div>';


  /* — 历史日线形态与当前盘中约束均通过的回踩候选 — */
  var al=DATA.alerts||[];
  var alertStocks={};(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(function(s){alertStocks[s.code]=s;});
  document.getElementById('ov-alert-n').textContent=al.length?al.length+' 条 · 展示前 '+Math.min(al.length,7)+' 条':'';
  document.getElementById('ov-alerts').innerHTML = al.length
    ? al.slice(0,7).map(function(a){
        var lv=a.level==='high'?'high':'mid';
        var stock=alertStocks[a.target]||{};
        var at=stock.intraday_quote_at||stock.last_valid_quote_at||'';
        var timeLabel=at?(stock.intraday_quote_fresh===true?'有效报价 ':'上次有效报价 ')+esc(at):'报价时间未知';
        var tg=a.target&&a.target!=='market'?'<div class="alert-meta"><time class="alert-time" datetime="'+esc(String(at).replace(' ','T'))+'">'+timeLabel+'</time><span>'+esc(a.target)+' · 点击查看详情</span></div>':'';
        var clk=(a.target==='market')?'':' onclick="showStock(\''+esc(a.target)+'\')"';
        return '<div class="alert '+lv+'"'+clk+'><div class="ic">'+(lv==='high'?'!':'◆')+'</div>'
          +'<div style="flex:1"><div class="tx"><b>'+esc(a.type)+'</b> · '+esc(a.text)+'</div>'+tg+'</div></div>';}).join('')
    : '<div class="empty" style="padding:34px 12px"><div class="big">◌</div>当前无通过盘中约束的回踩候选</div>';

  /* — 涨停题材云 —
     词直接取自涨停股身上的同花顺概念标签，与个股页筛选同一个字段，
     所以点任何一个词都必然筛得到股票（旧版用的是同花顺 event 的归因短语，
     如「次新股 / 业绩增长」，跟个股标签对不上，点了 0 命中）。 */
  var tags=((DATA.themes||{}).hot_tags)||[];
  document.getElementById('ov-themes').innerHTML = tags.length
    ? tags.slice(0,18).map(function(x,i){
        var sz=Math.max(12.5,20-i*0.42);
        return '<span style="font-size:'+sz.toFixed(1)+'px" onclick="pickThemeByName(\''
          +jsq(x.theme)+'\')" title="'+esc(x.theme)+' · 当日 '+n(x.count)+' 只涨停">'
          +esc(x.theme)+'<b>'+n(x.count)+'</b></span>';}).join('')
    : '<div class="empty" style="padding:30px">暂无题材数据</div>';

  /* — 行业支持 — */
  var rs=stocks.filter(function(s){return s.watch_candidate&&s.industry_supported;});
  document.getElementById('ov-reso').innerHTML = rs.length
    ? '<div class="row wrap" style="gap:8px">'+rs.slice(0,40).map(function(s){
        return '<span class="chip" onclick="showStock(\''+s.code+'\')">'+esc(s.name)
          +bpill(s)
          +'<span style="color:var(--txt3);font-size:11px">'+esc(s.code)+'</span></span>';}).join('')
      +(rs.length>40?'<span class="chip" onclick="goPane(\'stocks\');applyPreset(\'行业支持\')">还有 '+(rs.length-40)+' 只 →</span>':'')
      +'</div>'
    : '<div class="empty">当前无行业支持个股</div>';

}

/* ═══════════════ 板块页 ═══════════════ */
var FUND_TIP='资金强度为全市场分位分（0-100），非绝对金额。\n东财不可用时使用新浪当日超大单净额，口径不同；行业、题材、概念归属仍使用同花顺。';
var LINK_TIP='板块内联动 = 同花顺概念成员组内上涨家数占比。\n覆盖率不足的板块不参与打分。';

function sortRows(rows,key,asc){
  return rows.slice().sort(function(a,b){
    var x=a[key],y=b[key];
    if(x==null&&y==null)return 0; if(x==null)return 1; if(y==null)return -1;
    if(typeof x==='string')return asc?String(x).localeCompare(y):String(y).localeCompare(x);
    return asc?x-y:y-x;});
}
function thSort(pane,key,label,left,tip){
  var s=STATE.sort[pane];
  var on=s.k===key;
  return '<th class="'+(left?'l ':'')+(on?'sorted':'')+'" onclick="setSort(\''+pane+'\',\''+key+'\')"'
    +(tip?' title="'+tip+'"':'')+'>'+label
    +(on?'<span class="ar">'+(s.asc?'▲':'▼')+'</span>':'')+'</th>';
}
function setSort(pane,key){
  var s=STATE.sort[pane];
  if(s.k===key)s.asc=!s.asc; else {s.k=key;s.asc=false;}
  if(pane==='boards')renderBoards();
  else if(pane==='stocks')renderStocks();
  else if(pane==='hold')renderHold&&renderHold();
}

/* ── 选股雷达：A/B/C 是趋势候选关注层级，全体强度排名另列。 ── */
var RADAR_TIER='A';
function setRadarTier(k){ RADAR_TIER=k; renderRadar(); }
function radarItems(){
  var R=(DATA.radar||{})[strat()]||{};
  return (R.items||[]).filter(function(x){return x.tier===RADAR_TIER;});
}
function renderRadar(){
  var R=(DATA.radar||{})[strat()]||{}, ts=R.tiers||[];
  var host=document.getElementById('rad-tiers'), tb=document.getElementById('tb-radar');
  if(!host||!tb)return;
  if(!ts.length){
    host.innerHTML='<div class="empty" style="padding:22px">本次快照不含雷达数据（请重新运行一次扫描）</div>';
    tb.innerHTML=''; return;
  }
  var T={}; ts.forEach(function(t){T[t.key]=t;});
  function rangeOf(k){return T[k]&&T[k].short||'';}
  var rsub=document.getElementById('rad-sub');

  if(rsub){
    rsub.innerHTML='全体强度与趋势池内分位分别计算；A/B/C 是趋势候选关注层级，不代表买点。<br>'
      +ts.map(function(t){return esc(t.label)+'：'+esc(t.desc);}).join('　｜　')
      +'。判断日：'+esc((DATA.strength_model||{}).asof||'—');
  }

  host.innerHTML=ts.map(function(t){
    var it=(R.items||[]).filter(function(x){return x.tier===t.key;});
    var hi=it.filter(function(x){return x.risk_hi;}).length;
    return '<div class="tcard'+(RADAR_TIER===t.key?' on':'')+'" onclick="setRadarTier(\''+t.key+'\')">'
      +'<div class="tk">'+esc(t.label)+'<span class="tr">'+rangeOf(t.key)+'</span></div>'
      +'<div class="tn">'+n(t.n)+'<span class="tu">只</span></div>'
      +'<div class="td">'+esc(t.desc)+'</div>'
      +(hi?'<div class="tw2">其中 '+hi+' 只有位置或结构风险项</div>':'')
      +'</div>';}).join('');

  var rows=radarItems();
  if(!rows.length){ tb.innerHTML='<tbody><tr><td class="empty" style="padding:24px">该档为空</td></tr></tbody>'; return; }
  var h='<thead><tr><th class="l" style="width:34px">#</th><th class="l">名称</th>'
    +'<th>全体分位</th><th>池内分位</th><th>近5日</th><th>近20日</th>'
    +'<th class="l">关注层级</th><th class="l">位置风险</th></tr></thead><tbody>';
  rows.forEach(function(x,i){
    h+='<tr class="clickable" onclick="showStock(\''+jsq(x.code)+'\')">'
      +'<td class="l"><span class="rk'+(i<3?' t'+(i+1):'')+'">'+(i+1)+'</span></td>'
      +'<td class="l"><span class="nm">'+esc(x.name)+'</span><span class="cd">'+esc(x.code)+'</span>'
      +bpill(x)+'</td>'
      +'<td><b style="color:'+scoreColor(x.score)+'">'+fmt(x.score,1)+'</b></td>'
      +'<td>'+fmt(x.pool_percentile,1)+'</td>'
      +'<td class="'+cls(x.ret5)+'">'+pct(x.ret5,1)+'</td>'
      +'<td class="'+cls(x.ret20)+'">'+pct(x.ret20,1)+'</td>'
      +'<td class="l">'+esc(x.tier+' · '+x.tier_name)+'</td>'
      +'<td class="l">'+(x.risk_hi?'<span class="pill wa">位置/结构</span>'
        :((x.risk&&x.risk.length)?'<span class="pill gr">有短板</span>'
        :'<span class="flat">—</span>'))+'</td></tr>';
  });
  tb.innerHTML=h+'</tbody>';
  var more=document.getElementById('rad-more');
  var t=T[RADAR_TIER]||{};
  if(more)more.innerHTML=(t.n>t.shown)
    ? '<span class="chip">本档共 '+n(t.n)+' 只，此处按强度分位列出前 '+n(t.shown)+' 只（其余请用「个股」页按分位区间筛）</span>' : '';
}

function renderBoards(){
  var B=(DATA.boards||[]);
  var tr=(DATA.theme_rank||[]);
  var cov=B.filter(function(x){return (x.fund_src||'').indexOf('东财')===0;}).length;
  var best=B[0]||{};
  document.getElementById('bd-metrics').innerHTML=[
    {l:'有效板块',v:B.length,s:'同花顺概念（已剔风格类）'},
    {l:'资金真实覆盖',v:cov+'<span style="font-size:1.1rem">/'+B.length+'</span>',
     s:'其余为成交额动量降级口径'},
    {l:'最强板块',v:'<span style="font-size:1.5rem">'+esc(best.name||'—')+'</span>',
     s:best.score?'综合强度 '+fmt(best.score,1):''},
    {l:'入选题材组',v:tr.length,s:'覆盖率达标且成员数够'}
  ].map(function(m,i){return '<div class="metric ani" style="animation-delay:'+(i*45)+'ms">'
    +'<div class="lbl">'+m.l+'</div><div class="val">'+m.v+'</div><div class="sub">'+m.s+'</div></div>';}).join('');

  document.getElementById('bd-sub').innerHTML=
    '资金口径覆盖 '+cov+'/'+B.length+' · 点击行 → 直接筛出该板块成分股，点 ⓘ → 看板块明细';

  var rows=sortRows(B,STATE.sort.boards.k,STATE.sort.boards.asc);
  var h='<thead><tr>'
    +thSort('boards','rank','#','','')
    +thSort('boards','name','板块','l','')
    +thSort('boards','ret1','今日%')
    +thSort('boards','ret5','5日%')
    +thSort('boards','ret20','20日%')
    +thSort('boards','up_days_5','5日涨天')
    +thSort('boards','position60','60日位置')
    +thSort('boards','vol_expand','量能')
    +thSort('boards','rs','相对强度')
    +thSort('boards','fund','<span class="tip" data-tip="'+esc(FUND_TIP)+'">资金强度</span>')
    +thSort('boards','linkage','<span class="tip" data-tip="'+esc(LINK_TIP)+'">联动</span>')
    +thSort('boards','momentum','动能')
    +thSort('boards','score','综合')
    +'</tr></thead><tbody>';
  rows.forEach(function(b){
    var lnk=b.linkage==null?'<span class="flat">—</span>':fmt(b.linkage,0);
    // 当前覆盖股票池无成员时显式说明。
    var nk=tagCount(b.name);
    var cls2 = nk ? 'clickable' : '';
    var clk  = nk ? 'pickThemeByName(\''+jsq(b.name)+'\')'
                  : 'explainNoMembers(\''+jsq(b.name)+'\')';
    var mark = nk ? '' : ' <span class="pill wa" title="当前覆盖股票池暂无成员">⌀ 暂无覆盖成员</span>';
    h+='<tr class="'+cls2+'" onclick="'+clk+'">'
      +'<td><span class="rk'+(b.rank<=3?' t'+b.rank:'')+'">'+b.rank+'</span></td>'
      +'<td class="l"><span class="nm">'+esc(b.name)+'</span>'
      +(n(b.gate,1)<1?' <span class="pill wa">跌势</span>':'')
      + (nk ? ' <span class="mini" title="查看板块明细" onclick="event.stopPropagation();'
        +'showBoardByName(\''+jsq(b.idx_code||'')+'\')">ⓘ</span>' : mark)
      +'</td>'
      +'<td class="'+cls(b.ret1)+'">'+pct(b.ret1)+'</td>'
      +'<td class="'+cls(b.ret5)+'">'+pct(b.ret5,1)+'</td>'
      +'<td class="'+cls(b.ret20)+'">'+pct(b.ret20,1)+'</td>'
      +'<td>'+n(b.up_days_5)+'/5</td>'
      +'<td>'+fmt(b.position60,0)+'</td>'
      +'<td class="'+(n(b.vol_expand)>=1.3?'up':'flat')+'">'+fmt(b.vol_expand)+'x</td>'
      +'<td>'+hm(b.rs)+'</td>'
      +'<td>'+hm(b.fund)+'</td>'
      +'<td>'+(b.linkage==null?'<span class="flat">—</span>':hm(b.linkage))+'</td>'
      +'<td>'+hm(b.momentum)+'</td>'
      +'<td><b style="color:'+scoreColor(b.score)+'">'+fmt(b.score,1)+'</b></td></tr>';});
  document.getElementById('tb-boards').innerHTML=h+'</tbody>';

  /* 题材组榜 */
  var rr=sortRows(tr,STATE.sort.themes?STATE.sort.themes.k:'avg_chg',false);
  var g='<thead><tr><th>#</th><th class="l">题材</th><th>成员</th><th>覆盖</th>'
    +'<th>上涨占比</th><th class="l">涨/跌/平</th><th>等权涨幅</th><th>成交额</th><th>主力净额</th></tr></thead><tbody>';
  rr.forEach(function(t){
    var tnk=tagCount(t.name);
    var tclk=tnk ? 'pickThemeByName(\''+jsq(t.name)+'\')' : 'explainNoMembers(\''+jsq(t.name)+'\')';
    g+='<tr class="'+(tnk?'clickable':'')+'" onclick="'+tclk+'">'
      +'<td><span class="rk'+(t.rank<=3?' t'+t.rank:'')+'">'+t.rank+'</span></td>'
      +'<td class="l"><span class="nm">'+esc(t.name)+'</span>'
      + (tnk ? ' <span class="mini" title="查看题材组明细" onclick="event.stopPropagation();'
        +'showThemeGroup('+t.rank+')">ⓘ</span>' : '')
      +'</td>'
      +'<td>'+n(t.n)+'</td>'
      +'<td class="'+(n(t.coverage)>=80?'flat':'up')+'">'+fmt(t.coverage,0)+'%</td>'
      +'<td class="'+(n(t.up_ratio)>=60?'up':(n(t.up_ratio)<=40?'down':'flat'))+'"><b>'+fmt(t.up_ratio,1)+'%</b></td>'
      +'<td class="l flat">'+n(t.up)+' / '+n(t.down)+' / '+n(t.flat)+'</td>'
      +'<td class="'+cls(t.avg_chg)+'">'+pct(t.avg_chg)+'</td>'
      +'<td>'+yi(t.amount_wan)+'</td>'
      +'<td class="'+(n(t.main_net_sum)>0?'up':(n(t.main_net_sum)<0?'down':'flat'))+'">'
      +yi(Math.abs(n(t.main_net_sum))/1e4*1e4===0?n(t.main_net_sum):n(t.main_net_sum))+'</td></tr>';});
  document.getElementById('tb-themes').innerHTML=g+'</tbody>';

  /* 四象限（只取东财真实资金口径，避免纵轴被价量代理污染） */
  var qrows=(DATA.boards||[]).filter(function(b){
    return b.fund!=null && (b.fund_src||'').indexOf('东财')===0;
  }).sort(function(a,b){return n(b.score)-n(a.score);}).slice(0,150);
  var qcv=document.getElementById('q-cv');
  var qt=document.getElementById('q-toggle');
  if(qt){
    qt.textContent=window.QUAD_MORE?'收起标签':'显示更多标签';
    qt.onclick=function(){window.QUAD_MORE=!window.QUAD_MORE;
      qt.textContent=window.QUAD_MORE?'收起标签':'显示更多标签';
      if(qcv)drawQuadrant(qcv,qrows);};
  }
  if(qcv)drawQuadrant(qcv,qrows);
  renderQuadrantFocus(qrows);
  var qs=document.getElementById('q-sub');
  if(qs)qs.innerHTML='纵轴仅纳入东财真实资金口径的板块 <b>'+qrows.length+'</b> 个；'
    +'成交额动量降级口径不参与（价量代理放上纵轴会让"资金潜伏"与"涨幅先行"混为一谈）。'
    +'左上角含义：主力资金已净流入、但今日涨幅仍未启动 —— 轮动的前哨位。';
}

/* ── 板块明细抽屉 ── */
/* 总览页的板块卡用的是「板块榜第 i 名」的下标，
   这里转成 idx_code 再交给 showBoardByName。
   之前总览卡直接 onclick=showBoard(i)，但函数从来没定义过 ——
   点了会抛 ReferenceError，什么都不会发生（悬空调用）。 */
function showBoard(i){
  var b=(DATA.boards||[])[i];
  if(!b){ toast('未找到该板块'); return; }
  showBoardByName(b.idx_code||'');
}
function boardChainFor(b){
  if(!b)return null;
  var C=DATA.board_chain||{};
  return C[String(b.idx_code||'')]||C[b.name]||null;
}
function renderBoardChain(b){
  var c=boardChainFor(b), src=(DATA.theme_source||{}).name||'同花顺概念';
  var title='<h3>板块已覆盖成员 <small>'+esc(src)+'口径 · 个股按20日涨幅列出</small></h3>';
  if(!c||!c.leader){
    return '<div class="card chain-card" style="margin-bottom:16px">'+title
      +'<div class="empty" style="padding:12px 4px">当前板块没有可展示的有效成员。</div>'
      +'</div>';
  }
  var l=c.leader, fs=c.followers||[];
  var leader='<div class="chain-node lead" onclick="showStock(\''+jsq(l.code)+'\')">'
    +'<div class="chain-k">20日领涨 · 当前有效样本</div>'
    +'<div class="chain-title">'+esc(l.name||l.code)+'</div>'
    +'<div class="chain-score"><b style="color:'+scoreColor(l.score)+'">'+fmt(l.score,1)+'</b>'
    +'　'+pct(l.change_pct,1)+' · '+esc(l.axis_group||'数据不足')+'</div></div>';
  var follow=fs.length?fs.map(function(x){
    return '<div class="chain-frow" onclick="showStock(\''+jsq(x.code)+'\')">'
      +'<span class="chain-fname">'+esc(x.name||x.code)+'</span>'
      +'<span class="chain-fmeta"><b style="color:'+scoreColor(x.score)+'">'+fmt(x.score,1)
      +'</b>　'+esc((x.roles||[]).join('、')||x.axis_group||'一般成员')+'</span></div>';}).join('')
    :'<div class="flat" style="font-size:12px;padding:4px 0">暂无其他有效成交成员</div>';
  var follower='<div class="chain-followers"><div class="chain-k">其他已覆盖成员 · 仅作并列观察</div>'
    +follow+'</div>';
  return '<div class="card chain-card" style="margin-bottom:16px">'+title
    +'<div class="chain-flow">'
    +'<div class="chain-node"><div class="chain-k">板块强度</div>'
    +'<div class="chain-title">'+esc(b.name)+'</div>'
    +'<div class="chain-score"><b style="color:'+scoreColor(b.score)+'">'+fmt(b.score,1)
    +'</b>　排名 #'+n(b.rank)+' · '+n(c.member_count)+' 只成员</div></div>'
    +leader+follower
    +'</div><div class="chain-note">排序依据：'+esc(c.sort_basis||'复用个股20日涨幅排名')
    +'。同日共同走强不等于领涨股带动了其他成员；该概念名单仅覆盖主榜有效股票。</div></div>';
}
function showBoardByName(idxCode){
  var b=(DATA.boards||[]).filter(function(x){return x.idx_code===idxCode;})[0];
  if(!b)return toast('未找到该板块');
  var rel=(DATA.stocks||[]).filter(function(s){return (s.boards||[]).indexOf(b.name)>=0;})
    .filter(function(s){return s.traded!==0;}).slice(0,40);
  var h='<div class="grid g4" style="grid-template-columns:repeat(3,1fr);margin-bottom:20px">'
    +[['今日',pct(b.ret1),cls(b.ret1)],['5日',pct(b.ret5,1),cls(b.ret5)],['20日',pct(b.ret20,1),cls(b.ret20)],
      ['5日涨天',n(b.up_days_5)+'/5',''],['60日位置',fmt(b.position60,0),''],
      ['量能',fmt(b.vol_expand)+'x',n(b.vol_expand)>=1.3?'up':''],
      ['相对强度',fmt(b.rs,1),''],['资金强度',b.fund==null?'—':fmt(b.fund,1),''],
      ['板块内联动',b.linkage==null?'—':fmt(b.linkage,1),'']]
    .map(function(x){return '<div class="metric"><div class="lbl">'+x[0]+'</div>'
      +'<div class="val" style="font-size:1.5rem" class="'+x[2]+'"><span class="'+x[2]+'">'+x[1]+'</span></div></div>';}).join('')
    +'</div>';
  h+=renderBoardChain(b);
  h+='<div class="card" style="margin-bottom:16px"><h3>口径说明</h3>'
    +'<div style="font-size:13px;color:var(--txt2);line-height:1.7">'
    +'资金强度：<b>'+esc(b.fund_src||'—')+'</b>　'
    +(b.linkage_src?'板块内联动：<b>'+esc(b.linkage_src)+'</b>':'')
    +(n(b.gate,1)<1?'<br><span style="color:var(--orange)">⚠ 该板块 5/20 日处于下跌，强度分已施加跌势闸门</span>':'')
    +'</div></div>';
  h+='<div class="card"><h3>该题材下已覆盖个股 <small>共 '+rel.length+' 只（当前股票池，已排除无成交）</small></h3>';
  h+=rel.length?('<div class="tw" style="border:0;background:transparent"><table><thead><tr>'
    +'<th class="l">名称</th><th class="l">板别</th><th>现价</th><th>涨跌</th><th>5日</th><th>强度分位</th></tr></thead><tbody>'
    +rel.map(function(s){return '<tr class="clickable" onclick="showStock(\''+s.code+'\')">'
      +'<td class="l"><span class="nm">'+esc(s.name)+'</span><span class="cd">'+esc(s.code)+'</span></td>'
      +'<td class="l">'+bpill(s)+npill(s)+'</td>'
      +'<td>'+fmt(s.price)+'</td><td class="'+cls(s.change_pct)+'">'+pct(s.change_pct)+'</td>'
      +'<td class="'+cls(s.ret5)+'">'+pct(s.ret5,1)+'</td>'
      +'<td><b style="color:'+scoreColor(s.score)+'">'+fmt(s.score,1)+'</b></td></tr>';}).join('')
    +'</tbody></table></div>'):'<div class="empty">该题材下暂无个股数据</div>';
  h+='</div>';
  h+='<div style="margin-top:18px;display:flex;gap:10px">'
    +'<button class="btn primary" onclick="closeDrawer();pickThemeByName(\''
    +jsq(b.name)+'\')">筛选该板块全部成分股 →</button>'
    +'<span style="font-size:12.5px;color:var(--txt3);align-self:center">'
    +'跳到个股页并应用筛选条件，可按资金 / 涨幅 / 五日线再叠加排序</span></div>';
  openDrawer(esc(b.name),'板块强度 '+fmt(b.score,1)+' · 排名第 '+b.rank,h,true);
}

/* ═══════════════ 题材页 ═══════════════ */
function renderThemesPage(){
  var tags=((DATA.themes||{}).hot_tags)||[];
  document.getElementById('th-cloud').innerHTML=tags.length
    ? tags.map(function(x,i){var sz=Math.max(12.5,26-i*0.5);
        return '<span style="font-size:'+sz.toFixed(1)+'px" onclick="pickThemeByName(\''
          +jsq(x.theme)+'\')" title="'+esc(x.theme)+' · 当日 '+n(x.count)+' 只涨停">'
          +esc(x.theme)+'<b>'+n(x.count)+'</b></span>';}).join('')
    : '<div class="empty">暂无题材词频数据</div>';

  var tr=(DATA.theme_rank||[]);
  var h='<thead><tr><th>#</th><th class="l">题材</th><th>成员</th><th>覆盖</th><th>上涨占比</th><th>涨幅</th></tr></thead><tbody>';
  tr.slice(0,40).forEach(function(t){
    var tnk=tagCount(t.name);
    var tclk=tnk ? 'pickThemeByName(\''+jsq(t.name)+'\')' : 'explainNoMembers(\''+jsq(t.name)+'\')';
    h+='<tr class="'+(tnk?'clickable':'')+'" onclick="'+tclk+'">'
      +'<td><span class="rk'+(t.rank<=3?' t'+t.rank:'')+'">'+t.rank+'</span></td>'
      +'<td class="l"><span class="nm">'+esc(t.name)+'</span>'
      + (tnk ? ' <span class="mini" title="查看题材组明细" onclick="event.stopPropagation();'
        +'showThemeGroup('+t.rank+')">ⓘ</span>' : '')
      +'</td>'
      +'<td>'+n(t.n)+'</td><td class="flat">'+fmt(t.coverage,0)+'%</td>'
      +'<td class="l" style="min-width:110px">'+bar(t.up_ratio,n(t.up_ratio)>=60?'hi':'')+' '
      +'<b class="'+(n(t.up_ratio)>=60?'up':(n(t.up_ratio)<=40?'down':'flat'))+'">'+fmt(t.up_ratio,1)+'%</b></td>'
      +'<td class="'+cls(t.avg_chg)+'">'+pct(t.avg_chg)+'</td></tr>';});
  document.getElementById('tb-th2').innerHTML=h+'</tbody>';

  var by=tr.slice().sort(function(a,b){return n(b.main_net_sum)-n(a.main_net_sum);});
  var g='<thead><tr><th>#</th><th class="l">题材</th><th>成员</th><th>主力净额</th><th>上涨占比</th><th>涨幅</th></tr></thead><tbody>';
  by.slice(0,40).forEach(function(t,i){
    var v=n(t.main_net_sum);
    var tnk=tagCount(t.name);
    var tclk=tnk ? 'pickThemeByName(\''+jsq(t.name)+'\')' : 'explainNoMembers(\''+jsq(t.name)+'\')';
    g+='<tr class="'+(tnk?'clickable':'')+'" onclick="'+tclk+'">'
      +'<td><span class="rk'+(i<3?' t'+(i+1):'')+'">'+(i+1)+'</span></td>'
      +'<td class="l"><span class="nm">'+esc(t.name)+'</span>'
      + (tnk ? ' <span class="mini" title="查看题材组明细" onclick="event.stopPropagation();'
        +'showThemeGroup('+t.rank+')">ⓘ</span>' : '')
      +'</td>'
      +'<td>'+n(t.n)+'</td>'
      +'<td class="'+(v>0?'up':(v<0?'down':'flat'))+'">'+yi(Math.abs(v))+'</td>'
      +'<td class="flat">'+fmt(t.up_ratio,1)+'%</td>'
      +'<td class="'+cls(t.avg_chg)+'">'+pct(t.avg_chg)+'</td></tr>';});
  document.getElementById('tb-th3').innerHTML=g+'</tbody>';
}

function showThemeGroup(rank){
  var t=(DATA.theme_rank||[]).filter(function(x){return x.rank===rank;})[0];
  if(!t)return;
  var rel=(DATA.stocks||[]).filter(function(s){return (s.boards||[]).indexOf(t.name)>=0;})
    .filter(function(s){return s.traded!==0;}).slice(0,50);
  var h='<div class="grid g4" style="grid-template-columns:repeat(3,1fr);margin-bottom:18px">'
    +[['成员数',n(t.n),''],['成交覆盖',fmt(t.coverage,0)+'%',n(t.coverage)>=80?'':'up'],
      ['上涨占比',fmt(t.up_ratio,1)+'%',n(t.up_ratio)>=60?'up':''],
      ['等权涨幅',pct(t.avg_chg),cls(t.avg_chg)],
      ['涨/跌/平',n(t.up)+'/'+n(t.down)+'/'+n(t.flat),''],
      ['主力净额',yi(Math.abs(n(t.main_net_sum))),n(t.main_net_sum)>0?'up':'down']]
    .map(function(x){return '<div class="metric"><div class="lbl">'+x[0]+'</div>'
      +'<div class="val" style="font-size:1.45rem"><span class="'+x[2]+'">'+x[1]+'</span></div></div>';}).join('')
    +'</div>';
  var themeBoard=(DATA.boards||[]).filter(function(x){return x.name===t.name;})[0];
  if(themeBoard)h+=renderBoardChain(themeBoard);
  h+='<div style="font-size:12.5px;color:var(--txt3);line-height:1.7;margin-bottom:18px">'
    +'「上涨占比」的分母是<b>当日有成交的成员数</b>，未成交个股不计入分母，'
    +'因此该指标不会因开盘初期样本不足而被虚高。当前成交覆盖率 '
    +'<b style="color:var(--txt2)">'+fmt(t.coverage,0)+'%</b>。</div>';
  h+='<div class="card"><h3>成分股 <small>按20日涨幅排序</small></h3>';
  h+=rel.length?('<div class="tw" style="border:0;background:transparent"><table><thead><tr>'
    +'<th class="l">名称</th><th class="l">板别</th><th>现价</th><th>涨跌</th><th>5日</th><th>换手</th><th>强度分位</th></tr></thead><tbody>'
    +rel.map(function(s){return '<tr class="clickable" onclick="showStock(\''+s.code+'\')">'
      +'<td class="l"><span class="nm">'+esc(s.name)+'</span><span class="cd">'+esc(s.code)+'</span>'
      +(s.limit_today?' <span class="pill up">涨停</span>':'')+'</td>'
      +'<td class="l">'+bpill(s)+npill(s)+'</td>'
      +'<td>'+fmt(s.price)+'</td><td class="'+cls(s.change_pct)+'">'+pct(s.change_pct)+'</td>'
      +'<td class="'+cls(s.ret5)+'">'+pct(s.ret5,1)+'</td><td>'+fmt(s.turnover)+'%</td>'
      +'<td><b style="color:'+scoreColor(s.score)+'">'+fmt(s.score,1)+'</b></td></tr>';}).join('')
    +'</tbody></table></div>'):'<div class="empty">该题材下暂无可展示个股</div>';
  h+='</div>';
  h+='<div style="margin-top:18px;display:flex;gap:10px">'
    +'<button class="btn primary" onclick="closeDrawer();pickThemeByName(\''
    +jsq(t.name)+'\')">筛选该题材全部成分股 →</button>'
    +'<span style="font-size:12.5px;color:var(--txt3);align-self:center">'
    +'跳到个股页并应用筛选条件，可按资金 / 涨幅 / 五日线再叠加排序</span></div>';
  openDrawer(esc(t.name),'题材组 · 第 '+t.rank+' 名 · '+n(t.n)+' 只成员',h,true);
}

/* ═══════════════ 个股页 ═══════════════ */

var FACTORS=[['rs','日线进攻强度分位'],['sector','行业广度%']];
var FACTORS_AUX=[['fund','主力资金分位（仅辅助）']];
var STATEFN={
  'persistent_strength':function(s){return s.persistent_strong===true;},
  'recent_strength':function(s){return s.recent_improving===true;},
  'fading_strength':function(s){return s.high_fading===true;},
  'axis_both':function(s){return s.axis_group==='情绪活跃·趋势在线';},
  'axis_emotion':function(s){return s.axis_group==='情绪活跃·趋势未在线';},
  'axis_trend':function(s){return s.axis_group==='趋势在线·情绪平稳';},
  'axis_weak':function(s){return s.axis_group==='趋势未在线·情绪平稳';},
  'watch':function(s){return s.watch_candidate;},
  'breakout':function(s){return currentCandidateActive(s,'current_pullback_candidate');},
  'pullback':function(s){return s.pullback_observe;},
  'failed10':function(s){return s.touch_state==='回踩失守'||s.touch_state==='收盘失守10日线';},
  'recover10':function(s){return s.touch_state==='跌破后收复';},
  'fundpos':function(s){return s.fund_positive_all===true;},
  'reso':function(s){return s.watch_candidate&&s.industry_supported;},
  'above60':function(s){return s.trend_aligned;},
  'above20':function(s){return s.above20;},
  'hot':function(s){return s.overheated;},
  'limit1':function(s){return n(s.limit_today)&&n(s.limit_streak)<=1;},
  'streak':function(s){return n(s.limit_streak)>=2;}
};
var STATE_LABEL={persistent_strength:'日线进攻强势',recent_strength:'日线近期增强',fading_strength:'日线高位衰减',axis_both:'情绪活跃·日线趋势在线',axis_emotion:'情绪活跃·日线趋势未在线',axis_trend:'日线趋势在线·情绪平稳',axis_weak:'日线趋势未在线·情绪平稳',watch:'日线趋势在线',breakout:'当前回踩观察',pullback:'日线回踩形态',failed10:'日线10日线失守',recover10:'日线跌破后收复',fundpos:'资金三期均正',reso:'行业支持',above60:'日线三线多头',above20:'日线站上20日线',hot:'盘中位置偏热',limit1:'今日首板',streak:'连板'};
var STATE_TIP={persistent_strength:'完成日趋势在线、进攻分≥65、5/20日上涨，且5日≥5%或10日≥8%或20日≥12%；不限制名额',recent_strength:'日线相邻等长窗口的相对表现增强或修复，且5日绝对收益为正；仅供观察',fading_strength:'日线20日涨幅分位≥80，但日线近期变化转弱；仅供观察',watch:'完成日MA5>MA10>MA20、MA20上行且收盘不低于MA10',breakout:'历史回踩形态成立，现价守住盘中MA10且通过风险、过热和成交限制',pullback:'最近完成日线记录的回踩形态',failed10:'完成日线趋势结构受损',recover10:'历史日线失守MA10后重新站回；不代表盘中转弱后收复',fundpos:'东财日级主力净额近3/5/10日均正；未知不算正',reso:'趋势在线且行业同伴多数站上20日线',above60:'完成日MA5>MA10>MA20且MA20上行',above20:'完成日线收盘高于20日均线',hot:'现价距离盘中暂态MA10超过3.5 ATR',limit1:'今日涨停且为第1板',streak:'连续2板及以上'};
var PRESETS={'全部有效样本':{},'日线进攻强势':{states:['persistent_strength'],sortK:'stock_strength_score'},'日线近期增强':{states:['recent_strength'],sortK:'strength_accel5_pp'},'日线高位衰减':{states:['fading_strength'],sortK:'ret20'},'情绪活跃·趋势在线':{states:['axis_both']},'情绪活跃·趋势未在线':{states:['axis_emotion']},'日线趋势在线·情绪平稳':{states:['axis_trend']},'日线趋势未在线·情绪平稳':{states:['axis_weak']},'日线趋势在线':{states:['watch']},'当前回踩观察':{states:['watch','breakout']},'日线回踩形态':{states:['pullback']},'日线10日线失守':{states:['failed10']},'日线跌破后收复':{states:['recover10']},'资金三期均正':{states:['fundpos']},'行业支持':{states:['reso']},'日线三线多头':{states:['above60']},'盘中位置偏热':{states:['hot']}};
STATEFN.attack_watch=function(s){return currentCandidateActive(s,'attack_watch_candidate');};
STATE_LABEL.attack_watch='当前进攻监测';
STATE_TIP.attack_watch='报价与价格尺度有效、暂态A且上涨≥3%或现价反包/突破；风险单列，待收盘确认';
PRESETS['当前进攻监测']={states:['attack_watch'],sortK:'live_attack_score'};

function activeFilterCount(){
  var f=STATE.filters,c=0;
  c+=f.themes.length+f.industries.length+f.boards.length+f.states.length;
  if(f.scoreMin>0||f.scoreMax<100)c++;
  if(f.chgMin>-21||f.chgMax<21)c++;
  if(f.intraMin>0||f.intraMax<100)c++;
  if(f.turnMin>0||f.turnMax<100)c++;
  if(f.vrMin>0||f.vrMax<200)c++;
  if(f.capMin>0||f.capMax<100000)c++;
  if(f.ret5Min>-50||f.ret5Max<200)c++;
  if(f.fundMin>0||f.fundMax<100)c++;
  if(f.pos60Min>0||f.pos60Max<100)c++;
  if(f.distMin>-10||f.distMax<10)c++;
  if(STATE.q)c++;
  if(STATE.boardFilterId)c++;
  return c;
}
/* 逐条列出当前生效的条件，供状态条与"筛不出结果"的归因提示复用 */
function activeLabels(){
  var f=STATE.filters,out=[];
  f.themes.forEach(function(t){out.push({k:'theme',v:t,label:'题材：'+t});});
  f.industries.forEach(function(t){out.push({k:'ind',v:t,label:'行业：'+t});});
  f.boards.forEach(function(t){out.push({k:'board',v:t,label:'板别：'+t});});
  if(STATE.boardFilterId){
    var selectedBoard=(DATA.board_catalog||[]).filter(function(b){return b.id===STATE.boardFilterId;})[0];
    out.push({k:'boardId',v:STATE.boardFilterId,label:'板块：'+(selectedBoard?selectedBoard.name:'已选板块')});
  }
  f.states.forEach(function(k){out.push({k:'state',v:k,label:'状态：'+(STATE_LABEL[k]||k)});});
  if(f.scoreMin>0||f.scoreMax<100)out.push({k:'score',label:'日线进攻强度分位 '+f.scoreMin+'~'+f.scoreMax});
  if(f.chgMin>-21||f.chgMax<21)out.push({k:'chg',label:'涨跌幅 '+f.chgMin+'~'+f.chgMax+'%'});
  if(f.intraMin>0||f.intraMax<100)out.push({k:'intra',label:'盘中强度 '+f.intraMin+'~'+f.intraMax});
  if(f.ret5Min>-50||f.ret5Max<200)out.push({k:'ret5',label:'5日涨幅 '+f.ret5Min+'~'+f.ret5Max+'%'});
  if(f.turnMin>0||f.turnMax<100)out.push({k:'turn',label:'换手 '+f.turnMin+'~'+f.turnMax+'%'});
  if(f.vrMin>0||f.vrMax<200)out.push({k:'vr',label:'量比 '+f.vrMin+'~'+f.vrMax});
  if(f.capMin>0||f.capMax<100000)out.push({k:'cap',label:'市值 '+f.capMin+'~'+f.capMax+'亿'});
  if(f.fundMin>0||f.fundMax<100)out.push({k:'fund',label:'资金分 '+f.fundMin+'~'+f.fundMax});
  if(f.pos60Min>0||f.pos60Max<100)out.push({k:'pos60',label:'60日位置 '+f.pos60Min+'~'+f.pos60Max});
  if(f.distMin>-10||f.distMax<10)out.push({k:'dist',label:'距MA10 '+f.distMin+'~'+f.distMax+' ATR'});
  return out;
}
function stockMatchesQuery(s,q){
  if(!q)return true;
  var hay=(String(s.code)+' '+String(s.name)+' '+(s.display_boards||s.boards||[]).join(' ')
    +' '+(s.concepts||[]).join(' ')+' '+(s.industry||[]).join(' ')
    +' '+(s.board_name||'')+(n(s.is_new)?' 次新':'')).toLowerCase();
  return hay.indexOf(q)>=0;
}
function passFilter(s,view){
  view=view||STOCK_VIEW;
  var f=STATE.filters, ign=(strat()==='ignition');
  var fa=stratFactors(s);
  if(view!=='all'&&n(s.traded,1)===0)return false;  // 全部样本保留停牌与无成交状态
  if(ign && view!=='all' && !s.ign_pass)return false; // 全部样本入口仍保留未通过启动策略的样本
  var q=STATE.q.trim().toLowerCase();
  // 查询只限定搜索范围；仍须满足当前入口和筛选条件，未命中项单独显示。
  if(q&&!stockMatchesQuery(s,q))return false;
  if(STATE.boardFilterId){
    var bf=(DATA.board_catalog||[]).filter(function(b){return b.id===STATE.boardFilterId;})[0];
    if(!bf||(bf.member_codes||[]).indexOf(s.code)<0)return false;
  }
  if(f.themes.length && !f.themes.some(function(t){
    var board=boardById('theme:'+t);
    return board?(board.member_codes||[]).indexOf(s.code)>=0
      :(s.display_boards||s.boards||[]).indexOf(t)>=0;
  }))return false;
  if(f.industries.length && !f.industries.some(function(t){return (s.industry||[]).indexOf(t)>=0;}))return false;
  // 板别多选：OR 语义（"创业板或科创板"是同时选中两个板，不是要同时属于两个板）
  if(f.boards.length && f.boards.indexOf(s.board_name||'')<0)return false;
  if(f.states.length && !ign){
    // and = 同时满足（"低位 + 放量"这种叠加）；or = 任一满足（"首板或连板"）
    // 状态标签是**波段口径**（首板/连板/多头…），短线启动模式下不适用
    var ok = STATE.stateMode==='or'
      ? f.states.some(function(k){return STATEFN[k]&&STATEFN[k](s);})
      : f.states.every(function(k){return STATEFN[k]&&STATEFN[k](s);});
    if(!ok)return false;
  }
  var sc=stratScore(s);
  if(f.scoreMin>0||f.scoreMax<100){
    if(sc==null||sc<f.scoreMin||sc>f.scoreMax)return false;
  }
  if(f.intraMin>0||f.intraMax<100){
    if(!quoteFreshAtClientNow(s)||s.intraday_score==null||s.intraday_score<f.intraMin||s.intraday_score>f.intraMax)return false;
  }
  var completed=useCompletedClose(),lunch=lunchDisplayQuote(s),bridge=afternoonBridgeQuote(s),
    openBridge=morningOpenBridgeQuote(s),auction=auctionDisplayQuote(s),closing=completed?closeDisplayQuote(s):null;
  var ch=completed?(closing&&closing.change):lunch?lunch.change:bridge?bridge.change:
    openBridge?openBridge.change:auction?auction.change:s.change_pct;
  if(f.chgMin>-21||f.chgMax<21){
    if((completed?ch==null:lunch||bridge||openBridge||auction?false:!quoteFreshAtClientNow(s))||ch<f.chgMin||ch>f.chgMax)return false;
  }
  if(f.ret5Min>-50||f.ret5Max<200){
    var t5=n(s.ret5);if(t5<f.ret5Min||t5>f.ret5Max)return false;
  }
  if(f.turnMin>0||f.turnMax<100){
    var tu=n(s.turnover);if(tu<f.turnMin||tu>f.turnMax)return false;
  }
  if(f.vrMin>0||f.vrMax<200){
    var vr=n(s.volume_ratio_closed);if(vr<f.vrMin||vr>f.vrMax)return false;
  }
  if(f.capMin>0||f.capMax<100000){
    var cap=n(s.float_mcap);if(cap<f.capMin||cap>f.capMax)return false;
  }
  // 以下都是**波段口径**的筛选，短线启动模式下跳过（避免把两套口径混在一张表里筛）
  if(!ign){
    if(f.pos60Min>0||f.pos60Max<100){
      var p60=n(s.position60);if(p60<f.pos60Min||p60>f.pos60Max)return false;
    }
    if(f.distMin>-10||f.distMax<10){
      var da=n(s.live_dist_atr,-999);
      if(da<f.distMin||da>f.distMax)return false;
    }
    if(f.fundMin>0||f.fundMax<100){
      var fu=fa.fund;
      if(fu==null||fu===''){return false;}
      if(n(fu)<f.fundMin||n(fu)>f.fundMax)return false;
    }
  }
  return true;
}
/* 逐条试算"去掉某条条件后能命中多少只"，用来定位是哪一条把结果卡死的。
   做法是临时清掉一条、跑一遍过滤、再还原 —— 纯计算，不改用户当前的条件。 */
var ZERO_CASES=[
  ['题材',function(){STATE.filters.themes=[];}],
  ['行业',function(){STATE.filters.industries=[];}],
  ['板别',function(){STATE.filters.boards=[];}],
  ['状态标签',function(){STATE.filters.states=[];}],
  ['日线强度分位区间',function(){STATE.filters.scoreMin=0;STATE.filters.scoreMax=100;}],
  ['涨跌幅区间',function(){STATE.filters.chgMin=-21;STATE.filters.chgMax=21;}],
  ['盘中强度区间',function(){STATE.filters.intraMin=0;STATE.filters.intraMax=100;}],
  ['5日涨幅',function(){STATE.filters.ret5Min=-50;}],
  ['换手率区间',function(){STATE.filters.turnMin=0;STATE.filters.turnMax=100;}],
  ['完成日量比区间',function(){STATE.filters.vrMin=0;STATE.filters.vrMax=200;}],
  ['流通市值区间',function(){STATE.filters.capMin=0;STATE.filters.capMax=100000;}],
  ['资金分区间',function(){STATE.filters.fundMin=0;STATE.filters.fundMax=100;}],
  ['60日位置区间',function(){STATE.filters.pos60Min=0;STATE.filters.pos60Max=100;}],
  ['距MA10(ATR)',function(){STATE.filters.distMin=-10;STATE.filters.distMax=10;}]
];
function diagnoseZero(){
  var all=stockPoolRows().filter(function(s){return stockViewMatches(s,STOCK_VIEW);});
  var rows=[];
  ZERO_CASES.forEach(function(c){
    var keep=JSON.parse(JSON.stringify(STATE.filters));
    c[1]();
    rows.push({label:c[0], n:all.filter(function(s){return passFilter(s,STOCK_VIEW);}).length});
    STATE.filters=keep;
  });
  var live=rows.filter(function(r){return r.n>0;}).sort(function(a,b){return a.n-b.n;});
  return {base:all.length, rows:rows, hint:live.length?live[0]:null};
}
function zeroTipHtml(){
  var d=diagnoseZero(), rows=d.rows.filter(function(r){return r.n>0;})
                               .sort(function(a,b){return a.n-b.n;});
  var h='<div class="zero-hint"><b>为什么一只都筛不出来？</b><br>'
    +'股票池内共有 <b>'+d.base+'</b> 只可筛选个股。逐条放宽后能命中：';
  if(!rows.length){
    h+='<br>每条单独放宽后仍是 0 —— 说明条件之间互斥（例如同时勾了「涨停」和「下跌」）。'
      +'建议先只留一个条件，再逐步叠加。';
  }else{
    h+='<div style="margin-top:9px;display:flex;flex-wrap:wrap;gap:7px">'
      + rows.slice(0,7).map(function(r){
          return '<span class="fchip" style="cursor:default">放宽「'+esc(r.label)+'」→ '
            + r.n +' 只</span>';}).join('')+'</div>'
      +'<div style="margin-top:10px">卡得最紧的是 <b>'+esc(rows[0].label)+'</b>，'
      +'放宽它应该就能看到结果。</div>';
  }
  h+='<div style="margin-top:13px"><button class="btn" onclick="clearFilters()">清除全部条件</button> '
    +'<button class="btn" onclick="renderFilterPanel()">打开筛选面板</button></div></div>';
  return h;
}


function fundTri(s){
  var keys=['fund3_yi','fund5_yi','fund10_yi'];
  if(keys.every(function(k){return s[k]==null;}))return '<span class="flat">未知</span>';
  return keys.map(function(k){var v=s[k];return v==null?'—':'<span class="'+cls(v)+'">'+(v>=0?'+':'')+fmt(v,2)+'</span>';}).join(' / ')
    +'<small class="flat"> 亿</small>';
}

var STOCK_VIEW='all';
var STOCK_VIEW_NAMES={all:'全部样本'};
function stockObservationTag(s){
  if(s.trade_status==='no_trade')return {label:'当日无成交',kind:'pending'};
  if(s.trade_status==='trade_recovered_wait_daily')return {label:'恢复成交待评分',kind:'pending'};
  if(currentCandidateQuoteUsable(s)){
    if(s.attack_watch_candidate)return {label:'进攻 · '+(s.live_attack_stage||'趋势推进'),kind:'strong'};
    var state=s.intraday_observation_state;
    var kinds={'风险观察':'risk','封板状态／成交受限':'risk','分歧观察':'weak',
      '当前强势':'strong','初步转强，待收盘确认':'startup','盘中修复':'weak',
      '活跃观察':'normal','相对抗跌':'weak','今日转弱':'weak',
      '暂态趋势成立，待观察':'daily'};
    if(kinds[state])return {label:state,kind:kinds[state]};
  }
  if(s.watch_candidate||(s.coverage_only&&s.trend_online===1))return {label:'日线趋势',kind:'daily'};
  if(s.coverage_only)return {label:'待评分',kind:'pending'};
  return {label:'普通样本',kind:'normal'};
}
function stockTagHtml(s){
  var tag=stockObservationTag(s);
  return '<span class="stock-tag '+tag.kind+'">'+tag.label+'</span>';
}
function stockViewMatches(){return true;}
function sortStockViewRows(rows,view){
  if(STATE.sort.stocks.k==='change_pct'&&['集合竞价','竞价结束','早盘','午间休市','午盘','尾盘'].indexOf(sessionNow())>=0){
    var sign=STATE.sort.stocks.asc?1:-1;
    return rows.sort(function(a,b){
      var aq=quoteFreshAtClientNow(a)?{change:a.change_pct}:lunchDisplayQuote(a)||afternoonBridgeQuote(a)||morningOpenBridgeQuote(a)||auctionDisplayQuote(a);
      var bq=quoteFreshAtClientNow(b)?{change:b.change_pct}:lunchDisplayQuote(b)||afternoonBridgeQuote(b)||morningOpenBridgeQuote(b)||auctionDisplayQuote(b);
      var av=aq&&aq.change,bv=bq&&bq.change;
      if(av==null||bv==null)return Number(av==null)-Number(bv==null)||String(a.code).localeCompare(String(b.code));
      return sign*(av-bv)||String(a.code).localeCompare(String(b.code));
    });
  }
  if(STATE.sort.stocks.k==='change_pct'&&useCompletedClose()){
    var direction=STATE.sort.stocks.asc?1:-1;
    return rows.sort(function(a,b){
      var ac=closeDisplayQuote(a),bc=closeDisplayQuote(b);
      var av=ac&&ac.change,bv=bc&&bc.change;
      if(av==null||bv==null)return Number(av==null)-Number(bv==null)||String(a.code).localeCompare(String(b.code));
      return direction*(av-bv)||String(a.code).localeCompare(String(b.code));
    });
  }
  if(STATE.sort.stocks.k)return sortRows(rows,STATE.sort.stocks.k,STATE.sort.stocks.asc);
  var byCode=function(a,b){return String(a.code||'').localeCompare(String(b.code||''));};
  return rows.sort(function(a,b){
    var ascore=a.intraday_score_stale===true||!quoteFreshAtClientNow(a)?null:a.intraday_score;
    var bscore=b.intraday_score_stale===true||!quoteFreshAtClientNow(b)?null:b.intraday_score;
    var av=a.stock_strength_score!=null||ascore!=null;
    var bv=b.stock_strength_score!=null||bscore!=null;
    return Number(bv)-Number(av)
      ||n(b.stock_strength_score,-1)-n(a.stock_strength_score,-1)
      ||n(bscore,-1)-n(ascore,-1)
      ||Number(quoteFreshAtClientNow(b))-Number(quoteFreshAtClientNow(a))||byCode(a,b);});
}
function stockViewRows(view,applyFilters,sourceRows){
  view=view||STOCK_VIEW;
  var rows=(sourceRows||stockPoolRows()).filter(function(s){return stockViewMatches(s,view);});
  if(applyFilters!==false)rows=rows.filter(function(s){return passFilter(s,view);});
  return sortStockViewRows(rows,view);
}
function clearStockFilters(){
  STATE.filters=defaultFilters();STATE.boardFilterId=null;STATE.q='';
  var q=document.getElementById('q');if(q)q.value='';
  STATE.sort.stocks={k:null,asc:false};STATE.limit=80;renderStocks();
  toast('已清除个股筛选');
}
function stockKeyStatus(s,fresh,phaseObs){
  if(sessionNow()==='午间休市')return {label:lunchDisplayQuote(s)?'上午 · '+(s.last_valid_intraday_trend_state||'盘中观察留存'):'上午报价待核对',risk:false};
  if(useCompletedClose())return {label:s.trend_online==null?'收盘趋势待核验':s.trend_online?'收盘趋势在线':'收盘趋势未成立',risk:false};
  if(afternoonBridgeQuote(s))return {label:'午后报价待更新 · 暂显11:30价格',risk:false};
  if(morningOpenBridgeQuote(s))return {label:'开盘报价待更新 · 竞价参考',risk:false};
  if(phaseObs)return {label:phaseObs.kind,risk:false};
  if(!fresh)return {label:'报价待更新',risk:false};
  var flags=s.intraday_risk_flags||[];
  var priorities=['接近跌停','大幅下跌','一字跌停','明显冲高回落',
    '现价失守盘中MA20','现价失守盘中MA10','触板未封',
    '现价距盘中MA10过远，位置偏热'];
  for(var i=0;i<priorities.length;i++)if(flags.indexOf(priorities[i])>=0)
    return {label:priorities[i].replace('现价失守盘中','失守').replace('现价距盘中MA10过远，位置偏热','位置偏热'),risk:true};
  if(s.intraday_transition)return {label:s.intraday_transition,risk:false};
  if(s.intraday_trend_ok===true)return {label:'暂态趋势成立',risk:false};
  return {label:'趋势待确认',risk:false};
}
function renderStocks(){
  document.getElementById('btn-filter').onclick=renderFilterPanel;
  var onlyBtn=document.getElementById('btn-only-view');
  onlyBtn.onclick=clearStockFilters;
  onlyBtn.disabled=activeFilterCount()===0;
  onlyBtn.title=onlyBtn.disabled?'当前没有筛选条件':'清除搜索与筛选，查看全部样本';
  var pool=stockPoolRows(), res=stockViewRows(STOCK_VIEW,true,pool);
  var shown=res.slice(0,STATE.limit), count=activeFilterCount();
  var badge=document.getElementById('fcount'); badge.style.display=count?'inline-block':'none';badge.textContent=count;
  var pending=res.filter(function(s){return s.coverage_only;}).length;
  var selectedConcept=STATE.boardFilterId&&boardById(STATE.boardFilterId);
  var resultScope=selectedConcept
    ? (selectedConcept.type==='theme'?'概念':'行业')+'「'+esc(selectedConcept.name)+'」· 当前覆盖成员 <b>'+n(selectedConcept.pool_members)+'</b> 只'
      +' · 已评分 '+n(selectedConcept.valid_members)+' 只'
      +(res.length!==n(selectedConcept.pool_members)?' · 当前条件显示 <b>'+res.length+'</b> 只':'')
    :STOCK_VIEW_NAMES[STOCK_VIEW]+' · '+(STATE.filters.themes.length?'概念筛选后 ':'')+'显示 <b>'+res.length+'</b> 只';
  var extraCount=Math.max(0,count-(selectedConcept?1:0));
  document.getElementById('stk-res').innerHTML=resultScope+' · 当前加载 '+shown.length
    +(extraCount?' · <span class="flat">另有 '+extraCount+' 项筛选</span>':'')
    +(pending?' · <span class="flat">其中 '+pending+' 只强度待评分</span>':'');
  var completed=useCompletedClose(),lunchPhase=sessionNow()==='午间休市';
  var h='<thead><tr>'+thSort('stocks','name','股票','l')
    +thSort('stocks','change_pct',completed?'最近收盘':lunchPhase?'午休参考':'今日')
    +thSort('stocks','stock_strength_score','日线分')
    +thSort('stocks','intraday_score','盘中分')
    +'<th>盘中进攻</th><th class="l">关键状态</th><th class="l">行业／概念</th>'
    +'</tr></thead><tbody>';
  shown.forEach(function(s){
    var fresh=quoteFreshAtClientNow(s);
    var lunch=lunchDisplayQuote(s);
    var bridge=afternoonBridgeQuote(s);
    var openBridge=morningOpenBridgeQuote(s);
    var closing=completed?closeDisplayQuote(s):null;
    var auction=auctionDisplayQuote(s);
    var dayValue=completed?(closing&&closing.change):lunch?lunch.change:fresh?s.change_pct:bridge?bridge.change:openBridge?openBridge.change:auction?auction.change:null;
    var shownPrice=completed?(closing&&closing.price):lunch?lunch.price:fresh?s.price:bridge?bridge.price:openBridge?openBridge.price:auction?auction.price:null;
    var quoteAt=completed?(closing&&closing.at):lunch?lunch.at:fresh?s.intraday_quote_at:bridge?bridge.at:openBridge?openBridge.at:auction?auction.at:s.last_valid_quote_at;
    var quoteTime=quoteAt?String(quoteAt).slice(11,16):'';
    var daily=s.stock_strength_score==null?'<span class="flat">强度待评分</span>':
      '<b>'+fmt(s.stock_strength_score,1)+'</b>'+(s.trend_tier?'<small>日线'+esc(s.trend_tier)+'档</small>':'');
    var score=(lunch||bridge)?(s.intraday_score==null?'<span class="flat">上午分未知</span>':
      '<b>'+fmt(s.intraday_score,1)+'</b><small>上午分 · '+esc(String(s.last_valid_quote_at||s.intraday_quote_at||'').slice(11,16))+'</small>'):
      openBridge||auction?'<span class="flat">竞价观察</span>':
      s.intraday_score==null?'<span class="flat">待评分</span>':
      fresh?'<b>'+fmt(s.intraday_score,1)+'</b>':
        '<span class="flat">—</span><small>上次 '+fmt(s.intraday_score,1)+'</small>';
    var key=stockKeyStatus(s,fresh,auction);
    var conceptFocus=selectedConcept&&selectedConcept.type==='theme'?selectedConcept.name:STATE.filters.themes[0];
    var visibleThemes=(s.display_boards||s.boards||[]).slice();
    if(conceptFocus&&visibleThemes.indexOf(conceptFocus)>=0){
      visibleThemes.splice(visibleThemes.indexOf(conceptFocus),1);visibleThemes.unshift(conceptFocus);
    }
    var themes=visibleThemes.slice(0,2).join(' · ')||'概念待核对';
    var industry=s.primary_industry||(s.industry||[])[0]||'行业待核对';
    var support='<span class="stock-key">'+esc(industry)+'</span>'
      +'<small class="stock-theme" title="'+esc(visibleThemes.join(' · '))+'">'+esc(themes)+'</small>';
    var rowClass='clickable'+(!completed&&!lunch&&!fresh&&!bridge&&!openBridge&&!auction?' stale-row':'');
    h+='<tr class="'+rowClass+'" onclick="showStock(\''+jsq(s.code)+'\')">'
      +'<td class="l"><div class="stock-identity"><span class="nm">'+esc(s.name)+'</span>'
      +'<span class="cd">'+esc(s.code)+'</span>'+stockTagHtml(s)+'</div></td>'
      +'<td class="'+(dayValue!=null?cls(dayValue):'flat')+'"><b>'+(dayValue==null?'—':pct(dayValue,1))+'</b>'
      +'<small>'+(completed?esc(closing?closing.kind:'收盘待核对')+' '+esc(quoteAt||'日期待核对')+' · ':lunch?esc(lunch.kind)+' · ':bridge?'午后待更新 · 11:30参考 · ':openBridge?'开盘待更新 · '+esc(openBridge.kind)+' · ':auction?esc(auction.kind)+' · ':'')
      +(shownPrice==null?(completed?'收盘数据不足':'报价待更新'):'¥'+fmt(shownPrice,2))
      +(lunch?(lunch.kind==='午间截至11:30'?' · 源 '+esc(lunch.sourceAt.slice(11,16)):''):
        bridge?' · 源 '+esc(bridge.sourceAt.slice(11,16)):
        openBridge?' · 源 '+esc(openBridge.sourceAt.slice(11,16)):
        completed&&closing&&closing.sourceAt?' · 源 '+esc(closing.sourceAt.slice(11,16)):
        !completed&&quoteTime?' · '+esc(quoteTime):'')+'</small></td>'
      +'<td>'+daily+'</td><td>'+score+'</td><td>'
      +(fresh&&s.live_attack_score!=null?'<b>'+esc(s.live_attack_tier||'未在线')+' · '+fmt(s.live_attack_score,1)+'</b><small>'+esc(s.live_attack_stage)+'</small>':'<span class="flat">待核验</span>')+'</td>'
      +'<td class="l"><span class="stock-key '+(key.risk?'risk-严重':'')+'">'+esc(key.label)+'</span></td>'
      +'<td class="l">'+support+'</td></tr>';
  });
  document.getElementById('tb-stocks').innerHTML=h+'</tbody>';
  document.getElementById('zero-tip').innerHTML=res.length?'':zeroTipHtml();
  var query=STATE.q.trim().toLowerCase();
  var searchMatches=query?pool.filter(function(s){return stockMatchesQuery(s,query);}):[];
  var outside=searchMatches.filter(function(s){return !stockViewMatches(s,STOCK_VIEW)
    ||!passFilter(s,STOCK_VIEW);}).slice(0,10);
  document.getElementById('search-outside').innerHTML=outside.length
    ?'<div class="card"><b>搜索结果，不满足当前条件</b><small class="flat">　不计入当前列表</small><div class="row wrap" style="gap:8px;margin-top:10px">'
      +outside.map(function(s){return '<button class="btn" onclick="showStock(\''+jsq(s.code)+'\')">'+esc(s.name)+' '+esc(s.code)+'</button>';}).join('')+'</div></div>':'';
  document.getElementById('stk-more').innerHTML=res.length>shown.length?'<button class="btn" onclick="STATE.limit+=120;renderStocks()">加载更多</button>':'';
  var m=DATA.strength_model||{}, im=DATA.intraday_model||{};
  var auctionOnly=['集合竞价','竞价结束'].indexOf(DATA.session)>=0;
  var latestQuote=auctionOnly?im.auction_latest_quote_at:im.latest_valid_quote_at;
  var lunchQuotes=lunchPhase?pool.map(lunchDisplayQuote).filter(Boolean):[];
  var lunchQuoteCount=lunchQuotes.filter(function(q){return q.kind==='午间截至11:30';}).length;
  var lunchEarlierCount=lunchQuotes.length-lunchQuoteCount;
  var closeBatch=(DATA.boundary_prices||{}).close;
  var closeAt=closeBatch&&parseDT(closeBatch.captured_at);
  var closeQuoteCount=completed&&sessionNow()==='已收盘'&&closeAt
    &&closeAt.toDateString()===new Date().toDateString()?Number(closeBatch.count||0):0;
  var bridgeQuoteCount=['午盘','尾盘'].indexOf(sessionNow())>=0
    ?pool.filter(function(s){return !!afternoonBridgeQuote(s);}).length:0;
  var morningBridgeCount=sessionNow()==='早盘'
    ?pool.filter(function(s){return !!morningOpenBridgeQuote(s);}).length:0;
  var auctionCount=['集合竞价','竞价结束'].indexOf(sessionNow())>=0
    ?pool.filter(function(s){return !!auctionDisplayQuote(s);}).length:0;
  document.getElementById('stk-sub').textContent=completed
    ? (closeQuoteCount?'收盘报价覆盖 '+closeQuoteCount+' / '+pool.length
        +' 只（交易截至15:00）· 正式日线判断 '+(m.asof||'待更新'):
        '休市显示逐股最近完成日收盘 · 日线判断 '+(m.asof||'—'))
      +' · 上次盘中报价 '+(latestQuote||'未知')
    : lunchPhase?'午间休市 · 11:30 价格覆盖 '+lunchQuoteCount+' / '+pool.length
      +' 只'+(lunchEarlierCount?' · 另有 '+lunchEarlierCount+' 只仅有更早报价':'')
      +' · 盘中评分留存截至 '+(latestQuote||'未知')
    : bridgeQuoteCount&&String(latestQuote||'').slice(11,16)<'13:00'
      ?'午后报价待更新 · 暂显11:30价格 '+bridgeQuoteCount+' / '+pool.length+' 只 · 上午评分截至 '+(latestQuote||'未知')
    : morningBridgeCount
      ?'开盘报价待更新 · 暂显竞价参考 '+morningBridgeCount+' / '+pool.length+' 只 · 正式盘中评分待更新'
    : ['集合竞价','竞价结束'].indexOf(sessionNow())>=0
      ?sessionNow()+' · 有效报价 '+auctionCount+' / '+pool.length+' 只 · 最新 '+(im.auction_latest_quote_at||'待更新')
    : '日线判断 '+(m.asof||'—')+' · '
      +(auctionOnly?'竞价报价 '+n(im.auction_quote_count):'盘中有效报价 '+n(im.valid_quote_count))
      +' / '+n(im.reference_pool_count)+' · 最新 '+(latestQuote||'未知');
  document.getElementById('intraday-note').textContent=(completed
    ? (DATA.session==='非交易日'?'非交易日':sessionNow())+': '
      +(closeQuoteCount?'先显示 15:00 收盘报价，正式日线到齐后按完成日因子更新；':'显示逐股最近完成日收盘；')
      +'盘中评分仅保留上次观察。'
    : lunchPhase?'午间休市：价格采用午休行情源给出的上午最后成交价，交易截至11:30；源刷新时间与盘中评分时间分开标注。'
    : bridgeQuoteCount&&String(latestQuote||'').slice(11,16)<'13:00'
      ?'午后开盘：有效午后报价尚未到达，暂显11:30参考价；不生成新的盘中候选。'
    : morningBridgeCount?'正式开盘：逐股正式报价尚未到达，暂显竞价参考价；不生成新的盘中候选。'
    : ['集合竞价','竞价结束'].indexOf(sessionNow())>=0?'集合竞价：9:15起获取报价，9:25保存竞价结束参考；不生成正常盘中评分。'
    : (im.phase_status||'盘中阶段待核验')+'；日线进攻强度 '+(m.asof||'—'))
    +'；最新逐股报价 '+(latestQuote||'未知')+'；页面生成 '+(DATA.generated_at||'—')
    +(lunchPhase?'。午休不生成新的盘中评分或状态转换；11:30 价格覆盖 '+lunchQuoteCount+' / '+pool.length
      +(lunchEarlierCount?'，另有 '+lunchEarlierCount+' 只显示更早有效报价':'')+'。':
      ['集合竞价','竞价结束'].indexOf(sessionNow())>=0?'。竞价阶段不要求成交额；竞价报价覆盖 '
      +auctionCount+' / '+pool.length+'。':
      '。盘中分三项齐全才生成，缺一项不补权重；行业、题材、资金分开展示。报价覆盖 '
      +n(im.valid_quote_count)+' / '+n(im.reference_pool_count)+'。')
    +(im.sample_changed_since_previous?'分位比较样本较上次扫描变化，分数变化需谨慎解读。':'')
    +(n(im.price_basis_mismatch_count)?'有 '+n(im.price_basis_mismatch_count)+' 只历史与报价口径异常，已暂停其均线判断。':'')
    +(pool.some(function(s){return !!s.auction_observation;})?' 盘前/竞价观察独立展示，不计入正常盘中榜。':'');
  if(DATA.intraday_close_confirmation){
    var cc=DATA.intraday_close_confirmation;
    document.getElementById('intraday-note').textContent+=' 收盘核对 '+esc(cc.asof||'')+'：盘中转强收盘未确认 '+n(cc.unconfirmed)+' 只。';
  }
  renderFbar();
}

function stockPoolRows(){
  var byCode={};
  (DATA.coverage_catalog||[]).concat(DATA.stocks||[]).forEach(function(s){
    var code=String(s.code||'');if(code&&!byCode[code])byCode[code]=s;
    else if(code&&s.coverage_only!==true)byCode[code]=s;
  });
  return Object.keys(byCode).map(function(code){return byCode[code];});
}

function renderFbar(){
  var f=STATE.filters, out=[];
  function rm(js,label){
    // × 挂在子元素上单独绑事件，避免"点标签也删条件"的误触
    return '<span class="fchip">'+esc(label)+'<span class="x" onclick="event.stopPropagation();'
      +js+'">×</span></span>';
  }
  // 用名字而不是下标删除：下标在连续删除时会错位（删了第 0 个，第 1 个就变成第 0 个）
  f.themes.forEach(function(t){out.push(rm("rmThemeByName('"+jsq(t)+"')",'题材：'+t));});
  f.industries.forEach(function(t){out.push(rm("rmIndByName('"+jsq(t)+"')",'行业：'+t));});
  f.boards.forEach(function(t){out.push(rm("rmBoardByName('"+jsq(t)+"')",'板别：'+t));});
  if(STATE.boardFilterId){
    var selectedBoard=(DATA.board_catalog||[]).filter(function(b){return b.id===STATE.boardFilterId;})[0];
    out.push(rm("STATE.boardFilterId=null;renderStocks()",'板块：'+(selectedBoard?selectedBoard.name:'已选板块')));
  }
  f.states.forEach(function(k){out.push(rm("rmStateByName('"+jsq(k)+"')",'状态：'+(STATE_LABEL[k]||k)));});
  if(f.scoreMin>0||f.scoreMax<100)out.push(rm("rmRange('score')",'日线进攻强度分位 '+f.scoreMin+'~'+f.scoreMax));
  if(f.chgMin>-21||f.chgMax<21)out.push(rm("rmRange('chg')",'涨跌幅 '+f.chgMin+'~'+f.chgMax+'%'));
  if(f.intraMin>0||f.intraMax<100)out.push(rm("rmRange('intra')",'盘中强度 '+f.intraMin+'~'+f.intraMax));
  if(f.ret5Min>-50||f.ret5Max<200)out.push(rm("rmRange('ret5')",'5日 ≥'+f.ret5Min+'%'));
  if(f.turnMin>0||f.turnMax<100)out.push(rm("rmRange('turn')",'换手 '+f.turnMin+'~'+f.turnMax+'%'));
  if(f.vrMin>0||f.vrMax<200)out.push(rm("rmRange('vr')",'量比 '+f.vrMin+'~'+f.vrMax));
  if(f.capMin>0||f.capMax<100000)out.push(rm("rmRange('cap')",'市值 '+f.capMin+'~'+f.capMax+' 亿'));
  if(f.fundMin>0||f.fundMax<100)out.push(rm("rmRange('fund')",'资金分 '+f.fundMin+'~'+f.fundMax));
  if(f.pos60Min>0||f.pos60Max<100)out.push(rm("rmRange('pos60')",'60日位置 '+f.pos60Min+'~'+f.pos60Max));
  if(f.distMin>-10||f.distMax<10)out.push(rm("rmRange('dist')",'距MA10 '+f.distMin+'~'+f.distMax+' ATR'));
  if(STATE.q)out.push(rm("rmQ()",'搜索：'+STATE.q));
  var bar=document.getElementById('fbar');
  if(!out.length){bar.innerHTML='';return;}
  bar.innerHTML='<span class="lbl">已选 '+out.length+' 项'
    +(STATE.states&&STATE.states.length?'':'')+'</span>'+out.join('')
    +'<span class="fclear" onclick="clearFilters()">全部清除</span>';
}
function rmThemeByName(t){var a=STATE.filters.themes,i=a.indexOf(t);if(i>=0)a.splice(i,1);renderStocks();}
function rmIndByName(t){var a=STATE.filters.industries,i=a.indexOf(t);if(i>=0)a.splice(i,1);renderStocks();}
function rmBoardByName(t){var a=STATE.filters.boards,i=a.indexOf(t);if(i>=0)a.splice(i,1);renderStocks();}
function rmStateByName(k){var a=STATE.filters.states,i=a.indexOf(k);if(i>=0)a.splice(i,1);renderStocks();}
function rmQ(){STATE.q='';var q=document.getElementById('q');if(q)q.value='';renderStocks();}
function rmRange(k){
  var f=STATE.filters;
  if(k==='score'){f.scoreMin=0;f.scoreMax=100;}
  if(k==='chg'){f.chgMin=-21;f.chgMax=21;}
  if(k==='ret5'){f.ret5Min=-50;f.ret5Max=200;}
  if(k==='turn'){f.turnMin=0;f.turnMax=100;}
  if(k==='vr'){f.vrMin=0;f.vrMax=200;}
  if(k==='cap'){f.capMin=0;f.capMax=100000;}
  if(k==='fund'){f.fundMin=0;f.fundMax=100;}
  if(k==='pos60'){f.pos60Min=0;f.pos60Max=100;}
  if(k==='dist'){f.distMin=-10;f.distMax=10;}
  renderStocks();
  if(document.getElementById('drawer').classList.contains('open'))renderFilterPanel();
}
function clearFilters(){
  STATE.filters=defaultFilters();
  STATE.boardFilterId=null;
  STATE.q=''; var q=document.getElementById('q'); if(q)q.value='';
  STATE.sort.stocks={k:null,asc:false};
  STATE.limit=80; renderStocks();
}
function applyPreset(name){
  if(!Object.prototype.hasOwnProperty.call(PRESETS,name)){
    toast('筛选策略不可用：'+name);return;
  }
  var p=PRESETS[name];
  clearFilters();
  Object.keys(p).forEach(function(k){
    if(k==='states')STATE.filters.states=p[k].slice();
    else if(k==='boards')STATE.filters.boards=p[k].slice();
    else if(k==='themes')STATE.filters.themes=p[k].slice();
    else if(k==='sortK')STATE.sort.stocks={k:p[k],asc:false};
    else STATE.filters[k]=p[k];
  });
  RENDERED.stocks=false;
  renderStocks(); toast('已应用策略：'+name);
}
/* 题材 → 个股筛选的统一入口。
   所有榜单（板块卡 / 涨停题材云 / 题材组榜 / 板块表 / 每日分析）都从这里跳，
   保证"点哪个题材就落到哪个题材的个股上"。 */

/* 概念数量使用同花顺 F10 与详情合并后的当前覆盖成员，不使用候选资格数。 */
function explainNoMembers(name){
  toast('概念「'+name+'」在当前覆盖股票池暂无成员；此处不代表同花顺全市场成员数。');
}
function pickTheme(i,fromHot){
  var name = fromHot ? ((((DATA.themes||{}).hot_tags)||[])[i]||{}).theme
                     : (((DATA.theme_rank||[])[i])||{}).name;
  pickThemeByName(name);
}

/* ── 导出 ── */

function exportCSV(){
  var res=stockViewRows(STOCK_VIEW,true);
  var head=['代码','名称','判断日','日线进攻强度','日线强度分位','日线近期变化','综合状态','分位较前日变化','分位较前五日变化','5日攻击速度分','10日推进分','20日涨幅基础分','结构不计分','5日进攻依据','10日进攻依据','20日进攻依据','结构与量价依据','绝对方向','主要强项','主要短板','近10日跑赢主板天数','近3日收盘位置%','放量滞涨','当前距20日高点%','历史最大回撤修复%','5日相对优势变化百分点','20日涨幅%','20日涨幅分位','逐股报价时间','现价','今日涨跌%','双轴分类','趋势阶段','情绪热度','量价表现','行业状态','个股行业关系','趋势助攻','情绪助攻','个股角色','日线MA5','日线MA10','日线MA20','三线排列','日线趋势在线','完成日回踩形态','MA20近5日斜率%','20日最大回撤%','有方向20日路径效率','5日对市场超额百分点','20日对市场超额百分点','5日对同行超额百分点','20日对同行超额百分点','同行趋势在线%','同行趋势变化百分点','剔除前两名后趋势在线%','同行情绪活跃%','同行涨停数','主力3日净额亿元','主力5日净额亿元','主力10日净额亿元','资金核验日','行业','行业广度%','有效同伴','日线与历史风险'];
  head.push('扫描完成时间','盘中强度','相对评分变化','盘中趋势状态','盘中暂态MA5','盘中暂态MA10','盘中暂态MA20','日内位置%','距日内高点%','盘中风险等级','盘中风险标记','行业同期涨幅%','本股对同行超额点','历史回踩形态','当前回踩资格','报价是否有效','行情阶段','报价状态','最后有效报价时间','当日相对主板超额百分点','主板等权涨幅%','开盘后表现%','盘中评分完整项数','盘中观察分类','扫描状态变化','当前强势资格','初步启动资格','转弱修复资格','报价日前固定MA5','报价日前固定MA10','报价日前固定MA20','暂态MA20参考基准','当日资金净额亿元','当日资金来源','当日资金采集时间');
  head.push('同花顺题材关系','题材关系状态','题材有效同伴覆盖','题材归属依据');
  head=head.map(function(name){return ({'当前回踩资格':'扫描时当前回踩资格',
    '当前强势资格':'扫描时当前强势资格','初步启动资格':'扫描时初步启动资格',
    '转弱修复资格':'扫描时转弱修复资格'})[name]||name;});
  head.push('当前报价状态','当前强势候选','当前回踩候选','当前初步启动候选','当前转弱修复候选');
  function cell(x){return '"'+String(x==null?'':x).replace(/"/g,'""')+'"';}
  var lines=[head.map(cell).join(',')];
  res.forEach(function(s){var p=s.stock_strength_parts||{},e=s.stock_strength_evidence||{};
    lines.push([s.code,s.name,s.signal_date,s.stock_strength_score,s.stock_strength_percentile,s.daily_motion||s.stock_strength_motion,s.stock_strength_display_state,s.strength_delta1,s.strength_delta5,p.attack5,p.attack10,p.attack20,'',e.attack5,e.attack10,e.attack20,s.structure_evidence,s.strength_direction,s.stock_strength_main_good,s.stock_strength_main_weak,s.beat_days10,s.close_location3_pct,s.volume_spike_stall?'是':'否',s.current_drawdown_pct,s.drawdown_repair_pct,s.strength_accel5_pp,s.ret20,s.ret20_percentile,s.intraday_quote_at,s.price,s.change_pct,s.axis_group,s.trend_stage,s.emotion_heat,s.emotion_acceptance,s.industry_trend_state,s.industry_stock_relation,s.trend_assist,s.emotion_assist,(s.roles||[]).join('、'),s.ma5,s.ma10,s.ma20,s.trend_aligned?'是':'否',s.trend_online?'是':'否',s.touch_state,s.ma20_slope5_pct,s.max_dd20_pct,s.path_eff20,s.ret5_ex_market,s.ret20_ex_market,s.ret5_ex_industry,s.ret20_ex_industry,s.industry_peer_trend_pct,s.industry_peer_trend_delta_pp,s.industry_ex_top2_trend_pct,s.emotion_peer_active_pct,s.emotion_peer_limit,s.fund3_yi,s.fund5_yi,s.fund10_yi,s.fund_asof,s.primary_industry,s.industry_breadth,s.industry_peers,(s.risk_notes||[s.reason_text||'']).join('；'),DATA.scan_completed_at||DATA.generated_at,s.intraday_score,s.intraday_score_delta,s.intraday_trend_state,s.intraday_ma5,s.intraday_ma10,s.intraday_ma20,s.intraday_position_pct,s.intraday_drawdown_from_high_pct,s.intraday_risk_level,(s.intraday_risk_flags||[]).join('；'),s.industry_intraday_change_pct,s.industry_intraday_excess_pct,s.historical_pullback_shape?'是':'否',s.current_pullback_candidate?'是':'否',s.intraday_quote_fresh?'是':'否',s.intraday_phase_status,s.intraday_quote_status,s.last_valid_quote_at,s.intraday_relative_return_pct,s.intraday_market_return_pct,s.intraday_open_return_pct,s.intraday_score_available_components,s.intraday_observation_state,s.intraday_transition,s.current_strong_candidate?'是':'否',s.startup_candidate?'是':'否',s.turn_weak_repair_candidate?'是':'否',s.daily_ma5_fixed,s.daily_ma10_fixed,s.daily_ma20_fixed,s.intraday_previous_completed_ma20,s.fund_today_yi,s.fund_today_source,s.fund_today_at].map(cell).join(','));});
  lines[0]+=',10日涨幅%,日线价格形态,盘中暂态进攻分,盘中暂态进攻档,盘中价格形态,进攻监测候选,进攻状态时间口径';
  res.forEach(function(s,i){lines[i+1]+=','+[s.ret10,s.daily_attack_stage,s.live_attack_score,s.live_attack_tier,s.live_attack_stage,s.attack_watch_candidate?'是':'否',s.live_attack_status].map(cell).join(',');});
  lines[0]+=',全体强度名次,趋势池名次,趋势池分位,关注层级,行业归属来源,历史报价口径差异百分点,历史报价口径状态,扫描转换核验,当前强势未通过项';
  res.forEach(function(s,i){lines[i+1]+=','+[(s.theme_relations||[]).map(function(t){return t.name;}).join('、'),(s.theme_relations||[]).map(function(t){return t.name+':'+t.state;}).join('；'),(s.theme_relations||[]).map(function(t){return t.name+' '+t.peers+'只';}).join('；'),s.theme_basis,s.stock_strength_rank,s.trend_pool_rank,s.trend_pool_percentile,s.trend_tier,s.industry_basis,s.intraday_price_basis_gap_pct,s.intraday_price_basis_status,s.intraday_transition_state,(s.current_strong_missing||[]).join('；')].map(cell).join(',');});
  res.forEach(function(s,i){lines[i+1]+=','+[
    quoteFreshAtClientNow(s)?'报价有效':quoteStatusAtClientNow(s),
    currentCandidateActive(s,'current_strong_candidate')?'是':'否',
    currentCandidateActive(s,'current_pullback_candidate')?'是':'否',
    currentCandidateActive(s,'startup_candidate')?'是':'否',
    currentCandidateActive(s,'turn_weak_repair_candidate')?'是':'否'
  ].map(cell).join(',');});
  lines[0]+=',最近完成日日期,最近完成日收盘价,最近完成日涨跌幅%,页面展示口径,页面展示时间,页面展示价格,页面展示涨跌幅%';
  res.forEach(function(s,i){
    var bridge=afternoonBridgeQuote(s);
    var openBridge=morningOpenBridgeQuote(s),auction=auctionDisplayQuote(s);
    var shown=useCompletedClose()?closeDisplayQuote(s):lunchDisplayQuote(s)||bridge||openBridge||auction;
    lines[i+1]+=','+[s.last_completed_date,s.last_completed_close,s.last_completed_change_pct,
      bridge?'午后报价待更新·11:30参考':openBridge?'开盘报价待更新·'+openBridge.kind:shown?shown.kind:'当日报价',shown?shown.at:s.intraday_quote_at,
      shown?shown.price:s.price,shown?shown.change:s.change_pct].map(cell).join(',');
  });
  var blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download='强势观察_'+((DATA.strength_model||{}).asof||'')+'.csv';a.click();toast('已导出 '+res.length+' 条');
}

/* ── 个股详情 ── */
function drawTrend(cv,arr){
  var dpr=window.devicePixelRatio||1, w=cv.clientWidth||560, h=cv.clientHeight||180;
  cv.width=w*dpr; cv.height=h*dpr;
  var g=cv.getContext('2d'); g.scale(dpr,dpr); g.clearRect(0,0,w,h);
  if(!arr||arr.length<5)return;
  var m5=ma(arr,5), m10=ma(arr,10), m20=ma(arr,20);
  var pool=arr.slice();
  m5.forEach(function(v){if(v!=null)pool.push(v);});
  m10.forEach(function(v){if(v!=null)pool.push(v);});
  m20.forEach(function(v){if(v!=null)pool.push(v);});
  var mn=Math.min.apply(null,pool), mx=Math.max.apply(null,pool);
  if(mx===mn){mx+=.01;mn-=.01;}
  var pad=14, X=function(i){return pad+i*(w-pad*2)/(arr.length-1);},
      Y=function(v){return h-pad-(v-mn)/(mx-mn)*(h-pad*2);};
  var up=n(arr[arr.length-1])>=n(arr[0]);
  var grd=g.createLinearGradient(0,0,0,h);
  grd.addColorStop(0,up?'rgba(232,39,26,.24)':'rgba(18,164,92,.22)');
  grd.addColorStop(1,'rgba(0,0,0,0)');
  g.beginPath(); g.moveTo(X(0),Y(arr[0]));
  arr.forEach(function(v,i){g.lineTo(X(i),Y(v));});
  g.lineTo(X(arr.length-1),h); g.lineTo(X(0),h); g.closePath();
  g.fillStyle=grd; g.fill();
  function line(a,color,width){
    g.beginPath(); g.strokeStyle=color; g.lineWidth=width; g.lineJoin='round';
    var started=false;
    a.forEach(function(v,i){ if(v==null)return;
      if(!started){g.moveTo(X(i),Y(v));started=true;} else g.lineTo(X(i),Y(v)); });
    g.stroke();
  }
  line(m20,'rgba(0,113,227,.75)',1.3);
  line(m10,'rgba(110,75,190,.85)',1.3);
  line(m5,'rgba(240,140,0,.85)',1.3);
  line(arr,up?'#e8271a':'#12a45c',1.9);
  g.beginPath(); g.arc(X(arr.length-1),Y(arr[arr.length-1]),3.4,0,7);
  g.fillStyle=up?'#e8271a':'#12a45c'; g.fill();
  g.font='10px -apple-system,sans-serif'; g.textAlign='left';
  g.fillStyle='rgba(0,0,0,.24)';
  g.fillText(fmt(mx),4,11); g.fillText(fmt(mn),4,h-4);
  g.textAlign='right';
  g.fillStyle='rgba(240,140,0,.9)'; g.fillText('MA5',w-105,11);
  g.fillStyle='rgba(110,75,190,.9)'; g.fillText('MA10',w-55,11);
  g.fillStyle='rgba(0,113,227,.9)'; g.fillText('MA20',w-4,11);
}
function ma(arr,w){
  var out=[]; for(var i=0;i<arr.length;i++){
    if(i<w-1){out.push(null);continue;}
    var s=0; for(var j=i-w+1;j<=i;j++)s+=arr[j];
    out.push(s/w);} return out;
}
function showEmotionOnly(code){
  if((DATA.coverage_catalog||[]).some(function(x){return x.code===code;}))return showCoverageStock(code);
  var s=(DATA.emotion_candidates||[]).filter(function(x){return x.code===code;})[0];
  if(!s)return toast('未找到 '+code);
  var h='<div class="grid g2">'
    +'<div class="metric"><div class="lbl">今日涨跌</div><div class="val">'+pct(s.change_pct,1)
    +'</div><div class="sub">报价 '+fmt(s.price,2)+'</div></div>'
    +'<div class="metric"><div class="lbl">情绪热度 / 承接</div><div class="val" style="font-size:19px">'
    +esc(s.emotion_heat)+'</div><div class="sub">'+esc(s.emotion_acceptance)+' · '+esc(s.emotion_risk||'数据不足')+'</div></div></div>'
    +'<div class="card" style="margin-top:16px"><h3>观察依据</h3>'
    +'<p>所属行业：'+esc(s.primary_industry||'未知')+'；昨日涨停：'+(s.emotion_yesterday_limit?'是':'否')
    +'；'+(s.emotion_provisional?'当前':'收盘')+'涨停：'+(s.emotion_limit?'是':'否')+'。</p>'
    +'<p>其他同行的情绪活跃占比：'+(s.emotion_peer_active_pct==null?'数据不足':fmt(s.emotion_peer_active_pct,1)+'%')
    +'；触板未封只说明当日最高价触及而'+(s.emotion_provisional?'当前':'收盘')+'未封，不能推断开板次数。</p>'
    +(s.emotion_provisional?'<p class="flat">情绪证据来自盘中报价，收盘前可能变化。</p>':'')
    +'<p class="flat">该股未通过主榜的数据完整性或当日成交检查；具体原因与可核验的趋势状态见全池覆盖详情。</p></div>';
  openDrawer(esc(s.name)+' '+esc(s.code),'主榜外情绪候选 · 完成日线趋势未核验',h);
}
function stockAffiliationSub(s){
  var concepts=displayBoards(s).filter(Boolean), shown=concepts.slice(0,3);
  var html='<span class="detail-affiliation-label">所属行业概念</span>'
    +'<span class="detail-affiliation-tag industry" title="所属行业：'+esc(s.primary_industry||'待核对')+'">行业 · '+esc(s.primary_industry||'待核对')+'</span>';
  if(shown.length)html+=shown.map(function(name,i){return '<span class="detail-affiliation-tag" title="同花顺概念：'+esc(name)+'">'+(i===0?'概念 · ':'')+esc(name)+'</span>';}).join('');
  else html+='<span class="detail-affiliation-tag">概念待核对</span>';
  if(concepts.length>shown.length)html+='<span class="detail-affiliation-tag" title="全部概念：'+esc(concepts.join('、'))+'">另有 '+(concepts.length-shown.length)+' 项</span>';
  return html;
}
function detailCardLabel(label,explanation){
  return '<small class="detail-card-label"><span>'+esc(label)+'</span><span class="detail-help" tabindex="0" role="img" aria-label="'+esc(label)+'说明：'+esc(explanation)+'" title="'+esc(explanation)+'">?</span></small>';
}
function showCoverageStock(code){
  var s=(DATA.coverage_catalog||[]).filter(function(x){return x.code===code;})[0];
  if(!s)return toast('未找到 '+code);
  var e=(DATA.emotion_candidates||[]).filter(function(x){return x.code===code;})[0];
  var fresh=quoteFreshAtClientNow(s);
  var completed=useCompletedClose();
  var lunch=lunchDisplayQuote(s);
  var bridge=afternoonBridgeQuote(s);
  var openBridge=morningOpenBridgeQuote(s);
  var closing=completed?closeDisplayQuote(s):null;
  var auction=auctionDisplayQuote(s);
  var price=completed?(closing&&closing.price):lunch?lunch.price:fresh?s.price:bridge?bridge.price:openBridge?openBridge.price:auction?auction.price:s.price;
  var change=completed?(closing&&closing.change):lunch?lunch.change:fresh?s.change_pct:bridge?bridge.change:openBridge?openBridge.change:auction?auction.change:null;
  var quoteAt=completed?(closing&&closing.at):lunch?lunch.at:bridge?bridge.at:openBridge?openBridge.at:auction?auction.at:s.intraday_quote_at;
  var h='<div class="detail-hero"><div class="detail-eyebrow">全池个股 · '+esc(s.daily_strength_status||'日线强度待评分')+'</div>'
    +'<div class="detail-hero-main"><div><div class="detail-price">'+(price==null?'—':fmt(price,2))+'</div>'
    +'<div class="detail-live">'+(completed?(closing?closing.kind:'收盘待核对')+' ':lunch?'午间参考价 ':bridge?'午后报价待更新 · 11:30参考 ':openBridge?'开盘报价待更新 · '+esc(openBridge.kind)+' ':auction?esc(auction.kind)+' ':'逐股报价 ')+esc(quoteAt||'日期待核对')
    +(lunch?' · 源刷新 '+esc(lunch.sourceAt.slice(11,16))+' · 盘中观察截至 '+esc((s.last_valid_quote_at||'').slice(11,16))
      :bridge?' · 上午观察截至 '+esc((s.last_valid_quote_at||'').slice(11,16))
      :openBridge?' · 正式盘中观察待更新'
      :completed?(closing&&closing.sourceAt?' · 源刷新 '+esc(closing.sourceAt.slice(11,16)):''):' · 扫描完成 '+esc(DATA.scan_completed_at||DATA.generated_at||'—')+' · '+esc(s.intraday_quote_status||'报价待核验'))+'</div></div>'
    +'<div class="detail-pills"><span class="detail-pill '+(s.trend_online?'good':'')+'">'
    +(s.trend_online==null?'趋势待核验':s.trend_online?'趋势在线':'趋势未在线')+'</span>'
    +'<span class="detail-pill">'+esc(s.reason_text)+'</span></div></div>'
    +'<div class="detail-return-grid">'
    +'<div class="detail-return"><span>'+(completed?'上次盘中观察分':lunch||bridge?'上午盘中分 · 留存':'盘中强度 · 观察分')+'</span><b>'+((auction||openBridge)&&!completed?'竞价阶段不评分':s.intraday_score==null?'待评分':fmt(s.intraday_score,1)+(s.intraday_score_stale||completed||lunch||bridge?' · 留存':''))+'</b></div>'
    +'<div class="detail-return"><span>'+(completed?(closing&&closing.kind==='收盘报价截至15:00'?'收盘报价涨幅 · 待日线确认':'最近完成日涨幅'):lunch?'上午收市涨幅':bridge?'11:30参考涨幅':openBridge?'竞价参考涨幅':auction?'竞价涨幅':fresh?'当日涨幅 · 暂态':'当日涨幅 · 报价过期')+'</span><b class="'+(change!=null?cls(change):'flat')+'">'+(change!=null?pct(change,1):completed?'收盘涨幅未知':'报价不可判断')+'</b></div>'
    +'<div class="detail-return"><span>近5日 · 完成日线</span><b class="'+cls(s.ret5)+'">'+(s.ret5==null?'—':pct(s.ret5,1))+'</b></div>'
    +'<div class="detail-return"><span>近20日 · 完成日线</span><b class="'+cls(s.ret20)+'">'+(s.ret20==null?'—':pct(s.ret20,1))+'</b></div></div></div>';
  h+='<div class="detail-main-grid"><div class="detail-panel"><div class="detail-panel-title">近60日走势</div>'
    +'<div class="detail-panel-sub">现有有效收盘价 · 不插补缺失交易日</div>'
    +(s.k?'<canvas class="chart detail-chart" id="k-cv"></canvas>':'<div class="detail-chart flat">走势数据不足</div>')+'</div>'
    +'<div class="detail-panel"><div class="detail-panel-title">为什么暂未评分</div>'
    +'<div class="detail-score-head"><div class="detail-ring" style="--meter:0"><div class="detail-ring-inner">—</div></div>'
    +'<div class="detail-score-copy"><b>'+esc(s.reason_text)+'</b><span>趋势核验：'+esc(s.trend_basis||'完成日线不足')
    +'<br>完成日线判断日 '+esc(s.signal_date||'—')+'</span></div></div>'
    +'<p class="flat">可用日线足够时单独判断均线趋势；完整强度与雷达分位在数据齐备前保持未知。</p></div></div>';
  h+='<div class="detail-state-grid">'
    +[['日线MA10固定',s.ma10==null?'—':fmt(s.ma10,2)],['盘中MA10暂态',s.intraday_ma10==null?'—':fmt(s.intraday_ma10,2)],
      ['日线MA20固定',s.ma20==null?'—':fmt(s.ma20,2)],['盘中状态',esc(currentCandidateQuoteUsable(s)?(s.intraday_observation_state||'待核验'):quoteStatusAtClientNow(s))]]
      .map(function(x){return '<div class="detail-state"><small>'+x[0]+'</small><b>'+x[1]+'</b></div>';}).join('')+'</div>';
  h+='<details class="detail-fold"><summary>查看数据缺口与趋势依据</summary><div class="detail-fold-body">'
    +'<p><b>数据状态</b>　'+esc(s.reason_text)+'；没有用前一日价格填补缺失交易日。</p>'
    +(s.trend_online==null?'':'<p><b>均线依据</b>　MA5 '+fmt(s.ma5,2)+'、MA10 '+fmt(s.ma10,2)
      +'、MA20 '+fmt(s.ma20,2)+'；MA20 前日 '+fmt(s.ma20_prev,2)+'，完成日收盘 '+fmt(s.signal_close,2)+'。</p>')
    +(e?'<p><b>盘中情绪</b>　'+esc(e.emotion_heat||'待观察')+' · '+esc(e.emotion_acceptance||'承接待观察')+'</p>':'')
    +'<p><b>当日资金净额</b>　'+(s.fund_today_yi==null?'未知':sgn(s.fund_today_yi,3)+'亿元')
    +' · '+esc(s.fund_today_source||'来源未知')+' · 采集 '+esc(s.fund_today_at||'时间未知')
    +'；多日资金 '+esc(s.fund_state||'未知')+'</p>'
    +'<p><b>盘中趋势/风险</b>　'+esc(s.intraday_trend_state||'数据不可判断')+' · '
    +esc((s.intraday_risk_flags||[]).join('；')||s.intraday_quote_status||'无显著风险')+'</p>'
    +'<p class="flat">完成日MA10/MA20为固定参考；盘中MA以现价替换最近一个完成日收盘。缺少强度评分不代表个股转弱。</p></div></details>';
  openDrawer(esc(s.name)+' '+esc(s.code),stockAffiliationSub(s),h,true);
  var paint=function(){var cv=document.getElementById('k-cv');if(cv&&s.k)drawTrend(cv,s.k);};
  paint();requestAnimationFrame(paint);
}
function drawRadar(cv,vals,labels){
  var dpr=window.devicePixelRatio||1, w=cv.clientWidth||300, h=250;
  cv.width=w*dpr; cv.height=h*dpr;
  var g=cv.getContext('2d'); g.scale(dpr,dpr); g.clearRect(0,0,w,h);
  var cx=w/2, cy=h/2+4, R=Math.min(w,h)/2-34, N=labels.length;
  function pt(i,r){var a=-Math.PI/2+i*2*Math.PI/N;return [cx+Math.cos(a)*r,cy+Math.sin(a)*r];}
  for(var ring=1;ring<=4;ring++){
    g.beginPath();
    for(var i=0;i<N;i++){var p=pt(i,R*ring/4); i?g.lineTo(p[0],p[1]):g.moveTo(p[0],p[1]);}
    g.closePath(); g.strokeStyle='rgba(0,0,0,.1)'; g.lineWidth=1; g.stroke();
  }
  for(var i=0;i<N;i++){
    var p=pt(i,R); g.beginPath(); g.moveTo(cx,cy); g.lineTo(p[0],p[1]);
    g.strokeStyle='rgba(0,0,0,.05)'; g.stroke();
  }
  g.beginPath();
  for(var i=0;i<N;i++){var v=Math.max(4,Math.min(100,n(vals[i]))), p=pt(i,R*v/100);
    i?g.lineTo(p[0],p[1]):g.moveTo(p[0],p[1]);}
  g.closePath(); g.fillStyle='rgba(0,113,227,.22)'; g.fill();
  g.strokeStyle='#0071e3'; g.lineWidth=1.8; g.stroke();
  for(var i=0;i<N;i++){var v=Math.max(4,Math.min(100,n(vals[i]))), p=pt(i,R*v/100);
    g.beginPath(); g.arc(p[0],p[1],3,0,7); g.fillStyle='#0071e3'; g.fill();}
  g.font='11px -apple-system,sans-serif'; g.textAlign='center'; g.textBaseline='middle';
  for(var i=0;i<N;i++){
    var p=pt(i,R+19), v=Math.round(n(vals[i]));
    g.fillStyle='rgba(0,0,0,.55)'; g.fillText(labels[i],p[0],p[1]-6);
    g.fillStyle=scoreColor(v); g.fillText(String(v),p[0],p[1]+7);
  }
}

function renderAttackMonitor(lookup){
  var board=DATA.attack_monitor||{},rows=board.rows||[];
  var normal=['早盘','午盘','尾盘'].indexOf(sessionNow())>=0;
  var current=rows.filter(function(s){return normal&&workQuoteCurrent(s.intraday_quote_at);});
  document.getElementById('work-attack-count').textContent='当前有效 '+current.length+' / 本轮观察 '+rows.length+' 只';
  document.getElementById('work-attack-list').innerHTML=rows.map(function(s){
    var usable=current.indexOf(s)>=0,risk=(s.intraday_risk_flags||[]).slice();
    if(s.intraday_trade_restriction&&risk.indexOf(s.intraday_trade_restriction)<0)risk.push(s.intraday_trade_restriction);
    if(s.intraday_risk_level==='待核验')risk.push('风险仍有待核验项');
    return '<button type="button" class="work-observation" onclick="showStock(\''+jsq(s.code)+'\')">'
      +'<span class="work-observation-top"><span class="work-observation-name">'+esc(s.name)
      +'<span class="work-observation-code">'+esc(s.code)+'</span></span><span class="work-observation-change '+(usable?cls(s.change_pct):'flat')+'">'
      +(usable?pct(s.change_pct,1):'历史参考')+'</span></span>'+workProfileTags(s.code,lookup)
      +'<span class="work-observation-bottom"><span>'+(usable?'暂态A · ':'报价已过期 · ')+esc(s.live_attack_stage)
      +' · '+esc((s.intraday_quote_at||'').slice(11,16))+' · 日线'+esc(s.trend_tier||'未在线')
      +'</span><span class="work-observation-metric">进攻分 '+fmt(s.live_attack_score,1)+'</span></span>'
      +'<span class="work-observation-bottom"><span>'+esc(risk.length?'风险：'+risk.join('；'):'本轮未触发既定风险提示')+'</span></span></button>';
  }).join('')||'<div class="work-observation-empty">'+(normal?'当前没有通过进攻监测条件的股票':'当前阶段未产生新的盘中候选；日线进攻档位见个股榜')+'</div>';
}

function showStock(code,boardId){
  var s=(DATA.stocks||[]).filter(function(x){return x.code===code;})[0];
  if(!s)return showCoverageStock(code);
  var parts=s.stock_strength_parts||{}, evidence=s.stock_strength_evidence||{};
  var selected=(DATA.board_catalog||[]).filter(function(b){return b.id===boardId;})[0];
  var selectedRel=selected&&(selected.members||[]).filter(function(r){return r.code===code;})[0];
  var labels={attack5:'5日攻击速度 · 50%',attack10:'10日推进 · 30%',attack20:'20日涨幅基础 · 20%'};
  var currentStrongActive=currentCandidateActive(s,'current_strong_candidate');
  var factorBars=Object.keys(labels).map(function(k){
    var v=parts[k], width=Math.max(0,Math.min(100,n(v)));
    return '<div class="detail-factor"><div class="detail-factor-label"><span>'+labels[k]+'</span><b>'+fmt(v,0)+'</b></div>'
      +'<div class="detail-factor-track"><div class="detail-factor-fill" style="width:'+width+'%"></div></div></div>';
  }).join('');
  var score=Math.max(0,Math.min(100,n(s.stock_strength_percentile)));
  var fresh=quoteFreshAtClientNow(s);
  var completed=useCompletedClose();
  var lunch=lunchDisplayQuote(s);
  var bridge=afternoonBridgeQuote(s);
  var openBridge=morningOpenBridgeQuote(s);
  var closing=completed?closeDisplayQuote(s):null;
  var auction=auctionDisplayQuote(s);
  var change=completed?(closing&&closing.change!=null?pct(closing.change,1):'收盘涨幅未知'):
    lunch?pct(lunch.change,1):
    fresh&&s.change_pct!=null?pct(s.change_pct,1):
    bridge?pct(bridge.change,1):
    openBridge?pct(openBridge.change,1):auction&&auction.change!=null?pct(auction.change,1):'报价不可判断';
  var shownPrice=completed?(closing&&closing.price):lunch?lunch.price:fresh?s.price:bridge?bridge.price:openBridge?openBridge.price:auction?auction.price:(s.last_valid_price||s.price);
  var h='<div class="detail-hero"><div class="detail-eyebrow">日线进攻强度 · 判断日 '+esc(s.signal_date||'—')+'</div>'
    +'<div class="detail-hero-main"><div><div class="detail-price">'+(shownPrice==null?'—':fmt(shownPrice,2))+'</div>'
    +'<div class="detail-live">'+(completed?esc(closing?closing.kind:'收盘待核对')+' '+esc(closing&&closing.at||'日期待核对')
        +(closing&&closing.sourceAt?' · 源刷新 '+esc(closing.sourceAt.slice(11,16)):''):
      lunch?esc(lunch.kind)+' · 源刷新 '+esc(lunch.sourceAt.slice(11,16))
        +' · 盘中观察截至 '+esc((s.last_valid_quote_at||'').slice(11,16)):
      bridge?'午后报价待更新 · 暂显11:30参考价 · 上午观察截至 '+esc((s.last_valid_quote_at||'').slice(11,16)):
      openBridge?'开盘报价待更新 · 暂显'+esc(openBridge.kind)+' · 源 '+esc(openBridge.sourceAt.slice(11,16)):
      (auction?esc(auction.kind):'逐股')+'报价 '+esc(auction?auction.at:s.intraday_quote_at||s.last_valid_quote_at||'—')
      +' · 扫描完成 '+esc(DATA.scan_completed_at||DATA.generated_at||'—')
      +(fresh?'':' · '+esc(s.intraday_quote_status||'报价已过期')))+'</div></div>'
    +'<div class="detail-pills"><span class="detail-pill '+(s.trend_online?'good':'')+'">'
    +(s.trend_tier?esc(s.trend_tier+' · '+s.trend_tier_name):'趋势未在线')+'</span>'
    +'<span class="detail-pill">'+(completed?'上次盘中观察 · ':lunch||bridge?'上午观察 · ':'')
    +esc((lunch||bridge?s.last_valid_intraday_trend_state:s.intraday_trend_state)||'盘中状态待核验')+'</span>'
    +'<span class="detail-pill">'+(fresh?'盘中暂态进攻 ':'历史进攻参考 ')+esc(s.live_attack_tier||'待核验')+' · '+esc(s.live_attack_stage||'待核验')+'</span>'
    +'<span class="detail-pill">日线近期变化 '+esc(s.daily_motion||s.stock_strength_motion||'待观察')+'</span></div></div>'
    +'<div class="detail-return-grid">'
    +'<div class="detail-return"><span>'+(completed?(closing&&closing.kind==='收盘报价截至15:00'?'收盘报价涨幅 · 待日线确认':'最近完成日涨幅'):lunch?'上午收市涨幅':bridge?'11:30参考涨幅':openBridge?'竞价参考涨幅':auction?'竞价涨幅':fresh?'当日涨幅 · 暂态':'当日涨幅 · 报价过期')+'</span><b class="'+(completed?(closing&&closing.change!=null?cls(closing.change):'flat'):lunch?cls(lunch.change):bridge?cls(bridge.change):openBridge?cls(openBridge.change):auction?cls(auction.change):fresh?cls(s.change_pct):'flat')+'">'+change+'</b></div>'
    +'<div class="detail-return"><span>'+(completed?'上次盘中观察分':lunch||bridge?'上午盘中分 · 留存':'盘中强度 · 观察分')+'</span><b>'+ ((auction||openBridge)&&!completed?'竞价阶段不评分':s.intraday_score==null?'待评分':fmt(s.intraday_score,1)+(s.intraday_score_stale||completed||lunch||bridge?' · 留存':'')) +'</b></div>'
    +'<div class="detail-return"><span>近5日 · 完成日线</span><b class="'+cls(s.ret5)+'">'+pct(s.ret5,1)+'</b></div>'
    +'<div class="detail-return"><span>近20日 · 完成日线</span><b class="'+cls(s.ret20)+'">'+pct(s.ret20,1)+'</b></div></div></div>';
  h+='<div class="detail-main-grid">'
    +'<div class="detail-panel"><div class="detail-panel-title">近60日走势</div>'
    +'<div class="detail-panel-sub">收盘价与 MA5 / MA10 / MA20 · 截至 '+esc(s.signal_date||'—')+'</div>'
    +(s.k?'<canvas class="chart detail-chart" id="k-cv"></canvas>':'<div class="detail-chart flat">走势数据待补齐</div>')+'</div>'
    +'<div class="detail-panel"><div class="detail-panel-title">日线进攻强度 · 三个周期</div>'
    +'<div class="detail-score-head"><div class="detail-ring" style="--meter:'+score+'"><div class="detail-ring-inner">'+fmt(score,0)+'</div></div>'
    +'<div class="detail-score-copy"><b>全体强度分位</b><span>全体第 '+n(s.stock_strength_rank)+' / '+n(s.stock_strength_reference_count)+' 名'
    +(s.trend_pool_rank?' · 趋势池第 '+n(s.trend_pool_rank)+' 名（分位 '+fmt(s.trend_pool_percentile,1)+'）':'')
    +'<br>日线进攻 '+fmt(s.stock_strength_score,1)+' 分<br>5/10/20日权重50/30/20；每项60%绝对推进+40%相对速度</span></div></div>'
    +factorBars+'<p class="flat">日线形态：'+esc(s.daily_attack_stage||'待核验')+'。风险不参与进攻计分。</p></div></div>';
  var liveAttackFresh=fresh&&['早盘','午盘','尾盘'].indexOf(sessionNow())>=0&&s.intraday_price_basis_comparable===true;
  h+='<div class="detail-panel" style="margin:12px 0 18px"><div class="detail-panel-title">盘中进攻与再启动</div>'
    +'<div class="detail-stat-grid"><div class="detail-stat"><small>'+(liveAttackFresh?'暂态进攻档位':'历史参考 · 当前未判断')+'</small><b>'
    +esc(s.live_attack_tier||'未在线')+' · '+fmt(s.live_attack_score,1)+'分</b></div>'
    +'<div class="detail-stat"><small>现价形态 · 待收盘确认</small><b>'+esc(s.live_attack_stage||'待核验')+'</b></div>'
    +'<div class="detail-stat"><small>报价日前20日高点 · 报价尺度</small><b>'
    +(liveAttackFresh&&s.live_attack_pattern?fmt(s.live_attack_pattern.high20,2):'待核验')+'</b></div></div>'
    +'<p class="flat">'+esc(liveAttackFresh?s.live_attack_status:'旧观察不能作为当前信号')+'；风险：'
    +esc((s.intraday_risk_flags||[]).join('；')||'本轮未触发既定风险提示')+'</p></div>';
  h+='<div class="detail-state-grid">'
    +'<div class="detail-state" title="完成日线的 MA5、MA10、MA20 排列和 MA20 方向；与盘中暂态趋势分开判断。">'+detailCardLabel('趋势结构','用完成日线核对 MA5、MA10、MA20 的排列与 MA20 方向；盘中变化另行判断。')+'<b>'+(s.trend_online?'三线多头':'尚未在线')+'</b><em>MA20 '+(s.ma20>s.ma20_prev?'向上':'未上行')+'</em></div>'
    +'<div class="detail-state" title="历史回踩形态基于完成日线；盘中跌破及收盘是否站回需要分开观察。">'+detailCardLabel('回踩状态','历史回踩形态基于完成日线；盘中跌破及收盘是否站回需要分开观察。')+'<b>'+esc(s.touch_state||'数据不足')+'</b><em>盘中可跌破，收盘站回才算守住</em></div>'
    +'<div class="detail-state" title="展示涨停、回封和价格承接等观察事实；不等于资金流入或后续上涨保证。">'+detailCardLabel('情绪 / 承接','展示涨停、回封和价格承接等观察事实；不等于资金流入或后续上涨保证。')+'<b>'+esc(s.emotion_heat||'数据不足')+'</b><em>'+esc(s.emotion_acceptance||'承接待观察')+'</em></div>'
    +'<div class="detail-state" title="展示所属板块及同行关系；同行比较剔除本股，板块表现不能抵消个股风险。">'+detailCardLabel('板块关系','展示所属板块及同行关系；同行比较剔除本股，板块表现不能抵消个股风险。')+'<b>'+esc(selected?selected.name:(s.industry_trend_state||'按板块查看'))+'</b><em>'
    +esc(selectedRel?(selectedRel.role+' · '+selected.trend_state):'从板块中心进入可查看对应关系')+'</em></div></div>';
  if(selectedRel){
    var selectedTheme=(s.theme_relations||[]).filter(function(r){return r.id===boardId;})[0];
    h+='<div class="detail-panel" style="margin:12px 0 18px"><div class="detail-panel-title">'+esc(selected.name)+' · 本股在该板块</div>'
      +'<div class="detail-stat-grid">'
      +[['板块内强度',selectedRel.rank+' / '+selected.valid_members],['全体强度',selectedRel.global_rank+' / '+n(s.stock_strength_reference_count)],
        ['5日对同伴',selectedRel.excess5==null?'同伴不足':sgn(selectedRel.excess5,1)+'点'],
        ['20日对同伴',selectedRel.excess20==null?'同伴不足':sgn(selectedRel.excess20,1)+'点']]
       .map(function(x){return '<div class="detail-stat"><small>'+x[0]+'</small><b>'+x[1]+'</b></div>';}).join('')+'</div>'
      +'<p class="flat" style="margin:12px 0 0">板块趋势 '+esc(selected.trend_state)+' · 今日活跃 '+fmt(selected.emotion_pct,1)+'%'
      +(selectedTheme?' · 题材助攻 '+esc(selectedTheme.state):'')+'。超额已剔除本股；共同走强不等于带动。</p></div>';
  }
  var basisPending=String(s.intraday_trend_state||'').indexOf('均线待核验')===0;
  var quoteScaleValue=function(value){return basisPending?'待核验':fmt(value,2);};
  h+='<div class="detail-stat-grid">'
    +[['报价日前完成日MA10',quoteScaleValue(s.daily_ma10_fixed||s.ma10),'报价日之前最近 10 个完成交易日收盘价，已换到当前报价尺度。'],
      ['盘中暂态MA10',quoteScaleValue(s.intraday_ma10),'报价日前最近 9 个完成交易日收盘价加当前价；已统一到当前报价尺度。'],
      ['报价日前完成日MA20',quoteScaleValue(s.daily_ma20_fixed||s.ma20),'报价日之前最近 20 个完成交易日收盘价，已换到当前报价尺度。'],
      ['盘中暂态MA20',quoteScaleValue(s.intraday_ma20),'报价日前最近 19 个完成交易日收盘价加当前价；已统一到当前报价尺度。']]
      .map(function(x){return '<div class="detail-stat" title="'+esc(x[2])+'">'+detailCardLabel(x[0],x[2])+'<b>'+x[1]+'</b></div>';}).join('')+'</div>';
  var panelCurrent=fresh&&!auction&&s.intraday_quote_fresh===true;
  var panelRisks=s.intraday_risk_flags||[];
  var panelTrend=panelCurrent?(s.intraday_trend_state||'数据不足'):
    basisPending?'均线待核验':auction||openBridge?'竞价观察':s.intraday_close_confirmation?'收盘对照':'当前未知';
  var panelTrendNote=panelCurrent?(s.intraday_trend_failure||'均线结构满足暂态条件'):
    basisPending?String(s.intraday_trend_state||'').replace(/^均线待核验（/,'').replace(/）$/,''):
      (s.intraday_close_confirmation||s.intraday_quote_status||'等待有效报价');
  var panelRisk=panelCurrent?(panelRisks[0]||
    (s.intraday_risk_level==='待核验'?'待核验（均线或ATR口径未确认）':'未触发明显风险')):
    basisPending?'待核验（'+panelTrendNote+'，当前风险未确认）':'当前未知';
  var panelCandidate=panelCurrent?(s.intraday_observation_state||'观察'):'暂不判断';
  var maTimeNotes=[5,10,20].map(function(period){
    var note=s['intraday_ma'+period+'_minute_note'];
    if(!panelCurrent)return 'MA'+period+'：当前报价无效，分钟记录不作为当前判断';
    if(note)return 'MA'+period+'：'+note;
    var holds=s['intraday_ma'+period+'_current_holds'];
    return 'MA'+period+'：'+(holds===true?'现价守住触线价':holds===false?'现价低于触线价':'当前关系待核验')
      +'；分钟记录待核验';
  }).join('；');
  var observationNotes={'当前强势':'历史强势延续，方向、评分与风险条件均通过',
    '初步转强，待收盘确认':'趋势与价格方向通过，盘中分达标；待收盘确认',
    '盘中修复':'开盘后回升，但仍下跌或落后主板',
    '活跃观察':'盘中价格活跃，尚未满足强势或初步转强资格'};
  var panelCandidateNote=panelCurrent?(observationNotes[panelCandidate]||
    ((s.current_strong_missing||[])[0]||'查看完整资格依据')):(s.intraday_quote_status||'等待有效报价');
  h+='<div class="detail-panel detail-verdict" style="margin:12px 0 18px">'
    +'<div class="detail-verdict-head"><div><div class="detail-panel-title">盘中判断</div>'
    +'<div class="detail-panel-sub">先看趋势、资格与风险；详细计算依据可展开</div></div>'
    +'<span class="detail-verdict-time">'+esc(s.last_valid_quote_at||s.intraday_quote_at||'暂无有效报价')+'</span></div>'
    +'<div class="detail-verdict-grid">'
    +'<div class="detail-verdict-item"><small>暂态趋势</small><b>'+esc(panelTrend)+'</b><em>'+esc(panelTrendNote)+'</em></div>'
    +'<div class="detail-verdict-item '+(panelCurrent?(currentStrongActive?'good':'muted'):'muted')+'"><small>盘中观察状态</small><b>'+esc(panelCandidate)+'</b><em>'+esc(panelCandidateNote)+'</em></div>'
    +'<div class="detail-verdict-item '+(panelCurrent&&panelRisks.length?'warn':'muted')+'"><small>风险</small><b>'+esc(panelRisk)+'</b><em>'+(panelCurrent&&panelRisks.length>1?'另有 '+(panelRisks.length-1)+' 项风险':'报价状态 · '+esc(s.intraday_quote_status||'未知'))+'</em></div></div>'
    +'<div class="detail-metric-grid">'
    +'<div class="detail-metric"><small>跑赢主板等权</small><b class="'+(panelCurrent?cls(s.intraday_relative_return_pct):'flat')+'">'+(panelCurrent&&s.intraday_relative_return_pct!=null?sgn(s.intraday_relative_return_pct,2)+' 点':'—')+'</b></div>'
    +'<div class="detail-metric"><small>开盘后涨幅</small><b class="'+(panelCurrent?cls(s.intraday_open_return_pct):'flat')+'">'+(panelCurrent&&s.intraday_open_return_pct!=null?pct(s.intraday_open_return_pct,2):'—')+'</b></div>'
    +'<div class="detail-metric"><small>日内位置</small><b>'+(panelCurrent?(s.intraday_position_pct==null?esc(s.intraday_position_status||'不适用'):fmt(s.intraday_position_pct,1)+'%'):'—')+'</b></div>'
    +'<div class="detail-metric"><small>距暂态MA10</small><b>'+(panelCurrent&&s.intraday_distance_ma10_pct!=null?sgn(s.intraday_distance_ma10_pct,2)+'% · '+(s.intraday_distance_ma10_atr==null?'ATR待核验':fmt(s.intraday_distance_ma10_atr,2)+' ATR'):'待核验')+'</b></div>'
    +'<div class="detail-metric"><small>相对评分变化</small><b>'+(panelCurrent?(s.intraday_score_delta==null?esc(s.intraday_delta_state||'无可比扫描'):sgn(s.intraday_score_delta,2)+' 分'):'—')+'</b></div></div>'
    +((panelCurrent||basisPending)?'<div class="detail-transition-note"><b>MA5/10/20当前与分钟时间关系</b>　'+esc(maTimeNotes)+'</div>':'')
    +(panelCurrent&&s.intraday_transition&&!/未观察|无转换/.test(s.intraday_transition)?'<div class="detail-transition-note">扫描观察 · '+esc(s.intraday_transition)+' · '+esc(s.intraday_transition_state||'待核验')+'</div>':'')
    +'<details class="detail-fold"><summary>查看完整核验依据</summary><div class="detail-fold-body">'
    +'<p><b>趋势依据</b>　'+esc(s.intraday_trend_state||'数据不足')+'；'+esc(s.intraday_trend_failure||'均线结构满足暂态条件')+'</p>'
    +'<p><b>报价与分数</b>　距日内高点 '+(s.intraday_drawdown_from_high_pct==null?'未知':pct(s.intraday_drawdown_from_high_pct,2))
    +'；相对评分变化 '+(s.intraday_score_delta==null?esc(s.intraday_delta_state||'无可比扫描'):sgn(s.intraday_score_delta,2)+' 分 · '+esc(s.intraday_delta_state||''))+'</p>'
    +'<p><b>同行表现</b>　行业同行当日 '+(s.industry_intraday_change_pct==null?'数据不足':pct(s.industry_intraday_change_pct,2))
    +'；本股对同行 '+(s.industry_intraday_excess_pct==null?'数据不足':sgn(s.industry_intraday_excess_pct,2)+' 点')
    +'；题材 '+esc(displayBoards(s).slice(0,3).join('、')||'未知')+'</p>'
    +'<p><b>风险与报价</b>　'+(s.intraday_quote_fresh===true?esc(panelRisks.join('；')||'未触发明显风险'):esc(s.intraday_quote_status||'数据不可判断'))
    +'；报价状态 '+esc(s.intraday_quote_status||'未知')+'</p>'
    +'<p><b>当前强势资格</b>　'+(currentStrongActive?'全部通过':
      (s.current_strong_candidate?'报价过期或当前非连续交易时段，已退出当前候选':
        esc((s.current_strong_missing||[]).join('；')||'未进入当前强势入口')))
    +'；初步转强资格：'+(currentCandidateActive(s,'startup_candidate')?'全部通过，待收盘确认':
      (s.startup_candidate?'报价过期或当前非连续交易时段，已退出当前候选':
        esc((s.startup_missing||[]).join('；')||'未进入初步转强候选')))+'；最后有效报价 '+
      esc(s.last_valid_quote_at||s.intraday_quote_at||'未知')
    +'；日线进攻强势：'+esc(s.persistent_strong?'全部通过，近期'+(s.stock_strength_motion||'待观察'):(s.persistent_missing||[]).join('；')||'未评分')
    +'；当前回踩：'+esc(currentCandidateActive(s,'current_pullback_candidate')?'全部通过':(s.current_pullback_candidate?'报价已过期或时段不适用':(s.current_pullback_missing||[]).join('；')||'未核验'))+'</p>'
    +'<p><b>扫描转换事实</b>　'+esc(s.intraday_transition||'本轮未观察到MA10收复或失守')
    +'；'+esc(s.intraday_transition_state||'首轮或无可比报价')+'</p>'
    +'<p><b>历史价格口径</b>　'+esc(s.intraday_price_basis_status||'待核验')
    +(s.intraday_price_basis_gap_pct==null?'':'；差异 '+pct(s.intraday_price_basis_gap_pct,2))
    +(s.intraday_price_basis_reason?'；原因 '+esc(s.intraday_price_basis_reason):'')
    +(s.intraday_price_basis_expected_date?'；应有完成日 '+esc(s.intraday_price_basis_expected_date):'')
    +(s.intraday_price_basis_reference_date?'；历史完成日 '+esc(s.intraday_price_basis_reference_date):'')
    +(s.intraday_price_basis_scale_factor==null?'':'；转换系数 '+fmt(s.intraday_price_basis_scale_factor,6))+'</p>'
    +'<p><b>ATR20完整窗口</b>　'+esc(s.intraday_atr20_status||'待核验')
    +(s.intraday_atr20_reason?'；原因 '+esc(s.intraday_atr20_reason):'')+'</p>'
    +(s.intraday_close_confirmation?'<p><b>盘中与收盘对照</b>　'+esc(s.intraday_close_confirmation)+'；盘中：'+esc(s.intraday_close_intraday_state||'—')+'</p>':'')
    +'<p class="flat">报价日前完成日均线是固定参考；盘中暂态MA5/10/20由已对齐的D日前最近4/9/19个完成日收盘价加当前价计算。均线、距离和ATR距离使用未舍入数值；分钟触线使用等价触线价格。收复或失守须有两轮有效且时间前进的报价，并分别与各轮MA10配对；第一轮不推断。</p>'
    +'</div></details></div>';
  h+='<details class="detail-fold detail-insight"><summary><span class="detail-insight-icon">◉</span>'
    +'<span class="detail-insight-head"><b>量价与风险</b><small>完成日线强弱、分位变化和风险依据</small>'
    +'<span class="detail-insight-peek"><span>较强 · '+esc(s.stock_strength_main_good||'待判断')+'</span>'
    +'<span>1日分位 '+(s.strength_delta1==null?'历史不足':sgn(s.strength_delta1,1)+' 点')+'</span>'
    +'<span>日线风险 '+((s.risk_notes||[]).length?((s.risk_notes||[]).length+' 项'):'未触发')+'</span></span></span></summary>'
    +'<div class="detail-fold-body detail-insight-body">'
    +'<div class="detail-insight-grid">'
    +'<div class="detail-insight-tile"><small>较强维度</small><b>'+esc(s.stock_strength_main_good||'待判断')+'</b></div>'
    +'<div class="detail-insight-tile"><small>较弱维度</small><b>'+esc(s.stock_strength_main_weak||'待判断')+'</b></div>'
    +'<div class="detail-insight-tile"><small>日线近期变化</small><b>'+esc(s.daily_motion||s.stock_strength_motion||'待观察')+'</b></div></div>'
    +(s.stock_strength_motion_basis?'<div class="detail-insight-note">'+esc(s.stock_strength_motion_basis)+'</div>':'')
    +'<div class="detail-insight-section"><h4>强度分位变化</h4><div class="detail-insight-grid">'
    +'<div class="detail-insight-tile"><small>较前一判断日</small><b>'+(s.strength_delta1==null?'历史不足':sgn(s.strength_delta1,1)+' 点')+'</b></div>'
    +'<div class="detail-insight-tile"><small>较前五个判断日</small><b>'+(s.strength_delta5==null?'历史不足':sgn(s.strength_delta5,1)+' 点')+'</b></div></div>'
    +'<div class="detail-insight-note">这里比较的是综合强度分位；上方收益率来自等长价格窗口，两者不能互相替代。</div></div>'
    +'<div class="detail-insight-section"><h4>三个周期进攻依据</h4>'
    +Object.keys(labels).map(function(k){return '<div class="detail-insight-factor"><b>'+labels[k]+'<em>'+(parts[k]==null?'—':fmt(parts[k],0))+'</em></b>'
      +'<span>'+esc(evidence[k]||'数据不足')+'</span></div>';}).join('')+'</div>'
    +'<div class="detail-insight-section"><h4>结构与量价 · 不计入进攻分</h4><p>'+esc(s.structure_evidence||'数据不足')+'</p></div>'
    +'<div class="detail-insight-section"><h4>风险提示</h4><div class="detail-insight-row"><strong>'+(s.risk_notes&&s.risk_notes.length?'需留意':'未触发')+'</strong>'
    +'<span>'+esc((s.risk_notes||[]).join('；')||'未触发既定阈值')+'</span></div></div>'
    +'<div class="detail-insight-note">日线强度分位来自完成日线；盘中分只比较价格表现。资金、题材数量和所属最强概念不计入，研究权重尚未经过样本外验证。</div>'
    +'</div></details>';
  var themeRelations=s.theme_relations||[];
  var themeItem=function(r){return '<div class="detail-insight-theme"><b>'+esc(r.name||'题材待核对')+'</b><span>'
    +esc(r.state||'状态待核对')+' · '+n(r.peers)+' 只有效同伴'+(r.wide?' · 宽题材':'')
    +(r.overlap_group&&r.overlap_group!==r.id?' · 与 '+esc(r.overlap_group.slice(6))+' 高度重叠':'')
    +(r.reason?' · '+esc(r.reason):'')+'</span></div>';};
  h+='<details class="detail-fold detail-insight"><summary><span class="detail-insight-icon market">◈</span>'
    +'<span class="detail-insight-head"><b>行业与题材</b><small>同行对比、概念环境与情绪观察</small>'
    +'<span class="detail-insight-peek"><span>行业 · '+esc(s.primary_industry||'待核对')+'</span>'
    +'<span>5日对同行 '+(s.ret5_ex_industry==null?'数据不足':sgn(s.ret5_ex_industry,1)+' 点')+'</span>'
    +'<span>概念 '+displayBoards(s).length+' 项</span></span></span></summary>'
    +'<div class="detail-fold-body detail-insight-body">'
    +'<div class="detail-insight-grid">'
    +'<div class="detail-insight-tile"><small>同行趋势在线</small><b>'+(s.industry_peer_trend_pct==null?'数据不足':pct(s.industry_peer_trend_pct,1))+'</b>'
    +'<em>较前日 '+(s.industry_peer_trend_delta_pp==null?'数据不足':sgn(s.industry_peer_trend_delta_pp,1)+' 个百分点')+'</em></div>'
    +'<div class="detail-insight-tile"><small>5日对同行</small><b>'+(s.ret5_ex_industry==null?'数据不足':sgn(s.ret5_ex_industry,1)+' 点')+'</b></div>'
    +'<div class="detail-insight-tile"><small>5日对主板</small><b>'+(s.ret5_ex_market==null?'数据不足':sgn(s.ret5_ex_market,1)+' 点')+'</b>'
    +'<em>20日对主板 '+(s.ret20_ex_market==null?'数据不足':sgn(s.ret20_ex_market,1)+' 点')+'</em></div></div>'
    +'<div class="detail-insight-section"><h4>行业关系</h4>'
    +'<div class="detail-insight-row"><strong>所属申万行业</strong><span>'+esc(s.primary_industry||'未知')+' · '+esc(s.industry_basis||'来源待核对')+'</span></div>'
    +'<div class="detail-insight-row"><strong>同行关系</strong><span>'+esc(s.industry_stock_relation||'关系待确认')+'；交易板别 '+esc(s.board_name||'未知')+'</span></div></div>'
    +'<div class="detail-insight-section"><h4>题材关系 · '+themeRelations.length+' 项分析</h4>'
    +'<div class="detail-insight-note" style="margin:0 0 10px">不自动挑选最有利方向。'+esc(s.theme_selection_reason||'')+'</div>'
    +(themeRelations.length?'<div class="detail-insight-theme-list">'+themeRelations.slice(0,4).map(themeItem).join('')+'</div>'
      +(themeRelations.length>4?'<details class="detail-insight-more"><summary>查看其余 '+(themeRelations.length-4)+' 项题材依据</summary>'
        +'<div class="detail-insight-theme-list">'+themeRelations.slice(4).map(themeItem).join('')+'</div></details>':'')
      :'<div class="detail-insight-row"><strong>题材分析</strong><span>暂无可比较的有效同伴</span></div>')+'</div>'
    +'<div class="detail-insight-section"><h4>情绪观察</h4><div class="detail-insight-grid">'
    +'<div class="detail-insight-tile"><small>情绪风险</small><b>'+esc(s.emotion_risk||'风险待观察')+'</b></div>'
    +'<div class="detail-insight-tile"><small>同行活跃</small><b>'+(s.emotion_peer_active_pct==null?'数据不足':pct(s.emotion_peer_active_pct,1))+'</b></div></div>'
    +(s.emotion_assist?'<div class="detail-insight-note">'+esc(s.emotion_assist)+'</div>':'')+'</div>'
    +'<div class="detail-insight-note">行业和题材只说明共同参与；同日走势不能证明谁带动谁，也不能抵消个股风险。</div>'
    +'</div></details>';
  var todayFundLabel=s.fund_today_source&&s.fund_today_source.indexOf('新浪')>=0?'当日超大单净额':'当日主力净额';
  h+='<details class="detail-fold detail-insight"><summary><span class="detail-insight-icon data">▤</span>'
    +'<span class="detail-insight-head"><b>资金与数据口径</b><small>当日与多日资金分开看，归属来源可核对</small>'
    +'<span class="detail-insight-peek"><span>今日 '+(s.fund_today_yi==null?'未知':sgn(s.fund_today_yi,3)+' 亿')+'</span>'
    +'<span>历史资金 · '+esc(s.fund_state||'未知')+'</span>'
    +'<span>已核对概念 '+displayBoards(s).length+' 项</span></span></span></summary>'
    +'<div class="detail-fold-body detail-insight-body">'
    +'<div class="detail-insight-funds">'
    +'<div class="detail-insight-fund"><small>'+todayFundLabel+'</small><b class="'+(s.fund_today_yi==null?'flat':cls(s.fund_today_yi))+'">'
    +(s.fund_today_yi==null?'未知':sgn(s.fund_today_yi,3)+' 亿元')+'</b>'
    +'<p>'+(s.fund_today_ratio==null?'':'成交额占比 '+sgn(s.fund_today_ratio,1)+'% · ')
    +esc(s.fund_today_source||'来源未知')+' · 采集 '+esc(s.fund_today_at||'时间未知')+'</p></div>'
    +'<div class="detail-insight-fund"><small>3 / 5 / 10 日主力净额</small><b>'+fundTri(s)+'</b>'
    +'<p>'+esc(s.fund_state||'历史资金未知')+(s.fund_history_source?' · '+esc(s.fund_history_source):' · 来源未知')
    +(s.fund_asof?' · 截至 '+esc(s.fund_asof):'')+'</p></div></div>'
    +'<div class="detail-insight-note">两组资金按各自来源和日期展示，不拼成连续变化曲线；缺失保持未知。</div>'
    +'<div class="detail-insight-section"><h4>个股归属</h4>'
    +'<div class="detail-insight-row"><strong>个股角色</strong><span>'+esc((s.roles||['一般成员']).join('、'))+'；判断日 '+esc(s.signal_date||'—')+'</span></div>'
    +'<div class="detail-insight-row"><strong>同花顺题材</strong><span class="detail-insight-tags">'
    +(displayBoards(s).length?displayBoards(s).map(function(b){return '<span>'+esc(b)+'</span>';}).join(''):'暂无已核对题材')+'</span></div>'
    +'<div class="detail-insight-row"><strong>属性标签</strong><span>'+((s.attribute_tags||[]).length?s.attribute_tags.map(esc).join(' · '):'无')
    +'；只作背景，不进入题材强弱榜。</span></div></div>'
    +'<div class="detail-insight-section"><h4>归属核对</h4>'
    +'<div class="detail-insight-row"><strong>来源与日期</strong><span>'+esc(s.theme_basis||'待核对')
    +(s.theme_checked_at?' · '+esc(s.theme_checked_at):'')+'</span></div>'
    +(s.member_only_themes&&s.member_only_themes.length?'<div class="detail-insight-row"><strong>仅成员页出现</strong><span>'+s.member_only_themes.map(esc).join(' · ')+'</span></div>':'')
    +(s.f10_only_themes&&s.f10_only_themes.length?'<div class="detail-insight-row"><strong>仅个股 F10 出现</strong><span>'+s.f10_only_themes.map(esc).join(' · ')+'</span></div>':'')
    +'</div><div class="detail-insight-note">资金按成交单分类，不证明机构持仓；所有盘中数据均为暂态。</div>'
    +'</div></details>';
  openDrawer(esc(s.name)+' '+esc(s.code),stockAffiliationSub(s),h,true);
  var paint=function(){var cv=document.getElementById('k-cv');if(cv&&s.k)drawTrend(cv,s.k);};
  paint();requestAnimationFrame(paint);
}

/* ═══════════════ 筛选面板 ═══════════════ */
function setThemeFilter(name){
  pickBoardMembers('theme:'+String(name||'').trim());
}

/* ── 板块四象限：横轴涨幅 × 纵轴资金 ──
   只看「东财真实资金口径」的板块：成交额动量是价量代理，放上纵轴会让
   "资金潜伏" 与 "涨幅先行" 混在一起，失去判断意义。
   旧版把 16 个标签直接画在点旁边，强势板块集中时会全部叠成黑团。
   现在改为：点可悬停/点击、标签做碰撞避让、重点板块另列清单。 */
window.QUAD_MORE=window.QUAD_MORE||false;
function quadrantInfo(b){
  var up=n(b.ret1)>0, inf=n(b.fund)>=50;
  if(up&&inf)return {label:'双强共振',color:'#e8271a'};
  if(up&&!inf)return {label:'涨幅先行',color:'#0071e3'};
  if(!up&&inf)return {label:'资金潜伏',color:'#f08c00'};
  return {label:'双弱',color:'#6e6e73'};
}
function quadrantText(b){
  var q=quadrantInfo(b);
  return '<b>'+esc(b.name)+'</b> · '+q.label+'　今日 '+pct(b.ret1,1)
    +' · 资金 '+fmt(b.fund,1)+' · 综合 '+fmt(b.score,1);
}
function renderQuadrantFocus(rows){
  var el=document.getElementById('q-focus'); if(!el)return;
  if(!rows||!rows.length){el.innerHTML='';return;}
  var top=rows.slice().sort(function(a,b){return n(b.score)-n(a.score);}).slice(0,8);
  el.innerHTML='<div style="grid-column:1/-1;font-size:11.5px;color:var(--txt3);margin:1px 2px 0">'
    +'重点板块（按板块榜分数前 8，点击查看已覆盖成员与各自角色）</div>'
    +top.map(function(b){var q=quadrantInfo(b);
      return '<div class="q-focus-item" onclick="showBoardByName(\''+jsq(b.idx_code||'')+'\')">'
        +'<i class="q-dot" style="background:'+q.color+'"></i>'
        +'<span class="q-name" title="'+esc(b.name)+'">'+esc(b.name)+'</span>'
        +'<span class="q-meta">'+fmt(b.score,1)+' · '+pct(b.ret1,1)+'</span></div>';}).join('');
}
function drawQuadrant(cv,rows){
  var dpr=window.devicePixelRatio||1, w=cv.clientWidth||900, h=cv.clientHeight||430;
  cv.width=Math.round(w*dpr); cv.height=Math.round(h*dpr);
  var g=cv.getContext('2d'); g.setTransform(1,0,0,1,0,0); g.scale(dpr,dpr);
  g.clearRect(0,0,w,h);
  if(!rows||!rows.length){
    g.font='13px -apple-system,sans-serif'; g.textAlign='center'; g.fillStyle='rgba(0,0,0,.24)';
    g.fillText('暂无东财真实资金口径的板块数据',w/2,h/2);
    cv._quadPoints=[]; return;
  }
  var pad={l:48,r:20,t:20,b:36};
  var xmax=1.0;
  rows.forEach(function(b){xmax=Math.max(xmax,Math.abs(n(b.ret1)));});
  xmax=Math.ceil(xmax*1.18*10)/10;
  var X=function(v){return pad.l+(n(v)+xmax)/(2*xmax)*(w-pad.l-pad.r);};
  var Y=function(v){return h-pad.b-(n(v)/100)*(h-pad.t-pad.b);};
  var mid=X(0), midY=Y(50);

  g.fillStyle='rgba(232,39,26,.06)';   g.fillRect(mid,pad.t,w-pad.r,midY-pad.t);
  g.fillStyle='rgba(240,140,0,.06)';  g.fillRect(pad.l,pad.t,mid-pad.l,midY-pad.t);
  g.fillStyle='rgba(0,113,227,.06)';  g.fillRect(mid,midY,w-pad.r,h-pad.b-midY);
  g.fillStyle='rgba(0,0,0,.02)'; g.fillRect(pad.l,midY,mid-pad.l,h-pad.b-midY);

  g.strokeStyle='rgba(0,0,0,.05)'; g.lineWidth=1;
  [0,25,50,75,100].forEach(function(v){g.beginPath();g.moveTo(pad.l,Y(v));g.lineTo(w-pad.r,Y(v));g.stroke();});
  g.strokeStyle='rgba(0,0,0,.13)';
  g.beginPath();g.moveTo(mid,pad.t);g.lineTo(mid,h-pad.b);g.stroke();
  g.beginPath();g.moveTo(pad.l,midY);g.lineTo(w-pad.r,midY);g.stroke();

  g.font='10px -apple-system,sans-serif';
  g.fillStyle='rgba(0,0,0,.24)';
  g.textAlign='right'; g.textBaseline='middle';
  [0,50,100].forEach(function(v){g.fillText(String(v),pad.l-9,Y(v));});
  g.textAlign='center'; g.textBaseline='top';
  [-xmax,-xmax/2,0,xmax/2,xmax].forEach(function(v){g.fillText(sgn(v,1)+'%',X(v),h-pad.b+9);});

  g.font='11px -apple-system,sans-serif';
  g.textAlign='left';  g.textBaseline='top';
  g.fillStyle='rgba(232,39,26,.72)';  g.fillText('双强共振 · 主升',mid+11,pad.t+7);
  g.textAlign='right'; g.fillStyle='rgba(240,140,0,.72)'; g.fillText('资金潜伏 · 轮动前哨',mid-11,pad.t+7);
  g.textAlign='left';  g.fillStyle='rgba(0,113,227,.72)'; g.fillText('涨幅先行 · 资金未跟',mid+11,h-pad.b-20);
  g.textAlign='right'; g.fillStyle='rgba(0,0,0,.42)'; g.fillText('双弱 · 回避',mid-11,h-pad.b-20);

  var colors=['#e8271a','#0071e3','#f08c00','#6e6e73'], points=[];
  rows.forEach(function(b){
    var q=quadrantInfo(b), qi=q.label==='双强共振'?0:(q.label==='涨幅先行'?1:(q.label==='资金潜伏'?2:3));
    var r=3.4+Math.max(0,Math.min(100,n(b.score))-42)/58*5.4;
    var px=X(b.ret1), py=Y(b.fund);
    points.push({b:b,x:px,y:py,r:r});
    g.beginPath(); g.arc(px,py,r,0,Math.PI*2);
    g.fillStyle=colors[qi]+'d9'; g.fill();
    g.strokeStyle='rgba(0,0,0,.42)'; g.lineWidth=1; g.stroke();
  });
  cv._quadPoints=points;

  // 只给重点板块做标签，并且逐个尝试四个方向，避免文本互相盖住。
  var ranked=rows.slice().sort(function(a,b){return n(b.score)-n(a.score);});
  var lab=ranked.slice(0,window.QUAD_MORE?18:8), occupied=[];
  g.font='10.5px -apple-system,sans-serif'; g.textBaseline='middle';
  function hit(a,b){return !(a.r<b.l||a.l>b.r||a.b<b.t||a.t>b.b);}
  lab.forEach(function(b){
    var p=points.filter(function(x){return x.b===b;})[0]; if(!p)return;
    var tw=Math.min(174,g.measureText(b.name).width+10), th=17;
    var opts=p.x<mid
      ? [{l:p.x+10,dy:-11,side:'left'},{l:p.x+10,dy:11,side:'left'},
         {l:p.x-10-tw,dy:-11,side:'right'},{l:p.x-10-tw,dy:11,side:'right'}]
      : [{l:p.x-10-tw,dy:-11,side:'right'},{l:p.x-10-tw,dy:11,side:'right'},
         {l:p.x+10,dy:-11,side:'left'},{l:p.x+10,dy:11,side:'left'}];
    var placed=null;
    opts.some(function(o){
      var t=Math.max(pad.t+th/2,Math.min(h-pad.b-th/2,p.y+o.dy));
      var box={l:o.l-4,r:o.l+tw+4,t:t-th/2,b:t+th/2};
      if(box.l<pad.l||box.r>w-pad.r||occupied.some(function(x){return hit(box,x);}))return false;
      placed={o:o,t:t,box:box}; return true;
    });
    if(!placed)return;
    occupied.push(placed.box);
    g.strokeStyle='rgba(0,0,0,.20)'; g.lineWidth=1;
    g.beginPath();g.moveTo(p.x,p.y);g.lineTo(placed.o.side==='left'?placed.box.l:placed.box.r,placed.t);g.stroke();
    g.fillStyle='rgba(255,255,255,.94)';g.fillRect(placed.box.l,placed.box.t,placed.box.r-placed.box.l,th);
    g.strokeStyle='rgba(0,0,0,.18)';g.strokeRect(placed.box.l,placed.box.t,placed.box.r-placed.box.l,th);
    g.fillStyle='#1d1d1f';g.textAlign=placed.o.side==='left'?'left':'right';
    g.fillText(b.name,placed.o.side==='left'?placed.box.l+5:placed.box.r-5,placed.t);
  });

  var hover=document.getElementById('q-hover');
  function resetHover(){
    if(hover)hover.innerHTML='将鼠标移到圆点上查看板块名称、涨幅、资金强度和综合分。';
    cv.style.cursor='default';
  }
  function pointAt(ev){
    var rr=cv.getBoundingClientRect(), x=ev.clientX-rr.left, y=ev.clientY-rr.top, best=null, bd=1e9;
    points.forEach(function(p){var d=Math.hypot(x-p.x,y-p.y), lim=Math.max(9,p.r+5);
      if(d<=lim&&d<bd){best=p;bd=d;}}); return best;
  }
  cv.onmousemove=function(ev){var p=pointAt(ev); if(!p){resetHover();return;}
    cv.style.cursor='pointer'; if(hover)hover.innerHTML=quadrantText(p.b)+'　<span style="color:var(--blue)">点击查看板块链路 →</span>';};
  cv.onmouseleave=resetHover;
  cv.onclick=function(ev){var p=pointAt(ev);if(p&&p.b&&p.b.idx_code)showBoardByName(p.b.idx_code);};
}


function renderFilterPanel(){
  var f=STATE.filters, tc={}, ic={};
  boardCatalog().forEach(function(b){if(b.type==='theme')tc[b.name]=n(b.pool_members);});
  stockPoolRows().forEach(function(s){
    (s.industry||[]).forEach(function(b){ic[b]=(ic[b]||0)+1;});
  });
  var themes=Object.keys(tc).sort(function(a,b){return tc[b]-tc[a];});
  var inds=Object.keys(ic).sort(function(a,b){return ic[b]-ic[a];});

  function numRow(label,key,min,max,step,unit){
    return '<div class="fgrp"><div class="ft">'+label
      +'<span class="n"><span id="pv-'+key+'">'+f[key+'Min']+' ~ '+f[key+'Max']+'</span></span></div>'
      +'<div class="rng">'
      +'<input type="number" value="'+f[key+'Min']+'" step="'+step+'" '
      +'onchange="setRange(\''+key+'\',\'Min\',this.value,'+min+','+max+')">'
      +'<span class="sep">~</span>'
      +'<input type="number" value="'+f[key+'Max']+'" step="'+step+'" '
      +'onchange="setRange(\''+key+'\',\'Max\',this.value,'+min+','+max+')">'
      +'<span class="unit">'+unit+'</span></div></div>';
  }

  var h='<div class="fgrp"><div class="ft">板别<span class="n">已选 '+f.boards.length+' 项 · '
    +'不选＝全部</span></div>'
    +'<div class="chips">'
    +boardOrder().map(function(b){
      var cnt=n((DATA.board_mix||{})[b]&&(DATA.board_mix||{})[b].n);
      var on=f.boards.indexOf(b)>=0;
      return '<span class="chip'+(on?' on':'')+'" onclick="tgBoard(\''+esc(b)+'\',this)">'
        +'<i class="bd bd-'+esc(k2type(b))+'" style="margin:0 5px 0 0">±'
        +n((DATA.board_limit_by_name||{})[b])+'%</i>'
        +esc(b)+' <b style="opacity:.5;font-weight:400">'+cnt+'</b></span>';}).join('')
    +'</div>'
    +'<div style="font-size:11.5px;color:var(--txt3);margin-top:9px;line-height:1.6">'
    +boardOrder().map(function(b){return b+' ±'+n((DATA.board_limit_by_name||{})[b])+'%';}).join('、')
    +'。<b>涨停判定已按各板限制分别计算</b>，20% 板的票不会因为涨 10% 被记成涨停。'
    +'<br>当前股票池只纳入：<b>'+(DATA.pool_boards||['沪主板','深主板']).join(' · ')
    +'</b>（创业板/科创板不在池内，口径见 README）。</div></div>';

  h+='<div class="fgrp"><div class="ft">硬门槛 <span class="n">Risk Gate · 不计权重</span></div>'
    +'<div style="font-size:11.5px;color:var(--txt3);line-height:1.65">'
     +'下列是数据有效性与当日成交检查，未通过的股票可在全池搜索中查看原因：'
     +'<br>· ST / *ST / 退市 / PT　· 停牌或当日无成交　· 上市交易日不足 '
     +n((DATA.risk_gate||{}).min_trading_days||25)
     +'　· 历史日线缺失或日期不齐'
     +'<br>历史成交额只作参考，不影响入榜。'
    +gateHtml()+'</div></div>';

  h+='<div class="fgrp"><div class="ft">快速策略<span class="n">一键套用</span></div>'
    +'<div class="chips">'+Object.keys(PRESETS).map(function(k){
      return '<span class="chip" onclick="applyPreset(\''+k+'\');renderFilterPanel()">'+esc(k)+'</span>';}).join('')
    +'</div></div>';

  h+='<div class="fgrp"><div class="ft">状态标签<span class="n">日线历史状态与当前回踩观察 · 已选 '+f.states.length+' 项</span></div>'
    +'<div class="row" style="margin-bottom:11px;gap:7px;flex-wrap:wrap">'
    +'<span class="chip'+(STATE.stateMode==='and'?' on':'')+'" onclick="setStateMode(\'and\')">同时满足</span>'
    +'<span class="chip'+(STATE.stateMode==='or'?' on':'')+'" onclick="setStateMode(\'or\')">任一满足</span>'
    +'<span style="font-size:11.5px;color:var(--txt3)">'
    +(STATE.stateMode==='and'?'勾选越多命中越少':'勾选越多命中越多')+'</span></div>'
    +'<div class="chips">'+Object.keys(STATE_LABEL).map(function(k){
      var on=f.states.indexOf(k)>=0;
      return '<span class="chip'+(on?' on':'')+'" data-v="'+esc(k)+'" title="'+esc(STATE_TIP[k]||'')
        +'" onclick="tgState(\''+k+'\',this)">'+STATE_LABEL[k]+'</span>';}).join('')
    +'</div></div>';

  h+='<div class="fgrp"><div class="ft">日线条件<span class="n">完成日依据</span></div>';
  h+=numRow('日线进攻强度分位','score',0,100,5,'百分位');
  h+=numRow('完成日5日涨幅','ret5',-50,200,1,'%');
  h+=numRow('完成日量比','vr',0,200,0.5,'倍')+'</div>';
  h+='<div class="fgrp"><div class="ft">盘中条件<span class="n">当前有效报价</span></div>';
  h+=numRow('当日涨跌幅','chg',-21,21,1,'%');
  h+=numRow('盘中观察分','intra',0,100,5,'分');
  h+=numRow('盘中距暂态MA10','dist',-10,10,0.5,'ATR')+'</div>';
  h+='<div class="fgrp"><div class="ft">辅助条件<span class="n">不进入盘中分</span></div>';
  h+=numRow('换手率','turn',0,100,1,'%');
  h+=numRow('流通市值','cap',0,100000,50,'亿')+'</div>';

  h+='<div class="fgrp"><div class="ft">题材<span class="n">已选 '+f.themes.length+' · 共 '+themes.length+'</span></div>'
    +'<div class="search" style="margin-bottom:10px"><span class="ic">⌕</span>'
    +'<input id="th-q" placeholder="搜索题材" oninput="filterChips(\'th-list\',this.value)"></div>'
    +'<div class="chips" id="th-list">'
    +themes.map(function(t){var on=f.themes.indexOf(t)>=0;
      return '<span class="chip'+(on?' on':'')+'" data-v="'+esc(t)+'" onclick="tgTheme(\''+esc(t)+'\',this)">'
        +esc(t)+' <b style="opacity:.5;font-weight:400">'+tc[t]+'</b></span>';}).join('')
    +'</div></div>';

  h+='<div class="fgrp"><div class="ft">行业<span class="n">已选 '+f.industries.length+'</span></div>'
    +'<div class="chips">'
    +inds.map(function(t){var on=f.industries.indexOf(t)>=0;
      return '<span class="chip'+(on?' on':'')+'" onclick="tgInd(\''+esc(t)+'\',this)">'
        +esc(t)+' <b style="opacity:.5;font-weight:400">'+ic[t]+'</b></span>';}).join('')
    +'</div></div>';

  h+='<div style="display:flex;gap:10px;margin-top:22px">'
    +'<button class="btn primary" style="flex:1;justify-content:center" onclick="closeDrawer()">查看结果</button>'
    +'<button class="btn" onclick="clearFilters();renderFilterPanel()">重置</button></div>';

  openDrawer('筛选条件','实时生效 · '+STOCK_VIEW_NAMES[STOCK_VIEW]+' · 当前显示 '
    +(stockPoolRows().filter(stockViewMatches).filter(passFilter).length)+' 只',h);
}
function filterChips(listId,q){
  q=(q||'').trim().toLowerCase();
  var box=document.getElementById(listId); if(!box)return;
  [].forEach.call(box.children,function(c){
    var v=(c.getAttribute('data-v')||'').toLowerCase();
    c.style.display=(!q||v.indexOf(q)>=0)?'':'none';});
}
function setRange(key,which,val,min,max){
  var v=parseFloat(val); if(!isFinite(v))return;
  v=Math.max(min,Math.min(max,v));
  STATE.filters[key+which]=v;
  var el=document.getElementById('pv-'+key);
  if(el)el.textContent=STATE.filters[key+'Min']+' ~ '+STATE.filters[key+'Max'];
  STATE.limit=80; renderStocks();
}
function setStateMode(m){
  STATE.stateMode=(m==='or'?'or':'and');
  STATE.limit=80; renderStocks();
  if(document.getElementById('drawer').classList.contains('open'))renderFilterPanel();
}
function tgState(k,el){
  var a=STATE.filters.states,i=a.indexOf(k);
  if(i>=0)a.splice(i,1); else a.push(k);
  el.classList.toggle('on'); STATE.limit=80; renderStocks();
}
function tgTheme(t,el){
  var a=STATE.filters.themes,i=a.indexOf(t);
  if(i>=0)a.splice(i,1);
  else {
    if(!a.length){STATE.filters=defaultFilters();a=STATE.filters.themes;}
    a.push(t);
  }
  STATE.boardFilterId=null;STOCK_VIEW='all';STATE.q='';
  var input=document.getElementById('q');if(input)input.value='';
  STATE.sort.stocks={k:null,asc:false};STATE.limit=80;
  renderStocks();renderFilterPanel();
}
function tgInd(t,el){
  var a=STATE.filters.industries,i=a.indexOf(t);
  if(i>=0)a.splice(i,1); else a.push(t);
  el.classList.toggle('on'); STATE.limit=80; renderStocks();
}
function tgBoard(b,el){
  var a=STATE.filters.boards,i=a.indexOf(b);
  if(i>=0)a.splice(i,1); else a.push(b);   // 多选＝OR：选两个板就是两个板的并集
  el.classList.toggle('on'); STATE.limit=80; renderStocks();
}
/* 列显示开关。
   之前 renderColPanel 里 onclick="tgCol(...)"，但 tgCol 从来没定义过 ——
   点"列设置"里的任何一项都毫无反应（悬空事件处理器，不报错也不冒泡）。 */
function tgCol(k,el){
  STATE.cols[k]=!STATE.cols[k];
  if(el)el.classList.toggle('on');
  renderStocks();
}
function renderColPanel(){
  var c=STATE.cols;
  var h='<div class="fgrp"><div class="ft">显示列</div><div class="chips">'
    +[['board','题材标签'],['industry','行业'],['extra','扩展列（当前量比 / 距20日线）']]
    .map(function(x){return '<span class="chip'+(c[x[0]]?' on':'')+'" onclick="tgCol(\''+x[0]+'\',this)">'
      +x[1]+'</span>';}).join('')
    +'</div><div style="font-size:12.5px;color:var(--txt3);margin-top:14px;line-height:1.7">'
    +'「板别」列与名称旁的 <b>次新</b> 徽标<b>常驻显示、不可关闭</b> —— 四板混榜时'
    +'不标板别会把 20% 板的中阳误当主板涨停看。<br>'
    +'盘中未完成日K只展示截至当前的累计量比，不外推全天成交量；它不进入盘中观察分。'
    +'筛选中的量比使用完成日数值。悬停表头可见更多说明。</div></div>';
  openDrawer('列设置','选择要显示的列',h);
}

/* ═══════════════ 持仓体检 ═══════════════ */
function parseHold(){
  var raw=(document.getElementById('hold-in').value||'').split('\n');
  var out=[];
  raw.forEach(function(line){
    line=line.trim(); if(!line)return;
    var p=line.split(/[\s,，\t]+/);
    var code=(p[0]||'').replace(/\D/g,'');
    if(code.length!==6)return;
    out.push({code:code,cost:parseFloat(p[1])||null,pos:parseFloat(p[2])||null});
  });
  return out;
}
function renderHold(silent){
  var hs=parseHold();
  var sum=document.getElementById('hold-sum');
  if(!hs.length){
    sum.innerHTML='<div class="empty">尚未录入持仓</div>';
    document.getElementById('tb-hold').innerHTML='';
    return;
  }
  var byCode={};
  (DATA.stocks||[]).forEach(function(s){byCode[s.code]=s;});
  var rows=[];
  hs.forEach(function(x){
    var s=byCode[x.code];
    rows.push({inp:x,st:s});
  });
  var found=rows.filter(function(r){return r.st;});

  var totW=0, wsum=0, wpnl=0, hasPnL=false;
  found.forEach(function(r){
    var w=r.inp.pos||0; totW+=w;
    wsum+=n(r.st.score)*w;
    if(r.inp.cost){hasPnL=true; wpnl+=(n(r.st.price)/r.inp.cost-1)*100*w;}
  });
  var avgScore=totW?wsum/totW:0;
  var avgPnl=totW&&hasPnL?wpnl/totW:null;
  var strong=found.filter(function(r){return r.st.trend_online;}).length;
  var weak=found.filter(function(r){return !r.st.trend_online;}).length;

  sum.innerHTML='<div class="grid" style="grid-template-columns:1fr 1fr;gap:11px">'
    +[['持仓数',hs.length+' 只',found.length<hs.length?((hs.length-found.length)+' 只未匹配'):''],
      ['加权分位',fmt(avgScore,1),(avgScore>=65?'整体偏强':avgScore>=45?'强弱分化':'整体偏弱')],
      ['加权浮动',avgPnl==null?'—':pct(avgPnl),(avgPnl==null?'需填写成本':
        (avgPnl>0?'盈利中':'浮亏中'))],
      ['均线趋势',strong+' 在线 / '+weak+' 未在线','以完成日线判断']]
    .map(function(x){return '<div class="metric" style="padding:14px 16px">'
      +'<div class="lbl" style="font-size:11.5px">'+x[0]+'</div>'
      +'<div class="val" style="font-size:1.4rem;margin-top:4px">'+x[1]+'</div>'
      +'<div class="sub" style="margin-top:4px">'+x[2]+'</div></div>';}).join('')+'</div>';


  function advice(r){
    var s=r.st;
    if(!s.trend_online)return ['趋势未在线','wa',s.touch_state];
    if(s.overheated)return ['位置偏热','wa','现价距10日线超过3.5 ATR'];
    return [s.entry_state,'gr',(s.risk_notes||[]).join('；')||'未触发既定风险阈值；排名不代表持有建议'];
  }

  var h='<thead><tr>'
    +thSort('hold','name','名称','l','')
    +'<th class="l">板别</th>'
    +'<th>成本</th><th>现价</th><th>浮动</th><th class="l">仓位</th>'
    +thSort('hold','score','强度分位')
    +'<th>行业广度%</th><th>均线趋势</th><th class="l">题材</th><th class="l">观察</th>'
    +'</tr></thead><tbody>';
  rows.forEach(function(r){
    if(!r.st){
      h+='<tr><td class="l"><span class="nm">'+esc(r.inp.code)+'</span> '
        +'<span class="pill gr">未匹配</span></td><td colspan="10" class="l flat">'
        +'不在当前股票池（可能为 ST / 退市 / 停牌，或代码有误；北交所暂未纳入）</td></tr>';
      return;
    }
    var s=r.st, pnl=r.inp.cost?(n(s.price)/r.inp.cost-1)*100:null;
    var ad=advice(r), pn=r.inp.pos;
    h+='<tr class="clickable" onclick="showStock(\''+esc(s.code)+'\')">'
      +'<td class="l"><span class="nm">'+esc(s.name)+'</span><span class="cd">'+esc(s.code)+'</span>'
      +npill(s)
      +(n(s.limit_today)?' <span class="pill up">涨停</span>':'')+'</td>'
      +'<td class="l">'+bpill(s)+'</td>'
      +'<td>'+(r.inp.cost?fmt(r.inp.cost):'—')+'</td>'
      +'<td class="'+cls(s.change_pct)+'">'+fmt(s.price)+'</td>'
      +'<td class="'+(pnl==null?'flat':cls(pnl))+'"><b>'+(pnl==null?'—':pct(pnl))+'</b></td>'
      +'<td class="l"><div class="row" style="gap:8px">'+(pn!=null?bar(pn)+' <span class="flat">'
        +fmt(pn,0)+'%</span>':'<span class="flat">—</span>')+'</div></td>'
      +'<td><b style="color:'+scoreColor(s.score)+'">'+fmt(s.score,1)+'</b></td>'
      +'<td class="flat">'+fmt(s.industry_breadth,1)+'</td>'
      +'<td class="flat">'+(s.trend_online?'在线':'未在线')+'</td>'
      +'<td class="l"><div class="tags">'+displayBoards(s).slice(0,2).map(function(b){
        return tagHtml(b,(DATA.theme_index||{})[b]);}).join('')+'</div></td>'
      +'<td class="l"><span class="pill '+ad[1]+'">'+ad[0]+'</span>'
      +'<div style="font-size:11px;color:var(--txt3);margin-top:3px">'+ad[2]+'</div></td></tr>';
  });
  document.getElementById('tb-hold').innerHTML=h+'</tbody>';
  if(!silent)toast('已体检 '+found.length+' 只持仓');
}
document.getElementById('hold-run').onclick=function(){renderHold();};
document.getElementById('hold-clear').onclick=function(){
  document.getElementById('hold-in').value='';
  try{localStorage.removeItem('sm_hold');}catch(e){}
  renderHold();};
document.getElementById('hold-in').addEventListener('input',function(){
  try{localStorage.setItem('sm_hold',this.value);}catch(e){}
  renderHold(true);});

/* ═══════════════ 初始化 ═══════════════ */
function init(){
  if(!DATA||!DATA.stocks){
    document.getElementById('hero-p').innerHTML=
      '<span style="color:var(--orange)">当前页面没有可用的数据快照。</span>'
      +'你可能打开了模板或旧页面；请双击项目目录里的 '
      +'<code style="background:rgba(0,0,0,.07);padding:2px 7px;border-radius:5px">打开看板.bat</code> '
      +'，它会启动服务并载入最新看板。';
    return;
  }
  segInit(document.getElementById('seg'),function(p){goPane(p);});
  segInit(document.getElementById('seg-strategy'),function(s){setStrategy(s);});
  segInit(document.getElementById('work-switch'),function(mode){setWorkMode(mode,true);});
  document.getElementById('work-close-export').onclick=exportCloseBoard;
  segInit(document.getElementById('seg-period'),function(k){
    STATE.period=k;
    STATE.sort.stocks={k:k==='all'?'stock_strength_score':'stock_strength_score',asc:false};
    STATE.limit=80; renderStocks();});
  document.getElementById('dr-x').onclick=closeDrawer;
  document.getElementById('scrim').onclick=closeDrawer;
  document.getElementById('btn-filter').onclick=renderFilterPanel;
  document.getElementById('btn-export').onclick=exportCSV;
   document.getElementById('btn-refresh').onclick=refreshData;
  document.getElementById('btn-fresh').onclick=function(){
    var m=freshness();
    var when=(m===null)?'未知':m+' 分钟前';
    toast('数据生成于 '+(DATA.generated_at||'—')+'（'+when+'）· 想立刻更新就点左边的「刷新数据」');
  };
  var qi=document.getElementById('q');
  var qt=null;
  qi.addEventListener('input',function(){
    clearTimeout(qt); var v=this.value;
    qt=setTimeout(function(){STATE.q=v;STATE.limit=80;renderStocks();},180);});
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape')closeDrawer();
    if(e.key==='/'&&document.activeElement!==qi){e.preventDefault();qi.focus();}
  });
  // 表头点击（事件委托，表格内容会被重建）
  document.getElementById('tb-stocks').addEventListener('click',function(e){
    var th=e.target.closest('th'); if(!th)return;
    var pane='stocks';
    var map={'名称':'name','现价':'price','涨跌幅':'change_pct','5日':'ret5','20日':'ret20',
      '60日':'ret60','量比(实时)':'vol_ratio_rt','量比(截至当前/5日均量)':'vol_ratio5','换手%':'turnover',
      '流通市值':'float_mcap','60日位置':'position60','多头':'bull_count','综合':'score',
      '强度分位':'stock_strength_percentile','日线进攻强度':'stock_strength_score',
      '20日分位':'ret20_percentile','60日结构':'above60','行业':'primary_industry','#':'rank'};
    var t=th.textContent.trim().replace(/[▲▼]/g,'').trim();
    if(map[t]){setSort(pane,map[t]);}
  });
  document.getElementById('tb-boards').addEventListener('click',function(e){
    var th=e.target.closest('th'); if(!th)return;
    var map={'板块':'name','今日%':'ret1','5日%':'ret5','20日%':'ret20','5日涨天':'up_days_5',
      '60日位置':'position60','量能':'vol_expand','相对强度':'rs','资金强度':'fund',
      '联动':'linkage','动能':'momentum','综合':'score','#':'rank'};
    var t=th.textContent.trim().replace(/[▲▼]/g,'').trim();
    if(map[t])setSort('boards',map[t]);
  });
  var saved=null;
  try{saved=localStorage.getItem('sm_hold');}catch(e){}
  if(saved)document.getElementById('hold-in').value=saved;

  // 兜底归一化：任何筛选键缺失都补回默认值。
  // 少一个键就是一个 TypeError，而且是"首次进入空白、重置后正常"这种最难查的症状。
  STATE.filters=Object.assign(defaultFilters(),STATE.filters||{});
  setStrategy(DATA.default_strategy||'trend', true);
   renderFresh(); LAST_CANDIDATE_WINDOW=(DATA.stocks||[]).concat(DATA.coverage_catalog||[])
     .some(currentCandidateQuoteUsable);
   setInterval(refreshPageFreshness,60000);
   watchDataVersion(); setInterval(watchDataVersion,10000);
  renderOverview();
  RENDERED.overview=true;
  setTimeout(auditSticky,90);
}
/* 板块中心 V4：行业/题材与成员共用 board_catalog.id。 */
var BC_KIND='industry',BC_SORT='trend',BC_SEARCH='';
function boardCatalog(){return DATA.board_catalog||[];}
function boardById(id){return boardCatalog().filter(function(b){return b.id===id;})[0];}
function boardCard(b){
  var valid=n(b.valid_members),fund=b.fund_today_covered?('当日 '+b.fund_today_covered+'/'+valid):(b.fund_covered?('5日 '+b.fund_covered+'/'+valid):'未知');
  return '<tr class="clickable" onclick="showBoardById(\''+jsq(b.id)+'\')">'
    +'<td class="l"><b>'+esc(b.name)+'</b>'+(b.wide?' <span class="pill wa">宽题材</span>':'')
    +'<span class="cd">'+esc(b.type==='industry'?'行业':'题材')+' · '+esc(b.trend_state)+' · '+esc(b.ranking_reason||'')+'</span></td>'
    +'<td>'+valid+'</td><td class="'+cls(b.member_ret5)+'">'+pct(b.member_ret5,1)+'</td>'
    +'<td>'+fmt(b.trend_pct,0)+'%</td><td class="'+cls(b.member_today)+'">'+pct(b.member_today,1)+'</td>'
    +'<td>'+fmt(b.emotion_pct,0)+'% / '+n(b.limit_count)+'</td><td>'+fmt(b.positive_top3_share,0)+'%</td>'
    +'<td>'+fund+'</td></tr>';
}
function centerMarkup(kind,showTabs){
  var boards=boardCatalog().filter(function(b){return b.type===kind&&b.valid_members>0;});
  if(BC_SEARCH)boards=boards.filter(function(b){return b.name.toLowerCase().indexOf(BC_SEARCH.toLowerCase())>=0;});
  boards.sort(function(a,b){
    if(a.ranking_eligible!==b.ranking_eligible)return a.ranking_eligible?-1:1;
    if(!a.ranking_eligible)return a.name.localeCompare(b.name);
    if(BC_SORT==='today')return n(b.member_today)-n(a.member_today)||n(b.emotion_pct)-n(a.emotion_pct);
    return n(a.trend_rank,1e9)-n(b.trend_rank,1e9)||a.name.localeCompare(b.name);
  });
  return '<div class="card" style="margin-bottom:18px"><div class="row wrap" style="gap:8px;align-items:center">'
    +(showTabs?'<button class="btn '+(kind==='industry'?'primary':'')+'" onclick="BC_KIND=\'industry\';renderBoards()">行业</button>'
      +'<button class="btn '+(kind==='theme'?'primary':'')+'" onclick="BC_KIND=\'theme\';renderBoards()">题材</button>':'')
    +'<button class="btn '+(BC_SORT==='trend'?'primary':'')+'" onclick="BC_SORT=\'trend\';renderBoards();renderThemesPage()">板块趋势</button>'
    +'<button class="btn '+(BC_SORT==='today'?'primary':'')+'" onclick="BC_SORT=\'today\';renderBoards();renderThemesPage()">今日热度</button>'
    +'<input id="bc-search-'+(showTabs?'boards':'themes')+'" aria-label="搜索板块" placeholder="搜索行业或题材" value="'+esc(BC_SEARCH)+'" '
    +'oninput="updateBoardSearch(this)" style="margin-left:auto;max-width:240px;padding:8px;border:1px solid var(--line);border-radius:8px">'
    +'</div><p class="flat" style="font-size:12px;margin:10px 0">'+(BC_SORT==='trend'
      ?'至少6只有效成员才参与趋势排名；在线比例相同时优先覆盖较齐、样本较多者，再看5日表现。小样本列末尾，仅供查询。'
      :'今日按主板成员等权涨幅排列，情绪活跃比例和涨停数独立展示。')
    +'资金仅显示真实覆盖，未知不计中性分。板块关系只说明共同表现。</p>'
    +'<div class="tw" style="border:0;background:transparent"><table><thead><tr>'
    +'<th class="l">板块</th><th>有效成员</th><th>5日等权</th><th>趋势在线</th><th>今日等权</th>'
    +'<th>活跃/涨停</th><th>前三上涨贡献</th><th>资金覆盖</th></tr></thead><tbody>'
    +(boards.length?boards.map(boardCard).join(''):'<tr><td colspan="8" class="empty">暂无匹配板块</td></tr>')
    +'</tbody></table></div></div>';
}
function renderBoards(){
  var all=boardCatalog(), themes=all.filter(function(b){return b.type==='theme';});
  var industry=all.filter(function(b){return b.type==='industry';});
  var covered=all.filter(function(b){return b.fund_covered>0||b.fund_today_covered>0;}).length;
  document.getElementById('bd-metrics').innerHTML=[['行业',industry.length,'同花顺行业归属'],
    ['题材',themes.length,'属性标签已剔除'],['资金有覆盖',covered+'/'+all.length,'其余未知'],
    ['完成日线',esc((DATA.strength_model||{}).asof||'—'),'主板有效成员']]
    .map(function(x){return '<div class="metric"><div class="lbl">'+x[0]+'</div><div class="val">'+x[1]+'</div><div class="sub">'+x[2]+'</div></div>';}).join('');
  document.getElementById('board-center').innerHTML=centerMarkup(BC_KIND,true);
}
function renderThemesPage(){document.getElementById('theme-center').innerHTML=centerMarkup('theme',false);}
function updateBoardSearch(input){
  BC_SEARCH=input.value;var id=input.id,pos=input.selectionStart;
  renderBoards();renderThemesPage();
  var current=document.getElementById(id);if(current){current.focus();current.setSelectionRange(pos,pos);}
}
function boardMemberRows(b,codes){
  var by={};(b.members||[]).forEach(function(r){by[r.code]=r;});
  if(!codes.length)return '<div class="empty" style="padding:10px 0">当前没有符合条件的成员</div>';
  return '<div class="tw" style="border:0;background:transparent"><table><thead><tr><th class="l">个股</th>'
    +'<th>进攻强度</th><th>全体名次</th><th>板块名次</th><th>5日超额</th><th>20日超额</th><th>今日</th><th>当日情绪</th></tr></thead><tbody>'
    +codes.map(function(c){var r=by[c];if(!r)return '';return '<tr class="clickable" onclick="showStock(\''+jsq(c)+'\',\''+jsq(b.id)+'\')">'
      +'<td class="l"><b>'+esc(r.name)+'</b><span class="cd">'+esc(c)+' · '+esc(r.role)+' · '+esc(r.strength_motion||'待观察')+'</span></td>'
      +'<td>'+fmt(r.score,1)+'</td><td>'+n(r.global_rank)+'</td><td>'+n(r.rank)+'/'+n(b.valid_members)+'</td>'
      +'<td class="'+cls(r.excess5)+'">'+(r.excess5==null?'—':sgn(r.excess5,1))+'</td>'
      +'<td class="'+cls(r.excess20)+'">'+(r.excess20==null?'—':sgn(r.excess20,1))+'</td>'
      +'<td class="'+cls(r.change_pct)+'">'+pct(r.change_pct,1)+'</td>'
      +'<td>'+esc(r.emotion_heat||'数据不足')+'</td></tr>';}).join('')+'</tbody></table></div>';
}
function showBoardById(id){
  var b=boardById(id);if(!b)return toast('板块归属暂未核对');
  var source=b.source_members==null?'未知':n(b.source_members);
  var idx=b.index_trend;
  var h='<div class="grid g4" style="margin-bottom:16px">'
    +[[b.source_complete?'来源成员':'当前覆盖归集',source],['系统主板成员',n(b.pool_members)],['有效日线',n(b.valid_members)],['今日行情覆盖',n(b.quote_covered)]]
    .map(function(x){return '<div class="metric"><div class="lbl">'+x[0]+'</div><div class="val">'+x[1]+'</div></div>';}).join('')+'</div>'
    +'<div class="grid g4" style="margin-bottom:16px">'
    +[['趋势在线',fmt(b.trend_pct,1)+'%'],['趋势变化',esc(b.trend_state)+' · '+sgn(b.trend_delta1_pp,1)+'点'],
      ['今日活跃',fmt(b.emotion_pct,1)+'% · 涨停'+n(b.limit_count)],
      ['上涨集中度',b.positive_top3_share==null?'无正收益':fmt(b.positive_top3_share,1)+'%']]
    .map(function(x){return '<div class="metric"><div class="lbl">'+x[0]+'</div><div class="val" style="font-size:1.15rem">'+x[1]+'</div></div>';}).join('')+'</div>'
    +'<div class="card" style="margin-bottom:16px"><h3>主板成员与指数分开看</h3><p>主板成员5日等权 '+pct(b.member_ret5,1)
    +'，20日等权 '+pct(b.member_ret20,1)+'；今日等权 '+pct(b.member_today,1)+'。'
    +(idx?'同花顺概念指数（含非主板）5日 '+pct(idx.ret5,1)+'、20日 '+pct(idx.ret20,1)+'。':'暂无对应概念指数。')
    +'</p><p>资金：'+(b.fund_today_covered?('当日覆盖 '+n(b.fund_today_covered)+'/'+n(b.valid_members)+'，已覆盖成员净额合计 '+sgn(b.fund_sum_today/1e8,2)+'亿元；来源 '+esc(DATA.fund_source||'未知')+'，抓取 '+esc(b.fund_observed_at||'时间未知')+'。'):(b.fund_covered?('5日覆盖 '+n(b.fund_covered)+'/'+n(b.valid_members)+'，抓取 '+esc(b.fund_observed_at||'时间未知')+'。'):'未知，未参与强度判断。'))
    +' 昨日强势成员今日反馈：'+(b.prior_strong_count?('样本'+n(b.prior_strong_count)+'只，中位涨幅 '+pct(b.prior_strong_today_median,1)+'，上涨占比 '+fmt(b.prior_strong_up_pct,0)+'%'):'暂无可比样本。')
    +' 来源：'+esc(b.source_basis)+(b.source_complete?'，详情名单可用':'，仅表示当前已覆盖主板成员，不代表全市场来源成员数')
    +(b.source_checked_at?'，详情缓存时间 '+new Date(b.source_checked_at*1000).toLocaleString():'')
    +(b.membership_disagreements!=null?'；本板块已覆盖成员中 F10/详情差异 '+n(b.membership_disagreements)+' 只':'')
    +'；完成日线 '+esc(b.asof)+'。成员浏览合并 F10 与详情，评分仍按原有口径；个股详情保留逐项来源。</p></div>';
  if(b.wide){
    var sub=boardCatalog().filter(function(x){return x.type==='theme'&&x.id!==b.id&&x.valid_members>=5&&x.valid_members<b.valid_members;})
      .map(function(x){var shared=(x.member_codes||[]).filter(function(c){return b.member_codes.indexOf(c)>=0;}).length;
        return {b:x,shared:shared};}).filter(function(x){return x.shared>=5;})
      .sort(function(a,b){return b.shared-a.shared;}).slice(0,5);
    h+='<div class="card" style="margin-bottom:16px"><h3>相关细分观察</h3><p class="flat">由同花顺成员交集得到，仅表示重叠，未认定层级或上涨原因。</p>'
      +(sub.length?sub.map(function(x){return '<button class="btn" style="margin:3px" onclick="showBoardById(\''+jsq(x.b.id)+'\')">'
        +esc(x.b.name)+' · 交集'+x.shared+'</button>';}).join(''):'暂无可核对的细分交集')+'</div>';
  }
  [['trend','趋势强势股',(b.list_criteria||{}).trend||'统一日线进攻强势资格；近期变化单列'],
   ['recent','近期转强股',(b.list_criteria||{}).recent||'统一日线近期增强资格'],
   ['emotion','情绪活跃股','活跃程度与承接分开观察']].forEach(function(x){
     h+='<div class="card" style="margin-bottom:16px"><h3>'+x[1]+' <small>'+n(b.lists[x[0]].length)+'只</small></h3>'
       +'<p class="flat" style="font-size:12px">'+x[2]+'</p>'+boardMemberRows(b,b.lists[x[0]])+'</div>';
   });
  h+='<details class="detail-fold"><summary>查看全部 '+n(b.valid_members)+' 只有效成员</summary><div class="detail-fold-body">'
    +boardMemberRows(b,(b.members||[]).map(function(r){return r.code;}))+'</div></details>'
    +'<button class="btn primary" style="margin-top:15px" onclick="closeDrawer();pickBoardMembers(\''+jsq(b.id)+'\')">在个股页查看该板块全部成员</button>';
  openDrawer(esc(b.name),esc(b.type==='industry'?'行业板块':'题材板块')+' · '+esc(b.trend_state)+' · '+n(b.valid_members)+'只主板有效成员',h,true);
}
function showBoard(i){var b=(DATA.boards||[])[i];if(b)showBoardById('theme:'+b.name);}
function showBoardByName(idx){var b=(DATA.boards||[]).filter(function(x){return x.idx_code===idx;})[0];
  if(b)showBoardById('theme:'+b.name);else toast('未找到该板块');}
function showThemeGroup(rank){var t=(DATA.theme_rank||[]).filter(function(x){return x.rank===rank;})[0];
  if(t)showBoardById('theme:'+t.name);}
function tagCount(name){var b=boardById('theme:'+name);return b?n(b.pool_members):0;}
function pickBoardMembers(id){
  var b=boardById(id);if(!b)return toast('板块成员暂无数据');
  STATE.filters=defaultFilters();STATE.boardFilterId=id;STATE.q='';
  STOCK_VIEW='all';STATE.sort.stocks={k:null,asc:false};
  var input=document.getElementById('q');if(input)input.value='';
  STATE.limit=80;RENDERED.stocks=false;goPane('stocks');renderStocks();
  toast('正在查看'+(b.type==='industry'?'行业':'概念')+'「'+b.name+'」· 当前覆盖 '+n(b.pool_members)+' 只');
}
function pickThemeByName(name){
  name=String(name||'').trim();
  if(!name)return toast('概念名称为空，无法查看');
  pickBoardMembers('theme:'+name);
}
init();




