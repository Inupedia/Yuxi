import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { computed, reactive } from 'vue'

const source = readFileSync(new URL('../../src/shared/ui/WidgetNode.vue', import.meta.url), 'utf8')

/** 执行真实节点样式映射，允许浏览器的 Row 规则提供换行基准。 */
function setupStyle(node) {
  const props = reactive({ node })
  const tags = source.slice(source.indexOf('const textTags ='), source.indexOf('const icons ='))
  const code = tags + source.slice(source.indexOf('const nodeStyle ='), source.indexOf('/** 图片组'))
  const style = new Function('computed', 'props', `${code}; return nodeStyle`)(computed, props)
  return { props, style }
}

test('等分列保留容器的换行基准，不把 basis 覆盖成零', () => {
  const { style } = setupStyle({ type: 'Col', flex: 1 })
  assert.equal(style.value.flexGrow, 1)
  assert.equal(style.value.flexShrink, 1)
  assert.equal(style.value.flexBasis, undefined)
  assert.equal(style.value.flex, undefined)
})

test('非扩展列按内容占宽，auto 列允许扩展', () => {
  const { props, style } = setupStyle({ type: 'Col', flex: 0 })
  assert.equal(style.value.flexGrow, 0)
  assert.equal(style.value.flexBasis, 'auto')
  props.node.flex = 'auto'
  assert.equal(style.value.flexGrow, 1)
  assert.equal(style.value.flexBasis, 'auto')
  delete props.node.flex
  assert.deepEqual(style.value, {})
})

test('表单外观属于最近的卡片，布局容器透传归属', () => {
  const props = reactive({ node: { type: 'Card', children: [] } })
  const code = source.slice(source.indexOf('const isFormCard ='), source.indexOf('const nodeStyle ='))
  const isFormCard = new Function('computed', 'props', `${code}; return isFormCard`)(computed, props)
  const form = { type: 'Form', children: [] }
  assert.equal(isFormCard.value, false)
  props.node.children = [{ type: 'Row', children: [{ type: 'Col', children: [form] }] }]
  assert.equal(isFormCard.value, true)
  props.node.children = [{ type: 'Card', children: [form] }]
  assert.equal(isFormCard.value, false)
  props.node.children.push(form)
  assert.equal(isFormCard.value, true)
  props.node.type = 'Col'
  assert.equal(isFormCard.value, false)
})
