/// Tier A/B 元组件的 DOM 渲染实现（§38.1）：确定性的 节点+已解析状态 →
/// DOM 形状（§7.3 基线 18 语义对齐）。宿主可按 type 覆盖任意 builder。
/// 现代平台原语对位：<dialog>、popover API、语义表格/列表、原生输入族。

import type { MFNodeJson } from '../model/types.ts';
import type { MFRenderContext } from './interpreter.ts';

export type MFPrimitiveBuilder = (ctx: MFRenderContext, view: MFNodeView) => HTMLElement;

export interface MFNodeView {
  node: MFNodeJson;
  children: HTMLElement[];
  slots: Record<string, HTMLElement[]>;
}

export interface MFPrimitiveTable {
  builders: Map<string, MFPrimitiveBuilder>;
}

export function createPrimitiveTable(): MFPrimitiveTable {
  return { builders: new Map(defaultBuilders()) };
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

const MONOLINE_ICONS: Record<string, string> = {
  search: '<circle cx="9.5" cy="9.5" r="5.5"/><path d="m14 14 5 5"/>',
  close: '<path d="m5 5 12 12M17 5 5 17"/>',
  menu: '<path d="M4 7h14M4 12h14M4 17h14"/>',
  arrow_upward: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  arrow_downward: '<path d="M12 5v14m6-6-6 6-6-6"/>',
  arrow_forward: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  notifications: '<path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 19a2.5 2.5 0 0 0 4 0"/>',
  light_mode: '<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
  dark_mode: '<path d="M20 13.5A8 8 0 1 1 10.5 4 6.5 6.5 0 0 0 20 13.5"/>',
  add: '<path d="M12 5v14M5 12h14"/>',
  remove: '<path d="M5 12h14"/>',
  star: '<path d="m12 4 2.4 5 5.6.8-4 3.9 1 5.5-5-2.7-5 2.7 1-5.5-4-3.9 5.6-.8z"/>',
  open_in_new: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>',
};

function iconSvg(name: string, size: number): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.6');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = MONOLINE_ICONS[name] ?? MONOLINE_ICONS['close'] ?? '';
  return svg;
}

function num(props: Record<string, unknown>, key: string, fallback: number): number {
  const v = props[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

function str(props: Record<string, unknown>, key: string): string {
  const v = props[key];
  return typeof v === 'string' ? v : '';
}

function bool(props: Record<string, unknown>, key: string): boolean {
  return props[key] === true;
}

/** 默认 Tier A/B 渲染表。语义与无障碍：原生元素优先（§ accessibility 指南）。 */
function defaultBuilders(): [string, MFPrimitiveBuilder][] {
  return [
    ['Text', (ctx, view) => {
      const level = str(ctx.props, 'level');
      const raw = ctx.props['text'];
      const text = raw === null || raw === undefined ? '' : `${raw}`;
      const tone = str(ctx.props, 'tone');
      const toneClass = tone ? ` mf-text--${tone}` : '';
      if (['h1', 'h2', 'h3', 'h4'].includes(level)) {
        const h = el(level as 'h1', `mf-text mf-text-heading${toneClass}`);
        h.textContent = text;
        return h;
      }
      const span = el('span', `mf-text${toneClass}`);
      span.textContent = text;
      if (str(ctx.props, 'align')) span.style.textAlign = str(ctx.props, 'align');
      return span;
    }],
    ['Icon', (ctx, _view) => {
      const wrap = el('span', 'mf-icon');
      wrap.appendChild(iconSvg(str(ctx.props, 'name'), num(ctx.props, 'size', 20)));
      return wrap;
    }],
    ['Image', (ctx, _view) => {
      const img = el('img', 'mf-image');
      img.src = str(ctx.props, 'src');
      img.alt = str(ctx.props, 'alt');
      img.loading = 'lazy';
      img.decoding = 'async';
      return img;
    }],
    ['Button', (ctx, view) => {
      const variant = str(ctx.props, 'variant') || 'primary';
      const button = el('button', `mf-button mf-button--${variant}`);
      button.type = 'button';
      button.textContent = str(ctx.props, 'label');
      button.addEventListener('click', () => ctx.onEvent(view.node.id, 'press'));
      return button;
    }],
    ['Input', (ctx, view) => {
      const input = el('input', 'mf-input');
      const type = str(ctx.props, 'inputType') || 'text';
      input.type = ['text', 'email', 'password', 'number', 'tel', 'search', 'url'].includes(type) ? type : 'text';
      input.placeholder = str(ctx.props, 'placeholder');
      input.value = typeof ctx.props['value'] === 'string' ? (ctx.props['value'] as string) : '';
      if (str(ctx.props, 'name')) input.name = str(ctx.props, 'name');
      if (bool(ctx.props, 'obscure')) input.type = 'password';
      input.setAttribute('autocomplete', str(ctx.props, 'autocomplete') || 'off');
      input.addEventListener('change', () => ctx.onEvent(view.node.id, 'change', { value: input.value }));
      input.addEventListener('input', () => ctx.onEvent(view.node.id, 'input', { value: input.value }));
      return input;
    }],
    ['Select', (ctx, view) => {
      const select = el('select', 'mf-select');
      const options = Array.isArray(ctx.props['items']) ? ctx.props['items'] as { value: unknown; label?: string }[] : [];
      for (const option of options) {
        const opt = el('option');
        opt.value = `${option.value}`;
        opt.textContent = option.label ?? `${option.value}`;
        select.appendChild(opt);
      }
      select.value = typeof ctx.props['value'] === 'string' ? (ctx.props['value'] as string) : '';
      select.addEventListener('change', () => ctx.onEvent(view.node.id, 'change', { value: select.value }));
      return select;
    }],
    ['Checkbox', (ctx, view) => {
      const label = el('label', 'mf-checkbox');
      const input = el('input');
      input.type = 'checkbox';
      input.checked = bool(ctx.props, 'value');
      input.addEventListener('change', () => ctx.onEvent(view.node.id, 'change', { value: input.checked }));
      const text = el('span');
      text.textContent = str(ctx.props, 'label');
      label.append(input, text);
      return label;
    }],
    ['Stack', (ctx, view) => {
      const div = el('div', 'mf-stack');
      const direction = str(ctx.props, 'direction') || 'vertical';
      div.classList.add(direction === 'horizontal' ? 'mf-stack--horizontal' : 'mf-stack--vertical');
      const gap = ctx.props['gap'];
      if (typeof gap === 'number') div.style.gap = `${gap}px`;
      const align = str(ctx.props, 'align');
      if (align) div.dataset.align = align;
      if (bool(ctx.props, 'center')) div.dataset.center = 'true';
      const maxWidth = ctx.props['maxWidth'];
      if (typeof maxWidth === 'number') div.style.maxWidth = `${maxWidth}px`;
      for (const child of view.children) div.appendChild(child);
      return div;
    }],
    ['Scroll', (ctx, view) => {
      const div = el('div', 'mf-scroll');
      if (bool(ctx.props, 'horizontal')) div.classList.add('mf-scroll--horizontal');
      div.append(...(view.children.length ? view.children : []));
      return div;
    }],
    ['Overlay', (ctx, view) => {
      const div = el('div', 'mf-overlay');
      for (const child of view.children) div.appendChild(child);
      return div;
    }],
    ['List', (ctx, view) => {
      const list = el('ul', 'mf-list');
      for (const child of view.children) {
        const li = el('li', 'mf-list__item');
        li.appendChild(child);
        list.appendChild(li);
      }
      return list;
    }],
    ['Modal', (ctx, view) => {
      const dialog = el('dialog', 'mf-modal');
      if (str(ctx.props, 'title')) {
        const header = el('header', 'mf-modal__header');
        header.textContent = str(ctx.props, 'title');
        dialog.appendChild(header);
      }
      for (const child of view.children) dialog.appendChild(child);
      if (bool(ctx.props, 'open')) {
        // showModal 要求元素已连接文档树——构建期是 detached 的，挂载后微任务再开。
        queueMicrotask(() => {
          if (dialog.isConnected && !dialog.open) dialog.showModal();
        });
      }
      return dialog;
    }],
    // ---- Tier B ----
    ['Grid', (ctx, view) => {
      const div = el('div', 'mf-grid');
      const columns = num(ctx.props, 'columns', 2);
      const gap = num(ctx.props, 'gap', 8);
      div.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
      div.style.gap = `${gap}px`;
      for (const child of view.children) div.appendChild(child);
      return div;
    }],
    ['Split', (ctx, view) => {
      const div = el('div', 'mf-split');
      const horizontal = (str(ctx.props, 'direction') || 'horizontal') !== 'vertical';
      div.classList.add(horizontal ? 'mf-split--horizontal' : 'mf-split--vertical');
      const gap = num(ctx.props, 'gap', 0);
      if (gap) div.style.gap = `${gap}px`;
      const weights = Array.isArray(ctx.props['weights']) ? ctx.props['weights'] as number[] : [];
      view.children.forEach((child, i) => {
        const pane = el('div', 'mf-split__pane');
        pane.style.flex = `${weights[i] ?? 1} 1 0%`;
        pane.appendChild(child);
        div.appendChild(pane);
      });
      return div;
    }],
    ['Anchor', (ctx, view) => {
      const div = el('div', 'mf-anchor');
      const anchor = str(ctx.props, 'anchor');
      if (anchor) div.dataset.anchor = anchor;
      if (view.children.length) div.appendChild(view.children[0]!);
      return div;
    }],
    ['Tabs', (ctx, view) => {
      const wrap = el('div', 'mf-tabs');
      wrap.setAttribute('role', 'tablist');
      const items = Array.isArray(ctx.props['items']) ? ctx.props['items'] as { value: string; label?: string }[] : [];
      const current = str(ctx.props, 'value');
      for (const item of items) {
        const tab = el('button', 'mf-tabs__tab');
        tab.type = 'button';
        tab.setAttribute('role', 'tab');
        tab.textContent = item.label ?? item.value;
        tab.setAttribute('aria-selected', String(item.value === current));
        if (item.value === current) tab.classList.add('mf-tabs__tab--active');
        tab.addEventListener('click', () => ctx.onEvent(view.node.id, 'change', { value: item.value }));
        wrap.appendChild(tab);
      }
      return wrap;
    }],
    ['Drawer', (ctx, view) => {
      const aside = el('aside', 'mf-drawer');
      if (bool(ctx.props, 'open')) aside.setAttribute('open', '');
      for (const child of view.children) aside.appendChild(child);
      return aside;
    }],
    ['Table', (ctx, view) => {
      const table = el('table', 'mf-table');
      const columns = Array.isArray(ctx.props['columns']) ? ctx.props['columns'] as { key: string; label?: string }[] : [];
      const rows = Array.isArray(ctx.props['rows']) ? ctx.props['rows'] as Record<string, unknown>[] : [];
      const thead = el('thead');
      const headRow = el('tr');
      for (const col of columns) {
        const th = el('th');
        th.scope = 'col';
        th.textContent = col.label ?? col.key;
        headRow.appendChild(th);
      }
      thead.appendChild(headRow);
      const tbody = el('tbody');
      for (const row of rows) {
        const tr = el('tr');
        for (const col of columns) {
          const td = el('td');
          td.textContent = `${row[col.key] ?? ''}`;
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      table.append(thead, tbody);
      return table;
    }],
  ];
}
