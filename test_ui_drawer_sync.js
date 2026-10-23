const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2]||'ui_client.js','utf8');
async function scenario(selectionOpen,owner){
 const calls=[];
 const ctx={
  DATA:{ui_lazy:true,ui_generation:'previous'},PAGE_VERSION:1,
  STATE:{pane:'stocks'},RENDERED:{},SS_DETAIL:'000530',
  document:{activeElement:null,addEventListener(){},querySelectorAll(){return []},
   querySelector(selector){return selectionOpen&&selector==='#drawer.open #ss-detail'?{}:null},
   getElementById(){return null}},
  window:{scrollX:0,scrollY:0,scrollTo(){}},CSS:{escape:x=>x},
  fetch:async()=>({ok:true,json:async()=>({ui_lazy:true,ui_generation:'current'})}),
  renderOverview(){},renderStocks(){},renderRadar(){},renderBoards(){},renderThemesPage(){},
  renderEmotion(){},renderHold(){},renderFresh(){},rfDone(){},toast(){},
  showStock:async(id,boardId)=>calls.push(['stock',id,boardId,ctx.DATA.ui_generation]),
  showBoardById:async(id)=>calls.push(['board',id,ctx.DATA.ui_generation])
 };
 vm.createContext(ctx);vm.runInContext(source,ctx);ctx.UI_DRAWER=owner;
 await ctx.updateDashboardData({ui_generation:'current',data_version:2});
 return calls;
}
(async()=>{
 assert.deepStrictEqual(await scenario(true,null),[['stock','000530',undefined,'current']],'visible selection drawer must follow the new generation even if request tracking was cleared');
 assert.deepStrictEqual(await scenario(false,null),[],'closed drawer must remain closed');
 assert.deepStrictEqual(await scenario(false,{kind:'stock',id:'600519'}),[['stock','600519',undefined,'current']]);
 assert.deepStrictEqual(await scenario(false,{kind:'board',id:'theme:test'}),[['board','theme:test','current']]);
 console.log('4 drawer synchronization scenarios passed');
})().catch(e=>{console.error(e.stack);process.exit(1)});
