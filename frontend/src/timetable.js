import { h, ref, computed } from 'vue';

export const departmentStyle = item => ({ '--dept-color': item.department_color || '#637a50', '--dept-bg': item.department_background || '#f0f4e9' });
export const chinaDay = value => new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 10);
const add = (day, count) => new Date(Date.parse(day + 'T00:00:00Z') + count * 86400000).toISOString().slice(0, 10);
const monday = day => add(day, -((new Date(day).getUTCDay() + 6) % 7));
const time = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
const bands = [['上午 · 第一时段', '08:00—09:35'], ['上午 · 第二时段', '09:55—11:30'], ['下午 · 第一时段', '13:00—14:35'], ['下午 · 第二时段', '14:55—16:30'], ['晚间 · 第一时段', '18:30—20:05'], ['晚间 · 第二时段', '20:15—21:50']];
const band = item => { const minutes = Number(time(item.starts_at).slice(0, 2)) * 60 + Number(time(item.starts_at).slice(3)); return minutes < 590 ? 0 : minutes < 780 ? 1 : minutes < 890 ? 2 : minutes < 1080 ? 3 : minutes < 1210 ? 4 : 5; };

export const Timetable = {
  props: ['sessions'], emits: ['open'],
  setup(props, { emit }) {
    const today = chinaDay(new Date()), week = ref(monday(today));
    const dates = computed(() => Array.from({ length: 7 }, (_, index) => add(week.value, index)));
    const weekItems = computed(() => (props.sessions || []).filter(item => chinaDay(item.starts_at) >= week.value && chinaDay(item.starts_at) <= add(week.value, 6)));
    const cells = computed(() => { const result = new Map(); for (const item of weekItems.value) { const key = `${chinaDay(item.starts_at)}-${band(item)}`; if (!result.has(key)) result.set(key, []); result.get(key).push(item); } for (const items of result.values()) items.sort((a, b) => a.starts_at.localeCompare(b.starts_at)); return result; });
    function session(item) {
      return h('button', { class: 'timetable-course', style: departmentStyle(item), key: item.id, type: 'button', 'aria-label': `查看课表课堂：${item.id} ${item.course_name}`, onClick: () => emit('open', item) }, [
        h('span', { class: 'timetable-department' }, item.department_short || '综合课程'), h('strong', item.course_name),
        h('span', `${time(item.starts_at)}—${time(item.ends_at)}`), h('span', item.classroom), h('small', item.teacher_name),
        item.is_demo ? h('small', { class: 'timetable-demo' }, '演示') : null,
      ]);
    }
    return () => h('section', { class: 'timetable-section', 'aria-label': '每周课程表' }, [
      h('div', { class: 'timetable-toolbar' }, [h('div', [h('h3', `${week.value.slice(5).replace('-', '.')} — ${add(week.value, 6).slice(5).replace('-', '.')}`), h('p', `${weekItems.value.length} 节课堂 · 北京时间`)]), h('div', [h('button', { class: 'quiet-button', onClick: () => week.value = add(week.value, -7), 'aria-label': '上一周课表' }, '← 上一周'), h('button', { class: 'secondary-button', onClick: () => week.value = monday(today) }, '本周'), h('button', { class: 'quiet-button', onClick: () => week.value = add(week.value, 7), 'aria-label': '下一周课表' }, '下一周 →')])]),
      h('div', { class: 'timetable-scroll', tabindex: 0, 'aria-label': '周一至周日课程表，可横向滚动' }, [h('table', { class: 'timetable-grid' }, [
        h('thead', h('tr', [h('th', { scope: 'col', class: 'timetable-time' }, '时段'), ...dates.value.map((day, index) => h('th', { scope: 'col', class: { today: day === today } }, [h('span', ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][index]), h('small', day.slice(5).replace('-', '/')), day === today ? h('em', '今天') : null]))])),
        h('tbody', bands.map(([label, hours], index) => h('tr', { class: { evening: index >= 4 } }, [h('th', { scope: 'row' }, [h('strong', label), h('small', hours)]), ...dates.value.map(day => h('td', { class: { today: day === today }, 'data-day': day, 'data-slot': index }, (cells.value.get(`${day}-${index}`) || []).map(session)))]))),
      ])]),
      !weekItems.value.length ? h('p', { class: 'empty-note' }, '本周没有课堂安排，可以切换其他周查看。') : null,
    ]);
  },
};
