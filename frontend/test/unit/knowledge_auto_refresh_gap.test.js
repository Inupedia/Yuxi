import test from 'node:test'
import assert from 'node:assert/strict'

import { createPinia, setActivePinia } from 'pinia'
import { createApp } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { createTestServer } from '../helpers/createTestServer.js'

const storageValues = new Map()
globalThis.localStorage = {
  getItem: (key) => storageValues.get(key) ?? null,
  setItem: (key, value) => storageValues.set(key, String(value)),
  removeItem: (key) => storageValues.delete(key),
  clear: () => storageValues.clear()
}

async function setupStore(t, { fileStatus, processingCount = 0 }) {
  const server = await createTestServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  })
  const pinia = createPinia()
  const app = createApp({})
  app.use(pinia)
  app.use(createRouter({ history: createMemoryHistory(), routes: [] }))
  setActivePinia(pinia)
  const { documentApi, knowledgeBaseApi } = await server.ssrLoadModule('/src/apis/knowledge_api.js')
  const { useKnowledgeBaseStore, consumeSubmissionGrace } = await server.ssrLoadModule(
    '/src/modules/knowledge/model/knowledgeBase.js'
  )
  const store = app.runWithContext(() => useKnowledgeBaseStore())
  store.kbId = 'kb-gap'
  t.mock.method(message, 'success', () => {})
  t.mock.method(message, 'error', () => {})
  t.mock.method(console, 'error', () => {})
  t.mock.method(knowledgeBaseApi, 'getKnowledgeBaseInfo', async () => ({
    stats: { processing_count: processingCount }
  }))
  const list = t.mock.method(documentApi, 'listDocuments', async () => ({
    items: [{ file_id: 'f1', status: fileStatus }],
    stats: { processing_count: processingCount }
  }))
  t.mock.method(documentApi, 'indexDocuments', async () => ({ status: 'queued', job_id: 'job-1' }))
  return { server, store, consumeSubmissionGrace, list }
}

test('提交宽限只在存在等待领取文件且有剩余宽限时继续轮询', async () => {
  const server = await createTestServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  try {
    const { consumeSubmissionGrace } = await server.ssrLoadModule(
      '/src/modules/knowledge/model/knowledgeBase.js'
    )
    assert.deepEqual(consumeSubmissionGrace({ hasUploadedWaiting: true, gracePolls: 2 }), {
      continuePolling: true,
      gracePolls: 1
    })
    assert.deepEqual(consumeSubmissionGrace({ hasUploadedWaiting: true, gracePolls: 0 }), {
      continuePolling: false,
      gracePolls: 0
    })
    assert.deepEqual(consumeSubmissionGrace({ hasUploadedWaiting: false, gracePolls: 5 }), {
      continuePolling: false,
      gracePolls: 5
    })
  } finally {
    await server.close()
  }
})

test('提交入库后 uploaded 等待领取期间保持轮询', async (t) => {
  const { server, store } = await setupStore(t, { fileStatus: 'uploaded' })
  try {
    assert.equal(await store.indexFiles(['f1']), true)
    assert.equal(store.state.autoRefresh, true)

    // 连续多轮读取：uploaded 等待领取期间不应按"无处理活动"停止（旧行为是立即停止）。
    for (let i = 0; i < 8; i += 1) {
      await store.loadDocumentFiles({ isBackground: true })
      assert.equal(store.state.autoRefresh, true, `第 ${i} 次后台读取后仍应轮询`)
    }
  } finally {
    store.stopAutoRefresh()
    store.$dispose()
    await server.close()
  }
})

test('宽限有界：僵尸 uploaded 最终自动停止，不会无限轮询', async (t) => {
  const { server, store, list } = await setupStore(t, { fileStatus: 'uploaded' })
  try {
    assert.equal(await store.indexFiles(['f1']), true)
    let polls = 0
    while (store.state.autoRefresh && polls < 40) {
      await store.loadDocumentFiles({ isBackground: true })
      polls += 1
    }
    assert.equal(store.state.autoRefresh, false, '僵尸等待必须在有界轮数后停止')
    // 提交触发的 delayedRefresh 已消耗 2 次列表读取；宽限(12)耗尽后停止，远小于 40 轮。
    assert.ok(list.mock.callCount() <= 16, `轮询应有界，实际读取 ${list.mock.callCount()} 次`)
  } finally {
    store.stopAutoRefresh()
    store.$dispose()
    await server.close()
  }
})

test('负向：手动开启不受 ensure 自动停止（manual 语义保留），宽限只由提交授予', async (t) => {
  const { server, store } = await setupStore(t, { fileStatus: 'uploaded' })
  try {
    // 手动开启是用户意志：uploaded 不能触发 ensure 停止，也不消耗提交宽限。
    store.toggleAutoRefresh()
    assert.equal(store.state.autoRefresh, true)
    await store.loadDocumentFiles({ isBackground: true })
    assert.equal(store.state.autoRefresh, true)
    // 负向证明"宽限由提交授予"：手动轮没有宽限，僵尸停止只能由 tick 的 stale 上限完成。
  } finally {
    store.stopAutoRefresh()
    store.$dispose()
    await server.close()
  }
})

test('文件进入 processing 后宽限让位于真实处理信号并正常收尾', async (t) => {
  const { server, store, list } = await setupStore(t, { fileStatus: 'uploaded' })
  try {
    assert.equal(await store.indexFiles(['f1']), true)
    // worker 领取：状态变为 processing（真实 pending 信号，保持轮询且不消耗宽限）
    list.mock.mockImplementation(async () => ({
      items: [{ file_id: 'f1', status: 'processing' }],
      stats: { processing_count: 1 }
    }))
    await store.loadDocumentFiles({ isBackground: true })
    assert.equal(store.state.autoRefresh, true)

    // 处理完成：无 pending、无 uploaded -> 自动停止
    list.mock.mockImplementation(async () => ({
      items: [{ file_id: 'f1', status: 'indexed' }],
      stats: { processing_count: 0 }
    }))
    await store.loadDocumentFiles({ isBackground: true })
    assert.equal(store.state.autoRefresh, false)
  } finally {
    store.stopAutoRefresh()
    store.$dispose()
    await server.close()
  }
})
