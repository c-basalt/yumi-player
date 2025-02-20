<script setup lang="ts">
import { ref, computed } from 'vue'
import { NSpace, NInput, NButton, NCard, NList, NListItem, NText, NSpin, NEmpty, NGrid, NGridItem, NModal, NCheckbox, NTag, useMessage, useThemeVars } from 'naive-ui'

import { manualSearch } from '@/api/player'
import { logger } from '@/api/logging'
import { useSessionStorage } from '@vueuse/core'
import { useManualAdd } from '@/composables/manualAdd'
import { formatTime } from '@/utils/utils'

const message = useMessage()
const themeVars = useThemeVars()
const searchQuery = useSessionStorage('manual-add-search-query', '')
const addAsFallback = useSessionStorage('manual-add-as-fallback', true)
const searchLoading = ref(false)
const { isAdding, handleManualAdd } = useManualAdd(message)

const searchResults = useSessionStorage<Record<string, Array<{
    id: string
    title: string
    singer: string
    meta: Record<string, any>
}>>>('manual-add-search-results', {})

const handleSearch = async () => {
    if (!searchQuery.value.trim()) return

    searchLoading.value = true
    try {
        searchResults.value = await manualSearch(searchQuery.value)
    } catch (error) {
        message.error('搜索失败')
        logger.error('[ManualRequest] Search failed:', error)
    } finally {
        searchLoading.value = false
    }
}

const handleExpand = async (bvid: string) => {
    searchLoading.value = true
    try {
        const result = await manualSearch(bvid)
        console.log(result, searchResults.value.Bilibili)
        result.Bilibili.forEach(song => {
            searchResults.value.Bilibili.filter(s => s.id === song.id).forEach(s => {
                s.meta = song.meta
            })
        })
    } catch (error) {
        message.error('展开失败')
        logger.error('[ManualRequest] Expand failed:', error)
    } finally {
        searchLoading.value = false
    }
}

const handleAddBvPages = async (bvid: string, pages: number) => {
    for (let page = 1; page <= pages; page++) {
        await handleManualAdd('Bilibili', `${bvid}_p${page}`, addAsFallback.value)
    }
}

const sourceNames: Record<string, string> = {
    Bilibili: 'Bilibili',
    QQMusic: 'QQ音乐',
    NeteaseMusic: '网易云音乐'
}

const searchHasResults = computed(() => {
    return Object.values(searchResults.value).some(results => results.length > 0)
})

const performSearch = async (newQuery: string) => {
    searchQuery.value = newQuery
    await handleSearch()
};
defineExpose({ performSearch });
const show = defineModel<boolean>('show');
const addBtnProps = computed(() => ({
    type: addAsFallback.value ? 'info' : 'primary' as 'info' | 'primary',
    ghost: true,
}))
</script>

<template>
    <n-modal v-model:show="show" preset="card" style="max-width: 600px; min-height: 400px">
        <template #header>
            <n-space align="center">
                <n-text>手动点歌</n-text>
                <n-checkbox v-model:checked="addAsFallback" :focusable="false"
                    :style="{ '--n-color-checked': themeVars.infoColor, '--n-border-checked': `1px solid ${themeVars.infoColor}` }">
                    <n-text :depth="addAsFallback ? 1 : 3">添加为后备播放</n-text>
                </n-checkbox>
            </n-space>
        </template>
        <n-space vertical>
            <n-space>
                <n-input v-model:value="searchQuery" placeholder="输入歌曲名称搜索" @keyup.enter="handleSearch" />
                <n-button type="primary" :disabled="!searchQuery.trim()" :loading="searchLoading" @click="handleSearch">
                    搜索
                </n-button>
            </n-space>

            <n-spin :show="searchLoading" style="max-height: 80vh; overflow-y: auto"
                content-style="padding-bottom: 40px;">
                <n-space vertical v-if="searchHasResults">
                    <n-card v-for="source in Object.keys(searchResults)" :key="source" :title="sourceNames[source]"
                        header-style="padding-bottom: 5px;">
                        <n-list v-if="searchResults[source].length">
                            <n-list-item v-for="song in searchResults[source]" :key="song.id">
                                <n-grid :cols="24" :x-gap="12">
                                    <n-grid-item :span="(song.meta.pages || []).length > 1 ? 24 : 20">
                                        <n-space vertical size="small">
                                            <n-text>
                                                {{ song.title }} <n-text depth="3" size="small">{{ song.id }}</n-text>
                                            </n-text>
                                            <template v-if="(song.meta.pages || []).length > 1">
                                                <n-button size="small" v-bind="addBtnProps"
                                                    :loading="isAdding(source, song.id)"
                                                    @click="handleAddBvPages(song.id, song.meta.pages.length)">
                                                    添加全部
                                                </n-button>
                                                <n-text v-for="page in song.meta.pages" :key="page.page">
                                                    <n-button size="tiny" v-bind="addBtnProps"
                                                        :loading="isAdding(source, `${song.id}_p${page.page}`)"
                                                        :disabled="isAdding(source, song.id)"
                                                        @click="handleManualAdd(source, `${song.id}_p${page.page}`, addAsFallback)">
                                                        添加P{{ page.page }}
                                                    </n-button>
                                                    <n-tag round size="small" style="margin-left: 4px;">
                                                        {{ formatTime(page.duration) }}
                                                    </n-tag>
                                                    {{ page.part }}
                                                </n-text>
                                            </template>
                                            <n-text depth="3" size="small">
                                                {{ song.singer }}
                                                <n-tag round size="small"
                                                    v-if="song.meta.duration && !((song.meta.pages || []).length > 1)"
                                                    style="margin-left: 2px;">
                                                    {{ formatTime(song.meta.duration) }}
                                                </n-tag>
                                            </n-text>
                                        </n-space>
                                    </n-grid-item>
                                    <n-grid-item :span="4" v-if="!((song.meta.pages || []).length > 1)"
                                        style="display: flex; align-items: center; flex-flow: column; justify-content: center; gap: 4px">
                                        <n-button size="small" v-bind="addBtnProps"
                                            :loading="isAdding(source, song.id)"
                                            @click="handleManualAdd(source, song.id, addAsFallback)">
                                            添加{{ source !== 'Bilibili' ? '' : ((song.meta.pages || []).length === 1) ?
                                            '(无分P)' :
                                            'P1' }}
                                        </n-button>
                                        <n-button v-if="source === 'Bilibili' && !song.meta.pages" size="small"
                                            @click="handleExpand(song.id)">
                                            展开
                                        </n-button>

                                    </n-grid-item>
                                </n-grid>
                            </n-list-item>
                        </n-list>
                    </n-card>
                </n-space>
                <n-empty v-else-if="Object.keys(searchResults).length" description="无搜索结果" style="padding: 60px 0px;" />
            </n-spin>
        </n-space>
    </n-modal>
</template>

<style scoped>
.n-input {
    min-width: 300px;
}

:deep(.n-list .n-list-item:last-child) {
    padding-bottom: 0;
}
</style>
