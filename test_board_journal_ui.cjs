const fs=require('fs'),vm=require('vm'),assert=require('assert'),zlib=require('zlib');
const c={console,setTimeout,clearTimeout,Set,Intl,Date,location:{protocol:'http:'},document:{addEventListener:()=>{}},esc:s=>String(s),jsq:s=>String(s)};
vm.createContext(c);
vm.runInContext(fs.readFileSync('ui_client.js','utf8').split('var UI_CACHE')[0],c);
c.DATA=JSON.parse(zlib.gunzipSync(fs.readFileSync('research/board_journal_catalyst_20261022/model_fixture.json.gz')));
vm.runInContext(fs.readFileSync('board_journal_ui.js','utf8'),c);
let renders=0;c.bjRender=()=>renders++;
let input={value:'机器人'};c.bjSearch(input);assert(c.bjRows().length===2);assert(renders===1);
input.value='603278';c.bjSearch(input);assert(c.bjRows().length>0);assert(c.bjRows().every(b=>b.members.includes('603278')));
input.value='不存在的方向zz';c.bjSearch(input);assert(c.bjRows().length===0);
input.value='';c.bjSearch(input);assert(c.bjRows().length>0);assert(c.bjRows().every(b=>b.strength.eligible&&!b.broad));assert(c.bjRows().filter(b=>b.name==='电机'||b.name==='电机Ⅱ').length===1);
assert(c.bjNormalize('粤 传 媒')===c.bjNormalize('粤传媒'));
input.value='半导体';input._bjComposing=true;let before=renders;c.bjSearch(input,{isComposing:true});assert(renders===before);
c.document={getElementById:()=>input};c.bjSearchCommit();assert(c.bjRows().length>0);assert(!input._bjComposing);
const m=c.bjRoot().current;c.BJ_NEWS[c.DATA.ui_generation]={news:{checked_at:'9999'},by_board:{}};
const a=c.bjModel();assert(a===c.bjModel());assert(a!==m);
c.BJ_NEWS[c.DATA.ui_generation]={news:{checked_at:'99999'},by_board:{}};assert(c.bjModel()!==a);
assert(c.bjDirect({news:[{match_kind:'member'},{match_kind:'theme_title'}]}).length===1);
console.log('PASS: Chinese, code, empty, clear, normalized names, composition commit, bounded selection, news model cache invalidation, direct-news isolation');

c.BJ_VIEW.q='';c.BJ_VIEW.filter='all';c.BJ_VIEW.includeBroad=false;
assert(!c.bjRows().some(b=>b.name==='比亚迪概念'||b.name==='一带一路'));
c.BJ_VIEW.q='比亚迪';assert(c.bjRows().some(b=>b.name==='比亚迪概念'));
c.BJ_VIEW.q='';c.BJ_VIEW.includeBroad=true;assert(c.bjRows().some(b=>b.name==='一带一路'));
assert(c.bjEvents({news:[{match_kind:'member',title:'签约'},{match_kind:'theme_title',title:'机器人概念涨停'},{match_kind:'theme_title',title:'机器人新产品发布',catalyst:{kind:'product'}}]}).length===1);
c.BJ_NEWS={};c.BJ_VIEW.q='电机';const b=c.bjRows().find(b=>b.name==='电机'),card=c.bjCard(b);
for(const label of ['定义','逻辑','龙头','中军','跟风','点评'])assert(card.includes(label));
assert(card.includes('候选'));
console.log('PASS: existing strong gate, broad exclusion/search override, exact membership dedup, event classification, complete brief structure');

let exported='';c.bjDownload=(text)=>exported=text;c.BJ_VIEW.q='电机';c.bjCSV();
assert(exported.includes('龙头候选')&&exported.includes('催化')&&exported.includes('鸣志电器')&&exported.includes('趋势起点'));
console.log('PASS: CSV carries role, definition, event and review fields');

c.BJ_VIEW.q='PCB概念';const pcb=c.bjRows().find(b=>b.name==='PCB概念');
assert(c.bjEvents(pcb).some(e=>e.title.includes('三星电机')));
const brief=c.bjCard(pcb);assert(brief.includes('催化')&&brief.includes('投资扩产')&&brief.includes('2028'));
assert(!brief.includes('直接催化尚未证实')&&!brief.includes('暂无可核验的直接驱动'));
assert(c.bjLogic(pcb).length>=3);assert(c.bjReview(pcb).length>=3);
const motor=c.bjModel().boards['industry:电机'];assert(!motor.news.some(e=>e.title.includes('三星电机')));
console.log('PASS: substrate catalyst routing, full-text event capture, richer logic/review, no repetitive empty warning');

const bank={name:'国有大型银行Ⅱ',news:[]};
const bankLogic=c.bjLogic(bank).join('\n');
bank.news=[{published_at:'2099-01-01',match_kind:'industry_chain',catalyst:{label:'政策会议',transmission:'金融大模型'}}];
assert.equal(c.bjLogic(bank).join('\n'),bankLogic);
assert(bankLogic.includes('股息回报')&&bankLogic.includes('净息差')&&!bankLogic.includes('金融大模型'));
const withReorderedNews=Object.assign({},pcb,{news:pcb.news.slice().reverse()});
assert.equal(c.bjLogic(pcb).join('\n'),c.bjLogic(withReorderedNews).join('\n'));
assert(!c.bjLogic(pcb).join('\n').includes('三星电机'));
console.log('PASS: sector thesis stays independent of latest catalyst and news order');

const context={date:'2026-10-22',source_at:'2026-10-22 15:00:00',mode:'收盘归档',stocks:{},boards:{}};
for(let i=0;i<40;i++)context.stocks[''+i]={valid:true,quote_at:context.source_at,change_pct:i<6?1:-3};
const target={name:'国有大型银行Ⅱ',members:['0','1','2','3','4','5']};
context.boards.p={name:'PCB概念',members:['10','11','12','13','14']};
context.boards.c={name:'通信设备',members:['20','21','22','23','24']};
assert(c.bjMarketLogic(target,context).join('').includes('防御风格切换'));
assert(c.bjMarketLogic(target,context).join('').includes('PCB概念'));
for(let i=0;i<6;i++)context.stocks[''+i].change_pct=-1;
assert(c.bjMarketLogic(target,context).join('').includes('相对强势不等于已经上涨'));
for(const s of Object.values(context.stocks))s.quote_at='2026-10-21 15:00:00';
assert.equal(c.bjMarketLogic(target,context).length,0);
console.log('PASS: defensive rotation, negative relative strength and stale context boundaries');

assert(c.bjState({status:'比较不足',reasons:['缺少同一交易时段10—30分钟比较']},'盘中观察').includes('待补第二条数据'));
assert(c.bjState({status:'比较不足',reasons:['当前报价成员不足6只或覆盖不足80%。']},'盘中观察').includes('成员报价不足'));
assert(!c.bjLogic(bank).join('').includes('以上为板块产业逻辑框架'));
assert(!c.bjLogic(bank).join('').includes('不代表已追踪到资金迁移'));
console.log('PASS: precise comparison labels and concise narrative');

assert(c.bjState({status:'比较不足',return_pct:3.39,up_pct:68,limit_count:5,reliable:true},'收盘归档').includes('收盘上涨'));
assert(!c.bjState({status:'比较不足',return_pct:3.39,reliable:true},'收盘归档').includes('盘中对比'));
for(const s of Object.values(context.stocks))s.quote_at='2026-10-22 15:01:00';
assert.equal(c.bjMarketLogic(target,context).length,0);
console.log('PASS: close status uses available close values and excludes future quotes');

const trendBoard=Object.assign({},b,{strength:{basis:'index-trend',eligible:true,trend:true,label:'趋势回踩',priority:1,live:true,episode_start:'2026-10-23',ret5:2},status:'趋势回踩'});
const trendState=c.bjState(trendBoard,'盘中观察'),review=c.bjReview(trendBoard).join('');
assert(trendState.includes('趋势回踩')&&!trendState.includes('情绪'));
assert(review.includes('本轮起点2026-10-23')&&!review.includes('短线情绪'));
const hotOnly=Object.assign({},b,{strength:{basis:'index-trend',eligible:false,label:'暂未入选',priority:8},return_pct:10});
assert(c.bjCompare(trendBoard,hotOnly)<0);
assert(c.bjOverview(c.bjModel()).indexOf('情绪强势')<0);
console.log('PASS: trend stage, episode start and trend-only eligibility drive board presentation');

const chartInput={code:'886069',bars:[
 {date:'2026-10-23',open:10,high:12,low:9,close:11,volume:100},
 {date:'2026-10-28',open:12,high:14,low:11,close:13,volume:200},
 {date:'2026-10-29',open:13,high:15,low:12,close:14,volume:300}],current_price:13,current_at:'2026-10-28 11:30:00'};
const frozenChart=c.bjIndexChartData(chartInput,'2026-10-23','2026-10-23 15:00:00',true);
assert.equal(frozenChart.bars.length,1);assert.equal(frozenChart.asof,'2026-10-23');assert.equal(frozenChart.current_price,null);
assert.equal(chartInput.bars.length,3);
assert.equal(c.bjIndexChartData(chartInput,'2026-10-28','2026-10-28 11:20:00',false).current_price,null);
assert.equal(c.bjIndexChartData(chartInput,'2026-10-28','2026-10-28 11:30:00',false).current_price,13);
c.bjModel=()=>({});assert(c.bjFilter({strength:{tracked:true,eligible:false}},'tracking'));
console.log('PASS: direct candle data respects historical date and source cutoff; tracking stays separate from strong selection');

const liveChart={source:'日线源',current_source:'当日OHLC',display_captured_at:'2026-10-28 12:10:00',
bars:[{date:'2026-10-27',open:10,high:12,low:9,close:11,volume:100},{date:'2026-10-28',open:11,high:13,low:10,close:12,volume:120,partial:true,source_at:'2026-10-28 11:30:00'}],current_at:'2026-10-28 11:30:00',current_price:12};
assert.equal(c.bjIndexChartData(liveChart,'2026-10-28','2026-10-28 11:29:00',false).bars.length,2);
const oldDay=c.bjIndexChartData(liveChart,'2026-10-27','2026-10-27 15:00:00',true);
assert.equal(oldDay.bars.length,1);assert.equal(oldDay.current_source,null);assert.equal(oldDay.current_price,null);
console.log('PASS: latest unfinished candle keeps source time; historical chart excludes current-day candle');
