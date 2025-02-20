<script setup lang="ts">
import { computed, ref, shallowReactive, watch } from 'vue'
import { NSpace, NList, NListItem, NButton, NText, NIcon, NSpin, NSkeleton, NFlex, NTag, NCheckbox, NPopover, NPopconfirm, useThemeVars } from 'naive-ui'
import { useSessionStorage } from '@vueuse/core'
import { useSortable } from '@vueuse/integrations/useSortable'
import { Delete24Regular, ArrowCircleRight24Regular, ArrowDownload24Filled, ArrowUpload24Filled } from '@vicons/fluent'

import PlayListNavigator from '@/components/PlayListNavigator.vue'
import { usePlayerStatus } from '@/composables/playerStatus'
import { sortPlaylist, type SongEntry } from '@/api/player'
import { formatTime } from '@/utils/utils'

const themeVars = useThemeVars()
const combinedList = shallowReactive<SongEntry[]>([]);
let suppressStatusUntil = 0;
const { playerStatus, playerLoading: loading, sendCommand } = usePlayerStatus((command) => {
    if (Date.now() < suppressStatusUntil) {
        if (['status', 'progress'].includes(command.command?.cmd || '')) {
            return;
        }
    }
    if (JSON.stringify(command.status.combined_list) !== JSON.stringify(combinedList)) {
        combinedList.splice(0, combinedList.length, ...command.status.combined_list);
    }
});

const sortableRef = ref<HTMLElement | null>(null);
const createSortable = () => useSortable(sortableRef, combinedList, {
    onUpdate: (event: any) => {
        const item = combinedList.splice(event.oldIndex!, 1)[0]
        combinedList.splice(event.newIndex!, 0, item)
        sortPlaylist(combinedList.map(item => item.id))
    }
});
let sortableControl = createSortable();
watch(sortableRef, () => {
    sortableControl.stop();
    sortableControl = createSortable();
});

const hideFallback = useSessionStorage('playlist-control-hide-fallback', false)
const handleRemove = (id: number) => {
    sendCommand('cancel', id)
    suppressStatusUntil = 0;
}
const handleMoveDown = (id: number) => {
    sendCommand('move-to-end', id)
    suppressStatusUntil = Date.now() + 1000;
}
const handleMoveTop = (id: number) => {
    sendCommand('move-to-top', id)
    suppressStatusUntil = Date.now() + 1000;
}
const updateFallback = (id: number, fallback: boolean) => {
    sendCommand(fallback ? 'set-is-fallback' : 'unset-is-fallback', id)
}

const currentId = computed(() => playerStatus.value?.current?.id)
const nextId = computed(() => combinedList.filter(i => playerStatus.value?.current?.is_fallback || !i.is_fallback)[1]?.id)
const consoleItems = computed(() => combinedList.filter(item => item.is_from_control && (!hideFallback.value || !item.is_fallback)))
const fallbackItems = computed(() => combinedList.filter(item => item.is_fallback))

const handleBatchRemove = (item_ids: number[]) => {
    item_ids.forEach((id, index) => setTimeout(() => handleRemove(id), 50 * index));
}
</script>

<template>
    <PlayListNavigator title="播放列表">
        <template #header-extra>
            <n-space size="small">
                <n-checkbox v-model:checked="hideFallback">隐藏后备</n-checkbox>
                <n-popconfirm @positive-click="() => handleBatchRemove(consoleItems.map(item => item.id))"
                    negative-text="取消" positive-text="确认清空" placement="bottom"
                    :positive-button-props="{ type: 'error' }">
                    <template #trigger>
                        <n-button type="error" ghost size="small" :disabled="consoleItems.length === 0">
                            清空控制台添加
                        </n-button>
                    </template>
                    确定清空从控制台手动添加的 {{ consoleItems.length }} 首歌曲吗？
                </n-popconfirm>
                <n-popconfirm @positive-click="() => handleBatchRemove(fallbackItems.map(item => item.id))"
                    placement="bottom" negative-text="取消" positive-text="确认清空"
                    :positive-button-props="{ type: 'error' }">
                    <template #trigger>
                        <n-button type="error" ghost size="small"
                            :disabled="hideFallback || fallbackItems.length === 0">
                            清空后备
                        </n-button>
                    </template>
                    确定清空 {{ fallbackItems.length }} 首后备歌曲吗？
                </n-popconfirm>
            </n-space>
        </template>
        <n-spin :show="loading">
            <template v-if="playerStatus">
                <n-list v-if="combinedList.length" ref="sortableRef">
                    <TransitionGroup name="list">
                        <n-list-item v-for="item in combinedList" :key="item.id"
                            :class="{ current: item.id === currentId }"
                            :style="hideFallback && item.is_fallback ? { height: '0px', overflow: 'hidden', padding: '0px' } : { height: '75px' }">
                            <n-flex justify="space-between" align="center">
                                <n-space vertical size="small">
                                    <n-text :depth="item.is_fallback && item.id !== currentId ? 3 : 1"
                                        :style="{ fontWeight: item.id === currentId ? 'bold' : undefined }">{{
                                            item.music.title }}</n-text>
                                    <n-text depth="3" size="small">
                                        <n-tag :bordered="false" round size="small" style="margin-right: 2px;">
                                            {{ formatTime(item.progress) }}
                                            {{ item.music.duration ? ` / ${formatTime(item.music.duration)}` : '' }}
                                        </n-tag>
                                        <n-tag :bordered="false" round size="small" v-if="item.is_fallback" type="info"
                                            style="margin-right: 2px;">
                                            后备
                                        </n-tag>
                                        <n-tag v-if="item.is_from_control" :bordered="false" round size="small"
                                            type="success">
                                            控制台
                                        </n-tag>
                                        {{ item.music.singer }} ({{ {
                                            NeteaseMusic: '网易云',
                                            Bilibili: 'B站',
                                            QQMusic: 'QQ音乐'
                                        }[item.music.source] || item.music.source }})</n-text>
                                </n-space>
                                <n-space justify="end" size="small" align="center"
                                    style="flex-grow: 1; margin-top: 10px;">
                                    <n-text depth="3" size="small" v-if="item.user?.username">
                                        由 {{ item.user.username }} 添加
                                    </n-text>

                                    <n-popover trigger="hover" :delay="1500">
                                        <template #trigger>
                                            <n-button quaternary circle @click="handleMoveTop(item.id)"
                                                :disabled="item.id === currentId || item.id === fallbackItems[0]?.id || item.id === nextId">
                                                <template #icon>
                                                    <n-icon :component="ArrowUpload24Filled" size="24" />
                                                </template>
                                            </n-button>
                                        </template>
                                        {{ item.id === fallbackItems[0]?.id || item.id === nextId ? '已是队列首位' :
                                            item.id === currentId ? '已在播放' : '移动到队列首位' }}
                                    </n-popover>

                                    <n-popover trigger="hover" :delay="1500">
                                        <template #trigger>
                                            <n-button quaternary circle @click="handleMoveDown(item.id)"
                                                :disabled="item.id === combinedList[combinedList.length - 1].id">
                                                <template #icon>
                                                    <n-icon :component="ArrowDownload24Filled" size="24" />
                                                </template>
                                            </n-button>
                                        </template>
                                        {{ item.id === combinedList[combinedList.length - 1].id ? '已是播放列表末尾' :
                                            '移动到播放列表末尾'
                                        }}
                                    </n-popover>

                                    <n-popover trigger="hover" :delay="1500">
                                        <template #trigger>
                                            <n-button quaternary circle
                                                :color="item.is_fallback ? themeVars.infoColorPressed : undefined"
                                                @click="updateFallback(item.id, !item.is_fallback)" :focusable="false">
                                                <template #icon>
                                                    <n-icon :component="ArrowCircleRight24Regular" size="24" />
                                                </template>
                                            </n-button>
                                        </template>
                                        {{ item.is_fallback ? '取消后备' : '设置为后备' }}
                                    </n-popover>

                                    <n-popover trigger="hover" :delay="1500">
                                        <template #trigger>
                                            <n-button quaternary circle type="error" @click="handleRemove(item.id)">
                                                <template #icon>
                                                    <n-icon :component="Delete24Regular" size="24" />
                                                </template>
                                            </n-button>
                                        </template>
                                        从播放列表移除
                                    </n-popover>

                                </n-space>
                            </n-flex>
                        </n-list-item>
                    </TransitionGroup>
                </n-list>
                <n-text v-else depth="3">播放列表为空</n-text>
            </template>
            <n-skeleton v-else text :repeat="3" />
        </n-spin>

    </PlayListNavigator>
</template>

<style scoped>
.list-move,
.list-enter-active,
.list-leave-active {
    transition: all 0.2s ease;
}

.list-enter-from,
.list-leave-to {
    opacity: 0;
    transition: all 0.15s ease;
    transform: translateX(-20px);
}

.list-leave-active {
    position: absolute;
}
</style>
