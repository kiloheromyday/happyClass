import { h } from 'vue';
export const scopeOptions = [['ALL', '全部数据'], ['REAL', '排除演示'], ['DEMO', '仅演示']];
export const DataScope = { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], setup: (props, { emit }) => () => h('label', { class: 'data-scope-control' }, [h('span', '数据范围'), h('select', { name: 'data_scope', value: props.modelValue, disabled: props.disabled, onChange: e => emit('update:modelValue', e.target.value) }, scopeOptions.map(([value, text]) => h('option', { value }, text)))]) };
export const matchesScope = (item, scope) => scope === 'ALL' || Boolean(item.is_demo) === (scope === 'DEMO');
