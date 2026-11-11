import { h, ref } from 'vue';
import { useCommand, useDraft } from './client.js';
import {
  actions, all, badge, button, casePath, date, emotion, empty, field, label, notice,
  number, outcomes, section, select, submit, textarea,
} from './ui.js';

export const FeedbackReviews = {
  props: ['item', 'catalog', 'staff', 'expired'],
  emits: ['dirty', 'changed', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const mode = ref('');
    const round = ref(null);
    const defaults = () => ({
      prompt: '',
      due_days: props.item.policy.review_days,
      outcome: '',
      emotion: '',
      content: '',
    });
    const draft = useDraft(defaults(), value => emit('dirty', value), command.busy);
    const { values } = draft;
    const resultNote = ref('');
    const sourceVersion = ref(props.item.version);

    function start(name, value = null) {
      if (draft.dirty.value || command.busy.value) return;
      sourceVersion.value = props.item.version;
      mode.value = name;
      round.value = value;
      draft.restore(defaults());
      command.reset();
      resultNote.value = '';
    }

    function close() {
      mode.value = '';
      round.value = null;
      draft.restore(defaults());
      command.reset();
    }

    async function send(event) {
      event.preventDefault();
      let result;
      if (mode.value === 'request') {
        if (values.prompt.trim().length < 2 || !Number.isInteger(values.due_days)) return;
        result = await command.run(casePath(props.item.id) + '/reviews', {
          version: sourceVersion.value,
          prompt: values.prompt.trim(),
          due_days: values.due_days,
        });
      } else if (mode.value === 'answer' && values.outcome) {
        result = await command.run('/reviews/' + round.value.id + '/answer', {
          outcome: values.outcome,
          emotion: values.emotion || null,
          content: values.content.trim(),
        });
      } else if (mode.value === 'cancel') {
        result = await command.run('/reviews/' + round.value.id + '/cancel', {
          version: round.value.version,
          content: values.content.trim(),
        });
      }
      if (!result) return;
      resultNote.value = {
        request: '回访邀请已发送。',
        answer: '回访已提交。',
        cancel: '回访已取消。',
      }[mode.value];
      close();
      emit('changed', result);
    }

    function fields() {
      if (mode.value === 'request') {
        return [
          field('给学生的回访问题', textarea(values.prompt, value => { values.prompt = value; }, {
            required: true, minlength: 2, maxlength: 1000,
            placeholder: '例如：增加例题后，你现在能完成这一类题吗？',
          })),
          field('希望几天内收到回复', number(values.due_days, value => { values.due_days = value; }, {
            required: true, min: 1, max: 14,
          }), '超过期望日期会显示逾期，学生仍可答复。'),
        ];
      }
      if (mode.value === 'answer') {
        return [
          h('p', { class: 'ef-text' }, round.value.prompt),
          field('这次调整有帮助吗？', select(values.outcome, [all('请选择'), ...outcomes],
            value => { values.outcome = value; }, { required: true })),
          field('现在的情绪（可选）', select(values.emotion, [all('不选择'), ...props.catalog.emotions],
            value => { values.emotion = value; })),
          field('想补充什么？', textarea(values.content, value => { values.content = value; }, { maxlength: 1500 })),
          values.outcome === 'HELPED' && notice('选择已改善后，系统会以“学生确认改善”结案。', 'info'),
          ['PARTLY', 'UNCHANGED'].includes(values.outcome) && notice('老师会收到你的回应，反馈将继续处理。', 'info'),
        ];
      }
      return field('取消说明（可选）', textarea(values.content, value => { values.content = value; }, {
        maxlength: 1000,
        placeholder: '可以告诉学生为什么调整了安排',
      }));
    }

    function card(item, index) {
      const state = { OPEN: '待答复', ANSWERED: '已答复', CANCELLED: '已取消' }[item.state];
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', '第 ' + (props.item.reviews.length - index) + ' 轮回访'),
          actions(badge(state), item.overdue && badge('逾期', 'waiting')),
        ]),
        h('p', { class: 'ef-text' }, item.prompt),
        h('p', { class: 'ef-meta' }, '邀请于 ' + date(item.created_at) + ' · 期望答复于 ' + date(item.due_at)),
        item.answer && h('div', { class: 'ef-answer' }, [
          actions(
            badge(label(outcomes, item.answer.outcome), item.answer.outcome === 'HELPED' ? 'good' : 'waiting'),
            item.answer.emotion && badge(emotion(props.catalog, item.answer.emotion)),
            h('time', { datetime: item.answer.created_at }, date(item.answer.created_at)),
          ),
          item.answer.content && h('p', { class: 'ef-text' }, item.answer.content),
        ]),
        actions(
          item.can_answer && button('填写这轮回访', () => start('answer', item), { primary: true, disabled: Boolean(mode.value) }),
          item.can_cancel && button('取消这轮回访', () => start('cancel', item), { disabled: Boolean(mode.value) }),
        ),
      ]);
    }

    return () => section('课堂体验回访', [
      notice(resultNote.value, 'good'),
      props.item.reviews.length ? h('ul', { class: 'ef-list' }, props.item.reviews.map(card)) : empty('还没有回访记录'),
      mode.value && h('form', { class: 'ef-form', onSubmit: send }, [
        fields(),
        notice(command.error.value),
        command.conflict.value && button('刷新反馈状态', () => emit('refresh')),
        actions(
          submit({ request: '发出回访邀请', answer: '提交回访', cancel: '确认取消回访' }[mode.value], command.busy.value),
          button('放弃编辑', close, { disabled: command.busy.value }),
        ),
      ]),
    ], props.staff && props.item.capabilities.request_review && button('发起回访', () => start('request'), {
      primary: true, disabled: Boolean(mode.value),
    }));
  },
};
