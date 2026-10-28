import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { nextTick, reactive, ref, watch } from 'vue'
import { compileScript, parse } from 'vue/compiler-sfc'

const source = readFileSync(new URL('../../src/modules/knowledge/ui/FileSearchModal.vue', import.meta.url), 'utf8')
const executable = compileScript(parse(source).descriptor, { id: 'file-search-error' }).content
  .replace(/^import[\s\S]*?from '[^']+'\n/gm, '')
  .replace('export default', 'return')

/** 按真实组件执行搜索状态机，替换搜索接口。 */
function setupSearch(searchDocuments) {
  const component = new Function('nextTick', 'ref', 'watch', 'FileText', 'Search', 'X', 'dayjs', 'parseToShanghai', 'formatFileSize', 'documentApi', executable)(
    nextTick, ref, watch, {}, {}, {}, {}, () => null, () => '', { searchDocuments }
  )
  const props = reactive({ open: false, kbId: 'kb' })
  return { props, state: component.setup(props, { expose() {}, emit() {} }) }
}

test('搜索失败显示错误，重试成功后展示结果，空结果保持独立', async () => {
  let attempt = 0
  const { state } = setupSearch(async () => {
    attempt++
    if (attempt === 1) throw new Error('offline')
    return { files: attempt === 2 ? [{ file_id: 'file', filename: '报告.txt' }] : [] }
  })
  state.keyword.value = '报告'
  const warn = console.warn
  console.warn = () => {}
  try {
    await state.handleSearch()
  } finally {
    console.warn = warn
  }
  assert.equal(state.searchError.value, true)
  assert.equal(state.hasSearched.value, true)
  assert.equal(state.loading.value, false)
  assert.deepEqual(state.results.value, [])
  await state.handleSearch()
  assert.equal(state.searchError.value, false)
  assert.equal(state.results.value[0].filename, '报告.txt')
  await state.handleSearch()
  assert.equal(state.searchError.value, false)
  assert.deepEqual(state.results.value, [])
})

test('过期失败不能覆盖后一次搜索结果', async () => {
  const pending = []
  const { state } = setupSearch(() => new Promise((resolve, reject) => pending.push({ resolve, reject })))
  state.keyword.value = '旧'
  const oldRequest = state.handleSearch()
  state.keyword.value = '新'
  const newRequest = state.handleSearch()
  pending[1].resolve({ files: [{ file_id: 'new' }] })
  await newRequest
  pending[0].reject(new Error('offline'))
  await oldRequest
  assert.equal(state.searchError.value, false)
  assert.equal(state.results.value[0].file_id, 'new')
})
