import { h, ref, watch } from 'vue';

export const Avatar = {
  props: ['person', 'variant'],
  setup(props) {
    const failed = ref(false);
    watch(() => props.person?.avatar_url, () => failed.value = false);
    return () => h('div', { class: [props.variant || 'buddy-avatar', 'photo-avatar', `avatar-${props.person?.avatar_color || 'sage'}`], 'aria-hidden': 'true' }, props.person?.avatar_url && !failed.value
      ? h('img', { src: props.person.avatar_url, alt: '', loading: 'lazy', onError: () => failed.value = true })
      : (props.person?.nickname || props.person?.username || '?').slice(0, 1).toUpperCase());
  },
};
