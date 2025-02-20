<script setup lang="ts">
import { ref } from 'vue'
import { NModal, NCard, NSpace, NText, NButton, NIcon, NTag, NSpin, NPopover, useMessage } from 'naive-ui'
import { TextBulletListAdd20Filled, Open20Filled, Play12Regular, Search24Filled } from '@vicons/fluent'

import { manualAdd, type PlayerStatus, type UserInfo } from '@/api/player'
import { formatTime, formatLargeNumber } from '@/utils/utils'
import ReadOnlyInput from './ReadOnlyInput.vue'

const message = useMessage()
const addBvidLoading = ref(false)

const handleAddBvid = async (user: UserInfo, bvid: string, isMultiPart: boolean) => {
    addBvidLoading.value = true;
    try {
        const result = await manualAdd('Bilibili', bvid, { user });
        if (result.error) {
            message.error(result.error);
        } else {
            message.success(isMultiPart ? '已添加P1' : '添加成功');
        }
    } catch (error) {
        message.error('添加失败');
    } finally {
        addBvidLoading.value = false;
    }
}

const isMultiPart = (meta: PlayerStatus['recent_bvid'][number]['meta']) => {
    return (meta?.meta?.pages || []).length > 1;
}

const parseDuration = (meta: PlayerStatus['recent_bvid'][number]['meta']) => {
    return meta?.meta?.pages?.[0]?.duration || meta?.duration || 0;
}

const show = defineModel<boolean>('show');
defineProps<{ recentBvids: PlayerStatus['recent_bvid'], handleManualSearch: (bvid: string) => void }>();
</script>

<template>
    <n-modal v-model:show="show" preset="card" title="最近弹幕中的BV号" style="width: 500px; min-height: 300px;"
        content-style="padding: 0px">
        <n-card style="max-height: 500px; overflow-y: auto;" :bordered="false" content-style="padding-top: 0px">
            <n-space v-for="item in recentBvids" :key="`${item.bvid}-${item.user.uid_hash}`" vertical size="small">
                <n-space align="center" justify="space-between">
                    <n-text style="font-size: 16px; margin-left: 4px">{{ item.user.username }}</n-text>
                    <n-space align="center" :size="2">
                        <ReadOnlyInput :value="item.bvid" style="width: 130px; margin-right: 4px" />

                        <n-popover>
                            <template #trigger>
                                <n-button quaternary circle size="small"
                                    @click="() => { show = false; handleManualSearch(item.bvid) }">
                                    <n-icon :component="Search24Filled" :size="20" />
                                </n-button>
                            </template>
                            <n-text>手动点歌中打开</n-text>
                        </n-popover>

                        <n-popover trigger="hover" :delay="isMultiPart(item.meta) ? 0 : 800">
                            <template #trigger>
                                <n-spin :show="addBvidLoading" :size="24" stroke="#888">
                                    <n-button quaternary circle size="small"
                                        @click="handleAddBvid(item.user, item.bvid, isMultiPart(item.meta))">
                                        <n-icon :component="TextBulletListAdd20Filled" :size="20" />
                                    </n-button>
                                </n-spin>
                            </template>
                            <n-text>{{ isMultiPart(item.meta) ? '添加P1' : '添加到点歌队列' }}</n-text>
                        </n-popover>
                        <n-popover trigger="hover" :delay="800">
                            <template #trigger>
                                <n-button quaternary circle size="small" tag="a" target="_blank"
                                    :href="`https://www.bilibili.com/video/${item.bvid}/`" referrerpolicy="no-referrer">
                                    <n-icon :component="Open20Filled" :size="20" />
                                </n-button>
                            </template>
                            <n-text>在新标签页中打开B站视频</n-text>
                        </n-popover>
                    </n-space>
                </n-space>
                <n-space v-if="item.meta" style="margin-bottom: 10px">
                    <n-text depth="3" style="font-size: 12px; margin-left: -8px">
                        <n-tag round :bordered="false" style="font-size: 12px; margin-right: 2px;" size="small"
                            type="info">
                            <n-text depth="3">
                                <n-text depth="1">{{ isMultiPart(item.meta) ? 'P1 ' : '' }}</n-text>
                                {{ formatTime(parseDuration(item.meta)) }}
                            </n-text>
                        </n-tag>
                        <n-tag round :bordered="false" style="font-size: 12px; margin-right: 2px;" size="small"
                            type="success">
                            <n-icon depth="3" :component="Play12Regular" style="position: absolute" :size="12" />
                            <n-text depth="3" style="margin-left: 12px;">
                                {{ formatLargeNumber(item.meta.meta.play_count) }}
                            </n-text>
                        </n-tag>
                        <n-tag round :bordered="false" style="font-size: 12px" size="small">
                            <n-text depth="3">{{ item.meta.meta.type }}</n-text>
                        </n-tag>
                        {{ item.meta.title }}
                    </n-text>
                </n-space>
                <n-text v-else>&nbsp;</n-text>
            </n-space>
        </n-card>
    </n-modal>
</template>
