<script setup lang="ts">
import { NButton, NCard, NSpace, NH2 } from 'naive-ui'
import { RouterLink, useRoute } from 'vue-router'

import { isMobile } from '@/utils/breakpoint'

const route = useRoute()
const props = defineProps<{
    title: string
}>()

</script>

<template>
    <n-space vertical style="max-width: 800px; margin: 0 auto; padding: 20px;">
        <n-space class="actions">
            <router-link v-slot="{ navigate }" :to="{ name: 'home' }" custom>
                <n-button @click="navigate">返回首页</n-button>
            </router-link>
        </n-space>
        <n-card>
            <template #header>
                <n-space align="center">
                    <n-h2 style="margin-bottom: 0;">{{ props.title }}</n-h2>
                    <slot name="header-extra"></slot>
                </n-space>
            </template>
            <template #header-extra>
                <n-space :vertical="isMobile">
                    <router-link v-slot="{ navigate }" :to="{ name: 'playlist' }" custom>
                        <n-button @click="navigate" :disabled="route.name === 'playlist'">播放列表</n-button>
                    </router-link>
                    <router-link v-slot="{ navigate }" :to="{ name: 'history' }" custom>
                        <n-button @click="navigate" :disabled="route.name === 'history'">播放历史</n-button>
                    </router-link>
                    <router-link v-slot="{ navigate }" :to="{ name: 'query-history' }" custom>
                        <n-button @click="navigate" :disabled="route.name === 'query-history'">点歌历史</n-button>
                    </router-link>
                </n-space>
            </template>
            <slot></slot>
        </n-card>
    </n-space>
</template>
