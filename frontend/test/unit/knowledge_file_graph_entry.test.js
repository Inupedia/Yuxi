import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from 'vue/compiler-sfc'

/** 从组件中提取实际执行的声明，注入外部依赖以检查行为。 */
function componentLogic(path, names, dependencies, exported) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const { scriptSetupAst } = compileScript(descriptor, { id: 'file-graph-entry-test' })
  const declarations = names.map((name) => {
    const node = scriptSetupAst.find(
      (item) => item.type === 'VariableDeclaration' &&
        item.declarations.some((declaration) => declaration.id.name === name)
    )
    assert.ok(node, `缺少 ${name}`)
    return descriptor.scriptSetup.content.slice(node.start, node.end)
  })
  return new Function(...Object.keys(dependencies), `${declarations.join('\n')}; return ${exported}`)(
    ...Object.values(dependencies)
  )
}

const tablePath = '../../src/modules/knowledge/ui/FileTable.vue'
const pagePath = '../../src/pages/KnowledgeBaseInfoView.vue'

test('文件菜单提供查看图谱，点击关闭菜单并传递当前文件', () => {
  const source = readFileSync(new URL(tablePath, import.meta.url), 'utf8')
  assert.match(source, /<template v-else>\s*<a-button[^>]*@click="viewFileGraph\(row\)"[^>]*>[\s\S]*?查看图谱/)
  const visible = { value: { 'file-a': true } }
  const events = []
  const action = componentLogic(tablePath, ['closePopover', 'viewFileGraph'], {
    popoverVisibleMap: visible,
    emit: (...args) => events.push(args)
  }, 'viewFileGraph')
  const file = { file_id: 'file-a', file_name: '合同.pdf' }
  action(file)
  assert.equal(visible.value['file-a'], false)
  assert.deepEqual(events, [['view-graph', file]])
})

test('查看图谱直接进入所选文件并保留其他路由参数', () => {
  const pushes = []
  const action = componentLogic(pagePath, ['viewFileGraph'], {
    route: { query: { section: 'filetable', folder: 'folder-a' } },
    router: { push: (target) => pushes.push(target) }
  }, 'viewFileGraph')

  action({ file_id: 'file-a' })
  assert.deepEqual(pushes, [{ query: { section: 'graph', folder: 'folder-a', file_id: 'file-a' } }])
})
