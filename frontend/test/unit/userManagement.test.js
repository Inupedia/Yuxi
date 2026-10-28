import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'
import { compileScript, parse } from 'vue/compiler-sfc'
import { computed, reactive, ref } from 'vue'

test('用户类型默认排除 APP 身份，切换类型回到第一页并保留搜索条件', async () => {
  const source = await fs.readFile(
    new URL('../../src/modules/settings/ui/UserManagementComponent.vue', import.meta.url), 'utf8'
  )
  const { descriptor } = parse(source)
  const executable = compileScript(descriptor, { id: 'user-management' }).content
    .replace(/^import[\s\S]*?from '[^']+'\n/gm, '').replace('export default', 'return')
  const requests = []
  const watches = []
  let unmount
  const deps = {
    reactive, computed, ref,
    watch: (read, run) => watches.push({ read: typeof read === 'function' ? read : () => read?.value, run }),
    onMounted() {}, onUnmounted: (run) => { unmount = run },
    useUserStore: () => ({ isSuperAdmin: true, userId: 1 }),
    authApi: { getUsersPage: async (params) => {
      requests.push(params)
      return { items: [], total: 0 }
    } },
    departmentApi: {}, message: {}, Modal: {},
    formatDateTime: (value) => value,
    isPasswordLongEnough: () => true, MIN_PASSWORD_LENGTH: 8,
    FallbackAvatar: {},
    ...Object.fromEntries(['Plus', 'SquarePen', 'Trash2', 'User', 'UserLock', 'UserStar', 'RefreshCw', 'Search', 'ListFilter'].map((name) => [name, {}]))
  }
  const component = new Function(...Object.keys(deps), executable)(...Object.values(deps))
  const page = component.setup({}, { expose() {} })
  try {
    const endUser = { id: 2, user_kind: 'end_user', role: 'user', username: 'app-visitor' }
    assert.equal(page.isUserEditDisabled(endUser), true)
    page.showEditUserModal(endUser)
    assert.equal(page.userManagement.modalVisible, false)
    assert.equal(page.userManagement.editUserId, null)
    const human = { ...endUser, user_kind: 'human', username: 'product-user' }
    assert.equal(page.isUserEditDisabled(human), false)
    page.showEditUserModal(human)
    assert.equal(page.userManagement.modalVisible, true)
    assert.equal(page.userManagement.form.username, 'product-user')
    await page.fetchUsers()
    assert.equal(requests[0].userKind, 'human')
    page.userManagement.currentPage = 3
    page.userManagement.searchKeyword = 'visitor'
    page.userManagement.userKindFilter = 'end_user'
    const filterWatch = watches.find(({ read }) => Array.isArray(read()))
    assert.deepEqual(filterWatch.read(), ['visitor', [], [], 'end_user'])
    filterWatch.run()
    assert.equal(page.userManagement.currentPage, 1)
    assert.equal(page.hasActiveFilters.value, true)
    await page.fetchUsers()
    assert.deepEqual(requests.at(-1), {
      offset: 0, limit: 20, search: 'visitor', departmentIds: [], roles: [], userKind: 'end_user'
    })
    page.userManagement.userKindFilter = 'all'
    await page.fetchUsers()
    assert.equal(requests.at(-1).userKind, 'all')
  } finally {
    unmount()
  }
})

test('表头筛选支持角色与部门多选，未选值不下发筛选参数', async () => {
  const source = await fs.readFile(
    new URL('../../src/modules/settings/ui/UserManagementComponent.vue', import.meta.url), 'utf8'
  )
  const { descriptor } = parse(source)
  const executable = compileScript(descriptor, { id: 'user-management-multi' }).content
    .replace(/^import[\s\S]*?from '[^']+'\n/gm, '').replace('export default', 'return')
  const requests = []
  const watches = []
  let unmount
  const deps = {
    reactive, computed, ref,
    watch: (read, run) => watches.push({ read: typeof read === 'function' ? read : () => read?.value, run }),
    onMounted() {}, onUnmounted: (run) => { unmount = run },
    useUserStore: () => ({ isSuperAdmin: true, userId: 1 }),
    authApi: { getUsersPage: async (params) => {
      requests.push(params)
      return { items: [], total: 0 }
    } },
    departmentApi: {}, message: {}, Modal: {},
    formatDateTime: (value) => value,
    isPasswordLongEnough: () => true, MIN_PASSWORD_LENGTH: 8,
    FallbackAvatar: {},
    ...Object.fromEntries(['Plus', 'SquarePen', 'Trash2', 'User', 'UserLock', 'UserStar', 'RefreshCw', 'Search', 'ListFilter'].map((name) => [name, {}]))
  }
  const component = new Function(...Object.keys(deps), executable)(...Object.values(deps))
  const page = component.setup({}, { expose() {} })
  try {
    await page.fetchUsers()
    // 未选择任何表头筛选时不携带多选参数
    assert.deepEqual(requests.at(-1).departmentIds, [])
    assert.deepEqual(requests.at(-1).roles, [])
    assert.equal(page.hasActiveFilters.value, false)

    page.setFilterOpen('role', true)
    page.filterDraft.role = ['admin', 'user']
    await page.fetchUsers()
    assert.deepEqual(requests.at(-1).roles, [])
    page.setFilterOpen('role', false)
    page.setFilterOpen('role', true)
    assert.deepEqual(page.filterDraft.role, [])
    page.filterDraft.role = ['admin', 'user']
    page.applyFilter('role')
    assert.equal(page.filterOpen.role, false)

    page.setFilterOpen('department', true)
    page.filterDraft.department = ['3', '5']
    page.applyFilter('department')
    const filterWatch = watches.find(({ read }) => Array.isArray(read()))
    filterWatch.run()
    await page.fetchUsers()
    assert.deepEqual(requests.at(-1).roles, ['admin', 'user'])
    assert.deepEqual(requests.at(-1).departmentIds, ['3', '5'])
    assert.equal(page.hasActiveFilters.value, true)

    page.setFilterOpen('role', true)
    page.filterDraft.role = []
    page.setFilterOpen('role', false)
    page.setFilterOpen('role', true)
    assert.deepEqual(page.filterDraft.role, ['admin', 'user'])
    page.filterDraft.role = []
    page.applyFilter('role')
    assert.deepEqual(page.userManagement.roleFilterValues, [])

    // APP 终端用户视图隐藏表头筛选
    page.userManagement.userKindFilter = 'end_user'
    assert.equal(page.showHeaderFilter.value, false)
    page.userManagement.userKindFilter = 'human'
    assert.equal(page.showHeaderFilter.value, true)
  } finally {
    unmount()
  }
})

test('部门筛选选项只保留有用户的部门，无人部门不进入候选', async () => {
  const source = await fs.readFile(
    new URL('../../src/modules/settings/ui/UserManagementComponent.vue', import.meta.url), 'utf8'
  )
  const { descriptor } = parse(source)
  const executable = compileScript(descriptor, { id: 'user-management-dept-options' }).content
    .replace(/^import[\s\S]*?from '[^']+'\n/gm, '').replace('export default', 'return')
  const deps = {
    reactive, computed, ref,
    watch: () => {},
    onMounted() {}, onUnmounted() {},
    useUserStore: () => ({ isSuperAdmin: true, userId: 1 }),
    authApi: { getUsersPage: async () => ({ items: [], total: 0 }) },
    departmentApi: {}, message: {}, Modal: {},
    formatDateTime: (value) => value,
    isPasswordLongEnough: () => true, MIN_PASSWORD_LENGTH: 8,
    FallbackAvatar: {},
    ...Object.fromEntries(['Plus', 'SquarePen', 'Trash2', 'User', 'UserLock', 'UserStar', 'RefreshCw', 'Search', 'ListFilter'].map((name) => [name, {}]))
  }
  const component = new Function(...Object.keys(deps), executable)(...Object.values(deps))
  const page = component.setup({}, { expose() {} })
  try {
    page.departmentManagement.departments = [
      { id: 1, name: '研发部', user_count: 5 },
      { id: 2, name: '空部门', user_count: 0 },
      { id: 3, name: '产品部', user_count: 2 }
    ]
    // 当前页用户兜底：部门列表缺失时按用户所在部门补齐。
    page.userManagement.users = [
      { id: 9, department_id: 3, department_name: '产品部' },
      { id: 10, department_id: null, department_name: '' }
    ]
    const labels = page.departmentFilterOptions.value.map((option) => option.label)
    assert.deepEqual(labels, ['研发部', '产品部'])
  } finally {
    page.userManagement.users = []
  }
})
