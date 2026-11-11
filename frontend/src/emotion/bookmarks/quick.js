import { h, onBeforeUnmount, ref, watch } from 'vue';
import { actions, button, notice } from '../feedback/ui.js';
import { minuteText, sessionPath, useBookmarkWrite } from './client.js';

export const QuickBookmark = {
  props: ['session', 'disabled', 'expired'],
  emits: ['open', 'created', 'busy'],
  setup(props, { emit }) {
    const command = useBookmarkWrite(props.expired);
    const result = ref(null);

    watch(command.busy, value => emit('busy', value), { flush: 'sync' });
    onBeforeUnmount(() => emit('busy', false));

    function open() {
      emit('open', {
        tab: 'bookmarks',
        sessionId: props.session.id,
        view: 'mine',
      });
    }

    async function add() {
      const saved = await command.run(sessionPath(props.session.id, 'mine'), {});
      if (!saved) return;
      result.value = saved;
      emit('created', saved.bookmark);
    }

    return () => {
      const ongoing = props.session.live ?? props.session.status === 'ONGOING';
      const locked = props.disabled || command.busy.value;
      return h('div', { class: 'bookmark-quick' }, [
        actions(
          ongoing && button(command.busy.value ? '正在记书签…' : '记下这一分钟', add, {
            primary: true,
            disabled: locked,
          }),
          button('打开课堂书签', open, { disabled: locked }),
        ),
        notice(command.error.value),
        result.value && notice(
          (result.value.created ? '已记下' : '已经记过') + minuteText(result.value.bookmark.minute) + '。可以课后补笔记。',
          'good',
        ),
      ]);
    };
  },
};
