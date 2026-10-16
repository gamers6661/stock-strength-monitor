const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('dashboard_template.html','utf8');
const script=html.split('<script>')[1].split('</script>')[0].replace('/*__DATA__*/null','null');
new vm.Script(script); // 整页语法检查，不执行页面初始化。
function source(name){let start=script.indexOf('function '+name+'(');assert(start>=0);let end=script.indexOf('\nfunction ',start+1);return script.slice(start,end<0?undefined:end);}
const functions=source('consolidationDisplay')+'\n'+source('renderConsolidationMonitor');
let nodes={},phase='午盘',fresh=true;
const sandbox={document:{getElementById:id=>nodes[id]||(nodes[id]={})},DATA:{trend_consolidation:{rows:[],pending_rows:[],withdrawn_rows:[]}},
 sessionNow:()=>phase,workQuoteCurrent:()=>fresh,esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
 jsq:s=>String(s),cls:()=>'',pct:(n)=>n==null?'—':n.toFixed(1)+'%',sgn:n=>String(n),fmt:(n,d)=>n==null?'—':n.toFixed(d),workProfileTags:()=>''};
vm.createContext(sandbox);vm.runInContext(functions,sandbox);
const item={code:'600001',name:'<强股>',stage:'初步突破',quote_at:'2026-09-30 11:30:00',shape:'横盘整理',location:'横盘整理',
 trend_label:'趋势在线整理',days:4,impulse5_pct:12,pullback_atr:1,platform_distance_pct:-1,volume_ratio:.7,shrink_volume:true,
 confirmation_samples:2,daily_tier:'C',change_pct:2,risk_flags:[]};
let checks=0;
function check(fn){fn();checks++;}
check(()=>{phase='午间休市';let r=sandbox.consolidationDisplay(item,phase);assert(r.label.includes('上午截至11:30'));assert(!r.reference);});
check(()=>{phase='午盘';fresh=false;assert(sandbox.consolidationDisplay(item,phase).reference);});
check(()=>{fresh=true;assert(!sandbox.consolidationDisplay(item,phase).reference);});
check(()=>{assert(sandbox.consolidationDisplay({...item,reference_only:true},phase).reference);});
check(()=>{assert(sandbox.consolidationDisplay(item,'已收盘').reference);});
check(()=>{sandbox.DATA.trend_consolidation.rows=[item];sandbox.renderConsolidationMonitor({});assert(nodes['work-consolidation-list'].innerHTML.includes('&lt;强股>'));assert(nodes['work-consolidation-list'].innerHTML.includes('平台试探 2 次'));assert(nodes['work-consolidation-list'].innerHTML.includes('日线档 C'));});
check(()=>{phase='午间休市';sandbox.renderConsolidationMonitor({});assert(nodes['work-consolidation-list'].innerHTML.includes('上午截至11:30'));assert(nodes['work-consolidation-count'].textContent.startsWith('1 只'));});
check(()=>{phase='午盘';fresh=false;sandbox.renderConsolidationMonitor({});assert(nodes['work-consolidation-count'].textContent==='0 只 · 1 只留档');});
check(()=>{sandbox.DATA.trend_consolidation.rows=[];sandbox.DATA.trend_consolidation.pending_rows=[{code:'600001',name:'样本',reason:'价格口径待核验'}];sandbox.renderConsolidationMonitor({});assert(nodes['work-consolidation-pending'].innerHTML.includes('价格口径待核验'));});
check(()=>{phase='午盘';fresh=true;sandbox.DATA.trend_consolidation.rows=[{...item,attack_period:10,attack_gain_pct:25}];sandbox.DATA.trend_consolidation.completed_rows=[{code:'600002',name:'已启动案例',stage:'已整理完毕转强',reason:'已明显拉升'}];sandbox.renderConsolidationMonitor({});let text=nodes['work-consolidation-list'].innerHTML;assert(text.includes('此前10日进攻 25.0%'));assert(!text.includes('已启动案例'));assert(nodes['work-consolidation-pending'].innerHTML.includes('已启动案例'));assert(nodes['work-consolidation-pending-title'].textContent.includes('已整理完毕转强 1 只'));assert(nodes['work-consolidation-note'].textContent.includes('历史A档不豁免'));});
console.log(JSON.stringify({pageSyntax:'passed',frontendScenarios:checks}));
