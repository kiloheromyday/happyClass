import { h, ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { icon, moodFace } from '../ui.js';

const moods = [['HAPPY','开心','#b9abff'],['NEUTRAL','平静','#8bd8df'],['SURPRISED','惊讶','#a5e5cb'],['SAD','低落','#9dbcf7'],['ANGRY','生气','#f3a2b8'],['FEAR','担忧','#eac994'],['DISGUST','反感','#b9c99d']];
const label = code => moods.find(item => item[0] === code)?.[1] || code;
const clock = value => new Intl.DateTimeFormat('zh-CN', { timeZone:'Asia/Shanghai', hour:'2-digit', minute:'2-digit', hour12:false }).format(new Date(value));
const fullStamp = value => new Intl.DateTimeFormat('zh-CN', { timeZone:'Asia/Shanghai', month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false }).format(new Date(value));

export const ReplayPanel = {
  props: ['initialSessionId'], emits: ['expired', 'navigate'],
  setup(props, { emit }) {
    const sessions = ref([]), selected = ref(props.initialSessionId ? String(props.initialSessionId) : '');
    const source = ref('ALL'), scope = ref('ALL'), bucket = ref('1');
    const data = ref(null), index = ref(0), loading = ref(false), error = ref(''), playing = ref(false), speed = ref(1);
    let controller, bootController, timer, alive = true;
    const frames = computed(() => data.value?.frames || []);
    const current = computed(() => frames.value[index.value]);
    const dominant = computed(() => current.value?.dominant_emotions || []);
    const peak = computed(() => Math.max(1, ...frames.value.map(frame => frame.total)));
    const moment = computed(() => current.value ? `${clock(current.value.from_time)} — ${clock(current.value.to_time)}` : '—');
    const progress = computed(() => frames.value.length > 1 ? index.value / (frames.value.length-1)*100 : 0);
    function pause() { clearInterval(timer); timer = null; playing.value = false; }
    function seek(value) { pause(); index.value = Math.max(0, Math.min(frames.value.length-1, Number(value) || 0)); }
    function play() {
      if (playing.value) { pause(); return; }
      if (frames.value.length < 2 || !data.value.summary.total) return;
      if (index.value >= frames.value.length-1) index.value = 0;
      playing.value = true;
      timer = setInterval(() => {
        if (index.value < frames.value.length-1) index.value++;
        if (index.value >= frames.value.length-1) pause();
      }, 1000 / speed.value);
    }
    function setSpeed(value) { const resume = playing.value; pause(); speed.value = Number(value); if (resume) play(); }
    function jump(direction) {
      pause(); let next = index.value + direction;
      while (next >= 0 && next < frames.value.length) { if (frames.value[next].total) { index.value = next; return; } next += direction; }
    }
    const canJump = direction => frames.value.some((frame, i) => frame.total > 0 && (direction < 0 ? i < index.value : i > index.value));
    async function load() {
      pause(); controller?.abort(); controller = new AbortController(); const request = controller;
      data.value = null; index.value = 0; error.value = ''; loading.value = true;
      try {
        if (!selected.value) return;
        const query = new URLSearchParams({source:source.value,data_scope:scope.value,bucket_minutes:bucket.value});
        const result = await api(`/api/sessions/${selected.value}/emotion-replay?${query}`, {signal:request.signal});
        if (alive && !request.signal.aborted) { data.value = result.data; index.value = Math.max(0,result.data.frames.findIndex(frame => frame.total > 0)); }
      } catch (failure) { if (alive && !request.signal.aborted) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (controller === request) loading.value = false; }
    }
    function visibility() { if (document.hidden) pause(); }
    onMounted(async () => {
      document.addEventListener('visibilitychange',visibility); bootController = new AbortController(); loading.value = true;
      try {
        const result = await api('/api/sessions',{signal:bootController.signal});
        if (!alive) return;
        sessions.value = result.data.items;
        if (!selected.value) selected.value = String(sessions.value.find(item => item.record_count > 0)?.id || sessions.value[0]?.id || '');
        await load();
      } catch (failure) { if (alive && !bootController.signal.aborted) { error.value = failure.message; if (failure.status === 401) emit('expired'); } }
      finally { if (alive) loading.value = false; }
    });
    onBeforeUnmount(() => { alive = false; pause(); controller?.abort(); bootController?.abort(); document.removeEventListener('visibilitychange',visibility); });
    const filter = (title, name, value, change, options) => h('label', {class:'field'}, [h('span',title), h('select',{name,value,disabled:loading.value,onChange:event=>{change(event.target.value);load();}}, options.map(([id,text])=>h('option',{value:id},text)))]);
    return () => h('section', {class:'replay-panel','aria-label':'课堂情绪回放','aria-busy':loading.value}, [
      h('div',{class:'section-title'},[h('div',[h('p',{class:'eyebrow'},'CLASSROOM MOOD THEATER'),h('h2','课堂情绪回放')]),h('button',{type:'button',class:'secondary-button',disabled:loading.value||!selected.value,onClick:load},[icon('refresh',15),'刷新回放'])]),
      h('p',{class:'replay-intro'},'把时间轻轻往回拨，看看课堂里的每一种感受。'),
      h('div',{class:'replay-filters'},[
        filter('选择课堂','replay_session',selected.value,value=>selected.value=value,[['','请选择课堂'],...sessions.value.map(item=>[String(item.id),`${item.course_name} · ${item.class_name} · ${fullStamp(item.starts_at)}`])]),
        filter('记录来源','replay_source',source.value,value=>source.value=value,[['ALL','全部来源'],['MANUAL','学生主动反馈'],['AI','AI 识别记录']]),
        filter('数据范围','replay_scope',scope.value,value=>scope.value=value,[['ALL','全部数据'],['REAL','真实数据'],['DEMO','演示数据']]),
        filter('时间粒度','replay_bucket',bucket.value,value=>bucket.value=value,[['1','每 1 分钟'],['5','每 5 分钟'],['10','每 10 分钟']]),
      ]),
      error.value ? h('p',{class:'form-notice',role:'alert'},error.value) : null,
      loading.value ? h('div',{class:'replay-loading',role:'status'},[h('span',{class:'loading-ring'}),'正在整理这节课的情绪片段…']) : null,
      data.value && current.value ? h('div',{class:'replay-experience'},[
        h('div',{class:'replay-overview'},[h('span',[h('strong',String(data.value.summary.total)),' 条反馈记录']),h('span',`手动 ${data.value.summary.manual_count} · AI ${data.value.summary.ai_count}`),h('span',{class:'replay-snapshot'},`更新于 ${clock(data.value.updated_at)} · 北京时间`)]),
        data.value.demo_record_count ? h('p',{class:'replay-demo-note'},`含 ${data.value.demo_record_count} 条合成演示记录，用于体验回放效果，不是实际情绪识别结果。`) : null,
        h('div',{class:['replay-stage',{'is-playing':playing.value,'has-records':current.value.total>0}]},[
          h('div',{class:'replay-stage-orbit','aria-hidden':'true'}),h('span',{class:'replay-stage-star star-one','aria-hidden':'true'},'✧'),h('span',{class:'replay-stage-star star-two','aria-hidden':'true'},'✦'),
          h('div',{class:'replay-moment'},[h('span','正在回看'),h('strong',moment.value),h('small',current.value.from_time >= data.value.window.class_ends_at ? '课后反馈时段' : '课堂时段')]),
          h('div',{class:'replay-cast'},moods.map(([code,name,color],i)=>{
            const count = current.value.emotions.find(item=>item.emotion===code)?.count || 0;
            return h('div',{class:['replay-character',{'is-dominant':dominant.value.includes(code),'is-quiet':!count}],style:{'--mood-color':color,'--mood-delay':`${i*.14}s`},key:code},[h('span',{class:'replay-count'},count?`${count} 条`:'—'),h('div',{class:'replay-mascot'},moodFace(code,96)),h('strong',name),h('span',{class:'replay-character-shadow','aria-hidden':'true'})]);
          })),
          h('p',{class:'replay-stage-caption',role:'status'},!data.value.has_started?'这节课还没有开始。':!current.value.total?'这段时间还没有反馈。':`本时段最多：${dominant.value.map(label).join('、')}${dominant.value.length>1?'（并列）':''} · 共 ${current.value.total} 条记录`),
        ]),
        h('section',{class:'replay-player','aria-label':'情绪时间轴播放器'},[
          h('div',{class:'replay-transport'},[
            h('button',{class:'replay-play',type:'button',disabled:frames.value.length<2||!data.value.summary.total,onClick:play,'aria-pressed':playing.value},[h('span',{'aria-hidden':'true'},playing.value?'Ⅱ':'▶'),playing.value?'暂停':'播放回放']),
            h('button',{class:'secondary-button',type:'button',disabled:!canJump(-1),onClick:()=>jump(-1),'aria-label':'上个有反馈时刻'},'← 上个时刻'),
            h('button',{class:'secondary-button',type:'button',disabled:!canJump(1),onClick:()=>jump(1),'aria-label':'下个有反馈时刻'},'下个时刻 →'),
            h('label',{class:'replay-speed'},['播放速度',h('select',{name:'replay_speed',value:String(speed.value),onChange:event=>setSpeed(event.target.value)},[1,2,4].map(value=>h('option',{value:String(value)},`${value}×`)))]),
          ]),
          h('div',{class:'replay-density','aria-label':'各时段反馈数量'},frames.value.map((frame,i)=>h('button',{type:'button',class:{selected:i===index.value,empty:!frame.total},style:{height:`${frame.total?Math.max(8,frame.total/peak.value*100):5}%`},title:`${clock(frame.from_time)} · ${frame.total} 条`,tabindex:i===index.value?0:-1,'aria-label':`${clock(frame.from_time)}，${frame.total} 条反馈`,onClick:()=>seek(i)},h('span',{class:'sr-only'},String(frame.total))))),
          h('input',{class:'replay-slider',type:'range',min:0,max:Math.max(0,frames.value.length-1),step:1,value:index.value,disabled:frames.value.length<2,'aria-label':'拖动课堂情绪时间轴','aria-valuetext':`${moment.value}，${current.value.total} 条反馈`,style:{'--replay-progress':`${progress.value}%`},onInput:event=>seek(event.target.value)}),
          h('div',{class:'replay-time-labels'},[h('span',fullStamp(data.value.window.from_time)),h('strong',`第 ${index.value+1} / ${frames.value.length} 段`),h('span',fullStamp(data.value.window.to_time))]),
          h('p',{class:'replay-player-hint'},`拖动滑块，或点击上方的小柱子跳转。1× 每秒推进一个时段，每段 ${data.value.bucket_minutes} 分钟。`),
        ]),
        h('div',{class:'replay-moment-stats'},[h('div',[h('span','当前时段'),h('strong',`${current.value.total} 条`)]),h('div',[h('span','学生主动反馈'),h('strong',`${current.value.manual_count} 条`)]),h('div',[h('span','AI 识别记录'),h('strong',`${current.value.ai_count} 条`)])]),
        h('p',{class:'replay-boundary-note'},`按表情记录的条数回放。画面里的卡通角色不对应学生。${data.value.includes_after_class?'包含下课后 30 分钟反馈窗口内的已有记录。':''}${data.value.bucket_minutes!==data.value.requested_bucket_minutes?'这节课较长，时间轴用了更宽的时段。':''}`),
        h('button',{type:'button',class:'quiet-button',onClick:()=>emit('navigate',{tab:'classroom',sessionId:Number(selected.value),courseId:data.value.session.course_id})},['打开对应课堂',icon('arrow',15)]),
        h('button',{type:'button',class:'secondary-button',onClick:()=>emit('navigate',{tab:'insights',sessionId:Number(selected.value)})},['查看课堂情绪洞察',icon('chart',15)]),
      ]) : !loading.value && !error.value ? h('div',{class:'empty-state'},[icon('history',30),h('h3','选择一节课，开启情绪小剧场'),h('p','有权限访问的课堂会出现在上方列表中。')]) : null,
    ]);
  },
};
