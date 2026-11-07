import { Avatar } from './avatar.js';
import { h, ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon, learningStyles } from './ui.js';
import { BuddyWallPanel } from './wall.js';

export const BuddiesPanel = {
  props: ['user'], emits: ['expired', 'dirty-change'],
  setup(props, { emit }) {
    const wallOwner = ref(null);
    const data = ref({ friends: [], incoming: [], outgoing: [] }), tab = ref('friends');
    const filters = reactive({ q: '', scope: 'all', interests: '', major: '', grade: '', learning_style: '', relationship: 'all', common_course: false });
    const hasCriteria = computed(() => [filters.q, filters.interests, filters.major, filters.grade, filters.learning_style].some(value => value.trim()) || filters.common_course || filters.relationship !== 'all');
    const results = ref([]), searched = ref(false), loading = ref(false), searching = ref(false), busy = ref(false), searchTotal = ref(0), searchOffset = ref(0);
    let applied = null;
    const error = ref(''), message = ref(''), removeId = ref(null);
    const controller = new AbortController(); let disposed = false;
    onBeforeUnmount(() => { disposed = true; controller.abort(); });
    function fail(failure) { if (!disposed) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
    function syncResult() {
      results.value = results.value.map(person => {
        for (const [key, state] of [['friends', 'FRIEND'], ['incoming', 'INCOMING'], ['outgoing', 'OUTGOING']]) {
          const existing = data.value[key].find(item => item.id === person.id);
          if (existing) return { ...person, relationship: state, request_id: existing.request_id };
        }
        return { ...person, relationship: 'NONE', request_id: null };
      });
    }
    async function refresh() {
      loading.value = true;
      try { const result = await api('/api/buddies', { signal: controller.signal }); if (!disposed) { data.value = result.data; syncResult(); } }
      finally { if (!disposed) loading.value = false; }
    }
    onMounted(async () => { try { await refresh(); } catch (failure) { fail(failure); } });
    function invalidate() { results.value = []; searched.value = false; searchTotal.value = 0; searchOffset.value = 0; applied = null; }
    async function fetchSearch(selected, offset) {
      const query = new URLSearchParams(Object.entries(selected).filter(([, value]) => value !== '').map(([key, value]) => [key, String(value)]));
      query.set('limit', '12'); query.set('offset', String(offset));
      const result = await api('/api/buddies/search?' + query, { signal: controller.signal });
      if (disposed) return;
      results.value = result.data.items; searchTotal.value = result.data.total ?? result.data.items.length; searchOffset.value = offset; applied = selected; searched.value = true;
      if (offset > 0 && !results.value.length && searchTotal.value < offset + 1) await fetchSearch(selected, Math.max(0, Math.ceil(searchTotal.value / 12) - 1) * 12);
    }
    async function search(event, nextOffset = 0) {
      event?.preventDefault(); if (searching.value || busy.value || loading.value || !hasCriteria.value) return;
      searching.value = true; error.value = message.value = ''; results.value = []; searched.value = false;
      try {
        const selected = nextOffset > 0 && applied ? applied : { ...filters };
        await fetchSearch(selected, nextOffset);
      } catch (failure) { fail(failure); }
      finally { if (!disposed) searching.value = false; }
    }
    async function action(path, method, body, feedback) {
      if (busy.value || loading.value || searching.value) return;
      busy.value = true; error.value = message.value = ''; removeId.value = null;
      try {
        await api(path, { method, body, signal: controller.signal });
        if (disposed) return;
        await refresh();
        if (!disposed) {
          message.value = feedback;
          if (applied && searched.value) {
            try { await fetchSearch(applied, searchOffset.value); }
            catch (failure) { fail(failure); if (!disposed) message.value = feedback + '，搜索结果暂未刷新。'; }
          }
        }
      } catch (failure) { fail(failure); }
      finally { if (!disposed) busy.value = false; }
    }
    const locked = () => busy.value || loading.value || searching.value;
    const send = person => action('/api/buddies/requests', 'POST', { user_id: person.id }, '学伴申请已发送');
    const accept = person => action(`/api/buddies/requests/${person.request_id}/accept`, 'POST', undefined, '已成为学伴');
    const dismiss = (person, outgoing) => action(`/api/buddies/requests/${person.request_id}`, 'DELETE', undefined, outgoing ? '申请已撤回' : '已婉拒申请');
    function controls(person, kind) {
      if (kind === 'search') {
        if (person.relationship === 'NONE') return h('button', { class: 'secondary-button', disabled: locked(), onClick: () => send(person) }, '添加学伴');
        if (person.relationship === 'INCOMING') return h('button', { class: 'secondary-button', disabled: locked(), onClick: () => accept(person) }, '同意申请');
        return h('span', { class: 'buddy-state' }, person.relationship === 'FRIEND' ? '已是学伴' : '等待对方回应');
      }
      if (kind === 'incoming') return [h('button', { class: 'secondary-button buddy-accept', disabled: locked(), onClick: () => accept(person) }, '同意'), h('button', { class: 'text-button', disabled: locked(), onClick: () => dismiss(person, false) }, '婉拒')];
      if (kind === 'outgoing') return h('button', { class: 'text-button', disabled: locked(), onClick: () => dismiss(person, true) }, '撤回申请');
      if (removeId.value === person.id) return [h('button', { class: 'text-button danger', disabled: locked(), onClick: () => action(`/api/buddies/${person.id}`, 'DELETE', undefined, '已移除学伴') }, '确认移除'), h('button', { class: 'text-button', onClick: () => removeId.value = null }, '取消')];
      return h('button', { class: 'text-button', disabled: locked(), onClick: () => removeId.value = person.id }, '移除学伴');
    }
    function card(person, kind) {
      return h('article', { class: 'buddy-card', key: person.id }, [
        h('div', { class: 'buddy-person' }, [h(Avatar, { person }), h('div', { class: 'buddy-name' }, [h('strong', person.nickname || person.username), h('span', `@${person.username}`)])]),
        h('p', { class: 'buddy-bio' }, person.bio || '还没有填写简介。'),
        person.interests ? h('span', { class: 'interest-tag' }, [icon('book', 13), person.interests]) : null,
        person.major || person.grade || person.learning_style ? h('div', { class: 'buddy-traits' }, [person.major, person.grade, person.learning_style ? learningStyles[person.learning_style] : ''].filter(Boolean).map(value => h('span', value))) : null,
        person.study_goal ? h('p', { class: 'buddy-study-goal' }, [h('span', '学习目标'), person.study_goal]) : null,
        h('div', { class: 'buddy-card-actions' }, [kind === 'friends' ? h('button', { class: 'secondary-button', disabled: locked(), onClick: () => wallOwner.value = person.id }, '去留言') : null, controls(person, kind)]),
      ]);
    }
    return () => wallOwner.value ? h(BuddyWallPanel, { key: wallOwner.value, ownerId: wallOwner.value, user: props.user, onBack: () => wallOwner.value = null, onExpired: () => emit('expired'), onDirtyChange: value => emit('dirty-change', value) }) : h('section', { class: 'buddies-panel' }, [
      h('div', { class: 'section-title' }, [h('h2', '好友学伴'), h('button', { type: 'button', class: 'secondary-button', disabled: locked(), onClick: async () => { error.value = ''; try { await refresh(); } catch (failure) { fail(failure); } } }, [icon('refresh', 15), '刷新'])]),
      h('p', { class: 'muted' }, '找到一起学习的人，让课堂多一份陪伴。'),
      props.user ? h('button', { class: 'secondary-button', onClick: () => wallOwner.value = props.user.id }, [icon('leaf', 15), '我的留言墙']) : null,
      h('form', { class: 'buddy-search-form', onSubmit: search }, [
        h('div', { class: 'buddy-search' }, [
          h('label', { class: 'field' }, [h('span', '查找学伴'), h('input', { type: 'search', name: 'buddy_username', value: filters.q, onInput: event => { filters.q = event.target.value; invalidate(); }, placeholder: '搜昵称、兴趣、专业或学习目标', maxlength: 120, autocapitalize: 'none', autocomplete: 'off', spellcheck: false, disabled: locked() })]),
          h('button', { class: 'primary-button', disabled: locked() || !hasCriteria.value }, searching.value ? '正在查找…' : '查找'),
        ]),
        h('details', { class: 'buddy-filter-details' }, [h('summary', '更多筛选'), h('div', { class: 'buddy-filter-grid' }, [
          h('label', { class: 'field' }, [h('span', '关键词范围'), h('select', { name: 'buddy_scope', value: filters.scope, disabled: locked(), onChange: event => { filters.scope = event.target.value; invalidate(); } }, [['all', '全部学习资料'], ['username', '用户名'], ['nickname', '昵称'], ['interests', '学习兴趣'], ['bio', '个人简介'], ['major', '专业方向'], ['grade', '年级'], ['study_goal', '学习目标'], ['learning_style', '偏好方式']].map(([value, label]) => h('option', { value }, label)))]),
          ...[['interests', '兴趣', '例如：编程', 80], ['major', '专业 / 方向', '例如：计算机', 60], ['grade', '年级', '例如：大二', 20]].map(([key, label, placeholder, maxlength]) => h('label', { class: 'field' }, [h('span', label), h('input', { name: 'buddy_' + key, value: filters[key], placeholder, maxlength, disabled: locked(), onInput: event => { filters[key] = event.target.value; invalidate(); } })])),
          h('label', { class: 'field' }, [h('span', '偏好方式'), h('select', { name: 'buddy_style', value: filters.learning_style, disabled: locked(), onChange: event => { filters.learning_style = event.target.value; invalidate(); } }, Object.entries(learningStyles).map(([value, label]) => h('option', { value }, label)))]),
          h('label', { class: 'field' }, [h('span', '关系'), h('select', { name: 'buddy_relationship', value: filters.relationship, disabled: locked(), onChange: event => { filters.relationship = event.target.value; invalidate(); } }, [['all', '不限关系'], ['new', '还未联系'], ['friends', '已有学伴'], ['pending', '申请中']].map(([value, label]) => h('option', { value }, label)))]),
          h('label', { class: 'buddy-common-course' }, [h('input', { type: 'checkbox', name: 'buddy_common_course', checked: filters.common_course, disabled: locked(), onChange: event => { filters.common_course = event.target.checked; invalidate(); } }), '有共同课程']),
          h('button', { class: 'text-button', type: 'button', disabled: locked(), onClick: () => { Object.assign(filters, { q: '', scope: 'all', interests: '', major: '', grade: '', learning_style: '', relationship: 'all', common_course: false }); invalidate(); } }, '清空条件'),
        ])]),
        h('p', { class: 'data-note buddy-search-hint' }, '支持模糊查找，多个关键词用空格分开，筛选条件同时满足。'),
      ]),
      error.value ? h('div', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('div', { class: 'form-notice success', role: 'status' }, message.value) : null,
      searched.value ? h('section', { class: 'buddy-search-results', 'aria-label': '查找结果' }, [
        h('div', { class: 'section-title' }, [h('h3', '查找结果'), h('span', { class: 'count', role: 'status' }, `共 ${searchTotal.value} 位`)]),
        results.value.length ? h('div', { class: 'buddy-grid' }, results.value.map(person => card(person, 'search'))) : h('p', { class: 'empty-note' }, '还没有匹配的学伴，试试减少条件或更换关键词。'),
        searchTotal.value > 12 ? h('div', { class: 'pagination' }, [h('button', { type: 'button', disabled: locked() || searchOffset.value === 0, onClick: () => search(null, Math.max(0, searchOffset.value - 12)) }, '上一页'), h('span', `第 ${Math.floor(searchOffset.value / 12) + 1} 页`), h('button', { type: 'button', disabled: locked() || searchOffset.value + 12 >= searchTotal.value, onClick: () => search(null, searchOffset.value + 12) }, '下一页')]) : null,
      ]) : null,
      h('div', { class: 'buddy-tabs', 'aria-label': '学伴与申请' }, [['friends', '我的学伴'], ['incoming', '收到的申请'], ['outgoing', '发出的申请']].map(([key, label]) => h('button', { type: 'button', class: { active: tab.value === key }, 'aria-pressed': tab.value === key, onClick: () => { tab.value = key; removeId.value = null; } }, [label, h('span', String(data.value[key].length))]))),
      loading.value ? h('p', { class: 'data-note', role: 'status' }, '正在更新学伴列表…') : null,
      data.value[tab.value].length ? h('div', { class: 'buddy-grid' }, data.value[tab.value].map(person => card(person, tab.value))) : !loading.value ? h('div', { class: 'empty-state' }, [h('span', { class: 'empty-icon' }, icon('users', 28)), h('h3', tab.value === 'friends' ? '从一位学伴开始' : '暂时没有申请'), h('p', tab.value === 'friends' ? '按兴趣或学习目标，找到一起前进的人。' : tab.value === 'incoming' ? '新的学伴邀请会出现在这里。' : '发出的邀请会在这里等待回应。')]) : null,
      h('p', { class: 'data-note' }, '学伴之间不共享邮箱或个人情绪记录。'),
    ]);
  },
};
