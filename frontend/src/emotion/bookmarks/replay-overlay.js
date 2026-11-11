import { h } from 'vue';
import { actions, badge, button } from '../feedback/ui.js';
import { rangeText } from './client.js';

export function frameHasBookmarks(frame) {
  return Boolean(frame.bookmark_count || frame.study_materials?.length);
}

export const ReplayBookmarkOverlay = {
  props: ['frame', 'sessionId', 'bucketMinutes'],
  emits: ['navigate'],
  setup(props, { emit }) {
    function open(view, materialId = null) {
      emit('navigate', {
        tab: 'bookmarks',
        sessionId: props.sessionId,
        minute: props.frame.index * props.bucketMinutes,
        view,
        materialId,
      });
    }

    return () => {
      const resources = props.frame.study_materials || [];
      return h('section', { class: 'replay-bookmark-panel', 'aria-label': '这个时段的课堂书签' }, [
        h('div', { class: 'ef-list-row' }, [
          h('h3', '这个时段的书签'),
          actions(badge((props.frame.bookmark_count || 0) + ' 条书签'), badge(resources.length + ' 份资料')),
        ]),
        resources.length
          ? h('ul', resources.map(item => h('li', { key: item.id }, [
            button(item.title, () => open('materials', item.id), { class: 'ef-link' }),
            h('span', { class: 'ef-meta' }, ' · ' + rangeText(item.start_minute, item.end_minute)),
          ])))
          : h('p', { class: 'ef-meta' }, '这段还没有发布补学资料。'),
        button('在书签里查看这段', () => open('timeline')),
      ]);
    };
  },
};
