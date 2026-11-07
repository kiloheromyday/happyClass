import { h, useId } from 'vue';
import { moodFace } from './ui.js';

const names = { HAPPY: '开心', NEUTRAL: '平静', SAD: '低落', ANGRY: '生气', SURPRISED: '惊讶', FEAR: '担忧', DISGUST: '反感' };
const colors = { HAPPY: '#d5b46f', NEUTRAL: '#9aaf85', SAD: '#9db2c1', ANGRY: '#cda193', SURPRISED: '#b8a6cd', FEAR: '#bead85', DISGUST: '#9fb6a5' };

export const EmotionDistribution = {
  props: ['items', 'scaleMaximum'],
  setup(props) {
    return () => {
      const maximum = Math.max(1, Number(props.scaleMaximum) || 0, ...props.items.map(item => item.count));
      return h('div', { class: 'emotion-bars' }, props.items.map(item => h('div', { class: 'emotion-row', key: item.emotion }, [
        h('span', { class: 'emotion-name' }, [moodFace(item.emotion, 25), h('span', names[item.emotion] || item.emotion)]),
        h('div', { class: 'bar-track', role: 'img', 'aria-label': `${names[item.emotion] || item.emotion} ${item.count} 条` }, h('div', { class: 'bar-fill', style: { width: `${item.count / maximum * 100}%`, backgroundColor: colors[item.emotion] || colors.NEUTRAL } })),
        h('strong', String(item.count)),
      ])));
    };
  },
};

export const TrendChart = {
  props: ['points', 'realtime', 'bucket', 'maxPoints', 'interactive', 'selectedDate', 'disabled'], emits: ['select'],
  setup(props, { emit }) {
    const gradient = 'trend-' + useId();
    const timeLabel = point => props.realtime
      ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(point.timestamp))
      : props.bucket === 'day' ? point.timestamp.slice(5, 10) : point.timestamp.slice(5, 16).replace('T', ' ');
    return () => {
      const points = props.points.slice(-Math.min(366, Math.max(1, Number(props.maxPoints) || 48)));
      const ceiling = Math.max(4, Math.ceil(Math.max(0, ...points.map(point => point.total)) / 4) * 4);
      const left = 8, right = 592, top = 18, bottom = 166;
      const coordinates = points.map((point, index) => ({ ...point, x: points.length === 1 ? (left + right) / 2 : left + index * (right - left) / (points.length - 1), y: bottom - point.total / ceiling * (bottom - top) }));
      const line = coordinates.map((point, index) => `${index ? 'L' : 'M'}${point.x},${point.y}`).join(' ');
      const area = points.length > 1 ? `${line} L${right},${bottom} L${left},${bottom} Z` : '';
      const tickIndices = [...new Set(Array.from({ length: Math.min(3, points.length) }, (_, i) => points.length === 1 ? 0 : Math.round(i * (points.length - 1) / (Math.min(3, points.length) - 1))))];
      const choose = point => { if (props.interactive && !props.disabled) emit('select', point); };
      const graph = [
        h('div', { class: 'trend-plot' }, [
          h('div', { class: 'chart-y-axis', 'aria-hidden': 'true' }, [4, 3, 2, 1, 0].map(index => h('span', String(ceiling * index / 4)))),
          h('svg', { viewBox: '0 0 600 190', preserveAspectRatio: 'none', role: props.interactive ? 'group' : 'img', 'aria-label': props.interactive ? '每日反馈趋势，点击日期或用左右方向键选择' : points.length ? points.map(point => `${point.timestamp}: ${point.total} 条`).join('；') : '此范围内暂无趋势数据', class: 'trend-svg' }, [
          h('defs', h('linearGradient', { id: gradient, x1: 0, y1: 0, x2: 0, y2: 1 }, [h('stop', { offset: '0%', 'stop-color': '#a9bc94', 'stop-opacity': .35 }), h('stop', { offset: '100%', 'stop-color': '#a9bc94', 'stop-opacity': .02 })])),
          ...[0, 1, 2, 3, 4].map(index => {
            const y = top + index * (bottom - top) / 4;
            return h('line', { x1: left, y1: y, x2: right, y2: y, stroke: '#e5eadd', 'stroke-dasharray': index === 4 ? undefined : '3 5', 'vector-effect': 'non-scaling-stroke' });
          }),
          area ? h('path', { d: area, fill: `url(#${gradient})` }) : null,
          line ? h('path', { d: line, fill: 'none', stroke: '#7d9868', 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'vector-effect': 'non-scaling-stroke' }) : null,
          ...coordinates.map((point, index) => h('g', {
            key: point.timestamp, class: props.interactive ? 'trend-day-point' : undefined,
            role: props.interactive ? 'button' : undefined,
            tabindex: props.interactive && !props.disabled ? (props.selectedDate ? props.selectedDate === point.timestamp.slice(0, 10) : index === coordinates.length - 1) ? 0 : -1 : undefined,
            'data-point-index': index, 'data-day': props.interactive ? point.timestamp.slice(0, 10) : undefined,
            'aria-label': props.interactive ? `${point.timestamp.slice(0, 10)}，${point.total} 条反馈，查看当天详情` : undefined,
            'aria-pressed': props.interactive ? props.selectedDate === point.timestamp.slice(0, 10) : undefined,
            'aria-disabled': props.interactive ? !!props.disabled : undefined,
            onClick: props.interactive ? () => choose(point) : undefined,
            onKeydown: props.interactive ? event => {
              if (props.disabled) return;
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(point); }
              const target = event.key === 'ArrowLeft' ? index - 1 : event.key === 'ArrowRight' ? index + 1 : event.key === 'Home' ? 0 : event.key === 'End' ? coordinates.length - 1 : null;
              if (target !== null && coordinates[target]) { event.preventDefault(); choose(coordinates[target]); event.currentTarget?.parentNode?.querySelector(`[data-point-index="${target}"]`)?.focus(); }
            } : undefined,
          }, [
            props.interactive && props.selectedDate === point.timestamp.slice(0, 10) ? h('line', { x1: point.x, x2: point.x, y1: top, y2: bottom, stroke: '#7d9868', 'stroke-dasharray': '3 4', 'vector-effect': 'non-scaling-stroke' }) : null,
            h('circle', { cx: point.x, cy: point.y, r: props.selectedDate === point.timestamp.slice(0, 10) ? 5 : index === coordinates.length - 1 ? 4 : 2.5, fill: '#7d9868', stroke: '#fffefa', 'stroke-width': 1.5 }),
            h('circle', { cx: point.x, cy: point.y, r: 10, fill: 'transparent' }, h('title', `${point.timestamp} · ${point.total} 条`)),
          ])),
          ]),
        ]),
        h('div', { class: ['chart-x-axis', { 'single-point': points.length === 1 }], 'aria-hidden': 'true' }, tickIndices.map(index => h('span', timeLabel(points[index])))),
      ];
      return h('div', { class: ['trend-chart', { 'trend-interactive': props.interactive }] }, props.interactive
        ? h('div', { class: 'trend-day-scroll' }, h('div', { style: { minWidth: `${Math.max(480, points.length * 24)}px` } }, graph)) : graph);
    };
  },
};
