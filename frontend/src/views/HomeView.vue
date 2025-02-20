<script setup lang="ts">
import { ref, computed } from 'vue'
import { NCard, NSpace, NFormItem, NInput, NButton, useMessage, NModal, NGrid, NGridItem, NTag, NH3, NFlex, NText, NIcon, NPopover, NImage } from 'naive-ui'
import { RouterLink } from 'vue-router'
import { useClipboard } from '@vueuse/core'
import { useQRCode } from '@vueuse/integrations/useQRCode'
import { Link24Filled, Settings24Regular, TextBulletListLtr24Filled, QrCode24Filled } from '@vicons/fluent'

import PlayerControl from '@/components/PlayerControl.vue'
import StatusDot from '@/components/StatusDot.vue'
import ManualRequestModal from '@/components/ManualRequestModal.vue'

import { setRoomid } from '@/api/roomid'
import { logger } from '@/api/logging'

import { isMobile } from '@/utils/breakpoint'
import { useCookieStatus } from '@/composables/cookieStatus'
import { usePlayerUrl } from '@/composables/playerUrl'
import { useRoomInfo } from '@/composables/roomInfo'

const message = useMessage()

const { roomInfo, fetchRoomInfo } = useRoomInfo(message)
const loading = ref(false)
const showRoomidModal = ref(false)
const showManualRequestModal = ref(false)
const manualRequestModal = ref<InstanceType<typeof ManualRequestModal> | null>(null)
const roomidInputValue = ref('')
const playerControlRef = ref<InstanceType<typeof PlayerControl> | null>(null)

const showPlayerUrl = ref(false)
const { playerUrl } = usePlayerUrl()
const { copy: copyToClipboard, isSupported: isClipboardSupported } = useClipboard({ legacy: true })

const homeUrl = computed(() => window.location.href)
const homeUrlQRCode = useQRCode(homeUrl.value)
const { cookieSuccess } = useCookieStatus(message)

const app_version = __APP_VERSION__

const parsedNewRoomid = computed(() => {
    let input = roomidInputValue.value;
    const result = {
        id: 0,
        error: '',
    }
    if (!input) return result;
    try {
        if (!/^\d+$/.test(input)) {
            const url = new URL(input)

            const match = url.pathname.match(/^\/(?:blanc\/|h5\/)?(\d+)/)
            if (!match || url.hostname !== 'live.bilibili.com') {
                throw new Error('请输入有效的B站直播间链接')
            }
            input = match[1]
        }

        const id = parseInt(input)
        if (id > 0) {
            result.id = id;
        } else {
            throw new Error('请输入有效的房间号（正整数）')
        }

    } catch (e) {
        if (e instanceof Error && !e.message.match('Invalid URL')) {
            result.error = e.message
        } else {
            result.error = '请输入有效的房间号或B站直播间链接'
        }
    }
    return result
})

const copyPlayerLink = () => {
    copyToClipboard(playerUrl.value)
        .then(() => {
            message.success('链接已复制')
        })
        .catch((e) => {
            showPlayerUrl.value = true
            message.error('复制失败：' + e.message)
            logger.error('[HomeView] 复制链接失败', e)
        })
}

const handleConfirm = async () => {
    if (!parsedNewRoomid.value.id) return

    loading.value = true
    try {
        await setRoomid(parsedNewRoomid.value.id)
        await fetchRoomInfo()
        showRoomidModal.value = false
        roomidInputValue.value = ''
        message.success('房间更新成功')
    } catch (e) {
        message.error(e instanceof Error ? e.message : '更新房间失败')
    } finally {
        loading.value = false
    }
}
</script>

<template>
    <div class="main">
        <n-space vertical :size="16">
            <n-card title="房间信息">
                <template #header-extra>
                    <n-text depth="3" style="margin-right: 12px">{{ app_version }}</n-text>
                    <n-popover v-if="!homeUrl.startsWith('http://127.0.0.1')" trigger="hover"
                        style="padding: 0px; padding-bottom: 20px;">
                        <template #trigger>
                            <n-icon :component="QrCode24Filled" :size="24" />
                        </template>
                        <n-image :src="homeUrlQRCode" preview-disabled />
                        <n-text
                            style="position: absolute; width: 100%; left: 0; bottom: 10px; text-align: center;">手机上打开本页</n-text>
                    </n-popover>
                </template>

                <n-grid :cols="2" :x-gap="20">
                    <n-grid-item>
                        <n-card class="info-card">
                            <template #header>
                                <n-text depth="2" style="font-size: 14px">房间号</n-text>
                            </template>
                            <n-text class="card-content" :class="{ mobile: isMobile }">
                                <span v-if="!roomInfo" class="no-rooms">加载中...</span>
                                <span v-else-if="!roomInfo.roomid" class="no-rooms">未设置</span>
                                <span v-else>
                                    {{ roomInfo.roomid }}
                                    {{ roomInfo.short_id !== roomInfo.roomid ? `(${roomInfo.short_id})` : '' }}
                                </span>
                            </n-text>
                        </n-card>
                    </n-grid-item>
                    <n-grid-item>
                        <n-card class="info-card">
                            <template #header>
                                <n-text depth="2" style="font-size: 14px">主播信息</n-text>
                            </template>
                            <n-text class="card-content" :class="{ mobile: isMobile }">
                                {{ roomInfo?.roomid ? `${roomInfo.uname} (${roomInfo.uid})` : '&nbsp;' }}
                            </n-text>
                        </n-card>
                    </n-grid-item>
                </n-grid>

                <n-space class="actions" justify="center" :style="{ marginTop: '20px' }">
                    <n-button :type="!roomInfo?.roomid ? 'primary' : undefined" @click="showRoomidModal = true"
                        :loading="loading">
                        设置房间
                    </n-button>
                    <router-link v-slot="{ navigate }" :to="{ name: 'config' }" custom>
                        <n-button @click="navigate">
                            <template #icon>
                                <n-icon :component="Settings24Regular" />
                            </template>
                            前往设置
                        </n-button>
                    </router-link>
                    <n-popover trigger="hover">
                        <template #trigger>
                            <n-button @click="copyPlayerLink">
                                <template #icon>
                                    <n-icon :component="Link24Filled" />
                                </template>
                                复制OBS播放器链接
                            </n-button>
                        </template>
                        {{ playerUrl }}
                    </n-popover>
                    <router-link v-slot="{ navigate }" :to="{ name: 'playlist' }" custom>
                        <n-button @click="navigate">
                            <template #icon>
                                <n-icon :component="TextBulletListLtr24Filled" />
                            </template>
                            前往播放列表
                        </n-button>
                    </router-link>
                    <n-button @click="showManualRequestModal = true">手动点歌</n-button>
                </n-space>
                <n-space v-if="showPlayerUrl || !isClipboardSupported" align="center" style="margin-top: 10px;"
                    justify="center">
                    <n-text>OBS播放器链接</n-text>
                    <n-input v-model:value="playerUrl" style="min-width: 300px;" readonly
                        @focus="e => (e.target as HTMLInputElement).select()" />
                </n-space>

            </n-card>
            <n-card style="min-height: 60px;">
                <n-h3 style="position: absolute; margin: 0; margin-right: 8px;">Cookie 状态</n-h3>
                <n-space justify="center" :style="{ marginTop: isMobile ? '40px' : '0' }">
                    <n-tag v-for="site in Object.keys(cookieSuccess)" :key="site" :closable="false">
                        <n-flex align="center" :size="4">
                            <StatusDot :status="cookieSuccess[site] ? 'success' : 'error'" />
                            <n-text>{{ site }}</n-text>
                        </n-flex>
                    </n-tag>
                </n-space>
            </n-card>
            <n-card title="播放控制">
                <template #header-extra>
                    <n-text v-if="playerControlRef?.volume" depth="3">
                        音量: {{ playerControlRef.decibel }}dB ({{ (playerControlRef.volume * 100).toFixed(1) }}%)
                    </n-text>
                </template>
                <PlayerControl ref="playerControlRef" :handle-manual-search="(bvid) => {
                    showManualRequestModal = true;
                    manualRequestModal && manualRequestModal.performSearch(bvid)
                }" />
            </n-card>
        </n-space>

        <n-modal v-model:show="showRoomidModal" title="设置直播间号" preset="dialog" positive-text="确认" negative-text="取消"
            :positive-button-props="{ disabled: !parsedNewRoomid.id }" @positive-click="handleConfirm"
            :loading="loading">
            <n-form-item :validation-status="parsedNewRoomid.error ? 'error' : undefined"
                :feedback="parsedNewRoomid.error">
                <n-input v-model:value="roomidInputValue" @keyup.enter="parsedNewRoomid.id && handleConfirm()"
                    placeholder="请输入房间号（非UID）或链接" />
            </n-form-item>
        </n-modal>

        <ManualRequestModal ref="manualRequestModal" v-model:show="showManualRequestModal" />
    </div>
</template>

<style scoped>
.main {
    max-width: 800px;
    margin: 20px auto;
    padding: 0 20px;
}

.card-content {
    font-size: 1.5em;

    &.mobile {
        font-size: 1.2em;
    }
}

.no-rooms {
    color: #999;
}
</style>