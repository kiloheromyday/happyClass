import { h, ref, watch } from 'vue';
import { read, useCommand, useResource } from './client.js';
import { actions, badge, button, check, date, empty, notice, section } from './ui.js';

export const FeedbackInbox = {
  props: ['expired', 'revision'],
  emits: ['open', 'changed'],
  setup(props, { emit }) {
    const unreadOnly = ref(false);
    const entries = ref([]);
    const command = useCommand(props.expired);
    const listing = useResource((signal, beforeId) => read('/inbox', {
      unread_only: unreadOnly.value,
      before_id: beforeId,
      limit: 25,
    }, signal), props.expired);
    const result = ref('');

    async function load(before = null) {
      const page = await listing.load(before);
      if (page) entries.value = before ? [...entries.value, ...page.items] : page.items;
    }

    watch(unreadOnly, () => {
      listing.clear();
      entries.value = [];
      load();
    }, { immediate: true });
    watch(() => props.revision, () => load());

    async function mark(item, open = false) {
      const tab = item.code.startsWith('REVIEW_') ? 'reviews'
        : item.code === 'MESSAGE' || item.code === 'GROUP_REPLY' ? 'conversation'
          : item.code === 'ADJUSTMENT_LINKED' ? 'adjustments'
            : 'progress';
      if (item.read_at) {
        if (open) emit('open', item.case_id, tab);
        return;
      }
      const outcome = await command.run('/inbox/' + item.id + '/read', undefined, { idempotent: false });
      if (!outcome) return;
      emit('changed');
      if (open) emit('open', item.case_id, tab);
      else result.value = '已标记为已读。';
    }

    async function readAll() {
      const outcome = await command.run('/inbox/read-all', undefined, { idempotent: false });
      if (!outcome) return;
      result.value = '已将 ' + outcome.marked_count + ' 条通知标记为已读。';
      emit('changed');
    }

    function card(item) {
      return h('li', { key: item.id, class: !item.read_at ? 'ef-unread' : '' }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.title),
          actions(item.read_at ? badge('已读') : badge('未读', 'waiting'), h('time', {
            datetime: item.created_at,
          }, date(item.created_at))),
        ]),
        h('p', { class: 'ef-meta' }, item.course_name + ' · ' + item.class_name),
        actions(
          button('打开反馈', () => mark(item, true), { disabled: command.busy.value }),
          !item.read_at && button('标为已读', () => mark(item), { disabled: command.busy.value }),
        ),
      ]);
    }

    return () => {
      const page = listing.value.value;
      return section('反馈通知', [
        check('只看未读', unreadOnly.value, value => { unreadOnly.value = value; }, command.busy.value),
        notice(listing.error.value || command.error.value),
        notice(result.value, 'good'),
        listing.loading.value && notice('正在读取通知…', 'info'),
        entries.value.length
          ? h('ul', { class: 'ef-list' }, entries.value.map(card))
          : !listing.loading.value && empty(unreadOnly.value ? '没有未读通知' : '还没有反馈通知'),
        page?.has_more && button('加载更多通知', () => load(page.next_before_id), { disabled: listing.loading.value }),
      ], actions(
        badge((page?.unread_count ?? 0) + ' 条未读'),
        button('刷新通知', () => load(), { disabled: listing.loading.value }),
        button('全部标为已读', readAll, { disabled: command.busy.value || !page?.unread_count }),
      ));
    };
  },
};
