import { computed, h, onBeforeUnmount, ref, watch } from 'vue';
import {
  actions, badge, button, date, empty, field, keyValues, notice, option,
  pager, section, select,
} from '../feedback/ui.js';
import { minuteText, rangeText, useBookmarkResource, useBookmarkWrite } from './client.js';

const preferences = [
  option('MATERIAL', '先看有资料的书签'),
  option('TIME', '按课堂和分钟'),
  option('RECENT', '最近改过的在前'),
];

export const ReviewDesk = {
  props: ['session', 'expired', 'revision'],
  emits: ['dirty', 'changed', 'open-material', 'back'],
  setup(props, { emit }) {
    const listing = useBookmarkResource('/study-queue', props.expired);
    const command = useBookmarkWrite(props.expired);
    const prefer = ref('MATERIAL');
    const selected = ref(null);
    const expanded = ref(null);
    const reviewed = ref(0);
    const status = ref('');
    const active = computed(() =>
      listing.value.value?.items.find(item => item.id === selected.value) || null,
    );

    watch(command.busy, value => emit('dirty', value), { flush: 'sync' });
    onBeforeUnmount(() => emit('dirty', false));

    async function load(offset = 0, nextIndex = null) {
      const data = await listing.load({ session_id: props.session?.id, prefer: prefer.value, offset, limit: 10 });
      if (!data) return;
      if (!data.items.length && offset > 0) {
        await load(Math.max(0, offset - 10), 0);
        return;
      }
      if (nextIndex !== null) {
        selected.value = data.items[Math.min(nextIndex, data.items.length - 1)]?.id ?? null;
      } else if (!data.items.some(item => item.id === selected.value)) {
        selected.value = data.items[0]?.id ?? null;
      }
    }

    watch(prefer, () => {
      expanded.value = null;
      load();
    }, { immediate: true });
    watch(() => props.revision, () => load(listing.value.value?.offset || 0));

    function choose(item) {
      selected.value = item.id;
      expanded.value = null;
      command.reset();
    }

    function move(direction) {
      const page = listing.value.value;
      const index = page.items.findIndex(item => item.id === selected.value);
      const next = index + direction;
      if (next >= 0 && next < page.items.length) {
        choose(page.items[next]);
      } else if (direction < 0 && page.offset > 0) {
        expanded.value = null;
        load(page.offset - page.limit, page.limit - 1);
      } else if (direction > 0 && page.has_more) {
        expanded.value = null;
        load(page.offset + page.limit, 0);
      }
    }

    async function complete(item) {
      const index = listing.value.value.items.findIndex(value => value.id === item.id);
      const offset = listing.value.value.offset;
      const result = await command.run('/mine/' + item.id, {
        reason: item.reason, title: item.title, note: item.note, version: item.version, reviewed: true,
      }, { method: 'PUT', idempotent: false });
      if (!result) return;
      reviewed.value += 1;
      status.value = '已标为已复习，可以看下一条。';
      expanded.value = null;
      await load(offset, index);
    }

    function links(item) {
      return item.links.length > 0 && h('ul', { class: 'bookmark-inline-materials' }, item.links.map(link => h('li', {
        key: link.url,
      }, h('a', { href: link.url, target: '_blank', rel: 'noopener noreferrer' }, link.label))));
    }

    function material(item, bookmark) {
      const open = expanded.value === item.id;
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          button(item.title, () => { expanded.value = open ? null : item.id; }, {
            class: 'ef-link', 'aria-expanded': open,
          }),
          actions(
            badge(rangeText(item.start_minute, item.end_minute)),
            item.completed && badge('已看过', 'good'),
            item.changed_after_review && badge('资料有更新', 'waiting'),
          ),
        ]),
        open && h('div', { class: 'bookmark-material-body' }, [
          item.content && h('p', { class: 'ef-text' }, item.content),
          links(item),
          h('p', { class: 'ef-meta' }, '最近修改 ' + date(item.updated_at)),
          button('打开资料页', () => emit('open-material', bookmark.session_id, item.id), { disabled: command.busy.value }),
        ]),
      ]);
    }

    function activeCard(item, page) {
      const index = page.items.findIndex(value => value.id === item.id);
      return section(item.title || minuteText(item.minute), [
        h('p', { class: 'ef-meta' }, item.course_name + ' · ' + item.class_name + ' · ' + minuteText(item.minute)),
        item.note
          ? h('p', { class: 'ef-text' }, item.note)
          : h('p', { class: 'ef-meta' }, '这条书签还没写笔记。'),
        h('h4', '这一段的资料'),
        item.materials.length
          ? h('ul', { class: 'ef-list' }, item.materials.map(entry => material(entry, item)))
          : h('p', { class: 'ef-meta' }, '这一段还没发布资料，可以先回看自己的笔记。'),
        actions(
          button('上一条', () => move(-1), { disabled: command.busy.value || listing.loading.value || (!index && !page.offset) }),
          button('下一条', () => move(1), { disabled: command.busy.value || listing.loading.value || (index === page.items.length - 1 && !page.has_more) }),
          button('这条已复习', () => complete(item), { primary: true, disabled: command.busy.value || listing.loading.value }),
        ),
      ], badge(item.reason_label));
    }

    function queue(page) {
      return h('ol', { class: 'bookmark-review-list' }, page.items.map(item => h('li', { key: item.id }, [
        button(item.title || minuteText(item.minute), () => choose(item), {
          'aria-pressed': selected.value === item.id, disabled: command.busy.value,
        }),
        h('span', { class: 'ef-meta' }, item.course_name),
        item.materials.length > 0 && badge(item.materials.length + ' 份资料'),
      ])));
    }

    return () => {
      const page = listing.value.value;
      return [
        section('待复习书签', [
          field('复习顺序', select(prefer.value, preferences, value => { prefer.value = value; }, {
            disabled: command.busy.value,
          })),
          page && keyValues([
            ['待复习', page.coverage.pending],
            ['有资料可看', page.coverage.ready],
            ['暂时没有资料', page.coverage.waiting],
            ['本次已复习', reviewed.value],
          ]),
          notice(status.value, 'good'),
          notice(listing.error.value || command.error.value),
          command.conflict.value && button('刷新书签后再标记', () => load(page?.offset)),
          listing.loading.value && notice('正在整理待复习书签…', 'info'),
          page?.items.length
            ? queue(page)
            : !listing.loading.value && empty('暂时没有待复习书签', '新记下的书签会出现在这里。'),
          pager(page, listing.loading.value || command.busy.value, offset => {
            expanded.value = null;
            load(offset, 0);
          }),
        ], actions(
          button('返回我的书签', () => emit('back'), { disabled: command.busy.value }),
          button('刷新复习列表', () => load(page?.offset), { disabled: command.busy.value || listing.loading.value }),
        )),
        active.value && page && activeCard(active.value, page),
      ];
    };
  },
};
