<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { NSpace, NDescriptions, NDescriptionsItem, NButton, NText, NSwitch, useMessage, NModal, NFlex, NCard, NRadio, NRadioGroup, NInputNumber, NInputGroupLabel, NInputGroup, useThemeVars } from 'naive-ui'

import { loadCookie, resetCookie, configureAutoload, configureAutoReload } from '@/api/cookies'
import { logger } from '@/api/logging'
import StatusDot from '@/components/StatusDot.vue'
import ReadOnlyInput from '@/components/ReadOnlyInput.vue'
import { useCookieStatus } from '@/composables/cookieStatus'
import { usePlayerUrl } from '@/composables/playerUrl'

const themeVars = useThemeVars()
const message = useMessage()
const { playerUrl } = usePlayerUrl()
const { cookieStatus, fetchCookieStatus } = useCookieStatus(message)
const loading = reactive<Record<string, boolean>>({})
const showModal = ref(false)
const showCCHelperModal = ref(false)
const modalLoaderKey = ref<string | null>(null)
const cookieCloudApi = computed(() => new URL('/api/cookie', playerUrl.value).href)


type AutoloadOptions = {
    on: boolean
    expect_uid: boolean
    auto_reload: boolean
    auto_reload_interval_minutes: number
    try_appbound_debugger_workaround: boolean
}


const autoloadOptions = computed<{ [key: string]: AutoloadOptions }>(() => {
    const options: { [key: string]: AutoloadOptions } = {}
    for (const [key, value] of Object.entries(cookieStatus.value?.autoload || {})) {
        options[key] = {
            on: value.browser !== null,
            expect_uid: value.uid !== null,
            auto_reload: value.auto_reload,
            auto_reload_interval_minutes: value.auto_reload_interval_minutes,
            try_appbound_debugger_workaround: value.try_appbound_debugger_workaround,
        }
    }
    return options
})

const handleLoadCookie = async (loaderKey: string, browserName: string) => {
    loading[loaderKey] = true
    try {
        const result = await loadCookie(loaderKey, browserName)
        cookieStatus.value = result
        if (result.success[loaderKey]) {
            message.success('Cookie加载成功')
        } else {
            message.info('Cookie加载完成')
        }
    } catch (e) {
        message.error('Cookie加载失败')
        logger.error('[CookieConfig] Failed to load cookie:', e)
    } finally {
        loading[loaderKey] = false
    }
}

const handleResetCookie = async (loaderKey: string) => {
    loading[loaderKey] = true
    try {
        const result = await resetCookie(loaderKey)
        cookieStatus.value = result
        message.success('Cookie重置成功')
    } catch (e) {
        message.error('Cookie重置失败')
        logger.error('[CookieConfig] Failed to reset cookie:', e)
    } finally {
        loading[loaderKey] = false
    }
}

const handleAutoloadChange = async (loaderKey: string | null, update: Partial<AutoloadOptions>) => {
    if (!loaderKey) return
    try {
        const newOptions = { ...autoloadOptions.value[loaderKey], ...update }
        if (update.expect_uid) newOptions.on = true;
        const result = await configureAutoload(loaderKey, newOptions.on, newOptions.expect_uid)
        cookieStatus.value = result
    } catch (e) {
        message.error('自动加载设置失败')
        logger.error('[CookieConfig] Failed to configure autoload:', e)
    }
}

const handleAutoReloadChange = async (loaderKey: string | null, update: Partial<{
    auto_reload: boolean;
    auto_reload_interval_minutes: number;
    try_appbound_debugger_workaround: boolean;
}>) => {
    if (!loaderKey) return
    try {
        const result = await configureAutoReload(loaderKey, update)
        cookieStatus.value = result
    } catch (e) {
        message.error('自动刷新设置失败')
        logger.error('[CookieConfig] Failed to configure auto reload:', e)
    }
}

const toggleAppbound = async (loaderKey: string | null, value: boolean) => {
    if (value) {
        await handleAutoReloadChange(loaderKey, {
            try_appbound_debugger_workaround: true,
            auto_reload: false,
        });
        await handleAutoloadChange(loaderKey, { on: false });
    } else {
        await handleAutoReloadChange(loaderKey, { try_appbound_debugger_workaround: false })
    }
}

const handleConfig = (key: string) => {
    fetchCookieStatus()
    modalLoaderKey.value = key
    showModal.value = true
}
</script>

<template>
    <n-space vertical v-if="cookieStatus">
        <n-text>
            B站cookies仅用于连接弹幕显示用户名，建议使用小号。可使用支持的浏览器或者CookieCloud扩展进行配置
        </n-text>
        <n-button size="small" @click="() => showCCHelperModal = true">
            如何配置CookieCloud
        </n-button>

        <n-descriptions v-for="(label, key) in cookieStatus.site_loaders" :key="key" bordered size="small">
            <n-descriptions-item :label="label" content-style="width: 300px; vertical-align: middle;">
                <n-flex :size="6" align="center">
                    <StatusDot :status="cookieStatus.success[key] ? 'success' : 'error'" />
                    <n-text>{{ cookieStatus.results[key] || '未登录' }}</n-text>
                </n-flex>
            </n-descriptions-item>
            <n-descriptions-item label="自动加载" content-style="width: 150px; vertical-align: middle;">
                <n-text>
                    {{ cookieStatus.autoload[key].browser || '否' }}
                    <span v-if="cookieStatus.autoload[key].uid">({{ cookieStatus.autoload[key].uid }})</span>
                </n-text>
            </n-descriptions-item>
            <n-descriptions-item label="操作" content-style="width: 100px; vertical-align: middle;">
                <n-space size="small">
                    <n-button size="small" ghost :disabled="!cookieStatus.autoload[key].browser"
                        :type="cookieStatus.autoload[key].browser && autoloadOptions[key]?.try_appbound_debugger_workaround ? 'warning' : 'default'"
                        @click="() => handleLoadCookie(key, cookieStatus!.autoload[key].browser!)">
                        刷新
                    </n-button>
                    <n-button size="small" @click="() => handleConfig(key)">设置</n-button>
                </n-space>
            </n-descriptions-item>
        </n-descriptions>

        <n-modal v-model:show="showModal" title="从本地浏览器获取Cookie" preset="card" style="max-width: 700px;">
            <n-space vertical v-if="modalLoaderKey">
                <n-descriptions bordered>
                    <n-descriptions-item label="当前状态">
                        {{ cookieStatus.results[modalLoaderKey] || '未登录' }}
                    </n-descriptions-item>
                </n-descriptions>

                <n-space vertical>
                    <n-space v-if="autoloadOptions[modalLoaderKey]?.try_appbound_debugger_workaround">
                        <n-button v-for="browser in cookieStatus.appbound" :key="browser"
                            :disabled="loading[modalLoaderKey]" size="small" ghost
                            @click="() => modalLoaderKey && handleLoadCookie(modalLoaderKey, browser)">
                            从 {{ browser }} 加载（会重启浏览器）
                        </n-button>
                    </n-space>
                    <n-space v-else>
                        <n-button v-for="browser in cookieStatus.browsers" :key="browser"
                            :disabled="loading[modalLoaderKey]" size="small"
                            :type="/Cookie_?Cloud/i.test(browser) ? 'primary' : 'default'" ghost
                            @click="() => modalLoaderKey && handleLoadCookie(modalLoaderKey, browser)">
                            从 {{ browser }} 加载
                        </n-button>
                    </n-space>
                    <n-button type="error" ghost :disabled="loading[modalLoaderKey]"
                        @click="handleResetCookie(modalLoaderKey)" size="small">
                        重置
                    </n-button>
                </n-space>

                <n-space style="margin-top: 15px;" align="center">
                    <n-switch :value="autoloadOptions[modalLoaderKey]?.on"
                        :disabled="!cookieStatus.success[modalLoaderKey]"
                        :rail-style="autoloadOptions[modalLoaderKey]?.try_appbound_debugger_workaround ? ({ checked }) => ({ background: checked ? themeVars.warningColor : undefined, boxShadow: 'none' }) : undefined"
                        @update:value="value => handleAutoloadChange(modalLoaderKey, { on: value })">
                        <template #checked>启动时加载</template>
                        <template #unchecked>手动加载</template>
                    </n-switch>
                    <n-switch :value="autoloadOptions[modalLoaderKey]?.expect_uid"
                        :disabled="!cookieStatus.success[modalLoaderKey]"
                        @update:value="value => handleAutoloadChange(modalLoaderKey, { expect_uid: value })">
                        <template #checked>需UID一致</template>
                        <template #unchecked>不检查UID</template>
                    </n-switch>
                    <n-switch :value="cookieStatus.autoload[modalLoaderKey].auto_reload"
                        :disabled="!autoloadOptions[modalLoaderKey]?.on"
                        :rail-style="autoloadOptions[modalLoaderKey]?.try_appbound_debugger_workaround ? ({ checked }) => ({ background: checked ? themeVars.warningColor : undefined, boxShadow: 'none' }) : undefined"
                        @update:value="value => handleAutoReloadChange(modalLoaderKey, { auto_reload: value })">
                        <template #checked>自动刷新</template>
                        <template #unchecked>手动刷新</template>
                    </n-switch>
                    <n-input-group>
                        <n-input-group-label>刷新间隔（分钟）</n-input-group-label>
                        <n-input-number :value="cookieStatus.autoload[modalLoaderKey].auto_reload_interval_minutes"
                            :disabled="!autoloadOptions[modalLoaderKey]?.on" :min="10" :step="10"
                            style="max-width: 120px;"
                            @update:value="value => value && handleAutoReloadChange(modalLoaderKey, { auto_reload_interval_minutes: value })">
                        </n-input-number>
                    </n-input-group>
                    <n-input-group>
                        （实验）对Chromium v130+尝试重启浏览器提取Cookie：
                        <n-switch :value="autoloadOptions[modalLoaderKey]?.try_appbound_debugger_workaround"
                            :rail-style="({ checked }) => ({ background: checked ? themeVars.warningColor : undefined, boxShadow: 'none' })"
                            @update:value="value => toggleAppbound(modalLoaderKey, value)">
                            <template #checked>加载/刷新会重启浏览器</template>
                            <template #unchecked>不重启浏览器</template>
                        </n-switch>
                    </n-input-group>
                </n-space>
            </n-space>
        </n-modal>

        <n-modal v-model:show="showCCHelperModal" title="CookieCloud配置" preset="card" style="max-width: 600px;">
            <n-text>
                在浏览器中安装CookieCloud扩展后，按如下填写配置。填写完成后点击底部的保存、手动同步，即可从设置中选择“从本地CookieCloud加载”
            </n-text>
            <n-card size="small" style="max-width: 400px; margin: 20px auto;">
                <n-space vertical>
                    <n-text>工作模式</n-text>
                    <n-radio-group value="1">
                        <n-radio value="1">上传到服务器</n-radio>
                        <n-radio value="2">覆盖到浏览器</n-radio>
                        <n-radio value="3">暂停同步</n-radio>
                    </n-radio-group>
                    <n-text>服务器地址</n-text>
                    <ReadOnlyInput :value="cookieCloudApi" />
                    <n-text>用户KEY · UUID</n-text>
                    <ReadOnlyInput :value="cookieStatus.cookie_cloud_config.uuid" />
                    <n-text>端对端加密密码</n-text>
                    <ReadOnlyInput :value="cookieStatus.cookie_cloud_config.password" />
                    <n-text>……</n-text>
                </n-space>
            </n-card>
        </n-modal>

    </n-space>
</template>