import { h, ref } from 'vue';
import { useDraft } from '../feedback/client.js';
import {
  actions, badge, button, field, input, keyValues, notice, number, section, submit, textarea,
} from '../feedback/ui.js';
import { rangeText, sessionPath, useBookmarkWrite } from './client.js';

function initialValues(props) {
  if (props.item) {
    return {
      start_minute: props.item.start_minute,
      end_minute: props.item.end_minute,
      title: props.item.title,
      content: props.item.content,
      links: props.item.links.map(item => ({ ...item })),
    };
  }
  return {
    start_minute: props.interval?.start_minute ?? 0,
    end_minute: props.interval?.end_minute ?? Math.min(5, props.session.duration_minutes),
    title: '',
    content: '',
    links: [],
  };
}

function validate(values, maximum) {
  if (!Number.isInteger(values.start_minute) || !Number.isInteger(values.end_minute) ||
    values.start_minute < 0 || values.start_minute >= values.end_minute || values.end_minute > maximum) {
    return '开始和结束分钟要在课堂范围内，结束时间要晚于开始时间。';
  }
  if (values.title.trim().length < 2) return '请写一个至少两个字的标题。';
  if (!values.content.trim() && !values.links.length) return '请写下讲解，或添加资料链接。';
  const seen = new Set();
  for (const link of values.links) {
    if (!link.label.trim()) return '请给每个资料链接写一个名称。';
    try {
      const value = link.url.trim();
      const url = new URL(value);
      if (!/^https?:\/\//i.test(value) || url.username || url.password || !url.hostname || /[\s\\]/.test(value)) {
        return '资料链接需要以 http:// 或 https:// 开头。';
      }
      if (seen.has(value)) return '资料链接不能重复。';
      seen.add(value);
    } catch {
      return '请检查资料链接。';
    }
  }
  return '';
}

export const MaterialEditor = {
  props: ['session', 'item', 'interval', 'expired'],
  emits: ['dirty', 'saved', 'cancel', 'reload'],
  setup(props, { emit }) {
    const command = useBookmarkWrite(props.expired);
    const draft = useDraft(initialValues(props), value => emit('dirty', value), command.busy);
    const { values } = draft;
    const sourceVersion = ref(props.item?.version);
    const step = ref('edit');
    const validation = ref('');

    function addLink() {
      if (values.links.length < 5) values.links.push({ label: '', url: '' });
    }

    function removeLink(index) {
      values.links.splice(index, 1);
    }

    function cancel() {
      if (draft.dirty.value && !window.confirm('放弃这次资料编辑？')) return;
      draft.restore();
      emit('cancel');
    }

    function adopt() {
      if (!window.confirm('确认已对照当前版本，并用这份草稿继续编辑？')) return;
      sourceVersion.value = props.item.version;
      command.reset();
    }

    function preview(event) {
      event.preventDefault();
      validation.value = validate(values, props.session.duration_minutes);
      if (!validation.value) step.value = 'preview';
    }

    async function save(publish) {
      if (props.item && (sourceVersion.value !== props.item.version || props.item.state === 'ARCHIVED')) return;
      validation.value = validate(values, props.session.duration_minutes);
      if (validation.value) return;
      const payload = {
        start_minute: values.start_minute,
        end_minute: values.end_minute,
        title: values.title.trim(),
        content: values.content.trim(),
        links: values.links.map(link => ({ label: link.label.trim(), url: link.url.trim() })),
      };
      const result = props.item
        ? await command.run('/materials/' + props.item.id, {
          ...payload, version: sourceVersion.value,
        }, { method: 'PUT', idempotent: false })
        : await command.run(sessionPath(props.session.id, 'materials'), {
          ...payload, publish,
        });
      if (!result) return;
      draft.restore();
      emit('saved', result);
    }

    function links() {
      return h('fieldset', { class: 'ef-choices bookmark-link-editor' }, [
        h('legend', '资料链接（可选）'),
        h('p', { class: 'ef-meta' }, '最多五个。只填写已允许学生访问的网页地址。'),
        ...values.links.map((link, index) => h('div', { key: index, class: 'bookmark-link-fields' }, [
          field('链接 ' + (index + 1) + ' 的名称', input(link.label, value => { link.label = value; }, {
            maxlength: 100, required: true, placeholder: '比如：队列入队示意图',
          })),
          field('网页地址', input(link.url, value => { link.url = value; }, {
            type: 'url', maxlength: 1000, required: true, placeholder: 'https://',
          })),
          actions(button('移除链接 ' + (index + 1), () => removeLink(index))),
        ])),
        actions(button('添加资料链接', addLink, { disabled: values.links.length >= 5 })),
      ]);
    }

    function editor() {
      return h('form', { class: 'ef-form', onSubmit: preview }, [
        h('p', { class: 'ef-meta' }, '资料会出现在对应时间段，也会出现在该时段的学生书签里。'),
        h('div', { class: 'ef-grid' }, [
          field('开始分钟', number(values.start_minute, value => { values.start_minute = value; }, {
            min: 0, max: props.session.duration_minutes - 1, required: true,
          })),
          field('结束分钟', number(values.end_minute, value => { values.end_minute = value; }, {
            min: 1, max: props.session.duration_minutes, required: true,
          }), '不含结束这一分钟。例如 15–20 对应第 15 到 19 分钟。'),
        ]),
        field('资料标题', input(values.title, value => { values.title = value; }, {
          maxlength: 120, minlength: 2, required: true, placeholder: '比如：尾指针移动的顺序',
        })),
        field('补充讲解', textarea(values.content, value => { values.content = value; }, {
          maxlength: 4000, rows: 6, placeholder: '写下这段要点、解法或例题说明',
        }), values.content.length + ' / 4000'),
        links(),
        notice(validation.value),
        actions(submit('预览资料'), button('取消', cancel)),
      ]);
    }

    function previewCard() {
      const stale = props.item && sourceVersion.value !== props.item.version;
      return [
        keyValues([
          ['课堂', props.session.course_name + ' · ' + props.session.class_name],
          ['对应时间段', rangeText(values.start_minute, values.end_minute)],
          ['链接数', values.links.length],
        ]),
        h('h4', values.title.trim()),
        values.content.trim() && h('p', { class: 'ef-text' }, values.content.trim()),
        values.links.length > 0 && h('ul', values.links.map(link => h('li', { key: link.url }, [
          h('a', { href: link.url.trim(), target: '_blank', rel: 'noopener noreferrer' }, link.label.trim()),
        ]))),
        props.item?.state === 'PUBLISHED' && notice('保存后，学生会看到更新的资料。', 'info'),
        notice(validation.value || command.error.value),
        command.conflict.value && button('读取当前版本', () => emit('reload')),
        stale && section('教师端最新版本', [
          h('h4', props.item.title),
          h('p', { class: 'ef-text' }, props.item.content),
          h('p', { class: 'ef-meta' }, rangeText(props.item.start_minute, props.item.end_minute)),
          props.item.state !== 'ARCHIVED' && button('核对后继续', adopt),
        ]),
        actions(
          props.item
            ? button('保存修改', () => save(false), {
              primary: true, disabled: command.busy.value || stale || props.item.state === 'ARCHIVED',
            })
            : [
              button('保存为草稿', () => save(false), { disabled: command.busy.value }),
              button('发布给学生', () => save(true), { primary: true, disabled: command.busy.value }),
            ],
          button('返回编辑', () => { step.value = 'edit'; command.reset(); }, { disabled: command.busy.value }),
          button('取消', cancel, { disabled: command.busy.value }),
        ),
      ];
    }

    return () => section(props.item ? '编辑补学资料' : '添加补学资料',
      step.value === 'preview' ? previewCard() : editor(),
      step.value === 'preview' && badge('预览'),
    );
  },
};
