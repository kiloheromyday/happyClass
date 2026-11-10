const assert = require('node:assert/strict');
const {createRenderer,h,nextTick} = require('../../frontend/node_modules/vue');
const node=(type,text='')=>({type,text,props:{},children:[],parent:null});
const detach=n=>{if(n.parent){n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=null;}};
const renderer=createRenderer({createElement:type=>node(type),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(n,v)=>n.text=v,setElementText:(n,v)=>{n.text=v;n.children=[];},patchProp:(n,key,old,v)=>n.props[key]=v,insert(n,parent,anchor){detach(n);const i=anchor?parent.children.indexOf(anchor):-1;parent.children.splice(i<0?parent.children.length:i,0,n);n.parent=parent;},remove:detach,parentNode:n=>n.parent,nextSibling:n=>n.parent?.children[n.parent.children.indexOf(n)+1]||null});
const walk=n=>[n,...n.children.flatMap(walk)],text=n=>(n.type==='#comment'?'':n.text)+n.children.map(text).join('');
const find=(root,predicate)=>{const result=walk(root).find(predicate);assert(result,'Control not found');return result;};
const button=(root,label)=>find(root,n=>n.type==='button'&&text(n)===label);
const field=(root,name)=>find(root,n=>n.props.name===name);
const settle=async()=>{for(let i=0;i<8;i++){await new Promise(setImmediate);await nextTick();}};
const mount=(component,props)=>{const root=node('root'),app=renderer.createApp({render:()=>h(component,props)});app.mount(root);return{root,app};};
const json=(data,status=200,message='')=>new Response(JSON.stringify({data,message}),{status});
const metric=(total=0,concern_count=0)=>({total,concern_count,concern_ratio:total?concern_count/total:null,demo_count:0});
const sample=()=>({
 session:{id:1,course_id:1},privacy_mode:'AGGREGATE',rules:{bucket_minutes:5,min_records:5,concern_ratio:.6,consecutive_windows:2,version:0},
 updated_at:'2026-11-10T01:20:00Z',window:{bucket_minutes:5},summary:{total:10,demo_count:0},sources:{MANUAL:metric(10,8),AI:metric()},
 signals:[{id:'s1',source:'MANUAL',from_time:'2026-11-10T01:00:00Z',to_time:'2026-11-10T01:10:00Z',end_minute:10,total:10,concern_count:8,concern_ratio:.8,phase_titles:[]}],
 frames:[{from_time:'2026-11-10T01:00:00Z',to_time:'2026-11-10T01:05:00Z',total:5,complete:true,phase_titles:[],sources:{MANUAL:metric(5,4),AI:metric()}}],entries:[],
});

(async()=>{
 const {InsightsPanel}=await import('../../frontend/src/emotion/insights.js');
 const original={fetch:global.fetch,document:global.document};let mounted,writeFailure=false,ruleFailure=false,late,lateSignal;
 const calls=[],dirty=[];let current=sample();
 global.document={querySelector:()=>null};
 global.fetch=async(path,opts={})=>{
  calls.push({path,method:opts.method||'GET',body:opts.body?JSON.parse(opts.body):undefined});
  if(path==='/api/sessions')return json({items:[{id:1,course_name:'Course',class_name:'Class',starts_at:'2026-11-10T01:00:00Z',record_count:10}]});
  if(opts.method==='POST')return writeFailure?json(null,0+503,'暂时不可用'):json({id:1},201);
  if(opts.method==='PUT')return ruleFailure?json(null,409,'规则版本已变化'):json({version:1});
  if(new URL(path,'http://test').searchParams.get('source')==='AI'){lateSignal=opts.signal;return new Promise(resolve=>late=resolve);}
  return json(current);
 };
 try{
  mounted=mount(InsightsPanel,{onDirtyChange:value=>dirty.push(value)});await settle();
  assert(calls.some(call=>call.path.includes('data_scope=REAL')),'default excludes synthetic records');
  assert(text(mounted.root).includes('连续关注时段'));
  button(mounted.root,'记录一次教学调整').props.onClick();await settle();
  assert.equal(field(mounted.root,'insight_kind').props.value,'ACTION');
  assert.equal(field(mounted.root,'insight_start_minute').props.value,10);
  assert(dirty.at(-1));assert(field(mounted.root,'insight_session').props.disabled);
  const editorForm=()=>find(mounted.root,n=>n.type==='form'&&walk(n).some(child=>child.props.name==='insight_title'));
  writeFailure=true;await editorForm().props.onSubmit({preventDefault(){}});await settle();
  assert(text(mounted.root).includes('暂时不可用'));
  assert.equal(field(mounted.root,'insight_title').props.value,'放慢节奏并补充示例');
  const first=calls.filter(call=>call.method==='POST').at(-1).body;
  writeFailure=false;await editorForm().props.onSubmit({preventDefault(){}});await settle();
  const retried=calls.filter(call=>call.method==='POST').at(-1).body;
  assert.equal(first.request_id,retried.request_id,'lost-response retry keeps same UUID');
  assert(!dirty.at(-1));assert.equal(field(mounted.root,'insight_title').props.value,'');
  field(mounted.root,'insight_rule_min_records').props.onInput({target:{value:'8'}});await settle();
  assert(dirty.at(-1));assert(button(mounted.root,'刷新洞察').props.disabled);
  ruleFailure=true;const rulesForm=find(mounted.root,n=>n.type==='form'&&walk(n).some(child=>child.props.name==='insight_rule_min_records'));
  await rulesForm.props.onSubmit({preventDefault(){}});await settle();
  assert.equal(field(mounted.root,'insight_rule_min_records').props.value,8);assert(dirty.at(-1));
  button(mounted.root,'放弃草稿').props.onClick();await settle();assert(!dirty.at(-1));
  field(mounted.root,'insight_source').props.onChange({target:{value:'AI'}});await settle();
  field(mounted.root,'insight_source').props.onChange({target:{value:'MANUAL'}});await settle();
  assert(lateSignal.aborted);const stale=sample();stale.summary.total=999;late(json(stale));await settle();
  assert(!text(mounted.root).includes('999'));assert.equal(field(mounted.root,'insight_source').props.value,'MANUAL');
  field(mounted.root,'insight_source').props.onChange({target:{value:'AI'}});await settle();
  mounted.app.unmount();mounted=null;assert(lateSignal.aborted);late(json(sample()));await settle();
  assert.equal(dirty.at(-1),false);
  current=sample();current.signals=[];current.summary.total=0;global.fetch=async path=>path==='/api/sessions'?json({items:[{id:1,course_name:'Empty',class_name:'A',starts_at:'2026-11-10T01:00:00Z'}]}):json(current);
  mounted=mount(InsightsPanel,{});await settle();assert(text(mounted.root).includes('当前范围暂无反馈记录'));assert(!text(mounted.root).includes('连续关注时段'));
  console.log('Insights interactions passed: source/default scope, signal-to-action draft, dirty guards, idempotent retry, rule conflict preserves draft, discard, stale-response cancellation, unmount and empty state.');
 }finally{mounted?.app.unmount();Object.assign(global,original);}
})().catch(error=>{console.error(error);process.exitCode=1;});
