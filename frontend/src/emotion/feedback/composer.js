import { computed, h, ref, watch } from 'vue';
import { read, useCommand, useDraft, useResource } from './client.js';
import {
  actions, all, badge, button, casePath, date, emotion, empty, field, impacts,
  input, keyValues, label, notice, number, option, section, select, sessionLabel,
  submit, textarea,
} from './ui.js';

function initialValues(props) {
  const item = props.item;
  return {
    session_id: item?.session_id ?? props.initialSession ?? null,
    emotion: item?.emotion ?? '',
    reasons: item ? [...item.reasons] : [],
    title: item?.title ?? '',
    content: item?.content ?? '',
    impact: item?.impact ?? 'MEDIUM',
    topic_minute: item?.topic_minute ?? null,
    linked_record_id: null,
  };
}

export const FeedbackComposer = {
  props: ['catalog', 'initialSession', 'item', 'expired'],
  emits: ['dirty', 'saved', 'cancel', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const draft = useDraft(initialValues(props), value => emit('dirty', value), command.busy);
    const { values } = draft;
    const context = useResource((signal, id) => read('/sessions/' + id + '/context', {}, signal), props.expired);
    const step = ref('write');
    const error = ref('');
    const accepted = ref(false);
    const editVersion = ref(props.item?.version ?? null);
    const session = computed(() => props.catalog.sessions.find(item => item.id === values.session_id));
    const maxMinute = computed(() => {
      if (!session.value) return undefined;
      return Math.floor((Date.parse(session.value.ends_at) - Date.parse(session.value.starts_at)) / 60000);
    });
    const windowInfo = computed(() => context.value.value?.submission ?? session.value?.submission);
    const canSubmit = computed(() => Boolean(props.item || windowInfo.value?.can_submit));

    watch(() => values.session_id, id => {
      context.clear();
      if (id && !props.item) context.load(id);
    }, { immediate: true });

    function changeSession(value) {
      values.session_id = value ? Number(value) : null;
      values.topic_minute = null;
      values.linked_record_id = null;
      error.value = '';
    }

    function toggleReason(value) {
      if (values.reasons.includes(value)) {
        values.reasons = values.reasons.filter(item => item !== value);
      } else if (values.reasons.length < 3) {
        values.reasons = [...values.reasons, value];
      }
    }

    function associate(value) {
      values.linked_record_id = value ? Number(value) : null;
      const selected = context.value.value?.emotion_records.find(item => item.id === values.linked_record_id);
      if (selected) values.emotion = selected.emotion;
    }

    function validate() {
      if (!values.session_id) return '请选择这条反馈对应的课堂。';
      if (!canSubmit.value) return windowInfo.value?.reason || '这节课堂暂时无法提交反馈。';
      if (!values.emotion) return '请选择最贴近这次体验的情绪。';
      if (!values.reasons.length) return '请选择至少一个课堂原因。';
      if (values.title.trim().length < 2) return '请填写至少两个字的标题。';
      if (values.reasons.includes('OTHER') && !values.content.trim()) return '请选择其他原因时补充说明。';
      const minute = values.topic_minute;
      if (minute !== null && (!Number.isInteger(minute) || minute < 0 || minute > maxMinute.value)) {
        return '请填写课堂时长以内的整数分钟。';
      }
      return '';
    }

    function preview(event) {
      event.preventDefault();
      error.value = validate();
      if (error.value) return;
      step.value = 'preview';
      accepted.value = Boolean(props.item);
    }

    function cancel() {
      if (command.busy.value) return;
      if (draft.dirty.value && !window.confirm('放弃这次尚未提交的编辑？')) return;
      draft.restore();
      emit('cancel');
    }

    async function send(event) {
      event.preventDefault();
      if (!accepted.value) return;
      if (props.item && editVersion.value !== props.item.version) {
        error.value = '反馈已更新，请核对最新内容后继续。';
        return;
      }
      error.value = validate();
      if (error.value) return;
      const common = {
        title: values.title.trim(),
        content: values.content.trim(),
        emotion: values.emotion,
        reasons: [...values.reasons],
        impact: values.impact,
      };
      const result = props.item
        ? await command.run(casePath(props.item.id), { ...common, version: editVersion.value }, { method: 'PUT' })
        : await command.run('/cases', {
          ...common,
          session_id: values.session_id,
          topic_minute: values.topic_minute,
          linked_record_id: values.linked_record_id,
        });
      if (!result) return;
      draft.restore(initialValues(props));
      emit('saved', result);
    }

    function chooseEmotion() {
      return h('fieldset', { class: 'ef-choices' }, [
        h('legend', '你的课堂情绪'),
        h('div', { class: 'ef-choice-grid' }, props.catalog.emotions.map(item => h('label', {
          key: item.value,
          class: ['ef-choice', { 'ef-chosen': item.value === values.emotion }],
        }, [
          h('input', {
            type: 'radio',
            name: 'feedback-emotion',
            value: item.value,
            checked: item.value === values.emotion,
            onChange: () => { values.emotion = item.value; },
          }),
          h('span', { 'aria-hidden': 'true' }, item.emoji),
          item.label,
        ]))),
      ]);
    }

    function chooseReasons() {
      return h('fieldset', { class: 'ef-choices' }, [
        h('legend', '课堂原因（已选 ' + values.reasons.length + ' / 3）'),
        h('div', { class: 'ef-choice-grid' }, props.catalog.reasons.map(item => {
          const checked = values.reasons.includes(item.value);
          return h('label', {
            key: item.value,
            class: ['ef-choice', { 'ef-chosen': checked }],
          }, [
            h('input', {
              type: 'checkbox',
              checked,
              disabled: !checked && values.reasons.length >= 3,
              onChange: () => toggleReason(item.value),
            }),
            item.label,
          ]);
        })),
      ]);
    }

    function classroom() {
      if (props.item) return h('p', { class: 'ef-meta' }, sessionLabel(props.item));
      const choices = props.catalog.sessions.map(item => option(
        item.id,
        sessionLabel(item) + (item.submission?.can_submit ? '' : '（暂不可提交）'),
      ));
      return [
        field('课堂', select(values.session_id, [all('请选择课堂'), ...choices], changeSession, { required: true })),
        context.loading.value && notice('正在获取本节课堂的反馈设置…', 'info'),
        notice(context.error.value),
        context.error.value && button('重试读取课堂设置', () => context.load(values.session_id)),
        windowInfo.value?.can_submit && h('p', { class: 'ef-meta' },
          '截止于 ' + date(windowInfo.value.deadline) + '，今天还可提交 ' + windowInfo.value.remaining_today + ' 条。',
        ),
        windowInfo.value && !windowInfo.value.can_submit && notice(windowInfo.value.reason, 'waiting'),
      ];
    }

    function optionalFields() {
      if (props.item || !session.value) return null;
      const records = context.value.value?.emotion_records || [];
      return h('div', { class: 'ef-grid' }, [
        field('课堂时间点（可选）', number(values.topic_minute, value => { values.topic_minute = value; }, {
          min: 0,
          max: maxMinute.value,
          placeholder: '开课后第几分钟',
        }), '便于老师定位到课堂环节。'),
        records.length > 0 && field('关联我的情绪记录（可选）', select(values.linked_record_id, [
          all('不关联'),
          ...records.map(item => option(item.id, emotion(props.catalog, item.emotion) + ' · ' + date(item.recorded_at))),
        ], associate), '选择记录后会带入对应情绪，可继续修改。'),
      ]);
    }

    function editForm() {
      return h('form', { class: 'ef-form', onSubmit: preview }, [
        classroom(),
        chooseEmotion(),
        chooseReasons(),
        field('对学习的影响', select(values.impact, impacts, value => { values.impact = value; })),
        field('反馈标题', input(values.title, value => { values.title = value; }, {
          required: true,
          minlength: 2,
          maxlength: 120,
          placeholder: '例如：希望再演示一次队列的入队操作',
        })),
        field('想让老师知道什么？', textarea(values.content, value => { values.content = value; }, {
          placeholder: '说说发生在什么环节，你希望老师怎样帮助。',
          required: values.reasons.includes('OTHER'),
        }), values.content.length + ' / 2000'),
        optionalFields(),
        notice(error.value),
        actions(submit('预览反馈', !canSubmit.value || context.loading.value), button('取消', cancel)),
      ]);
    }

    function previewForm() {
      const hasNewVersion = props.item && editVersion.value !== props.item.version;
      return h('form', { class: 'ef-form', onSubmit: send }, [
        h('h4', values.title.trim()),
        keyValues([
          ['课堂', session.value ? sessionLabel(session.value) : sessionLabel(props.item)],
          ['情绪', emotion(props.catalog, values.emotion)],
          ['原因', values.reasons.map(value => label(props.catalog.reasons, value)).join('、')],
          ['影响', label(impacts, values.impact)],
          ['时间点', values.topic_minute === null ? '—' : '开课后 ' + values.topic_minute + ' 分钟'],
        ]),
        values.content.trim() && h('p', { class: 'ef-text' }, values.content.trim()),
        !props.item && h('label', { class: 'ef-check' }, [
          h('input', {
            type: 'checkbox',
            checked: accepted.value,
            onChange: event => { accepted.value = event.target.checked; },
          }),
          '我已检查标题和内容，未填写姓名、学号等身份信息。',
        ]),
        notice(error.value || command.error.value),
        hasNewVersion && section('服务器上的最新反馈', [
          h('strong', props.item.title),
          props.item.content && h('p', { class: 'ef-text' }, props.item.content),
          keyValues([
            ['进度', props.item.state_label],
            ['情绪', emotion(props.catalog, props.item.emotion)],
            ['原因', props.item.reason_labels.join('、')],
          ]),
          props.item.capabilities.edit && button('核对后保留我的草稿', () => {
            editVersion.value = props.item.version;
            error.value = '';
            command.reset();
          }),
        ]),
        command.conflict.value && button('刷新处理状态', () => {
          if (props.item) emit('refresh');
          else context.load(values.session_id);
        }),
        actions(
          submit(command.busy.value ? '正在提交…' : props.item ? '保存修改' : '发送给老师',
            command.busy.value || !accepted.value || hasNewVersion || Boolean(props.item && !props.item.capabilities.edit)),
          button('返回修改', () => { step.value = 'write'; command.reset(); }, { disabled: command.busy.value }),
          button('取消', cancel, { disabled: command.busy.value }),
        ),
      ]);
    }

    return () => section(
      props.item ? '编辑反馈' : '提交课堂情绪反馈',
      !props.item && !props.catalog.sessions.length
        ? empty('暂无可选课堂', '加入课堂后，可以在这里向任课教师发送反馈。', button('返回', cancel))
        : step.value === 'write' ? editForm() : previewForm(),
      badge('教师端隐藏账号身份'),
    );
  },
};
