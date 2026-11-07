import { h } from 'vue';

export const learningStyles = { '': '不限方式', pair: '结对练习', questions: '互相答疑', project: '项目协作', focus: '打卡自习' };

const paths = {
  smile: ['M8 14s1.4 3 4 3 4-3 4-3', 'M8.5 8.5h.01', 'M15.5 8.5h.01'],
  classroom: ['M4 5h16v11H4z', 'M8 20l4-4 4 4', 'M8 9h8', 'M8 12h4'],
  dashboard: ['M4 4h6v7H4z', 'M14 4h6v4h-6z', 'M4 15h6v5H4z', 'M14 12h6v8h-6z'],
  chart: ['M4 4v16h16', 'M8 15v-4', 'M13 15V7', 'M18 15v-6'],
  history: ['M4 10a8 8 0 1 1 1.7 7.2', 'M4 4v6h6', 'M12 8v5l3 2'],
  users: ['M15 20v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2', 'M17 4a4 4 0 0 1 0 8', 'M21 20v-2a4 4 0 0 0-3-3.87'],
  book: ['M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1z', 'M12 6v14'],
  profile: ['M4 21v-2a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v2'],
  lock: ['M6 10h12v11H6z', 'M8 10V6a4 4 0 0 1 8 0v4', 'M12 15v2'],
  logout: ['M9 4H4v16h5', 'M9 12h12', 'M17 8l4 4-4 4'],
  arrow: ['M4 12h16', 'M14 6l6 6-6 6'],
  refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M6.1 6.1A8 8 0 0 1 20 12', 'M4 12a8 8 0 0 0 13.9 5.9'],
  camera: ['M14 4l2 3h5v13H3V7h5l2-3z'],
  upload: ['M12 16V3', 'M7 8l5-5 5 5', 'M4 15v6h16v-6'],
  download: ['M12 3v13', 'M7 11l5 5 5-5', 'M4 15v6h16v-6'],
  chevron: ['M9 5l7 7-7 7'],
  leaf: ['M20 4C9 2 3 8 5 15c7 3 16-2 15-11z', 'M4 21L15 10'],
};

export function icon(name, size = 20) {
  const children = (paths[name] || paths.smile).map(d => h('path', { d }));
  if (name === 'smile') children.unshift(h('circle', { cx: 12, cy: 12, r: 10 }));
  if (name === 'users') children.push(h('circle', { cx: 9, cy: 7, r: 4 }));
  if (name === 'profile') children.push(h('circle', { cx: 12, cy: 6, r: 4 }));
  if (name === 'camera') children.push(h('circle', { cx: 12, cy: 13, r: 4 }));
  return h('svg', { class: 'ui-icon', width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.65, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false' }, children);
}

const moodColors = { HAPPY: '#f2dca8', NEUTRAL: '#d7e4ce', SAD: '#d7e3ed', ANGRY: '#eecbc2', SURPRISED: '#e6dcf0', FEAR: '#e9dfc8', DISGUST: '#d6e2d9' };

export function moodFace(code, size = 44) {
  const eyes = code === 'HAPPY'
    ? [h('path', { d: 'M13 20q3-4 6 0M29 20q3-4 6 0' })]
    : code === 'SAD' || code === 'FEAR'
      ? [h('path', { d: code === 'FEAR' ? 'M13 17l6-4M29 13l6 4' : 'M13 17l6-2M29 15l6 2' }), h('circle', { cx: 16, cy: 21, r: 1.15, fill: 'currentColor', stroke: 'none' }), h('circle', { cx: 32, cy: 21, r: 1.15, fill: 'currentColor', stroke: 'none' })]
      : code === 'DISGUST' ? [h('path', { d: 'M13 20h6M29 20h6' })]
        : [h('circle', { cx: 16, cy: 20, r: 1.5, fill: 'currentColor', stroke: 'none' }), h('circle', { cx: 32, cy: 20, r: 1.5, fill: 'currentColor', stroke: 'none' })];
  const mouths = { HAPPY: 'M16 28q8 10 16 0', NEUTRAL: 'M18 30h12', SAD: 'M17 32q7-7 14 0', ANGRY: 'M18 32q6-5 12 0', FEAR: 'M18 31q6-5 12 0', DISGUST: 'M17 29q4 5 7 0t7 0' };
  return h('svg', { class: 'mood-face', width: size, height: size, viewBox: '0 0 48 48', fill: 'none', 'aria-hidden': 'true', focusable: 'false' }, [
    h('circle', { cx: 24, cy: 24, r: 23, fill: moodColors[code] || moodColors.NEUTRAL }),
    h('g', { stroke: 'currentColor', 'stroke-width': 1.9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      ...eyes, code === 'ANGRY' ? h('path', { d: 'M12 14l8 3M28 17l8-3' }) : null,
      code === 'SURPRISED' || code === 'FEAR' ? h('ellipse', { cx: 24, cy: 31, rx: code === 'FEAR' ? 5 : 3.5, ry: code === 'FEAR' ? 3 : 4.5 }) : h('path', { d: mouths[code] || mouths.NEUTRAL }),
    ]),
  ]);
}

export function welcomeArt() {
  return h('div', { class: 'welcome-art', 'aria-hidden': 'true' }, [
    h('svg', { class: 'art-orbit', viewBox: '0 0 400 200', fill: 'none', focusable: 'false' }, [
      h('ellipse', { cx: 194, cy: 114, rx: 169, ry: 62, stroke: '#dce2d5', 'stroke-width': 1, transform: 'rotate(-12 194 114)' }),
      h('path', { d: 'M30 139C62 87 133 51 215 44', stroke: '#c6d2bd', 'stroke-width': 1.5, 'stroke-dasharray': '3 7', 'stroke-linecap': 'round' }),
      h('path', { d: 'M330 45v16M322 53h16', stroke: '#9aa98a', 'stroke-width': 1.8, 'stroke-linecap': 'round' }),
      h('circle', { cx: 65, cy: 48, r: 4, fill: '#d7c6af' }), h('circle', { cx: 341, cy: 151, r: 3, fill: '#b9c9ad' }),
    ]),
    h('span', { class: 'art-face art-face-calm' }, moodFace('NEUTRAL', 92)),
    h('span', { class: 'art-face art-face-happy' }, moodFace('HAPPY', 128)),
    h('span', { class: 'art-face art-face-wonder' }, moodFace('SURPRISED', 72)),
  ]);
}
