<script setup lang="ts">
import { reactive, ref, useTemplateRef, computed, onUnmounted } from 'vue'
import { watch } from 'vue';
import { NButton } from 'naive-ui';
import { useInterval } from '@vueuse/core';

import { PlayerWs, getAudioUrl, type PlayerStatus, type PlayerEventValue } from '@/api/player';
import { logger } from '@/api/logging';
import { cjkWidth, cjkTruncate } from '@/utils/cjkWidth';
import { getEntryTitle } from '@/utils/utils';

type StatusMessage = {
    text: string;
    type: 'info' | 'success' | 'error';
    event: PlayerEventValue;
    timeout?: number;
}

const status = reactive<Partial<PlayerStatus>>({});
const idleBannerCounter = useInterval(10e3);
const audioRef = useTemplateRef<HTMLAudioElement>('audio-player');
const musicUrl = computed(() => getAudioUrl((status.current?.music?.filename || null)));
const targetDbFS = computed(() => status.config?.target_db ?? -40);
const showingPlaylist = computed(() => status.playlist?.length ? status.playlist :
    status.current ? [status.current] : []);

const autoplayNeedGuesture = ref(false);
const retryCount = ref(3);

const messages = ref<StatusMessage[]>([]);
let removerTimeout: number | null = null;


const pushStatusMessage = async (message: StatusMessage, replaceLatest?: boolean) => {
    const shiftMessage = () => {
        if (messages.value.length > 0) messages.value.shift();
        if (messages.value.length > 0) {
            removerTimeout = window.setTimeout(shiftMessage, messages.value[0].timeout || 3000);
        } else {
            removerTimeout = null;
        }
    }

    if (replaceLatest && messages.value.length >= 1) {
        if (removerTimeout) {
            window.clearTimeout(removerTimeout);
            removerTimeout = null;
        }
        messages.value.splice(1, 0, message);
        await new Promise(resolve => setTimeout(resolve, 50));
        messages.value.shift();
    } else {
        messages.value.push(message);
    }
    if (!removerTimeout) removerTimeout = window.setTimeout(shiftMessage, message.timeout || 3000);
}


const handleEvent = (event: PlayerEventValue) => {
    const replaceSearching = () => {
        const searchingIndex = messages.value.findIndex(msg =>
            msg.event.type === 'searching' && msg.event.query === event.query
        );
        if (searchingIndex > 0) messages.value.splice(searchingIndex, 1);
        return searchingIndex === 0;
    }
    const replaceLoading = () => {
        const loadingIndex = messages.value.findIndex(msg =>
            msg.event.type === 'query-loading' && msg.event.query === event.query
        );
        if (loadingIndex > 0) messages.value.splice(loadingIndex, 1);
        return loadingIndex === 0;
    }

    const truncUsername = () => cjkTruncate(event.user.username, 12);

    const pushError = (text: string, replaceLatest?: boolean, timeout?: number) =>
        pushStatusMessage({ event, type: 'error', text, timeout }, replaceLatest)
    const pushInfo = (text: string, replaceLatest?: boolean, timeout?: number) =>
        pushStatusMessage({ event, type: 'info', text, timeout }, replaceLatest)
    const pushSuccess = (text: string, replaceLatest?: boolean, timeout?: number) =>
        pushStatusMessage({ event, type: 'success', text, timeout }, replaceLatest)

    if (['searching', 'query-loading', 'query-fail', 'query-success'].includes(event.type)) {
        const sourceNames: Record<string, string> = {
            BiliBili: 'B站',
            QQMusic: 'QQ音乐',
            NeteaseMusic: '网易云',
        };
        const source: string | undefined = sourceNames[event.source];
        if (event.type === 'searching') {
            pushInfo(`${source ? '从' + source : '正在'}搜索：${event.keywords}`, false, 3000)
        } else if (event.type === 'query-loading') {
            const replaceLatest = replaceSearching();
            pushInfo(`${source ? '从' + source : '正在'}加载：${event.keywords}`, replaceLatest, 5000)
        } else if (event.type === 'query-success') {
            const replaceLatest = replaceSearching() || replaceLoading();
            pushSuccess(`${source ? '从' + source : '已'}添加：${event.keywords}`, replaceLatest, 6000)
        } else if (event.type === 'query-fail') {
            const replaceLatest = replaceSearching() || replaceLoading();
            const msg = (event.reason === 'already-queued') ? `歌曲已队列：${event.query}` :
                `未${source ? '从' + source : ''}找到歌曲：${event.keywords}`;
            pushError(msg, replaceLatest, 6000)
        }
    } else if (event.type === 'cancel-fail') {
        const reasons: Record<string, string> = {
            'no-match': '你没有待播点歌',
        };
        pushError(`${truncUsername()}: ${reasons[event.reason] || '操作失败'}`)
    } else if (event.type === 'cancel-success') {
        pushSuccess(`${truncUsername()}: 已取消 ${event.title}`)
    } else if (event.type === 'skip-fail') {
        const reasons: Record<string, string> = {
            'not-user': '只能跳过自己的点歌',
            'use-startcmd': '刚开始的需用"切歌"指令',
            'no-playing': '当前无播放',
        };
        pushError(`${truncUsername()}: ${reasons[event.reason] || '操作失败'}`)
    } else if (event.type === 'skip-success') {
        pushSuccess(`${truncUsername()}: 已跳过 ${event.title}`)
    } else if (event.type === 'request-fail') {
        const reasons: Record<string, string> = {
            'rate-limit': '点歌太频繁',
            'success-rate-limit': '短时间点歌太多',
        };
        const replaceLatest = replaceSearching();
        pushError(`${truncUsername()}: ${reasons[event.reason] || '操作失败'}`, replaceLatest)
    }
}

const ws = new PlayerWs((command) => {
    status.paused = command.status.paused;
    status.progress = command.status.progress;
    Object.assign(status, command.status);
    const cmd = command.command?.cmd;
    if (cmd == 'progress') return;

    if (audioRef.value) {
        if (status.paused === false && audioRef.value.paused) {
            playAudio();
        } else if (status.paused && !audioRef.value.paused) {
            audioRef.value.pause();
        }
        // Handle seek
        if (cmd == 'seek') {
            audioRef.value.currentTime = command.command?.value;
        }
        if (cmd == 'show-event') {
            handleEvent(command.command?.value)
        }
    }
});

let retryTimeout: number | null = null;
const handlePlayError = (error: Error | MediaError) => {
    if (error && error.message.match(/user.*interact/i)) {
        logger.error('[PlayerView] Autoplay was prevented:', error);
        autoplayNeedGuesture.value = true;
    } else {
        if (!error.message.match(/(Empty src attribute|The element has no supported sources|The play\(\) request was interrupted by a new load request)/i)) {
            logger.error('[PlayerView] Audio playback error:', error);
        } else {
            console.error(error);
        }
        if (retryCount.value > 0) {
            if (retryTimeout) window.clearTimeout(retryTimeout);
            retryTimeout = window.setTimeout(() => {
                retryCount.value -= 1;
                if (status.paused === false) playAudio();
            }, 3000);
        } else {
            if (status.current) {
                ws.sendCommand('next', status.current.id);
            }
        }
    }
};

const playAudio = () => {
    if (audioRef.value) {
        audioRef.value.play().catch(handlePlayError);
    }
}

const dbFSCache = new Map<string, number>();

const calculateDBFS = async (url: string): Promise<number> => {
    const fallbackDbFS = -10;
    if (dbFSCache.has(url)) {
        return dbFSCache.get(url)!;
    }
    if (!url) return fallbackDbFS;

    logger.debug('[PlayerView] calculateDBFS', url.split('-').pop());

    try {
        const context = new AudioContext();
        const buffer = await fetch(url)
            .then(response => response.arrayBuffer())
            .then(arrayBuffer => context.decodeAudioData(arrayBuffer));

        const channelData = buffer.getChannelData(0);
        const squareSum = channelData.reduce((sum, sample) => sum + sample * sample, 0);
        const rms = Math.sqrt(squareSum / channelData.length);

        const roundTo = 1;
        const dbFS = Math.round(20 * Math.log10(rms) / roundTo) * roundTo;

        dbFSCache.set(url, dbFS);
        logger.debug('[PlayerView] dbFS calculated', url.split('-').pop(), dbFS);
        return dbFS;
    } catch (error) {
        logger.error('[PlayerView] Error analyzing audio:', error);
        return fallbackDbFS;
    }
};

const calculateVolumeLevel = async (url: string): Promise<number> => {
    const dbFS = await calculateDBFS(url)

    if (dbFS > targetDbFS.value) {
        const dbAttenuation = targetDbFS.value - dbFS;
        return Math.pow(10, dbAttenuation / 20);
    }
    return 1;
};

const updateVolume = async () => {
    const songList = (status.playlist || []).map(i => i.music).concat(status.cached_songs || []);
    songList.filter(song => song.decibel).forEach(song => {
        dbFSCache.set(getAudioUrl(song.filename), song.decibel!);
    });
    if (musicUrl.value && audioRef.value) {
        audioRef.value.volume = await calculateVolumeLevel('');
        audioRef.value.volume = await calculateVolumeLevel(musicUrl.value);
        ws.sendCommand('volume-report', audioRef.value.volume);
        // preload volume for upcoming
        songList.forEach(song => calculateVolumeLevel(getAudioUrl(song.filename)));
    }
};

const handleDataLoaded = (event: Event) => {
    (event.target as HTMLAudioElement).currentTime = status.progress || 0;
}
const handleProgressUpdate = (event: Event) => {
    const audio = (event.target as HTMLAudioElement);
    const progress = Math.floor(audio.currentTime);
    if (progress > 0 && progress !== status.progress) {
        ws.sendCommand('progress', Math.floor(audio.currentTime));
    }
}
const handleEnded = () => {
    ws.sendCommand('next', status.current?.id);
}
const handleError = (event: Event) => {
    const error = ((event as Event).target as HTMLAudioElement).error;
    if (error) handlePlayError(error);
}

watch(musicUrl, () => {
    updateVolume();
    retryCount.value = 3;
});
watch(targetDbFS, updateVolume);


onUnmounted(() => {
    ws.close();
});

</script>

<template>
    <n-button v-if="autoplayNeedGuesture" @click="playAudio(); autoplayNeedGuesture = false"
        id="browser-play-button">浏览器下需要用户交互，请点击该按钮</n-button>

    <div class="status-container">
        <TransitionGroup name="list">
            <div v-for="(msg, index) in messages" :key="JSON.stringify(msg)" class="status-message"
                :class="{ [msg.type]: true, first: index === 0 }">
                {{ msg.text }}
            </div>
            <div class="status-message idle" key="idle-disabled" v-if="status.config?.request_handler_off">弹幕点歌已禁用</div>
            <div class="status-message idle" key="idle-paused" v-else-if="status.paused">播放已暂停</div>
            <div class="status-message idle" key="idle-default-alt"
                v-else-if="idleBannerCounter % 30 === 29 && status.config">
                {{ `对自己可用 ${status.config?.cancel_cmd}、${status.config?.skipend_cmd} 指令` }}
            </div>
            <div class="status-message idle" key="idle-default-alt2" v-else-if="idleBannerCounter % 30 === 14">
                {{ `可在歌名后加上网易云、QQ音乐` }}
            </div>
            <div class="status-message idle" key="idle-default" v-else>
                {{ `${status.config?.request_cmd || '点歌'} 歌名/歌曲UID` }}
            </div>
        </TransitionGroup>
    </div>

    <audio ref="audio-player" :src="musicUrl" :autoplay="status.paused === false" @loadeddata="handleDataLoaded"
        @timeupdate="handleProgressUpdate" @ended="handleEnded" @error="handleError"></audio>

    <div v-if="showingPlaylist?.length" class="player-container" style="margin-top: 3px;">
        <TransitionGroup name="songs">
            <div v-for="(item, index) in showingPlaylist" :key="item.id" class="song-item"
                :class="{ 'is-current': index === 0 && !status.paused }">
                <div class="song-info">
                    <span class="song-name" :class="{
                        small: cjkWidth(getEntryTitle(item) || '') > 22,
                        tiny: cjkWidth(getEntryTitle(item) || '') > 32
                    }">
                        {{ getEntryTitle(item) }}
                    </span>
                    <div class="song-meta">
                        <span class="artist-name" :class="{ tiny: cjkWidth(item.music.singer) > 18 }">{{
                            cjkTruncate(item.music.singer || '&nbsp;', 25) }}</span>
                        <span v-if="item.user" class="user-name">{{ item.user.username }}</span>
                    </div>
                </div>
            </div>
        </TransitionGroup>
    </div>
</template>


<style>
body {
    background: transparent
}
</style>

<style lang="scss" scoped>
.song-item {
    --fontstack-sans-serif: ui-sans-serif, system-ui, "Helvetica Neue", "PingFang SC", "Microsoft Yahei", "WenQuanYi Micro Hei", Arial, sans-serif;
    --fontstack-serif: ui-serif, Georgia, serif;

    font-family: var(--fontstack-sans-serif);
    padding: 2px 8px;
    opacity: 0.7;
    transition: all 0.2s ease;
    font-weight: bold;
    text-shadow:
        -1px -1px 1px #111,
        1px -1px 1px #111,
        -1px 1px 1px #111,
        1px 0 1px #111,
        -1px 0 1px #111,
        0 1px 1px #111,
        0 -1px 1px #111,
        1px 1px 1px #111;

    &.is-current {
        opacity: 1;
        border-left: 3px solid #8CC8FF;
        padding-left: 12px;
    }

    .song-info {
        display: flex;
        flex-direction: column;
    }

    .song-name {
        font-size: 1.5em;
        color: #FFFFFF;
        max-width: 400px;
        line-height: 1.5em;
        line-break: anywhere;

        &.small {
            font-size: 1.2em;
            line-height: 1.9em;

            &.tiny {
                font-size: 1.05em;
            }
        }
    }

    .song-meta {
        font-size: 1em;
        color: #808080;
        display: flex;
        gap: 8px;

        & .tiny {
            font-size: 0.8em;
            line-height: 1.7em;
        }
    }

    &.is-current {
        .song-name {
            font-weight: bold;
            color: #8CC8FF;
        }

        .song-meta {
            color: #6699CC;
        }
    }
}

.status-container {
    --line-height: 25px;
    --width: 320px;
    --round-size: 8px;

    position: relative;
    width: var(--width);
    overflow: hidden;
    height: var(--line-height);
    opacity: 0.8;
    border-radius: var(--round-size);

    .status-message {
        padding: 0 var(--round-size);
        margin-bottom: -5px;
        padding-bottom: 5px;
        height: var(--line-height);
        width: var(--width);
        overflow: hidden;

        color: white; // Add white text color

        &.info {
            background: #2196F3; // Material Blue 500
        }

        &.success {
            background: #4CAF50; // Material Green 500
        }

        &.error {
            background: #F44336; // Material Red 500
        }

        &.idle {
            background: #757575; // Material Blue 500
        }
    }

    .list-move,
    .list-enter-active,
    .list-leave-active {
        transition: all 0.3s linear
    }

    .list-enter-active {
        &:not(.first) {
            transition: none;
            opacity: 0;
        }
    }

    .list-enter-from,
    .list-leave-to {
        transform: translateY(calc(-1 * var(--line-height)));
    }

    .list-leave-active {
        position: absolute;
    }
}

.songs-move,
.songs-enter-active,
.songs-leave-active {
    transition: all 0.3s ease;
}

.songs-enter-from,
.songs-leave-to {
    opacity: 0;
    transition: all 0.2s ease;
}

.songs-leave-active {
    position: absolute;
}
</style>