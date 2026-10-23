/* Local payload transport; all screening and judgment functions remain in the template. */
function decodeDashboardPackage(packet){
  if(!packet||['local-ui-1','local-ui-2'].indexOf(packet.format)<0)return packet;
  function visit(v){
    if(Array.isArray(v)){
      if(v.length&&typeof v[0]==='string'&&v[0].charAt(0)==='^'){
        var out={},shape=packet.shapes[parseInt(v[0].slice(1),36)];
        shape.forEach(function(key,i){out[packet.keys[key]]=visit(v[i+1]);});return out;
      }return v.map(visit);
    }
    if(v&&typeof v==='object'){
      var out={};Object.keys(v).forEach(function(k){out[packet.keys[Number(k)]]=visit(v[k]);});return out;
    }
    if(typeof v==='string'&&v.charAt(0)==='~')return packet.strings[parseInt(v.slice(1),36)];
    return v;
  }
  return visit(packet.root);
}
var UI_CACHE={},UI_PENDING={},UI_REQUEST=0,UI_DRAWER=null,UI_UPDATING=null;
var UI_COMPOSING=false;
document.addEventListener('compositionstart',function(){UI_COMPOSING=true;});
document.addEventListener('compositionend',function(){UI_COMPOSING=false;});
function uiLocal(){return location.protocol==='http:'||location.protocol==='https:';}
function uiFetch(kind,id,version){
  var key=version+'|'+kind+'|'+id;
  if(UI_CACHE[key])return Promise.resolve(UI_CACHE[key]);
  if(UI_PENDING[key])return UI_PENDING[key];
  if(!uiLocal())return Promise.reject(new Error('详情需要本地服务。请使用「打开看板.bat」，或打开导出的完整离线看板。'));
  UI_PENDING[key]=fetch('/__ui/detail?version='+encodeURIComponent(version)+'&kind='+kind+'&id='+encodeURIComponent(id))
    .then(function(r){if(!r.ok)throw new Error(r.status===409?'此版本已过期，请先更新页面再查看详情':'详情读取失败 '+r.status);return r.json();})
    .then(function(j){if(j.version!==version)throw new Error('详情版本不一致');UI_CACHE[key]=j.item;return j.item;})
    .finally(function(){delete UI_PENDING[key];});
  return UI_PENDING[key];
}
function uiPut(kind,item){
  var groups=kind==='board'?['board_catalog']:['stocks','coverage_catalog'];
  groups.forEach(function(group){var rows=DATA[group]||[];
    for(var i=0;i<rows.length;i++)if((kind==='board'?rows[i].id:rows[i].code)===(kind==='board'?item.id:item.code)){rows[i]=item;return;}
  });
}
function installLazyDetails(){
  if(!DATA)return;
  var renderStock=showStock,renderBoard=showBoardById,oldClose=closeDrawer,oldOpen=openDrawer,rendering=false;
  openDrawer=function(){
    if(!rendering){UI_REQUEST++;UI_DRAWER=null;}
    return oldOpen.apply(null,arguments);
  };
  function display(fn){rendering=true;try{return fn();}finally{rendering=false;}}
  closeDrawer=function(){UI_REQUEST++;UI_DRAWER=null;return oldClose();};
  function open(kind,id,boardId){
    if(!DATA.ui_lazy)return kind==='board'?renderBoard(id):renderStock(id,boardId);
    var request=++UI_REQUEST,version=DATA.ui_generation;
    UI_DRAWER={kind:kind,id:id,boardId:boardId};
    var existing=kind==='board'?boardById(id):stockPoolRows().filter(function(s){return s.code===id;})[0];
    display(function(){openDrawer(esc(existing&&existing.name||id),'','<p class="flat">正在读取本地详情…</p>',kind==='board');});
    var tasks=[uiFetch(kind,id,version)];
    if(kind==='stock'&&boardId)tasks.push(uiFetch('board',boardId,version));
    return Promise.all(tasks).then(function(items){
      if(request!==UI_REQUEST||version!==DATA.ui_generation)return;
      uiPut(kind,items[0]);if(items[1])uiPut('board',items[1]);
      return display(function(){return kind==='board'?renderBoard(id):renderStock(id,boardId);});
    }).catch(function(e){
      if(request===UI_REQUEST)display(function(){openDrawer(esc(existing&&existing.name||id),'','<p class="flat">'+esc(e.message)+'</p>',kind==='board');});
    });
  }
  showStock=function(code,boardId){return open('stock',code,boardId);};
  showBoardById=function(id){return open('board',id);};
  var offlineHost=document.getElementById('stk-actions');
  if(offlineHost&&DATA.ui_lazy){
    var button=document.createElement('button');button.id='ui-offline-button';button.className='btn ms-offline-button';button.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4" stroke-linecap="round" stroke-linejoin="round"/></svg><span>完整离线看板</span>';
    button.title='保存本轮全部页面、详情、图表及个股结果，使用同一发布版本。双击即可离线查看';
    button.onclick=function(){
      if(!uiLocal()){toast('请先通过打开看板.bat启动本地服务');return;}
      var a=document.createElement('a');a.href='/__ui/offline?version='+encodeURIComponent(DATA.ui_generation);
      a.download='股票看板_完整离线_'+String(DATA.generated_at||'').slice(0,10)+'.html';a.click();
    };offlineHost.appendChild(button);
  }
}
function updateDashboardData(status){
  if(!DATA.ui_lazy){location.reload();return Promise.resolve();}
  if(UI_UPDATING)return UI_UPDATING;
  var version=status&&status.ui_generation;
  if(!version)return Promise.reject(new Error('后台尚未载入新版页面接口'));
  if(version===DATA.ui_generation){PAGE_VERSION=status.data_version;rfDone();return Promise.resolve();}
  UI_UPDATING=fetch('/__ui/summary?version='+encodeURIComponent(version),{cache:'no-store'})
    .then(function(r){if(!r.ok)throw new Error('新数据读取失败 '+r.status);return r.json();})
    .then(function(packet){
      if(!UI_COMPOSING)return packet;
      return new Promise(function(resolve){
        document.addEventListener('compositionend',function finish(){
          document.removeEventListener('compositionend',finish);resolve(packet);
        });
      });
    })
    .then(function(packet){
      var next=decodeDashboardPackage(packet);
      if(next.ui_generation!==version||!next.ui_lazy)throw new Error('列表版本不一致');
      var focus=document.activeElement,focusId=focus&&focus.id,selection=null;
      if(focus&&typeof focus.selectionStart==='number')selection=[focus.selectionStart,focus.selectionEnd];
      var scrolls=Array.from(document.querySelectorAll('[id],.tw,.chips')).filter(function(el){return el.scrollTop||el.scrollLeft;})
        .map(function(el){
          var parts=[],node=el;
          while(node&&!node.id){
            parts.unshift(node.tagName.toLowerCase()+':nth-child('+(Array.prototype.indexOf.call(node.parentNode.children,node)+1)+')');
            node=node.parentNode;
          }
          return [node?'#'+CSS.escape(node.id)+(parts.length?' > '+parts.join(' > '):''):null,el.scrollTop,el.scrollLeft];
        });
      function restoreScrolls(){scrolls.forEach(function(s){var el=s[0]&&document.querySelector(s[0]);if(el){el.scrollTop=s[1];el.scrollLeft=s[2];}});}
      var folds=Array.from(document.querySelectorAll('#dr-b details[open]')).map(function(el){return el.querySelector('summary').textContent;});
      var x=window.scrollX,y=window.scrollY;
      var drawer=document.querySelector('#drawer.open #ss-detail')&&typeof SS_DETAIL==='string'
        ?{kind:'stock',id:SS_DETAIL}:UI_DRAWER;
      UI_REQUEST++;UI_CACHE={};UI_PENDING={};if(typeof SS_FULL!=='undefined')SS_FULL={};DATA=next;PAGE_VERSION=status.data_version;
      RENDERED={};renderOverview();RENDERED.overview=true;
      var render={stocks:renderStocks,radar:renderRadar,boards:renderBoards,themes:renderThemesPage,emotion:typeof renderEmotion==='function'?renderEmotion:null,hold:renderHold}[STATE.pane];
      if(render){render();RENDERED[STATE.pane]=true;}renderFresh();
      var drawerPromise=drawer?(drawer.kind==='stock'?showStock(drawer.id,drawer.boardId):showBoardById(drawer.id)):Promise.resolve();
      restoreScrolls();
      window.scrollTo(x,y);
      var target=focusId&&document.getElementById(focusId);
      if(target){target.focus({preventScroll:true});if(selection&&target.setSelectionRange)target.setSelectionRange(selection[0],selection[1]);}
      rfDone();toast('数据已更新，已保留当前筛选与页面位置');
      return Promise.resolve(drawerPromise).then(function(){
        document.querySelectorAll('#dr-b details').forEach(function(el){if(folds.indexOf(el.querySelector('summary').textContent)>=0)el.open=true;});
        restoreScrolls();
      });
    }).catch(function(e){rfDone();toast(e.message);throw e;})
    .finally(function(){UI_UPDATING=null;});
  return UI_UPDATING;
}
