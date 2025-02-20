<script setup lang="ts">
import { ref } from 'vue'
import { NH2, NCard, NSpace, NButton, NPopover, NIcon, NFlex, NPopconfirm, NP } from 'naive-ui'
import { RouterLink } from 'vue-router'
import { Info24Regular } from '@vicons/fluent'

import FallbackListConfig from '@/views/subconfigs/FallbackListConfig.vue'
import CookieConfig from '@/views/subconfigs/CookieConfig.vue'
import PlayerConfig from '@/views/subconfigs/PlayerConfig.vue'


const playerConfigComponent = ref<InstanceType<typeof PlayerConfig>>();

</script>

<template>
    <div class="main">
        <n-space vertical style="padding-bottom: 50px">
            <n-space class="actions">
                <router-link v-slot="{ navigate }" :to="{ name: 'home' }" custom>
                    <n-button @click="navigate">返回首页</n-button>
                </router-link>
            </n-space>

            <n-card>
                <n-h2>Cookie 状态</n-h2>
                <CookieConfig />
            </n-card>

            <n-card>
                <n-h2>
                    <n-flex :size="4" style="vertical-align: bottom" align="center">
                        <span>播放器设置</span>
                    </n-flex>
                </n-h2>
                <PlayerConfig ref="playerConfigComponent" />
            </n-card>

            <n-card>
                <n-h2>
                    <n-flex :size="4" style="vertical-align: bottom" align="center">
                        <span>后备播放歌单</span>
                        <NPopover trigger="hover">
                            <template #trigger>
                                <n-icon :component="Info24Regular" :size="20" />
                            </template>
                            <n-p>支持的URL类型：</n-p>
                            <n-p>网易云歌单 https://music.163.com/playlist?id=123456789</n-p>
                            <n-p>QQ歌单 https://y.qq.com/n/ryqq/playlist/123456789</n-p>
                            <n-p>B站系列 https://space.bilibili.com/123456789/lists/12345?type=series</n-p>
                            <n-p>B站合集 https://space.bilibili.com/123456789/lists/12345?type=season</n-p>
                            <n-p>B站收藏 https://space.bilibili.com/123456789/favlist?fid=12345</n-p>
                        </NPopover>
                    </n-flex>
                </n-h2>
                <n-p>为播放列表自动添加后备播放歌曲</n-p>
                <FallbackListConfig />
            </n-card>
            <n-card style="margin-top: 15px">
                <n-h2>重置设置</n-h2>
                <n-space>
                    <n-popconfirm @positive-click="playerConfigComponent?.resetPlayerConfig()" negative-text="取消"
                        positive-text="确认重置" :positive-button-props="{ type: 'error' }">
                        <template #trigger>
                            <n-button type="error" ghost>重置播放器配置</n-button>
                        </template>
                        你确定要重置播放器配置吗？
                    </n-popconfirm>
                </n-space>
            </n-card>
        </n-space>
    </div>
</template>

<style scoped>
.main {
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
}
</style>