async page => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('Input.imeSetComposition',{text:'',selectionStart:0,selectionEnd:0});
  await page.locator('#bc-search-boards').focus();
  await page.evaluate(()=>{window.originalSearch=document.getElementById('bc-search-boards');window.originalQuery=BC_SEARCH;});
  for(const text of ['d','dian','电池']){
    await cdp.send('Input.imeSetComposition',{text,selectionStart:text.length,selectionEnd:text.length});
    await page.waitForFunction(value=>document.getElementById('bc-search-boards').value===value,text);
    const state=await page.evaluate(()=>({same:originalSearch===document.getElementById('bc-search-boards'),focused:document.activeElement===originalSearch,query:BC_SEARCH,original:originalQuery,composing:originalSearch._bcComposing}));
    if(!state.same||!state.focused||!state.composing||state.query!==state.original)throw Error('IME interrupted: '+JSON.stringify(state));
  }
  await cdp.send('Input.insertText',{text:'电池'});
  await page.waitForFunction(()=>BC_SEARCH==='电池');
  const committed=await page.evaluate(()=>({same:originalSearch===document.getElementById('bc-search-boards'),focused:document.activeElement===originalSearch,value:originalSearch.value,query:BC_SEARCH,composing:originalSearch._bcComposing}));
  if(!committed.same||!committed.focused||committed.composing||committed.query!=='电池'||committed.value!=='电池')throw Error('IME commit wrong: '+JSON.stringify(committed));
  if(!await page.locator('#board-center [data-board-id="industry:电池"]').count())throw Error('battery not found');
  const checks=await page.evaluate(()=>{
    const input=originalSearch;input.value='电池xyz';input.setSelectionRange(2,5);
    input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));
    const selectionPreserved=input===document.getElementById(input.id)&&document.activeElement===input&&input.selectionStart===2&&input.selectionEnd===5;
    input.value='';input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'}));
    const cleared=BC_SEARCH===''&&document.querySelectorAll('#board-center .bc-card').length>0;
    input.value='PCB概念';input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertFromPaste'}));
    const switched=BC_KIND==='theme'&&!!document.querySelector('#board-center [data-board-id="theme:PCB概念"]');
    return {selectionPreserved,cleared,switched};
  });
  if(Object.values(checks).some(x=>!x))throw Error('search regression '+JSON.stringify(checks));
  await page.getByRole('button',{name:'题材',exact:true}).first().click();
  await page.locator('#bc-search-themes').focus();
  const theme=await page.evaluate(()=>{
    const input=document.getElementById('bc-search-themes'),query=BC_SEARCH;
    input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
    input.value='li';input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,inputType:'insertCompositionText'}));
    renderThemesPage();renderBoards();
    const interim=input===document.getElementById(input.id)&&document.activeElement===input&&BC_SEARCH===query;
    input.value='锂电池概念';input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'锂电池概念'}));
    input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false,inputType:'insertText'}));
    return {interim,same:input===document.getElementById(input.id),focused:document.activeElement===input,query:BC_SEARCH,found:!!document.querySelector('#theme-center [data-board-id="theme:锂电池概念"]')};
  });
  if(!theme.interim||!theme.same||!theme.focused||!theme.found||theme.query!=='锂电池概念')throw Error('theme IME regression '+JSON.stringify(theme));
  if(errors.length)throw Error(errors.join(';'));
  await cdp.detach();
  await page.screenshot({path:'output/playwright/board-search-ime-live.png'});
  return {chromiumComposition:committed,checks,theme,pageErrors:errors};
}

