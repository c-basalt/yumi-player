<script setup lang="ts">
import { ref, reactive, h, watch, nextTick } from 'vue'
import { NText, NDataTable, NCheckbox, NButton, NInput, useMessage, useThemeVars } from 'naive-ui'
import { useSessionStorage } from '@vueuse/core'

import { getPlayHistory, type PlayHistoryEntry } from '@/api/player'
import PlayListNavigator from '@/components/PlayListNavigator.vue'
import { useManualAdd } from '@/composables/manualAdd'
import { isMobile } from '@/utils/breakpoint'


const loading = ref(false)
const message = useMessage()
const themeVars = useThemeVars()
const { addLoading, handleManualAdd } = useManualAdd(message)
const hideCanceled = useSessionStorage('play-history-hide-canceled', false)
const playHistory = useSessionStorage<PlayHistoryEntry[]>('play-history', [])
const entryFilter = ref('')

const pagination = reactive({
  page: 1,
  pageSize: 10,
  pageCount: 1,
  itemCount: 0,
  pageSizes: [10, 20, 50, 100],
  showSizePicker: true,
  prefix(info: { itemCount: number | undefined }) {
    return `共 ${info.itemCount ?? 0} 条记录`
  },
  _filter: '',
  showQuickJumper: !isMobile.value,
  simple: isMobile.value,
})
watch(isMobile, (value) => {
  pagination.showQuickJumper = !value
  pagination.simple = value
})

const fetchPlayHistory = async () => {
  loading.value = true
  try {
    const res = await getPlayHistory(pagination.page, pagination.pageSize, hideCanceled.value, entryFilter.value)
    playHistory.value = res.data
    pagination.itemCount = res.total
    pagination.pageCount = Math.ceil(res.total / pagination.pageSize)
    pagination._filter = res.filter
  } finally {
    loading.value = false
  }
}

const toNText = (text: string) => h(NText, null, { default: () => text })

const columns = [
  {
    title: '歌曲',
    key: 'name',
    width: 300,
    render: (row: PlayHistoryEntry) => h('span', [
      h(NText, { class: 'song-name' }, { default: () => row.song.title }),
      '\u00A0 ',
      h(NText, { class: 'song-singer', depth: '3' }, { default: () => `(${row.song.singer})` })
    ])
  },
  {
    title: '用户',
    key: 'user',
    width: 200,
    render: (row: PlayHistoryEntry) => toNText(
      row.user.privilege === 'owner' && !row.user.username ? '' : // entry added from control panel
        `${row.user.username}${row.user.uid ? ` (${row.user.uid})` : ''}`)
  },
  {
    title: '添加时间',
    key: 'created_at',
    width: 180,
    render: (row: PlayHistoryEntry) => toNText((new Date(row.created_at * 1000)).toLocaleString())
  }, {
    title: '操作',
    key: 'action',
    width: 10,
    render: (row: PlayHistoryEntry) => h(NButton, {
      size: 'small',
      style: { margin: '0px -8px', maxWidth: '48px', overflow: 'hidden' },
      loading: addLoading.value[`${row.song.source}-${row.song.id}`],
      onClick: () => handleManualAdd(row.song.source, row.song.id)
    }, () => '添加')

  }
]

const rowProps = (row: PlayHistoryEntry) => {
  return {
    class: row.canceled ? 'canceled-row' : ''
  }
}

const handlePageChange = async (page: number) => {
  pagination.page = page
  await fetchPlayHistory()
}

const handlePageSizeChange = async (pageSize: number) => {
  pagination.pageSize = pageSize
  pagination.page = 1
  await fetchPlayHistory()
}

watch(hideCanceled, () => {
  pagination.page = 1
  fetchPlayHistory()
})

fetchPlayHistory()
</script>

<template>
  <PlayListNavigator title="播放历史">
    <template #header-extra>
      <n-checkbox v-model:checked="hideCanceled">隐藏未播放</n-checkbox>
      <n-input v-model:value="entryFilter" placeholder="过滤搜索" clearable
        @keyup.enter="($event.target as HTMLInputElement).blur()"
        @blur="pagination._filter != entryFilter && fetchPlayHistory()" @clear="nextTick(() => fetchPlayHistory())"
        :style="pagination._filter ? { '--n-border': `1px solid ${themeVars.successColorHover}` } : undefined" />
    </template>
    <n-data-table remote :loading="loading" :columns="columns" :data="playHistory" :bordered="false"
      :pagination="pagination" :page-sizes="pagination.pageSizes" :row-props="rowProps" @update:page="handlePageChange"
      @update:page-size="handlePageSizeChange" />
  </PlayListNavigator>
</template>

<style scoped>
:deep(.canceled-row td),
:deep(.canceled-row td) .n-text {
  color: #999 !important;
  text-decoration: line-through;
}
</style>