import assert from 'node:assert/strict'
import test from 'node:test'

import { createRenderer, h, nextTick } from 'vue'
import { compileScript, parse } from 'vue/compiler-sfc'
import { readFileSync } from 'node:fs'
import { createTestServer } from '../helpers/createTestServer.js'

const makeNode = (type) => ({ type, children: [], props: {}, parent: null, text: '' })

const renderer = createRenderer({
  createElement: makeNode,
  createText: (text) => ({ ...makeNode('text'), text }),
  createComment: (text) => ({ ...makeNode('comment'), text }),
  insert(child, parent, anchor = null) {
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove(child) {
    const index = child.parent?.children.indexOf(child) ?? -1
    if (index >= 0) child.parent.children.splice(index, 1)
  },
  setText: (node, text) => {
    node.text = text
  },
  setElementText: (node, text) => {
    node.text = text
    node.children = []
  },
  parentNode: (node) => node.parent,
  nextSibling: (node) => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  patchProp(node, key, _oldValue, value) {
    node.props[key] = value
  }
})

const find = (node, predicate) => {
  if (predicate(node)) return node
  for (const child of node.children || []) {
    const match = find(child, predicate)
    if (match) return match
  }
  return undefined
}

const textContent = (node) =>
  [node.text, ...(node.children || []).map((child) => textContent(child))].join('')

async function loadHeatmap() {
  const server = await createTestServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
    plugins: [
      {
        name: 'activity-heatmap-test',
        resolveId(id) {
          if (id === 'virtual:activity-heatmap-test') return `\0${id}`
        },
        load(id) {
          if (id !== '\0virtual:activity-heatmap-test') return
          const source = readFileSync(
            new URL('../../src/modules/dashboard/ui/DashboardActivityHeatmap.vue', import.meta.url),
            'utf8'
          )
          return compileScript(parse(source).descriptor, {
            id: 'activity-heatmap-test',
            inlineTemplate: true
          }).content
        }
      }
    ]
  })
  return { server, component: (await server.ssrLoadModule('virtual:activity-heatmap-test')).default }
}

test('热力图按 valueKey 渲染消息计数与总量', async () => {
  const { server, component } = await loadHeatmap()
  try {
    const host = makeNode('root')
    const app = renderer.createApp(() =>
      h(component, {
        data: [
          { date: '2026-10-24', message_count: 3 },
          { date: '2026-10-25', message_count: 4 }
        ],
        valueKey: 'message_count',
        valueLabel: '条消息',
        totalUnit: '条消息',
        ariaLabel: '近 120 天消息活动'
      })
    )
    app.mount(host)
    await nextTick()

    const grid = find(host, (node) => node.props['aria-label'] === '近 120 天消息活动')
    assert.ok(grid)
    const tooltip = find(host, (node) => node.props.title === '2026-10-25：4 条消息')
    assert.ok(tooltip)
    const footer = find(host, (node) => node.props.class === 'heatmap-total')
    assert.equal(textContent(footer), '7 条消息')
    app.unmount()
  } finally {
    await server.close()
  }
})

test('热力图默认口径保持 Dashboard 活跃用户语义', async () => {
  const { server, component } = await loadHeatmap()
  try {
    const host = makeNode('root')
    const app = renderer.createApp(() =>
      h(component, {
        data: [{ date: '2026-10-25', active_users: 2 }]
      })
    )
    app.mount(host)
    await nextTick()

    const tooltip = find(host, (node) => node.props.title === '2026-10-25：2 位活跃用户')
    assert.ok(tooltip)
    const footer = find(host, (node) => node.props.class === 'heatmap-total')
    assert.equal(textContent(footer), '2 次活跃记录')
    app.unmount()
  } finally {
    await server.close()
  }
})
