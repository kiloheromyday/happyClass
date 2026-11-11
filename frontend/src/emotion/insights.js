import { h, ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api, downloadCsv } from '../api.js';
import { icon, moodFace } from '../ui.js';

const originNames = { MANUAL: '学生主动反馈', AI: 'AI 识别记录' };
const statuses = { PLANNED: '计划中', DONE: '已实施', CANCELLED: '已取消' };
const percent = value => value == null ? '—' : `${Math.round(value * 100)}%`;
const stamp = value => new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
const clock = value => new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
const emptyEntry = () => ({kind:'PHASE',title:'',content:'',start_minute:0,end_minute:10,status:'PLANNED',outcome:'',version:0});
const ruleFields = value => ({bucket_minutes:value.bucket_minutes,min_records:value.min_records,concern_ratio:value.concern_ratio,consecutive_windows:value.consecutive_windows,version:value.version});

export const InsightsPanel = {
  props: ['initialSessionId'], emits: ['expired','navigate','dirty-change'],
  setup(props,{emit}) {
    const sessions=ref([]), selected=ref(props.initialSessionId?String(props.initialSessionId):'');
    const scope=ref('REAL'), source=ref('ALL'), windowMinutes=ref('5');
    const data=ref(null), loading=ref(false), busy=ref(false), error=ref(''), message=ref('');
    const form=ref(emptyEntry()), editingId=ref(null), formBase=ref(JSON.stringify(emptyEntry()));
    const ruleDraft=ref(null), ruleBase=ref(''), activeFrame=ref(0), confirmingDelete=ref(null);
    let alive=true, reader, boot, writer, requestId, lastSubmitted;
    const entryDirty=computed(()=>JSON.stringify(form.value)!==formBase.value);
    const ruleDirty=computed(()=>ruleDraft.value && JSON.stringify(ruleDraft.value)!==ruleBase.value);
    const dirty=computed(()=>!!(entryDirty.value||ruleDirty.value));
    watch(dirty,value=>emit('dirty-change',value),{flush:'sync'});
    const root=computed(()=>`/api/sessions/${selected.value}/insights`);
    const query=()=>new URLSearchParams({source:source.value,data_scope:scope.value,comparison_minutes:windowMinutes.value});
    const phases=computed(()=>(data.value?.entries||[]).filter(item=>item.kind==='PHASE'));
    const actions=computed(()=>(data.value?.entries||[]).filter(item=>item.kind==='ACTION'));
    const current=computed(()=>data.value?.frames[activeFrame.value]);
    function fail(failure) { error.value=failure.message; if(failure.status===401)emit('expired'); }
    function reset() {
      form.value=emptyEntry(); formBase.value=JSON.stringify(form.value); editingId.value=null;
      requestId=null;lastSubmitted=null;confirmingDelete.value=null;
      if(data.value){ruleDraft.value=ruleFields(data.value.rules);ruleBase.value=JSON.stringify(ruleDraft.value);}
    }
    async function load() {
      reader?.abort(); const request=new AbortController();reader=request;
      loading.value=true;error.value='';data.value=null;activeFrame.value=0;
      try {
        if(!selected.value)return;
        const response=await api(`${root.value}?${query()}`,{signal:request.signal});
        if(alive&&reader===request&&!request.signal.aborted){data.value=response.data;reset();}
      }catch(failure){if(alive&&reader===request&&!request.signal.aborted)fail(failure);}
      finally{if(alive&&reader===request)loading.value=false;}
    }
    async function mutate(path,method,body,successText) {
      if(busy.value)return false;
      writer=new AbortController();busy.value=true;error.value='';message.value='';
      try {
        await api(path,{method,body,signal:writer.signal});
        if(!alive)return false;
        message.value=successText;return true;
      }catch(failure){if(alive&&!writer.signal.aborted)fail(failure);return false;}
      finally{if(alive)busy.value=false;}
    }
    async function saveEntry(event) {
      event.preventDefault();if(ruleDirty.value){error.value='请先保存或放弃规则草稿。';return;}
      const fingerprint=JSON.stringify(form.value);
      if(lastSubmitted!==fingerprint){requestId=crypto.randomUUID();lastSubmitted=fingerprint;}
      const ok=await mutate(`${root.value}/entries${editingId.value?`/${editingId.value}`:''}`,editingId.value?'PUT':'POST',
        {...form.value,request_id:requestId},'教学记录已保存。');
      if(ok){reset();await load();}
    }
    async function saveRules(event) {
      event.preventDefault();if(entryDirty.value){error.value='请先保存或放弃教学记录草稿。';return;}
      if(await mutate(`${root.value}/rules`,'PUT',ruleDraft.value,'规则已保存，已重新计算关注时段。')){reset();await load();}
    }
    function edit(item) {
      if(dirty.value||busy.value)return;
      form.value={...emptyEntry(),...Object.fromEntries(Object.keys(emptyEntry()).map(key=>[key,item[key]]))};
      formBase.value=JSON.stringify(form.value);editingId.value=item.id;requestId=null;lastSubmitted=null;
      document.querySelector('.insight-editor')?.scrollIntoView({behavior:'smooth',block:'center'});
    }
    function propose(signal) {
      if(dirty.value||busy.value)return;
      const minute=Math.round(signal.end_minute);
      form.value={...emptyEntry(),kind:'ACTION',title:'放慢节奏并补充示例',content:`关注时段 ${clock(signal.from_time)}–${clock(signal.to_time)}；先用课堂提问核实理解情况，再决定调整。`,start_minute:minute,end_minute:minute};
      editingId.value=null;formBase.value=JSON.stringify(emptyEntry());
      document.querySelector('.insight-editor')?.scrollIntoView({behavior:'smooth',block:'center'});
    }
    async function remove(item) {
      if(dirty.value)return;
      if(await mutate(`${root.value}/entries/${item.id}?version=${item.version}`,'DELETE',undefined,'记录已删除。')){confirmingDelete.value=null;await load();}
    }
    async function exportCsv() {
      if(busy.value)return;
      busy.value=true;error.value='';writer=new AbortController();
      try{await downloadCsv(`${root.value}/export?${query()}`,writer.signal);if(alive)message.value='复盘报告已导出，包含当前筛选范围和计算规则。';}
      catch(failure){if(alive&&!writer.signal.aborted)fail(failure);}
      finally{if(alive)busy.value=false;}
    }
    onMounted(async()=>{
      boot=new AbortController();loading.value=true;
      try{
        const response=await api('/api/sessions',{signal:boot.signal});if(!alive)return;
        sessions.value=response.data.items;
        if(!selected.value)selected.value=String(sessions.value.find(item=>item.record_count>0)?.id||sessions.value[0]?.id||'');
        await load();
      }catch(failure){if(alive&&!boot.signal.aborted)fail(failure);}
      finally{if(alive)loading.value=false;}
    });
    onBeforeUnmount(()=>{alive=false;reader?.abort();boot?.abort();writer?.abort();emit('dirty-change',false);});
    const changeForm=(key,value)=>{form.value={...form.value,[key]:value};};
    const changeRule=(key,value)=>{ruleDraft.value={...ruleDraft.value,[key]:value};};
    const select=(title,name,value,callback,options,disabled=false)=>h('label',{class:'field'},[h('span',title),h('select',{name,value,disabled:disabled||busy.value||loading.value,onChange:event=>callback(event.target.value)},options.map(([id,text])=>h('option',{value:id},text)))]);
    const input=(title,name,type='text',extra={})=>h('label',{class:'field'},[h('span',title),h('input',{name:`insight_${name}`,type,value:form.value[name],disabled:busy.value,onInput:event=>changeForm(name,type==='number'?Number(event.target.value):event.target.value),...extra})]);
    const textarea=(title,name)=>h('label',{class:'field'},[h('span',title),h('textarea',{name:`insight_${name}`,value:form.value[name],rows:3,maxlength:2000,disabled:busy.value,onInput:event=>changeForm(name,event.target.value)})]);
    const changeKind=value=>{form.value={...form.value,kind:value,end_minute:value==='ACTION'?form.value.start_minute:form.value.start_minute+10};};
    const comparisonCard=metric=>h('div',{class:'insight-comparison',key:metric.source},[
      h('strong',originNames[metric.source]),h('div',{class:'insight-comparison-flow'},[
        h('div',[h('small','调整前'),h('b',percent(metric.before.concern_ratio)),h('span',`${metric.before.total} 条`)]),
        h('span',{'aria-hidden':'true'},'→'),
        h('div',[h('small','调整后'),h('b',percent(metric.after.concern_ratio)),h('span',`${metric.after.total} 条`)]),
      ]),metric.status==='COMPARABLE'?h('p',{class:metric.change_percentage_points<0?'insight-change lower':'insight-change'},`关注类别占比 ${metric.change_percentage_points>0?'+':''}${metric.change_percentage_points} 个百分点`):h('p',{class:'muted'},'样本不足、窗口未完整或尚未实施，暂不计算变化。'),
    ]);
    return()=>h('section',{class:'insights-panel','aria-label':'课堂情绪洞察','aria-busy':loading.value},[
      h('header',{class:'insight-hero'},[
        h('div',[h('p',{class:'eyebrow'},'NOTICE · RESPOND · REFLECT'),h('h2','看见情绪，也看见转机。'),h('p','找到值得停一停的时刻，把教学调整变成可回顾的记录。')]),
        h('div',{class:'insight-hero-faces','aria-hidden':'true'},[moodFace('NEUTRAL',58),moodFace('HAPPY',76)]),
      ]),
      h('div',{class:'insight-toolbar'},[
        select('选择课堂','insight_session',selected.value,value=>{selected.value=value;message.value='';load();},[['','请选择课堂'],...sessions.value.map(item=>[String(item.id),`${item.course_name} · ${item.class_name} · ${stamp(item.starts_at)}`])],dirty.value),
        select('记录来源','insight_source',source.value,value=>{source.value=value;load();},[['ALL','分别分析两种来源'],['MANUAL','学生主动反馈'],['AI','AI 识别记录']],dirty.value),
        select('数据范围','insight_scope',scope.value,value=>{scope.value=value;load();},[['REAL','排除演示数据'],['DEMO','仅演示数据'],['ALL','全部数据']],dirty.value),
        select('前后对比窗口','insight_comparison',windowMinutes.value,value=>{windowMinutes.value=value;load();},[['5','前后各 5 分钟'],['10','前后各 10 分钟'],['15','前后各 15 分钟']],dirty.value),
      ]),
      h('div',{class:'insight-top-actions'},[h('button',{class:'secondary-button',disabled:dirty.value||busy.value||loading.value,onClick:load},[icon('refresh',15),'刷新洞察']),h('button',{class:'secondary-button',disabled:dirty.value||busy.value||!data.value||loading.value,onClick:exportCsv},[icon('download',15),'导出复盘 CSV']),dirty.value?h('button',{class:'quiet-button',disabled:busy.value,onClick:reset},'放弃草稿'):null]),
      error.value?h('p',{class:'form-notice error',role:'alert'},error.value):null,
      message.value?h('p',{class:'form-notice success',role:'status'},message.value):null,
      loading.value?h('p',{class:'insight-empty',role:'status'},'正在整理课堂线索…'):null,
      data.value?h('div',{class:'insight-body'},[
        data.value.summary.demo_count?h('p',{class:'replay-demo-note'},`当前含 ${data.value.summary.demo_count} 条合成演示记录，用于体验流程。`):null,
        h('div',{class:'insight-metrics'},[
          ['反馈记录',data.value.summary.total,'统计次数，不代表人数'],
          ['学生主动反馈',data.value.sources.MANUAL.total,'主动表达的课堂感受'],
          ['AI 识别记录',data.value.sources.AI.total,'单独分析模型分类结果'],
          ['值得关注的时段',data.value.signals.length,'达到当前规则的连续时段'],
        ].map(([title,value,hint])=>h('article',{class:'insight-metric'},[h('span',title),h('strong',String(value)),h('small',hint)]))),
        h('section',{class:'insight-card'},[
          h('div',{class:'insight-section-heading'},[h('div',[h('p',{class:'eyebrow'},'01 / CLASSROOM SIGNALS'),h('h3','这节课，哪些时刻值得关注？')]),h('span',{class:'insight-chip'},`${data.value.window.bucket_minutes} 分钟 / 段`)]),
          h('p',{class:'muted'},`关注类别：低落、生气、担忧、反感。连续 ${data.value.rules.consecutive_windows} 个完整时段，每段至少 ${data.value.rules.min_records} 条记录且关注占比 ≥ ${percent(data.value.rules.concern_ratio)}。`),
          h('div',{class:'insight-signals'},data.value.signals.length?data.value.signals.map(signal=>h('article',{class:'insight-signal',key:signal.id},[
            h('span',{class:'insight-signal-icon','aria-hidden':'true'},'✦'),h('div',[h('span',{class:'insight-chip'},originNames[signal.source]),h('h4',`${clock(signal.from_time)}–${clock(signal.to_time)} · 连续关注时段`),h('p',`${signal.total} 条记录中，${signal.concern_count} 条属于关注类别（${percent(signal.concern_ratio)}）。`),h('small',signal.phase_titles.length?`关联环节：${signal.phase_titles.join('、')}`:'可在下方标注这一时段对应的教学环节。')]),
            h('button',{class:'secondary-button',disabled:dirty.value||busy.value,onClick:()=>propose(signal)},'记录一次教学调整'),
          ])):h('div',{class:'insight-empty'},[moodFace('NEUTRAL',42),h('p',data.value.summary.total?'目前没有连续时段达到提示条件。':'当前范围暂无反馈记录，可调整数据范围或来源。')]))
        ]),
        h('section',{class:'insight-card'},[
          h('div',{class:'insight-section-heading'},[h('div',[h('p',{class:'eyebrow'},'02 / EMOTION MAP'),h('h3','沿着课堂时间，寻找线索')]),h('button',{class:'quiet-button',disabled:dirty.value||busy.value,onClick:()=>emit('navigate',{tab:'replay',sessionId:Number(selected.value)})},'打开卡通情绪回放 →')]),
          h('p',{class:'muted'},'颜色越深，关注类别的占比越高。灰色表示没有记录。记录数够多、时段结束后才会判断。'),
          ...Object.entries(originNames).map(([code,name])=>h('div',{class:'insight-map-row'},[h('strong',name),h('div',{class:'insight-map-track'},data.value.frames.map((frame,index)=>{
            const metric=frame.sources[code];
            return h('button',{class:['insight-map-cell',{selected:index===activeFrame.value,empty:!metric.total,thin:metric.total<data.value.rules.min_records}],type:'button',style:{'--concern-opacity':metric.total?String(.16+(metric.concern_ratio||0)*.78):'0'},title:`${clock(frame.from_time)} · ${metric.total} 条 · ${percent(metric.concern_ratio)}`,'aria-label':`${name} ${clock(frame.from_time)}，${metric.total} 条，关注占比 ${percent(metric.concern_ratio)}`,'aria-pressed':index===activeFrame.value,onClick:()=>activeFrame.value=index},h('span',{class:'sr-only'},`${index+1}`));
          }))])),
          current.value?h('div',{class:'insight-frame-detail'},[h('strong',`${clock(current.value.from_time)}–${clock(current.value.to_time)}`),h('span',`共 ${current.value.total} 条 · ${current.value.complete?'完整时段':'时段尚未完整'}`),h('span',current.value.phase_titles.join(' / ')||'尚未标注教学环节')]):null,
          h('div',{class:'insight-phases'},phases.value.map(item=>h('button',{class:'insight-phase',disabled:dirty.value||busy.value,onClick:()=>edit(item)},[h('strong',item.title),h('span',`第 ${item.start_minute}–${item.end_minute} 分钟`)]))),
        ]),
        h('div',{class:'insight-workbench'},[
          h('section',{class:'insight-card insight-editor'},[
            h('p',{class:'eyebrow'},'03 / TEACHING JOURNAL'),h('h3',editingId.value?'编辑教学记录':'给这一刻，留下一条记录'),
            h('p',{class:'muted'},'标注讲解、讨论、练习等教学环节，或记录放慢节奏、补充示例、短暂休息等调整。时间以开课后分钟计。'),
            h('form',{onSubmit:saveEntry},[
              select('记录类型','insight_kind',form.value.kind,changeKind,[['PHASE','教学环节'],['ACTION','教学调整']],!!editingId.value),
              input('标题','title','text',{required:true,maxlength:120,placeholder:form.value.kind==='PHASE'?'例如：递归概念讲解':'例如：补充图示并现场提问'}),
              h('div',{class:'insight-form-grid'},[input(form.value.kind==='PHASE'?'开始分钟':'发生分钟','start_minute','number',{min:0,max:100000,required:true,onInput:event=>{const value=Number(event.target.value);form.value={...form.value,start_minute:value,...(form.value.kind==='ACTION'?{end_minute:value}:{})};}}),form.value.kind==='PHASE'?input('结束分钟','end_minute','number',{min:form.value.start_minute+1,max:100000,required:true}):select('实施状态','insight_status',form.value.status,value=>changeForm('status',value),Object.entries(statuses))]),
              textarea(form.value.kind==='PHASE'?'教学内容':'采取的措施','content'),
              form.value.kind==='ACTION'?textarea('教师复盘与观察','outcome'):null,
              h('div',{class:'insight-form-actions'},[h('button',{class:'primary-button',type:'submit',disabled:busy.value||!entryDirty.value||ruleDirty.value},busy.value?'正在保存…':'保存教学记录'),h('button',{class:'quiet-button',type:'button',disabled:busy.value,onClick:reset},editingId.value?'退出编辑':'清空草稿')]),
              editingId.value && form.value.kind==='PHASE' ? h('div',{class:'insight-form-actions'},[
                confirmingDelete.value===editingId.value ? h('span',[
                  h('button',{type:'button',class:'quiet-button',disabled:dirty.value||busy.value,onClick:()=>remove(data.value.entries.find(item=>item.id===editingId.value))},'确认删除环节'),
                  h('button',{type:'button',class:'quiet-button',disabled:busy.value,onClick:()=>confirmingDelete.value=null},'取消'),
                ]) : h('button',{type:'button',class:'quiet-button',disabled:dirty.value||busy.value,onClick:()=>confirmingDelete.value=editingId.value},'删除这个教学环节'),
              ]) : null,
            ]),
          ]),
          h('section',{class:'insight-card insight-actions'},[
            h('p',{class:'eyebrow'},'04 / BEFORE & AFTER'),h('h3','调整之后，发生了什么？'),
            h('p',{class:'muted'},`以调整时刻为界，前后各取 ${windowMinutes.value} 分钟。两边都达到最小样本且时间窗口完整时才计算变化。`),
            actions.value.length?actions.value.map(item=>h('article',{class:'insight-action-card',key:item.id},[
              h('div',{class:'insight-section-heading'},[h('h4',item.title),h('span',{class:'insight-chip'},statuses[item.status])]),h('small',`第 ${item.start_minute} 分钟 · ${stamp(item.updated_at)}`),item.content?h('p',item.content):null,
              h('div',{class:'insight-comparison-grid'},item.comparison.sources.map(comparisonCard)),
              item.outcome?h('p',{class:'insight-outcome'},`教师复盘：${item.outcome}`):null,
              h('div',{class:'insight-form-actions'},[h('button',{class:'quiet-button',disabled:dirty.value||busy.value,onClick:()=>edit(item)},'编辑与补充复盘'),confirmingDelete.value===item.id?h('span',[h('button',{class:'quiet-button',disabled:busy.value||dirty.value,onClick:()=>remove(item)},'确认删除'),h('button',{class:'quiet-button',onClick:()=>confirmingDelete.value=null},'取消')]):h('button',{class:'quiet-button',disabled:busy.value||dirty.value,onClick:()=>confirmingDelete.value=item.id},'删除')]),
            ])):h('div',{class:'insight-empty'},[icon('book',34),h('p','还没有教学调整记录。从左侧添加，或从关注时段生成一条计划。')]),
            h('p',{class:'insight-method-note'},'前后对比按来源分开算，可以结合当时的课堂情况一起看。'),
          ]),
        ]),
        h('details',{class:'insight-card insight-rules'},[
          h('summary','洞察规则与计算方法'),
          h('p',{class:'muted'},'老师可以修改提示条件。保存后会用原记录重新计算。中间有空白时段时，会重新开始计数。'),
          ruleDraft.value?h('form',{onSubmit:saveRules},[
            select('每段时长','insight_rule_bucket',String(ruleDraft.value.bucket_minutes),value=>changeRule('bucket_minutes',Number(value)),[['1','1 分钟'],['5','5 分钟'],['10','10 分钟']]),
            ...[['min_records','每段最少记录',3,1000,1],['concern_ratio','关注类别占比阈值',.3,1,.05],['consecutive_windows','连续完整时段数',2,6,1]].map(([key,title,min,max,step])=>h('label',{class:'field'},[h('span',title),h('input',{type:'number',name:`insight_rule_${key}`,value:ruleDraft.value[key],min,max,step,required:true,disabled:busy.value,onInput:event=>changeRule(key,Number(event.target.value))})])),
            h('button',{class:'primary-button',disabled:busy.value||!ruleDirty.value||entryDirty.value},'保存并重新计算'),
          ]):null,
          h('p',{class:'insight-method-note'},`按反馈次数分析，不进行学生身份匹配。默认关注分类为低落、生气、担忧、反感；平静与惊讶不自动归为问题。当前隐私模式：${{STANDARD:'标准',ANONYMOUS:'匿名',AGGREGATE:'仅聚合'}[data.value.privacy_mode]}。超长课堂最多生成 360 段，必要时自动合并粒度。`),
        ]),
        h('p',{class:'insight-footer'},`更新于 ${stamp(data.value.updated_at)} · 北京时间 · 规则 v${data.value.rules.version}`),
      ]):!loading.value&&!error.value?h('p',{class:'insight-empty'},'请选择有权限访问的课堂。'):null,
    ]);
  },
};
