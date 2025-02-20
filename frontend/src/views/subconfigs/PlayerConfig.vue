<script setup lang="ts">
import { reactive, onMounted, ref } from 'vue'
import { NSpace, NInputGroup, NInputGroupLabel, NInput, NInputNumber, NFlex, NDynamicTags, NDynamicInput, useMessage, NButton, NModal, NCard, NSlider, NText, NSpin, NP, NCheckbox, useThemeVars } from 'naive-ui'

import { type Config, fetchConfig, updateConfig, resetConfig } from '@/api/config'
import { getRecentUsers, getBannedUsers, addBannedUser as addBannedUserApi, testProxy, unshieldTest, type UserInfo } from '@/api/player'
import { logger } from '@/api/logging'

const themeVars = useThemeVars()
const message = useMessage()

const loading = ref(true)
const config = reactive<Partial<Config['player']>>({})
const bannedLists = reactive<Config['player_banned']>({
    banned_uids: [],
    banned_keywords: [],
})
const bannedUsers = reactive<Record<string, string>>({})
const recentUsers = ref<UserInfo[]>([])
const unshieldKeywords = ref<{ from: string, to: string }[]>([])
const unshieldTestResult = ref('')

const showUidModal = ref(false)
const showKeywordModal = ref(false)
const showRecentUsersModal = ref(false)
const showUnshieldModal = ref(false)
const loadingRecentUsers = ref(false)


const applyConfig = (data: Config) => {
    if (data.player) {
        loading.value = false
        const filteredEntries = Object.entries(data.player)
            .filter(([key]) => !['fallback'].includes(key))
        Object.assign(config, Object.fromEntries(filteredEntries))
    }
    if (data.player_banned) {
        Object.assign(bannedLists, data.player_banned)
    }
    if (data.player_unshield) {
        unshieldKeywords.value = data.player_unshield.keywords.map(v => v.split(','))
            .map(([k, v]) => ({ from: k, to: v }));
    }
}

const fetchRecentUsers = async (showMsg?: boolean) => {
    loadingRecentUsers.value = true
    try {
        recentUsers.value = await getRecentUsers()
        if (showMsg) {
            message.success('刷新成功')
        }
    } catch (error) {
        message.error('获取最近用户失败')
        logger.error('[PlayerConfig] Failed to fetch recent users:', error)
    }
    await new Promise(resolve => setTimeout(resolve, 5000))
    loadingRecentUsers.value = false
}

const fetchBannedUsers = () =>
    getBannedUsers().then(response => { Object.assign(bannedUsers, response) })


const addBannedUid = (uidStr: string) => {
    const uid = Number(uidStr);
    (isNaN(uid) ? getBannedUsers() : addBannedUserApi(uid)).then(response => {
        Object.assign(bannedUsers, response)
    })
    return uidStr
}

const addBannedUser = async (uid: number, username: string) => {
    Object.assign(bannedUsers, await addBannedUserApi(uid, username))
    fetchPlayerConfig()
}

const fetchPlayerConfig = async () => {
    try {
        applyConfig(await fetchConfig())
    } catch (error) {
        message.error('获取播放器配置失败')
        logger.error('[PlayerConfig] Failed to fetch player config:', error)
    }
}

const updatePlayerConfig = async (key: keyof Config['player'], value: any) => {
    try {
        applyConfig(await updateConfig({ player: { [key]: value } }))
    } catch (error) {
        message.error('更新配置失败')
        logger.error('[PlayerConfig] Failed to update config:', error)
    }
}

const updateBannedLists = async (key: keyof Config['player_banned'], value: any) => {
    try {
        applyConfig(await updateConfig({ player_banned: { [key]: value } }))
    } catch (error) {
        message.error('黑名单保存失败')
        logger.error('[PlayerConfig] Failed to update player_banned:', error)
    }
}

const updateUnshieldKeywords = async (apply: boolean) => {
    try {
        const keywords = unshieldKeywords.value.filter(v => v.from).map(({ from, to }) => `${from},${to}`)
        const result = await updateConfig({ player_unshield: { keywords } })
        if (apply) {
            applyConfig(result)
        }
    } catch (error) {
        message.error('屏蔽词保存失败')
        logger.error('[PlayerConfig] Failed to update player_unshield:', error)
    }
}

const resetPlayerConfig = async () => {
    try {
        applyConfig(await resetConfig(['player'], false))
    } catch (error) {
        message.error('重置配置失败')
        logger.error('[PlayerConfig] Failed to reset config:', error)
    }
}

const testingProxy = ref(false)
const handleTestProxy = async () => {
    try {
        testingProxy.value = true
        const result = await testProxy()
        if (result.success) {
            message.success('代理测试成功', { duration: 8000 })
        } else {
            const msg = {
                'no-proxy': '未设置代理',
                'connection-timeout': '连接超时',
                'geo-restricted': '代理地区受限，无法访问国区资源',
                'proxy-error': '其他错误',
            }[result.reason]
            message.error(`测试失败: ${msg || result.reason}`, { duration: 8000 })
        }
    } catch (e) {
        message.error('测试请求失败', { duration: 8000 })
        logger.error('[PlayerConfig] Failed to test proxy:', e)
    } finally {
        testingProxy.value = false
    }
}

onMounted(() => {
    fetchPlayerConfig()
    fetchBannedUsers()
    fetchRecentUsers()
})
defineExpose({
    resetPlayerConfig,
})
</script>

<template>
    <n-spin :show="loading">
        <n-space vertical>
            <n-p style="font-size: 16px;">弹幕指令</n-p>
            <n-checkbox v-model:checked="config.request_handler_off" size="large" :focusable="false"
                :style="{ '--n-color-checked': themeVars.errorColor, '--n-border-checked': `1px solid ${themeVars.errorColorPressed}` }"
                @update:checked="(checked) => updatePlayerConfig('request_handler_off', checked)">
                <n-text
                    :style="config.request_handler_off ? { color: themeVars.errorColorPressed } : {}">禁用弹幕点歌</n-text>
            </n-checkbox>
            <n-input-group>
                <n-input-group-label>点歌指令</n-input-group-label>
                <n-input v-model:value="config.request_cmd" :disabled="config.request_handler_off" placeholder="留空不使用"
                    @change="v => updatePlayerConfig('request_cmd', v)" />
                <n-input-group-label>取消点歌指令</n-input-group-label>
                <n-input v-model:value="config.cancel_cmd" :disabled="config.request_handler_off" placeholder="留空不使用"
                    @change="v => updatePlayerConfig('cancel_cmd', v)" />
            </n-input-group>
            <n-input-group>
                <n-input-group-label>切歌指令</n-input-group-label>
                <n-input v-model:value="config.skip_cmd" :disabled="config.request_handler_off" placeholder="留空不使用"
                    @change="v => updatePlayerConfig('skip_cmd', v)" />
                <n-input-group-label>跳过当前指令</n-input-group-label>
                <n-input v-model:value="config.skipend_cmd" :disabled="config.request_handler_off" placeholder="留空不使用"
                    @change="v => updatePlayerConfig('skipend_cmd', v)" />
            </n-input-group>

            <n-p style="font-size: 16px; margin-top: 5px;">频率限制</n-p>
            <n-input-group>
                <n-input-group-label>点歌请求最小间隔 (秒)</n-input-group-label>
                <n-input-number v-model:value="config.rate_limit_request" :min="0"
                    @update:value="v => updatePlayerConfig('rate_limit_request', v)" />
            </n-input-group>

            <n-input-group>
                <n-input-group-label>计数时间区间 (秒)</n-input-group-label>
                <n-input-number v-model:value="config.rate_limit_success_duration" :min="30"
                    @update:value="v => updatePlayerConfig('rate_limit_success_duration', v)" />

                <n-input-group-label>区间内最多可以点歌 (首)</n-input-group-label>
                <n-input-number v-model:value="config.rate_limit_success_count" :min="1"
                    @update:value="v => updatePlayerConfig('rate_limit_success_count', v)" />
            </n-input-group>

            <n-p style="font-size: 16px; margin-top: 5px;">歌曲缓存</n-p>
            <n-input-group>
                <n-input-group-label>歌曲缓存空间限制 (MB)</n-input-group-label>
                <n-input-number v-model:value="config.cache_limit_mb" :min="500"
                    @blur="() => config.cache_limit_mb && updatePlayerConfig('cache_limit_mb', config.cache_limit_mb)" />
            </n-input-group>

            <n-input-group>
                <n-input-group-label>海外回国代理</n-input-group-label>
                <n-input v-model:value="config.cache_proxy" placeholder="网易云无需，填写QQ音乐使用的HTTP代理"
                    @blur="() => config.cache_proxy && updatePlayerConfig('cache_proxy', config.cache_proxy)" />
                <n-button :disabled="!config.cache_proxy" :loading="testingProxy" @click="handleTestProxy">
                    测试</n-button>
            </n-input-group>

            <n-p style="font-size: 16px; margin-top: 5px;">其他</n-p>
            <n-checkbox v-model:checked="config.clear_playing_fallback" size="large"
                @update:checked="(checked) => updatePlayerConfig('clear_playing_fallback', checked)">
                开始播放时取消歌曲的后备属性（不会被新点歌打断）
            </n-checkbox>
            <n-input-group>
                <n-input-group-label>点歌弹幕记录保留（条）</n-input-group-label>
                <n-input-number v-model:value="config.query_history_count_limit" :min="0"
                    @update:value="v => updatePlayerConfig('query_history_count_limit', v)" />
            </n-input-group>
            <n-flex align="center">
                <n-input-group-label>降低超出的平均音量至</n-input-group-label>
                <span>{{ config.target_db }} dB</span>
                <n-slider v-model:value="config.target_db" :min="-60" :max="0" :step="1" :tooltip="false"
                    @update:value="v => updatePlayerConfig('target_db', v)" style="width: 300px" />
            </n-flex>


            <n-space style="margin-top: 15px; margin-bottom: -10px;">
                <n-button warning ghost @click="fetchPlayerConfig().then(() => showUidModal = true)">管理UID黑名单</n-button>
                <n-button @click="fetchPlayerConfig().then(() => showKeywordModal = true)">管理歌名关键词黑名单</n-button>
                <n-button @click="fetchPlayerConfig().then(() => showUnshieldModal = true)">管理屏蔽弹幕替换</n-button>
            </n-space>

            <n-modal v-model:show="showUidModal">
                <n-card style="width: 600px; min-height: 300px" content-style="padding: 0px">
                    <n-card v-if="!showRecentUsersModal" title="管理UID黑名单" :bordered="false" size="huge">
                        <template #header-extra>
                            <n-space style="margin-top: -5px;">
                                <n-button @click="showRecentUsersModal = true" type="primary" ghost
                                    size="small">查看最近用户</n-button>
                            </n-space>
                        </template>
                        <n-dynamic-tags
                            :value="(bannedLists.banned_uids).map(v => v.toString().trim()).map((v: string) => bannedUsers[v] ? `${v} (${bannedUsers[v]})` : v)"
                            @update:value="(v: string[]) => updateBannedLists('banned_uids', v.map(v => v.split(' ')[0]))"
                            :on-create="addBannedUid"
                            :input-props="{ allowInput: (value: string) => !value || /^\d+$/.test(value) }"
                            tag-style="min-width: 150px; justify-content: space-between" />
                    </n-card>
                    <n-card v-else title="最近用户" :bordered="false" size="huge">
                        <template #header-extra>
                            <n-space style="margin-top: -5px;">
                                <n-button @click="() => fetchRecentUsers(true)" :disabled="loadingRecentUsers"
                                    size="small">刷新</n-button>
                                <n-button @click="showRecentUsersModal = false" type="primary" ghost
                                    size="small">返回ID黑名单</n-button>
                            </n-space>
                        </template>
                        <n-space vertical size="small" style="max-height: 400px; overflow-y: auto;">
                            <n-card v-for="user in recentUsers" :key="user.uid" size="small"
                                :content-style="{ padding: '0px', paddingLeft: '10px' }"
                                style="background: #f5f5f5; margin-bottom: 5px;">
                                <n-space justify="space-between" align="center">
                                    <n-text>{{ user.username }} ({{ user.uid }})</n-text>
                                    <n-button size="small"
                                        :type="!bannedLists.banned_uids.includes(user.uid) ? 'warning' : undefined"
                                        :disabled="bannedLists.banned_uids.includes(user.uid)"
                                        @click="() => addBannedUser(user.uid, user.username)">
                                        {{ bannedLists.banned_uids.includes(user.uid) ? '已在黑名单' : '加入黑名单' }}
                                    </n-button>
                                </n-space>
                            </n-card>
                        </n-space>
                    </n-card>
                </n-card>
            </n-modal>
            <n-modal v-model:show="showKeywordModal" style="min-height: 300px">
                <n-card title="管理关键词黑名单" :bordered="false" size="huge" style="width: 600px">
                    <n-dynamic-tags :value="(bannedLists.banned_keywords)"
                        @update:value="(v: string[]) => updateBannedLists('banned_keywords', v.map(v => v.toString().trim()))"
                        tag-style="min-width: 80px; justify-content: space-between" />
                </n-card>
            </n-modal>
            <n-modal v-model:show="showUnshieldModal" style="max-height: 80vh; overflow-y: auto;"
                @update:show="() => updateUnshieldKeywords(true)">
                <n-card title="用于代替一些弹幕无法正常打出的歌名" :bordered="false" size="huge" style="width: 600px; min-height: 300px">
                    <n-input-group style="margin-top: -10px; margin-bottom: 10px;">
                        <n-input-group-label>弹幕发送</n-input-group-label>
                        <n-input placeholder="歌名" @update:value="v => unshieldTest(v).then(v => unshieldTestResult = v.text)">
                            <template #prefix>{{ config.request_cmd }}</template>
                        </n-input>
                        <n-input-group-label>实际点歌</n-input-group-label>
                        <n-input :value="unshieldTestResult" placeholder="" disabled/>
                    </n-input-group>

                    <n-dynamic-input v-model:value="unshieldKeywords" :min="1" @create="() => ({ key: '', value: '' })"
                        @remove="() => updateUnshieldKeywords(false)">
                        <template #default="{ value }">
                            <n-input pair :value="[value.from, value.to]"
                                @update:value="(v: [string, string]) => { value.from = v[0]; value.to = v[1]; }"
                                @blur="() => updateUnshieldKeywords(false)" :placeholder="['弹幕替代用词', '原歌名部分']"
                                separator="→" />
                        </template>
                    </n-dynamic-input>
                </n-card>
            </n-modal>
        </n-space>
    </n-spin>
</template>

<style scoped>
.n-input-group {
    max-width: 500px;
}
</style>