import { endpoint, requestJSON } from './common';
import { logger } from './logging';

export type UserInfo = {
    uid: number;
    uid_hash: string;
    username: string;
    privilege: 'user' | 'admin' | 'owner';
};

export type SongInfo = {
    id: string;
    title: string;
    singer: string;
    source: string;
    filename: string;
    decibel: number | null;
    duration: number | null;
    meta?: Record<string, any>;
};

export type SongMeta = {
    id: string;
    title: string;
    singer: string;
    source: string;
    duration: number | null;
    meta: Record<string, any>;
};

export type SongEntry = {
    id: number;
    progress: number;
    is_fallback: boolean;
    is_from_control: boolean;
    user: UserInfo;
    music: SongInfo;
};

export type PlayerStatus = {
    paused: boolean;
    progress: number;
    volume: number | null;
    current: SongEntry | null;
    playlist: SongEntry[];
    fallback: SongEntry[];
    combined_list: SongEntry[];
    cached_songs: SongInfo[];
    recent_bvid: {
        user: UserInfo;
        bvid: string;
        meta?: SongMeta;
    }[];
    config: {
        request_handler_off: boolean;
        request_cmd: string;
        cancel_cmd: string;
        skip_cmd: string;
        skipend_cmd: string;
        target_db: number;
        rate_limit_request: number;
        rate_limit_success_count: number;
        rate_limit_success_duration: number;
    };
};

export type PlayerCommand = {
    command?: {
        cmd: string;
        value: any;
    };
    status: PlayerStatus;
};

export type PlayerEventValue = {
    type: string;
    user: UserInfo;
} & Record<string, any>;

export type PlayHistoryEntry = {
    user: UserInfo;
    song: SongInfo;
    progress: number;
    created_at: number;
    canceled: boolean;
};

export type QueryHistoryEntry = {
    query_text: string;
    user: UserInfo;
    song: SongInfo;
    created_at: number;
    result: string;
    match_count: number;
};

export type UserPlaylists = {
    [api_key: string]: {
        url: string;
        title: string;
        count: number | null;
    }[];
};

export class PlayerWs {
    ws: WebSocket;
    onCommand: (command: PlayerCommand) => any;
    private closed: boolean = false;

    constructor(onCommand: (command: PlayerCommand) => any) {
        this.onCommand = onCommand;
        this.ws = this.createWs();
    }

    createWs() {
        if (this.closed) return this.ws;

        const ws = new WebSocket(`${endpoint.replace(/^http/, 'ws')}/player/ws`);
        ws.onclose = () => setTimeout(this.createWs.bind(this), 3000);
        ws.onmessage = this.onWSMsg.bind(this);
        this.ws = ws;
        return ws;
    }

    close() {
        this.closed = true;
        if (this.ws) {
            this.ws.onclose = null;
            this.ws.onmessage = null;
            this.ws.close();
        }
    }

    onWSMsg(ev: MessageEvent) {
        try {
            const data = JSON.parse(ev.data);
            this.onCommand(data);
        } catch (e) {
            logger.error('[PlayerWs] error parsing data', e);
        }
    }

    sendCommand(cmd: string, value: any) {
        this.ws.send(JSON.stringify({ cmd, value }));
    }
}

export const getAudioUrl = (path: string | null) =>
    path ? `${endpoint}/player/file?path=${encodeURIComponent(path)}` : '';

export const getRecentUsers = () => requestJSON('/player/recent_users') as Promise<UserInfo[]>;

export const getBannedUsers = () =>
    requestJSON('/player/banned_user') as Promise<{ [uid: string]: string }>;

export const addBannedUser = (uid: number, username?: string) =>
    requestJSON('/player/banned_user', {
        method: 'POST',
        body: JSON.stringify({ uid, username })
    }) as Promise<{ [uid: string]: string }>;

export const getPlayHistory = (pageNum: number, size: number, hideCanceled?: boolean, filter?: string) =>
    requestJSON(
        `/player/play_history?page_num=${pageNum}&size=${size}&${hideCanceled ? 'hide_canceled=1' : ''}&filter=${filter}`
    ) as Promise<{
        total: number;
        filter: string;
        data: PlayHistoryEntry[];
    }>;

export const getQueryHistory = (pageNum: number, size: number) =>
    requestJSON(`/player/query_history?page_num=${pageNum}&size=${size}`) as Promise<{
        total: number;
        data: QueryHistoryEntry[];
    }>;

export const getUserPlaylists = () =>
    requestJSON('/player/user_playlists') as Promise<UserPlaylists>;

export const testProxy = () =>
    requestJSON('/player/test_proxy') as Promise<{ success: boolean; reason: string }>;

export const manualSearch = (query: string) =>
    requestJSON('/player/manual_search', {
        method: 'POST',
        body: JSON.stringify({ query })
    }) as Promise<{
        [api_key: string]: {
            id: string;
            title: string;
            singer: string;
            meta: Record<string, any>;
        }[];
    }>;

export const manualAdd = (
    source: string,
    song_id: string,
    { user, is_fallback }: { user?: UserInfo; is_fallback?: boolean } = {}
) =>
    requestJSON('/player/manual_add', {
        method: 'POST',
        body: JSON.stringify({
            source,
            song_id,
            user,
            is_fallback
        })
    }) as Promise<{ error?: string }>;

export const sortPlaylist = (ordered_entry_ids: number[]) =>
    requestJSON('/player/sort_playlist', {
        method: 'POST',
        body: JSON.stringify(ordered_entry_ids)
    }) as Promise<{ error?: string }>;

export const unshieldTest = (text: string) =>
    requestJSON('/player/unsheild', {
        method: 'POST',
        body: JSON.stringify({ text })
    }) as Promise<{ text: string }>;
