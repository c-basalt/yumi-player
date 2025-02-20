<script setup lang="ts">
import { ref, computed } from 'vue'
import { NSpace, NButton, NSlider, NText, NElement, NIcon, NPopover, NDivider, NTag } from 'naive-ui'
import { Play24Regular, Pause24Regular, Next24Regular } from '@vicons/fluent'
import { MoveDownFilled } from '@vicons/material'
import { computedAsync, useSessionStorage } from '@vueuse/core'

import { getAudioUrl } from '@/api/player'
import { usePlayerStatus } from '@/composables/playerStatus'
import { formatTime, getEntryTitle } from '@/utils/utils'
import { isMobile } from '@/utils/breakpoint'
import RecentBvidModal from './RecentBvidModal.vue'

const { playerStatus, playlist, progress, current, playerLoading: loading, sendCommand } = usePlayerStatus()

const durationCache = useSessionStorage<{ [url: string]: number }>('player-duration-cache', {});
const showRecentBvidModal = ref(false)

const audioDuration = computedAsync(async () => {
    const filename = current.value?.music?.filename;
    if (!filename) return 0;

    const url = getAudioUrl(filename);
    if (durationCache.value[url]) {
        return durationCache.value[url];
    }

    const knownDuration = current.value?.music?.duration;
    if (knownDuration) {
        durationCache.value[url] = knownDuration;
        return knownDuration;
    }

    return new Promise<number>((resolve) => {
        const audio = new Audio();
        audio.addEventListener("loadedmetadata", () => {
            const duration = Math.floor(audio.duration);
            durationCache.value[url] = duration;
            resolve(duration);
        });
        audio.src = url;
    });
}, 0);


const handlePlay = () => sendCommand('paused', false)
const handlePause = () => sendCommand('paused', true)
const handleSeek = (value: number) => sendCommand('seek', value)
const handleSkip = () => {
    if (current.value) {
        sendCommand('next', current.value.id)
    }
}
const handleMoveDown = () => {
    if (current.value) {
        sendCommand('move-down', current.value.id)
    }
}

defineProps<{ handleManualSearch: (bvid: string) => void }>();
defineExpose({
    volume: computed(() => playerStatus.value?.volume),
    decibel: computed(() => playerStatus.value?.config.target_db),
})
</script>

<template>
    <n-element style="max-width: 600px; margin: 0 auto;">
        <n-space vertical>
            <n-space vertical justify="center" align="center">
                <n-text :style="{ fontSize: isMobile ? '18px' : '20px' }" :depth="current ? undefined : 3">
                    {{ getEntryTitle(current) || '无播放' }}
                </n-text>
                <n-text depth="3" :style="{ fontSize: isMobile ? '12px' : '14px' }">
                    {{ current?.music?.singer || '&nbsp;' }}
                </n-text>
            </n-space>

            <n-space vertical>
                <n-space justify="space-between">
                    <n-text depth="3" size="small">{{ formatTime(progress) }}</n-text>
                    <n-text depth="3" size="small">{{ formatTime(audioDuration) }}</n-text>
                </n-space>
                <n-slider v-model:value="progress" :max="audioDuration" :disabled="loading || !audioDuration"
                    @update:value="handleSeek" :tooltip="false" />
            </n-space>

            <n-space justify="center" :size="isMobile ? 28 : 12" :style="{ marginTop: isMobile ? '40px' : '0px' }">
                <n-popover trigger="hover" :delay="1500">
                    <template #trigger>
                        <n-button quaternary circle size="small" @click="showRecentBvidModal = true"
                            :disabled="loading">
                            <n-text depth="2" :style="{ fontSize: isMobile ? '22px' : undefined }">BV</n-text>
                        </n-button>
                    </template>
                    查看最近弹幕中的BV号
                </n-popover>
                <n-popover trigger="hover" :delay="1500">
                    <template #trigger>
                        <n-button quaternary circle size="small" @click="handlePlay"
                            :disabled="!playerStatus?.paused || loading">
                            <n-icon :component="Play24Regular" :size="isMobile ? 28 : 20" />
                        </n-button>
                    </template>
                    恢复播放
                </n-popover>
                <n-popover trigger="hover" :delay="1500">
                    <template #trigger>
                        <n-button quaternary circle size="small" @click="handlePause"
                            :disabled="playerStatus?.paused || loading">
                            <n-icon :component="Pause24Regular" :size="isMobile ? 28 : 20" />
                        </n-button>
                    </template>
                    暂停播放
                </n-popover>
                <n-popover trigger="hover" :delay="1500">
                    <template #trigger>
                        <n-button quaternary circle size="small" @click="handleSkip" :disabled="!current || loading">
                            <n-icon :component="Next24Regular" :size="isMobile ? 28 : 20" />
                        </n-button>
                    </template>
                    跳过当前歌曲
                </n-popover>
                <n-popover trigger="hover" :delay="1500">
                    <template #trigger>
                        <n-button quaternary circle size="small" @click="handleMoveDown"
                            :disabled="playlist.length < 2 || loading">
                            <n-icon :component="MoveDownFilled" :size="isMobile ? 28 : 20" />
                        </n-button>
                    </template>
                    {{ playlist.length < 2 ? '已是播放列表末尾' : '下移当前歌曲' }}
                </n-popover>
            </n-space>

            <RecentBvidModal v-model:show="showRecentBvidModal" :recent-bvids="playerStatus?.recent_bvid || []"
                :handle-manual-search="handleManualSearch" />
        </n-space>
        <n-divider />
    </n-element>
    <ul v-if="playerStatus" class="playlist-container">
        <li v-for="item in playerStatus.combined_list" :key="item.id" class="playlist-item"
            :class="{ current: item.id == current?.id }">
            <n-space size="small">
                <n-tag v-if="item.is_fallback" disabled size="small" round :bordered="false" type="info">后备</n-tag>
                <n-tag v-if="item.user.username" size="small" round :bordered="false">{{ item.user.username }}</n-tag>
                <n-text :depth="item.is_fallback ? 3 : 1">{{ item.music.title }}</n-text>
            </n-space>
        </li>
    </ul>
</template>

<style lang="scss" scoped>
.playlist-item.current {
    font-weight: bold;
}
</style>