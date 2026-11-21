import type { MFProjectJson } from '../../src/model/types.ts';

/** 最小可用 fixture：home 页 + 计数绑定 + 导航。 */
export function miniProject(): MFProjectJson {
  return {
    manifest: {
      project_id: 'mini',
      entry_page: 'home-page',
      default_theme: 'theme-light',
      default_locale: 'zh-CN',
      type_dialect_version: '1.0',
    },
    pages: [
      {
        id: 'home-page',
        route: '/',
        stateMembers: ['count', 'title'],
        tree: {
          id: 'root',
          type: 'Stack',
          children: [
            { id: 'title', type: 'Text', props: { text: { ref: 'state.title' } } },
            {
              id: 'inc',
              type: 'Button',
              props: { label: '加一' },
              children: [],
            },
            {
              id: 'count',
              type: 'Text',
              props: { text: { ref: 'state.count' } },
            },
            {
              id: 'goto',
              type: 'Button',
              props: { label: '去详情', variant: 'secondary' },
            },
          ],
        },
        onEnter: 'home-enter',
      },
      {
        id: 'detail-page',
        route: '/detail',
        stateMembers: [],
        tree: { id: 'detail-root', type: 'Stack', children: [{ id: 'd-title', type: 'Text', props: { text: '详情' } }] },
      },
    ],
    bindingMaps: {
      'map-home': {
        id: 'map-home',
        bindings: [
          {
            id: 'home-enter',
            on: 'home-page.onEnter',
            concurrency: 'reject-new',
            actions: [
              { kind: 'state', target: 'title', value: '首页', scope: 'page' },
              { kind: 'state', target: 'count', value: 0, scope: 'page' },
            ],
          },
          {
            id: 'inc-count',
            on: 'inc.press',
            concurrency: 'reject-new',
            actions: [
              {
                kind: 'adapter',
                call: 'mini.increment',
                arguments: { current: { ref: 'state.count' } },
                as: 'next',
                timeout_ms: 800,
              },
              { kind: 'state', target: 'count', value: { ref: 'prev.next' }, scope: 'page' },
            ],
          },
          {
            id: 'go-detail',
            on: 'goto.press',
            concurrency: 'reject-new',
            actions: [{ kind: 'navigation', target: 'detail-page' }],
          },
        ],
      },
    },
    tokens: {
      'tokens-mini': {
        id: 'tokens-mini',
        tokens: {
          'color.bg.canvas': { ref: 'color.bg.canvas.light' },
          'color.bg.canvas.light': '#F2F1EC',
          'color.bg.canvas.dark': '#0A0B0D',
          'color.glass.surface.light': '#C7FFFFFF',
          'color.accent': '#0071E3',
          'motion.entrance': { duration: 300, curve: [0.16, 1, 0.3, 1] },
          'motion.entrance.reduced': { duration: 0, curve: [0, 0, 1, 1] },
        },
      },
    },
    themes: {
      'theme-light': { id: 'theme-light', base: 'tokens-mini' },
      'theme-dark': {
        id: 'theme-dark',
        extends: 'theme-light',
        overrides: { 'color.bg.canvas': { ref: 'color.bg.canvas.dark' } },
      },
    },
    navigation: {
      edges: [{ from: 'home-page', to: 'detail-page' }],
      fallback: {},
    },
    registry: [
      {
        id: 'mini.increment',
        kind: 'function',
        contract: { output: { type: 'number' } },
        description: '计数 +1',
      },
      {
        id: 'Stack',
        kind: 'primitive',
        contract: { motion_surfaces: ['entrance', 'hover'], layout: { display: ['block'], sizing: ['hug', 'fill'] } },
        description: '布局容器',
      },
      {
        id: 'Text',
        kind: 'primitive',
        contract: { motion_surfaces: ['entrance'], props: { text: { type: 'string' } } },
        description: '文本',
      },
      {
        id: 'Button',
        kind: 'primitive',
        contract: { motion_surfaces: ['hover'], props: { label: { type: 'string' } }, events: { press: { type: 'string' } } },
        description: '按钮',
      },
    ],
  };
}
