const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = child => { if (child.parent) { child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({ createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text), setText: (n, value) => n.text = value, setElementText: (n, value) => { n.text = value; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value, insert(n, parent, anchor) { detach(n); const i = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(i < 0 ? parent.children.length : i, 0, n); n.parent = parent; }, remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null });
const walk = n => [n, ...n.children.flatMap(walk)], text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, condition) => { const n = walk(root).find(condition); assert(n, 'Control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const field = (root, name) => find(root, n => n.props.name === name);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = node('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };


(async()=>{
 const {ReplayPanel}=await import('../../frontend/src/emotion/replay.js');
 const original={fetch:global.fetch,document:global.document,setInterval:global.setInterval,clearInterval:global.clearInterval};
 const timers=new Map(),listeners=new Map();let seq=0,mounted,late,lateSignal;
 global.document={hidden:false,addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
 global.setInterval=(fn,ms)=>{timers.set(++seq,{fn,ms});return seq;};global.clearInterval=id=>timers.delete(id);
 const em=(code,count)=>['HAPPY','NEUTRAL','SAD','ANGRY','SURPRISED','FEAR','DISGUST'].map(emotion=>({emotion,count:emotion===code?count:0}));
 const sample=(source='ALL')=>({session:{id:1,course_id:1},source,data_scope:'ALL',bucket_minutes:1,requested_bucket_minutes:1,updated_at:'2026-11-09T01:03:00Z',has_started:true,includes_after_class:false,window:{from_time:'2026-11-09T01:00:00Z',to_time:'2026-11-09T01:03:00Z',class_ends_at:'2026-11-09T01:03:00Z'},summary:{total:source==='MANUAL'?2:3,manual_count:2,ai_count:source==='MANUAL'?0:1},frames:[
 {index:0,from_time:'2026-11-09T01:00:00Z',to_time:'2026-11-09T01:01:00Z',total:2,manual_count:2,ai_count:0,dominant_emotions:['HAPPY'],emotions:em('HAPPY',2)},
 {index:1,from_time:'2026-11-09T01:01:00Z',to_time:'2026-11-09T01:02:00Z',total:0,manual_count:0,ai_count:0,dominant_emotions:[],emotions:em('HAPPY',0)},
 {index:2,from_time:'2026-11-09T01:02:00Z',to_time:'2026-11-09T01:03:00Z',total:source==='MANUAL'?0:1,manual_count:0,ai_count:source==='MANUAL'?0:1,dominant_emotions:source==='MANUAL'?[]:['SAD'],emotions:em('SAD',source==='MANUAL'?0:1)}]});
 const json=data=>new Response(JSON.stringify({data}),{status:200});
 global.fetch=async(path,opts={})=>{
  if(path==='/api/sessions')return json({items:[{id:1,course_name:'Replay course',class_name:'Class A',starts_at:'2026-11-09T01:00:00Z',record_count:3}]});
  const u=new URL(path,'http://local.test');
  if(u.searchParams.get('source')==='AI'){lateSignal=opts.signal;return new Promise(resolve=>late=resolve);}
  return json(sample(u.searchParams.get('source')));
 };
 const slider=()=>find(mounted.root,n=>n.props['aria-label']==='拖动课堂情绪时间轴');
 const playButton=()=>find(mounted.root,n=>n.type==='button'&&String(n.props.class).includes('replay-play'));
 const sourceField=()=>field(mounted.root,'replay_source');
 try{
  mounted=mount(ReplayPanel,{});await settle();
  assert(text(mounted.root).includes('本时段最多：开心'));
  slider().props.onInput({target:{value:'2'}});await nextTick();assert(text(mounted.root).includes('本时段最多：低落'));
  playButton().props.onClick();await nextTick();assert.equal(slider().props.value,0);assert.equal(timers.size,1);
  [...timers.values()][0].fn();await nextTick();assert(text(mounted.root).includes('没有反馈记录，不代表大家都是平静'));
  [...timers.values()][0].fn();await nextTick();assert.equal(timers.size,0);assert.equal(playButton().props['aria-pressed'],false);
  slider().props.onInput({target:{value:'0'}});await nextTick();
  find(mounted.root,n=>n.props['aria-label']==='下个有反馈时刻').props.onClick();await nextTick();assert.equal(slider().props.value,2);
  playButton().props.onClick();field(mounted.root,'replay_speed').props.onChange({target:{value:'4'}});await nextTick();assert.equal([...timers.values()][0].ms,250);
  sourceField().props.onChange({target:{value:'AI'}});await settle();assert.equal(timers.size,0);
  sourceField().props.onChange({target:{value:'MANUAL'}});await settle();assert(lateSignal.aborted);
  const stale=sample();stale.summary.total=777;late(json(stale));await settle();assert(!text(mounted.root).includes('777'));assert.equal(sourceField().props.value,'MANUAL');
  playButton().props.onClick();await nextTick();assert.equal(timers.size,1);
  global.document.hidden=true;listeners.get('visibilitychange')();await nextTick();assert.equal(timers.size,0);
  mounted.app.unmount();mounted=null;assert.equal(listeners.size,0);
  const noData=sample();noData.summary={total:0,manual_count:0,ai_count:0};noData.has_started=false;noData.frames=[{...noData.frames[1],index:0}];
  global.fetch=async path=>path==='/api/sessions'?json({items:[{id:1,course_name:'Empty',class_name:'Future',starts_at:'2026-11-09T01:00:00Z'}]}):json(noData);
  mounted=mount(ReplayPanel,{});await settle();assert(playButton().props.disabled);assert(slider().props.disabled);assert(text(mounted.root).includes('还没有开始'));
  console.log('Replay checks passed: drag, empty gaps, nonempty jumps, speed, end stop, source cancellation, stale-response isolation, hidden-tab pause, cleanup and upcoming empty state.');
 }finally{mounted?.app.unmount();Object.assign(global,original);}
})().catch(e=>{console.error(e);process.exitCode=1});
