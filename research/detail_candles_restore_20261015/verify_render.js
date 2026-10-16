const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('radar_ui.js','utf8'),start=src.indexOf('function showStock(code,boardId)'),end=src.indexOf('\nvar MS_CHART=null;',start);
const calls=[],canvas={parentNode:{insertBefore(){}}};
const ctx={DATA:{stocks:[]},document:{getElementById(){return ctx.html.includes('id="k-cv"')?canvas:null},createElement(){return {}}},setTimeout(fn){fn()},esc:String,fmt:String,pctHtml:String,msDetail(){return ''},msBoardCatalog(){return []},openDrawer(a,b,h){ctx.html=h},msDrawCandles(cv,bars,price,n){calls.push({bars:bars.length,n})},drawTrend(){throw Error('Unexpected line chart')},MS_CHART:null};
vm.createContext(ctx);vm.runInContext(src.slice(start,end),ctx);
const bars=Array.from({length:60},(_,i)=>({date:'2026-01-'+i,open:10,high:12,low:9,close:11,volume:1000}));
for(const [name,row,want,paused] of [
 ['ohlc',{chart_history:bars},true,false],
 ['empty-chart-history',{chart_history:[],strength_history:bars},true,false],
 ['close-only',{k:[1,2,3,4,5]},false,false],
 ['invalid-ohlc',{chart_history:bars.map(b=>({...b,open:null})),k:[1,2,3,4,5]},false,false],
 ['halted-no-bars',{emotion_relay:{suspended_current:true}},false,true],
 ['halted-with-history',{chart_history:bars,emotion_relay:{suspended_current:true}},true,true],
 ['resumed',{chart_history:bars,emotion_relay:{suspended_current:false}},true,false]
]){
 ctx.DATA.stocks=[{code:'600001',name:'验证',...row}];calls.length=0;ctx.showStock('600001');
 assert.strictEqual(calls.length,want?1:0,name);assert.strictEqual(ctx.html.includes('id="k-cv"'),want,name);
 assert.strictEqual(ctx.html.includes('停牌中'),paused,name);if(!want&&!paused)assert(ctx.html.includes('OHLC数据不足'));if(want)assert.strictEqual(calls[0].n,60);
 console.log(name,'PASS');
}
