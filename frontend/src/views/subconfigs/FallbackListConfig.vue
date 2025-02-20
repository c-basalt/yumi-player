<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue';
import { NSpace, NFlex, NInput, NButton, NButtonGroup, NInputGroup, NInputGroupLabel, NSwitch, NText, useMessage, NModal, NCard, NDivider, NSkeleton, NEmpty, NTag, NCheckbox, useThemeVars } from 'naive-ui';
import { useSessionStorage } from '@vueuse/core';
import { useManualAdd } from '@/composables/manualAdd';

import { getFallbackPlaylists, updateFallbackPlaylist, refreshPlaylist, FallbackWs, type PlaylistCache, type PlaylistListResponse } from '@/api/fallback';
import { getUserPlaylists, type UserPlaylists } from '@/api/player';
import { logger } from '@/api/logging';
import { formatTime } from '@/utils/utils';

const message = useMessage();
const themeVars = useThemeVars();
const { addLoading, handleManualAdd } = useManualAdd(message);
const addAsFallback = useSessionStorage<boolean>('config-fallback-list-add-as-fallback', true);
const addAllLoading = ref(false);
const playlistState = reactive<PlaylistListResponse>({
    playlists: [],
    disabled: []
});
const details = ref<PlaylistCache>({});
const loading = ref(false);
const addingUrl = ref(false);
const togglingUrlEnabled = ref<Set<string>>(new Set());
const refreshingUrls = ref<Set<string>>(new Set());
const refreshingAll = ref(false);
const loadingUserPlaylists = ref(false);
const userPlaylists = ref<UserPlaylists | null>(null);

const newUrl = useSessionStorage('config-fallback-list-new-url', '');
const showUserPlaylistModal = ref(false);
const playlistDetailModalKey = ref<string>('');
const showPlaylistDetailModal = ref(false);

const fallbackWs = ref<FallbackWs>(new FallbackWs((cache: PlaylistCache) => {
    details.value = cache;
    console.debug('[FallbackListConfig] Updated playlist details:', cache);
}))

const loadUrls = async () => {
    loading.value = true;
    try {
        const response = await getFallbackPlaylists();
        playlistState.playlists = response.playlists;
        playlistState.disabled = response.disabled;
        logger.debug('[FallbackListConfig] Loaded playlist URLs:', playlistState.playlists);
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to load playlist URLs:', e);
        message.error('加载歌单失败');
        playlistState.playlists = [];
        playlistState.disabled = [];
    } finally {
        loading.value = false;
    }
};

const getPlaylistTitle = (url: string) => {
    return details.value[url]?.info.title || '';
};

const addPlaylist = async () => {
    if (!newUrl.value) return;
    addingUrl.value = true;
    try {
        await updateFallbackPlaylist('add', newUrl.value);
        message.success(`添加歌单成功`);
        newUrl.value = '';
        await loadUrls();
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to add playlist:', e);
        message.error('添加失败');
    } finally {
        addingUrl.value = false;
    }
};

const removePlaylist = async (url: string) => {
    loading.value = true;
    try {
        await updateFallbackPlaylist('remove', url);
        message.success(`已删除歌单：${getPlaylistTitle(url)}`);
        await loadUrls();
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to remove playlist:', e);
        message.error('删除失败');
    } finally {
        loading.value = false;
    }
};

const handleRefresh = async (url: string) => {
    if (refreshingUrls.value.has(url)) return;
    refreshingUrls.value.add(url);
    try {
        await refreshPlaylist(url);
        message.success(`成功刷新歌单: ${getPlaylistTitle(url)}`);
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to refresh playlist:', e);
        message.error('刷新失败');
    } finally {
        refreshingUrls.value.delete(url);
    }
};

const handleAddAll = async (url: string) => {
    addAllLoading.value = true;
    try {
        for (const song_id of details.value[url].info.song_ids) {
            await handleManualAdd(details.value[url].info.api_key, song_id, addAsFallback.value);
        }
    } finally {
        addAllLoading.value = false;
    }
};

const handleRefreshAll = async () => {
    if (refreshingAll.value || playlistState.playlists.length === 0) return;

    refreshingAll.value = true;
    try {
        for (const url of playlistState.playlists) {
            if (!refreshingUrls.value.has(url)) {
                refreshingUrls.value.add(url);
                try {
                    await refreshPlaylist(url);
                } finally {
                    refreshingUrls.value.delete(url);
                }
            }
        }
        message.success('全部刷新成功');
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to refresh all playlists:', e);
        message.error('刷新失败');
    } finally {
        refreshingAll.value = false;
    }
};

const isDisabled = (url: string) => {
    return playlistState.disabled.includes(url);
};

const handleToggleEnabled = async (url: string, enabled: boolean) => {
    togglingUrlEnabled.value.add(url);
    try {
        await updateFallbackPlaylist(enabled ? 'enable' : 'disable', url);
        const msg = `${enabled ? '启用' : '禁用'}歌单: ${getPlaylistTitle(url)}`;
        message.success(msg);
        await loadUrls();
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to toggle playlist:', e);
        message.error('操作失败');
    } finally {
        togglingUrlEnabled.value.delete(url);
    }
};

const handleAddFromUserPlaylist = async (url: string) => {
    loading.value = true;
    try {
        await updateFallbackPlaylist('add', url);
        message.success('添加歌单成功');
        await loadUrls();
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to add playlist from user playlists:', e);
        message.error('添加失败');
    } finally {
        loading.value = false;
    }
};

const loadUserPlaylists = async (refresh?: boolean) => {
    if (!refresh && userPlaylists.value) return;
    try {
        loadingUserPlaylists.value = true;
        userPlaylists.value = await getUserPlaylists();
    } catch (e) {
        logger.error('[FallbackListConfig] Failed to load user playlists:', e);
        message.error('加载用户歌单失败');
    } finally {
        loadingUserPlaylists.value = false;
    }
};

onMounted(() => {
    loadUrls();
});

onUnmounted(() => {
    fallbackWs.value.close();
});
</script>

<template>
    <n-space vertical>
        <n-input-group>
            <n-input-group-label>添加歌单</n-input-group-label>
            <n-input v-model:value="newUrl" placeholder="输入支持的歌单URL" :disabled="loading || addingUrl" />
            <n-button-group>
                <n-button type="primary" @click="addPlaylist" :loading="addingUrl"
                    :disabled="loading || !newUrl">添加</n-button>
                <n-button @click="handleRefreshAll" :loading="refreshingAll"
                    :disabled="loading || playlistState.playlists.length === 0">刷新全部</n-button>
                <n-button @click="showUserPlaylistModal = true; loadUserPlaylists(false)"
                    :disabled="loading">从登录账号添加</n-button>
            </n-button-group>
        </n-input-group>

        <n-modal v-model:show="showPlaylistDetailModal" preset="card" style="width: 550px;"
            content-style="padding: 0px;">
            <template #header>
                <n-space align="center">
                    <n-text>歌单：{{ details[playlistDetailModalKey]?.info.title }}</n-text>
                    <n-checkbox v-model:checked="addAsFallback" :focusable="false" :style="{
                        '--n-color-checked': themeVars.infoColor,
                        '--n-border-checked': `1px solid ${themeVars.infoColor}`
                    }">
                        <n-text :depth="addAsFallback ? 1 : 3">添加为后备播放</n-text>
                    </n-checkbox>
                    <n-button size="small" :type="addAsFallback ? 'info' : 'primary'" ghost :loading="addAllLoading"
                        :disabled="Object.values(addLoading).some(v => v)"
                        @click="handleAddAll(playlistDetailModalKey)">
                        添加全部
                    </n-button>
                </n-space>
            </template>
            <n-card :bordered="false" content-style="padding-top: 0px"
                style="min-height: 300px; max-height: 80vh; overflow-y: auto;">
                <n-space vertical>
                    <n-space v-for="song_id in details[playlistDetailModalKey]?.info.song_ids" :key="song_id"
                        size="small" align="center">
                        <n-button size="tiny" :type="addAsFallback ? 'info' : 'primary'" ghost :disabled="addAllLoading"
                            :loading="addLoading[`${details[playlistDetailModalKey]?.info.api_key}-${song_id}`]"
                            @click="handleManualAdd(details[playlistDetailModalKey]?.info.api_key, song_id, addAsFallback)">
                            {{ addAsFallback ? '加入后备' : '添加到播放' }}
                        </n-button>
                        <n-tag v-if="details[playlistDetailModalKey]?.info.songs_meta[song_id].duration" size="small"
                            round>
                            {{ formatTime(details[playlistDetailModalKey]?.info.songs_meta[song_id].duration) }}
                        </n-tag>
                        <n-text v-if="details[playlistDetailModalKey]?.info.songs_meta[song_id].title">
                            {{ details[playlistDetailModalKey]?.info.songs_meta[song_id].title }}
                            <n-text depth="3">{{ song_id }}</n-text>
                        </n-text>
                        <n-text v-else>{{ song_id }}</n-text>
                    </n-space>
                </n-space>
            </n-card>
        </n-modal>

        <n-modal v-model:show="showUserPlaylistModal" preset="card" style="width: 550px;" content-style="padding: 0px;">
            <template #header>
                <n-flex align="center" size="large">
                    <n-text>从登录账号添加</n-text>
                    <n-button size="small" @click="() => loadUserPlaylists(true)"
                        :loading="loadingUserPlaylists">刷新</n-button>
                </n-flex>
            </template>
            <n-card :bordered="false" content-style="padding-top: 0px"
                style="min-height: 300px; max-height: 80vh; overflow-y: auto;">
                <n-space vertical>
                    <template v-if="userPlaylists && Object.keys(userPlaylists).length > 0">
                        <n-flex
                            v-for="source in Object.keys(userPlaylists).filter(source => userPlaylists![source].length > 0)"
                            :key="source" vertical>
                            <n-text strong style="font-size: 18px; margin-top: 10px;">{{ {
                                QQMusic: 'QQ音乐',
                                NeteaseMusic: '网易云音乐',
                                Bilibili: 'B站',
                            }[source] }}</n-text>
                            <template v-for="(playlist, index) in userPlaylists[source]" :key="playlist.url">
                                <n-divider v-if="index > 0" style="margin: 0px; padding: 0px 15px;" />
                                <n-flex justify="space-between" style="margin-left: 10px;" align="center">
                                    <n-flex vertical size="small">
                                        <n-text>
                                            {{ playlist.title }}
                                            <n-tag v-if="playlist.count" size="small" round style="margin-left: 2px;">
                                                {{ playlist.count }}首
                                            </n-tag>
                                        </n-text>
                                        <n-text depth="3">{{ playlist.url }}</n-text>
                                    </n-flex>
                                    <n-button size="small"
                                        :type="playlistState.playlists.includes(playlist.url) ? 'default' : 'primary'"
                                        ghost @click="handleAddFromUserPlaylist(playlist.url)"
                                        :disabled="loading || playlistState.playlists.includes(playlist.url)">
                                        {{ playlistState.playlists.includes(playlist.url) ? '已添加' : '添加' }}
                                    </n-button>
                                </n-flex>
                            </template>
                        </n-flex>
                    </template>
                    <n-empty v-else-if="userPlaylists && Object.keys(userPlaylists).length === 0" description="没有可用歌单"
                        style="margin-top: 60px;" />
                    <n-skeleton v-else :repeat="3" size="medium" text style="margin-top: 15px;" />
                </n-space>
            </n-card>
        </n-modal>

        <n-flex v-for="url in playlistState.playlists" :key="url" justify="space-between" class="playlist-item">
            <n-flex vertical class="playlist-info" :class="{ 'disabled': isDisabled(url) }" size="small">
                <n-text class="playlist-url">{{ url }}</n-text>
                <n-text v-if="details[url]" class="playlist-detail">
                    {{ details[url].info.title }} ({{ details[url].info.song_ids.length }}首<span
                        v-if="details[url].failed_count">，已失败跳过{{ details[url].failed_count }}首</span>)
                </n-text>
            </n-flex>
            <n-flex size="small" align="center" class="playlist-actions">
                <n-switch :value="!isDisabled(url)" @update:value="(val) => handleToggleEnabled(url, val)"
                    :loading="togglingUrlEnabled.has(url)" :disabled="loading || refreshingUrls.has(url)">
                    <template #checked>启用</template>
                    <template #unchecked>关闭</template>
                </n-switch>
                <n-button size="small" @click="() => { playlistDetailModalKey = url; showPlaylistDetailModal = true; }"
                    :disabled="loading" :loading="refreshingUrls.has(url)">查看</n-button>
                <n-button size="small" @click="handleRefresh(url)" :disabled="loading"
                    :loading="refreshingUrls.has(url)">刷新</n-button>
                <n-button size="small" type="error" ghost @click="removePlaylist(url)"
                    :disabled="loading || refreshingUrls.has(url)"
                    style="margin-left: 6px; margin-right: -6px;">删除</n-button>
            </n-flex>
        </n-flex>
    </n-space>
</template>

<style scoped lang="scss">
.playlist-item {
    padding: 8px;

    .playlist-info {
        &.disabled {
            opacity: 0.5;
        }

        .playlist-detail {
            opacity: 0.8;
        }

        .playlist-url {
            word-break: break-all;
        }
    }
}
</style>