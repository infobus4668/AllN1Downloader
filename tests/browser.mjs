// Run by test_release.py against its isolated service and generated audio fixture.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as sleep} from 'node:timers/promises';

const [executable, base, fixture] = process.argv.slice(2);
const profile = await mkdtemp(join(tmpdir(), 'allinone-browser-'));
const args = [
  '--headless=new',
  ...(process.platform === 'linux' ? ['--no-sandbox', '--disable-dev-shm-usage'] : []),
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
  '--disable-background-networking', 'about:blank',
];
const child = spawn(executable, args, {stdio:'ignore'});
let socket;
async function until(check) {
  for (let i = 0; i < 100; i++) {
    const result = await check();
    if (result) return result;
    await sleep(100);
  }
  throw Error('Browser readiness or UI assertion timed out');
}
try {
  const port = await until(async () => (await readFile(join(profile, 'DevToolsActivePort'), 'utf8').catch(() => '')).split('\n')[0]);
  const page = await until(async () => (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(p => p.type === 'page'));
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((ok, fail) => { socket.onopen = ok; socket.onerror = fail; });
  const pending = new Map(), errors = [];
  let id = 0;
  socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    if (message.method === 'Runtime.exceptionThrown') {
      const details = message.params.exceptionDetails;
      errors.push(details.exception?.description || details.text);
    }
    pending.get(message.id)?.(message);
    pending.delete(message.id);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const seq = ++id;
    const timer = setTimeout(() => reject(Error(`Timed out: ${method}`)), 5000);
    pending.set(seq, msg => { clearTimeout(timer); msg.error ? reject(Error(msg.error.message)) : resolve(msg.result); });
    socket.send(JSON.stringify({id:seq, method, params}));
  });
  const run = async expression => {
    const {result, exceptionDetails} = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
    assert.equal(exceptionDetails, undefined);
    return result.value;
  };
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true});
  await send('Page.navigate', {url:base});
  const health = await (await fetch(base + '/api/health')).json();
  await until(() => run(`document.querySelector('#versionInfo')?.textContent === ${JSON.stringify(`AllN1Downloader v${health.version}`)}`));
  const completed = await run(`(() => {
    const job = document.querySelector('.job[data-status="completed"]');
    return job ? {
      stats: job.querySelector('[data-field="stats"]').textContent,
      actions: Object.fromEntries([...job.querySelectorAll('.job-actions .mini')].map(button => [
        button.textContent, !button.classList.contains('hidden'),
      ])),
    } : null;
  })()`);
  assert.ok(completed, 'completed fixture job should be listed');
  assert.match(completed.stats, /Verified: MP3/);
  assert.equal(completed.actions['Remove from history'], true);
  assert.equal(completed.actions['Delete files'], true);
  assert.equal(completed.actions['Open file'], true);
  assert.equal(completed.actions['Save file'], true);
  assert.equal(completed.actions['Download ZIP'], false);
  assert.equal(completed.actions.Retry, false);
  assert.ok(await run(`document.documentElement.scrollWidth <= innerWidth`));
  const key = async (key, code) => {
    for (const type of ['keyDown', 'keyUp']) await send('Input.dispatchKeyEvent', {
      type, key, code:key, windowsVirtualKeyCode:code, nativeVirtualKeyCode:code,
      text:type === 'keyDown' && key === 'Enter' ? '\r' : '',
    });
  };
  await run(`settingsBtn.focus()`);
  await key('Enter', 13);
  assert.ok(await run(`settingsPanel.open && document.activeElement === closeSettings`));
  await key('Tab', 9);
  assert.ok(await run(`settingsPanel.contains(document.activeElement)`));
  await key('Escape', 27);
  await until(() => run(`!settingsPanel.open && document.activeElement === settingsBtn`));
  await run(`settingsBtn.click()`);
  await run(`document.querySelector('[data-theme=cyan]').click()`);
  assert.equal(await run(`document.documentElement.dataset.theme`), 'cyan');
  await run(`closeSettings.click()`);
  await until(() => run(`!settingsPanel.open`));
  await run(`filters.querySelector('[data-filter=done]').click()`);
  assert.equal(await run(`filters.querySelector('[data-filter=done]').getAttribute('aria-selected')`), 'true');
  await run(`filters.querySelector('[data-filter=failed]').click()`);
  assert.ok(await run(`document.querySelector('.job[data-status="completed"]').classList.contains('hidden')`));
  await run(`filters.querySelector('[data-filter=all]').click()`);
  await run(`document.querySelector('[data-source=batch]').click(); batchInput.value='bad link'; batchBtn.click()`);
  assert.match(await run(`document.querySelector('#batchStatus').textContent`), /line 1/);
  assert.equal(await run(`batchInput.value`), 'bad link');
  await run(`document.querySelector('[data-source=single]').click(); Object.defineProperty(navigator,'clipboard',{configurable:true,value:{readText:async()=>${JSON.stringify(fixture)},writeText:async(value)=>{window.__copied=value}}}); pasteBtn.click()`);
  await until(() => run(`urlInput.value === ${JSON.stringify(fixture)}`));
  await run(`analyzeForm.requestSubmit()`);
  await until(() => run(`!mediaCard.classList.contains('hidden')`));
  assert.ok(await run(`document.querySelector('[data-mode=video]').disabled`));
  await until(() => run(`document.querySelector('#expectedLine').textContent.length > 0`));
  assert.match(await run(`document.querySelector('#expectedLine').textContent`), /Expected/);
  assert.ok(await run(`!document.querySelector('#clipDetails').classList.contains('hidden')`));
  await run(`document.querySelector('[data-preset=mp3]').click()`);
  assert.equal(await run(`formatSelect.value`), 'mp3');
  assert.match(await run(`document.querySelector('#expectedLine').textContent`), /MP3/);
  await run(`state.info={is_playlist:true,entries:[{index:1,title:'First',duration:20},{index:2,title:'Second',duration:30}],playlist_count:2}; state.mode='video'; renderPlaylist(state.info)`);
  await run(`invertBtn.click()`);
  assert.equal(await run(`state.selected.size`), 0);
  await run(`selectAll.click()`);
  assert.equal(await run(`state.selected.size`), 2);
  assert.ok(await run(`document.documentElement.scrollWidth <= innerWidth`));
  await run(`state.info={is_playlist:false,qualities:[]}; state.mode='video'; formatSelect.value='mp4'; qualitySelect.value='best'; codecSelect.value='auto'; updateSelectionUI()`);
  assert.ok(await run(`downloadBtn.disabled && downloadBtnText.textContent === 'Format unavailable'`));
  const actionStates = await run(`(() => {
    const base={url:'https://example.test/media',title:'UI action fixture',thumbnail:'',mode:'video',quality:'best',container:'mp4',codec:'auto',is_playlist:false,progress:0,speed:null,eta:null,downloaded:0,total:0,current_item:null,playlist_index:null,playlist_count:null,error:null,created_at:1,started_at:null,finished_at:null,total_size:4,media:null,log_count:0,logs:[]};
    const sidecar={...base,id:'sidecar-only',status:'completed',file_count:1,files:[{name:'captions.srt',rel:'captions.srt',size:4}],has_playable:false,can_retry:true};
    const sidecarEl=createJobEl(sidecar); updateJobEl(sidecarEl,sidecar);
    const notReady={...base,id:'retry-pending',status:'error',file_count:0,files:[],has_playable:false,can_retry:false};
    const errorEl=createJobEl(notReady); updateJobEl(errorEl,notReady);
    const ready={...notReady,id:'retry-ready',can_retry:true};
    const readyEl=createJobEl(ready); updateJobEl(readyEl,ready);
    return {
      sidecarOpenHidden:sidecarEl.querySelector('[data-action="open-file"]').classList.contains('hidden'),
      retryPendingHidden:errorEl.querySelector('[data-action="retry"]').classList.contains('hidden'),
      retryReadyShown:!readyEl.querySelector('[data-action="retry"]').classList.contains('hidden'),
    };
  })()`);
  assert.deepEqual(actionStates, {sidecarOpenHidden:true,retryPendingHidden:true,retryReadyShown:true});
  const presets = await run(`(() => {
    state.info={is_playlist:false,audio_only:false,duration:100,source_audio:{filesize:100,abr:128},qualities:[
      {height:1080,formats:[{codec:'h264',ext:'mp4',filesize:300,tbr:300},{codec:'av1',ext:'webm',filesize:100,tbr:100}]},
      {height:720,formats:[{codec:'h264',ext:'mp4',filesize:200,tbr:200}]},
    ]};
    populateQualities(state.info);
    modeSwitch.querySelector('[data-mode=video]').disabled=false;
    modeSwitch.querySelector('[data-mode=video]').click();
    presetButtons.querySelector('[data-preset=max]').click();
    const max=[formatSelect.value,qualitySelect.value,codecSelect.value];
    presetButtons.querySelector('[data-preset=compatible]').click();
    const compatible=[formatSelect.value,qualitySelect.value,codecSelect.value];
    presetButtons.querySelector('[data-preset=efficient]').click();
    const efficient=[formatSelect.value,qualitySelect.value,codecSelect.value];
    modeSwitch.querySelector('[data-mode=audio]').click();
    return {max,compatible,efficient,audioMode:state.mode};
  })()`);
  assert.deepEqual(presets, {
    max:['mkv','best','auto'], compatible:['mp4','1080','h264'],
    efficient:['mkv','best','av1'], audioMode:'audio',
  });

  await run(`(() => {
    const make=(id,status,files=[])=>({
      id,url:'https://button.test/'+id,title:'Button test '+id,thumbnail:null,dir:'/button-test/'+id,
      mode:'video',quality:'best',container:'mp4',codec:'auto',clip_start:null,clip_end:null,is_playlist:false,
      status,progress:status==='completed'?100:0,speed:null,eta:null,downloaded:0,total:0,current_item:null,
      playlist_index:null,playlist_count:null,error:status==='error'?'test failure':null,created_at:1,
      started_at:1,finished_at:status==='completed'?2:null,files:files.map(name=>({name,rel:name,size:10})),
      file_count:files.length,total_size:files.length*10,has_playable:files.some(name=>/\.(mp4|mkv|webm|mp3|m4a|wav)$/i.test(name)),
      can_retry:['error','cancelled','completed'].includes(status),media:null,log_count:1,logs:['fixture log'],
    });
    window.__fakeJobs=new Map([
      ['btn-active',make('btn-active','queued')],
      ['btn-error-1',make('btn-error-1','error')],
      ['btn-error-2',make('btn-error-2','error')],
      ['btn-complete',make('btn-complete','completed',['video.mp4','captions.srt'])],
      ['btn-single',make('btn-single','completed',['single.mp3'])],
      ['btn-clear',make('btn-clear','completed',['clear.mp4'])],
    ]);
    window.__buttonCalls=[];
    window.__requestBodies=[];
    window.__realFetch=window.fetch.bind(window);
    const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
    window.fetch=async(input,init={})=>{
      const url=typeof input==='string'?input:input.url;
      const method=String(init.method||'GET').toUpperCase();
      window.__buttonCalls.push({url,method});
      if(url==='/api/jobs'&&method==='GET'){
        const response=await window.__realFetch(input,init);
        return json([...(await response.json()),...window.__fakeJobs.values()]);
      }
      if(url==='/api/health'&&window.__androidHealthTest){
        const response=await window.__realFetch(input,init);
        const health=await response.json(); health.platform='android'; return json(health);
      }
      if(url==='/api/open-downloads') return json({ok:true});
      if(url==='/api/jobs/clear-finished'&&method==='POST'){
        let removed=0;
        for(const [id,job] of window.__fakeJobs){if(['completed','error','cancelled'].includes(job.status)){window.__fakeJobs.delete(id);removed++;}}
        return json({removed});
      }
      if(url==='/api/download'&&method==='POST'){
        const body=JSON.parse(init.body); window.__requestBodies.push(body);
        if(body.url.includes('duplicate')&&!body.force) return json({detail:{message:'Already saved',job_id:'btn-complete',status:'completed'}},409);
        const id=body.force?'btn-forced':'btn-batch-'+window.__requestBodies.length;
        const job=make(id,'queued'); window.__fakeJobs.set(id,job); return json(job);
      }
      const match=url.match(/^\\/api\\/jobs\\/([^/]+)(?:\\/([^/]+))?$/);
      if(match&&window.__fakeJobs.has(decodeURIComponent(match[1]))){
        const id=decodeURIComponent(match[1]), action=match[2]||'', job=window.__fakeJobs.get(id);
        if(action==='logs') return json({logs:['button log'],log_count:1});
        if(action==='cancel'){job.status='cancelled';job.can_retry=true;job.finished_at=3;return json(job);}
        if(action==='retry'){job.status='queued';job.can_retry=false;job.error=null;job.progress=0;job.finished_at=null;return json(job);}
        if(action==='reveal'||action==='open-file') return json({ok:true});
        if(action==='forget'||method==='DELETE'){window.__fakeJobs.delete(id);return json({ok:true});}
      }
      return window.__realFetch(input,init);
    };
    window.confirm=()=>true;
    return true;
  })()`);
  await run(`refreshJobs()`);
  await until(() => run(`state.jobs.has('btn-complete') && state.jobs.has('btn-error-1')`));
  assert.ok(await run(`retryFailedBtn.classList.contains('hidden') === false`));
  await run(`openDownloadsBtn.click()`);
  await until(() => run(`window.__buttonCalls.some(call=>call.url==='/api/open-downloads')`));
  const links = await run(`(() => {
    const multi=state.jobs.get('btn-complete').el;
    const single=state.jobs.get('btn-single').el;
    return {
      zipShown:!multi.querySelector('[data-action="zip"]').classList.contains('hidden'),
      zipHref:multi.querySelector('[data-action="zip"]').getAttribute('href'),
      saveShown:!single.querySelector('[data-action="save"]').classList.contains('hidden'),
      saveHref:single.querySelector('[data-action="save"]').getAttribute('href'),
    };
  })()`);
  assert.deepEqual(links, {
    zipShown:true,zipHref:'/api/jobs/btn-complete/zip',
    saveShown:true,saveHref:'/api/jobs/btn-single/files/single.mp3',
  });
  await run(`(() => {
    const card=state.jobs.get('btn-complete').el;
    card.querySelector('[data-action="open"]').click();
    card.querySelector('[data-action="open-file"]').click();
    card.querySelector('[data-action="copy"]').click();
    card.querySelector('[data-action="logs"]').click();
  })()`);
  await until(() => run(`state.jobs.get('btn-complete').el.querySelector('[data-field="logs"]').textContent==='button log'`));
  assert.ok(await run(`window.__buttonCalls.some(call=>call.url.endsWith('/reveal')) && window.__buttonCalls.some(call=>call.url.endsWith('/open-file'))`));
  assert.equal(await run(`window.__copied`), '/button-test/btn-complete');
  await run(`state.jobs.get('btn-complete').el.querySelector('[data-action="logs"]').click()`);
  await run(`state.jobs.get('btn-error-1').el.querySelector('[data-action="retry"]').click()`);
  await until(() => run(`state.jobs.get('btn-error-1')?.data.status==='queued'`));
  await run(`retryFailedBtn.click()`);
  await until(() => run(`retryFailedBtn.classList.contains('hidden')`));
  await run(`state.jobs.get('btn-active').el.querySelector('[data-action="cancel"]').click()`);
  await until(() => run(`state.jobs.get('btn-active')?.data.status==='cancelled'`));
  assert.ok(await run(`!state.jobs.get('btn-active').el.querySelector('[data-action="retry"]').classList.contains('hidden')`));
  await run(`state.jobs.get('btn-active').el.querySelector('[data-action="retry"]').click()`);
  await until(() => run(`state.jobs.get('btn-active')?.data.status==='queued'`));
  await run(`state.jobs.get('btn-complete').el.querySelector('[data-action="forget"]').click()`);
  await until(() => run(`!state.jobs.has('btn-complete')`));
  await run(`state.jobs.get('btn-single').el.querySelector('[data-action="delete"]').click()`);
  await until(() => run(`!state.jobs.has('btn-single')`));
  await run(`clearBtn.click()`);
  await until(() => run(`!state.jobs.has('btn-clear')`));

  await run(`document.querySelector('[data-source=batch]').click(); batchMode.value='audio'; batchMode.dispatchEvent(new Event('change')); batchInput.value=${JSON.stringify(fixture + '\nhttps://duplicate.test/video')}; batchBtn.click()`);
  await until(() => run(`document.querySelector('#batchStatus').textContent.includes('1 already queued or saved')`));
  assert.equal(await run(`batchInput.value`), '');
  await run(`document.querySelector('[data-source=single]').click()`);
  await run(`state.info={title:'Duplicate button test',webpage_url:'https://duplicate.test/video',thumbnail:null,is_playlist:false,audio_only:true,source_audio:{codec:'mp3',abr:128}}; state.sourceUrl=state.info.webpage_url; setMode('audio'); applyPreset('mp3'); downloadBtn.click()`);
  await until(() => run(`state.jobs.has('btn-forced')`));
  assert.ok(await run(`window.__requestBodies.some(body=>body.force===true)`));
  await run(`window.__androidHealthTest=true; loadHealth();`);
  await until(() => run(`state.platform==='android'`));
  await run(`refreshJobs()`);
  assert.ok(await run(`document.querySelector('#notifyLabel').classList.contains('hidden') && document.querySelector('#cookiesControl').classList.contains('hidden')`));
  assert.ok(await run(`state.jobs.get('btn-forced').el.querySelector('[data-action="copy"]').classList.contains('hidden')`));
  assert.ok(await run(`window.__buttonCalls.some(call=>call.url.endsWith('/forget')) && window.__buttonCalls.some(call=>call.method==='DELETE') && window.__buttonCalls.some(call=>call.url==='/api/jobs/clear-finished')`));
  assert.deepEqual(errors, []);
  console.log('Browser: input, preferences, presets, playlist, filters, batch, download override, queue toolbar and job actions passed.');
  await send('Browser.close').catch(() => {});
} finally {
  socket?.close();
  if (child.exitCode === null) {
    for (let i = 0; child.exitCode === null && i < 20; i++) await sleep(100);
    if (child.exitCode === null) child.kill();
  }
  await rm(profile, {recursive:true, force:true, maxRetries:8, retryDelay:250});
}
