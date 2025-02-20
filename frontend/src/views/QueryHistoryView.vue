<script setup lang="ts">
import { ref, reactive, h } from 'vue'
import { NText, NDataTable } from 'naive-ui'
import { useSessionStorage } from '@vueuse/core'

import { getQueryHistory, type QueryHistoryEntry } from '@/api/player'
import PlayListNavigator from '@/components/PlayListNavigator.vue'

const loading = ref(false)
const queryHistory = useSessionStorage<QueryHistoryEntry[]>('query-history', [])

const pagination = reactive({
  page: 1,
  pageSize: 10,
  pageCount: 1,
  itemCount: 0,
  pageSizes: [10, 20, 50, 100],
  showSizePicker: true,
  prefix(info: { itemCount: number | undefined }) {
    return `共 ${info.itemCount ?? 0} 条记录`
  }
})

const fetchQueryHistory = async () => {
  loading.value = true
  try {
    const res = await getQueryHistory(pagination.page, pagination.pageSize)
    queryHistory.value = res.data
    pagination.itemCount = res.total
    pagination.pageCount = Math.ceil(res.total / pagination.pageSize)
  } finally {
    loading.value = false
  }
}


const toNText = (text: string) => h(NText, null, {
  default: () => text
})


const columns = [
  {
    title: '搜索词',
    key: 'song',
    width: 200,
    render: (row: QueryHistoryEntry) => toNText(row.query_text)
  },
  {
    title: '用户',
    key: 'user',
    width: 150,
    render: (row: QueryHistoryEntry) => toNText(`${row.user.username}${row.user.uid ? ` (${row.user.uid})` : ''}`)
  },
  {
    title: '结果',
    key: 'result',
    width: 200,
    render: (row: QueryHistoryEntry) => {
      if (row.result == 'success') {
        return toNText(`添加"${row.song.title} / ${row.song.singer}"`)
      } else if (row.result == 'no-resource') {
        return toNText(`无资源（搜索结果${row.match_count}个）`)
      } else if (row.result == 'keyword-banned') {
        return toNText(`触发黑名单关键词 ${row.song.title}`)
      } else if (row.result == 'already-queued') {
        return toNText(`播放队列已有`)
      } else {
        return toNText(`失败（搜索结果${row.match_count}个）`)
      }
    }
  },
  {
    title: '搜索时间',
    key: 'created_at',
    width: 150,
    render: (row: QueryHistoryEntry) => toNText(new Date(row.created_at * 1000).toLocaleString())
  }
]

const rowProps = (row: QueryHistoryEntry) => {
  return {
    class: row.result !== 'success' ? 'failed' : ''
  }
}

const handlePageChange = async (page: number) => {
  pagination.page = page
  await fetchQueryHistory()
}

const handlePageSizeChange = async (pageSize: number) => {
  pagination.pageSize = pageSize
  pagination.page = 1
  await fetchQueryHistory()
}

fetchQueryHistory()
</script>

<template>
  <PlayListNavigator title="点歌历史">
    <n-data-table remote :loading="loading" :columns="columns" :row-props="rowProps" :data="queryHistory"
      :bordered="false" :pagination="pagination" :page-sizes="pagination.pageSizes" @update:page="handlePageChange"
      @update:page-size="handlePageSizeChange" />
  </PlayListNavigator>
</template>


<style scoped>
:deep(.failed td),
:deep(.failed td) .n-text {
  opacity: 0.75;
}
</style>