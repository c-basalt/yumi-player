import { endpoint, requestJSON } from './common';
import { logger } from './logging';

export interface PlaylistCache {
    [url: string]: {
        api: string;
        info: {
            url: string;
            title: string;
            api_key: string;
            song_ids: string[];
            songs_meta: Record<string, any & Partial<{
                title: string;
                duration: number;
                singer: string;
            }>>;
        };
        failed_count: number;
    };
}

// Update response interface for playlist list endpoint
export interface PlaylistListResponse {
    playlists: string[];
    disabled: string[];
}

export class FallbackWs {
    ws: WebSocket;
    onUpdate: (cache: PlaylistCache) => any;
    private closed: boolean = false;

    constructor(onUpdate: (cache: PlaylistCache) => any) {
        this.onUpdate = onUpdate;
        this.ws = this.createWs();
    }

    createWs() {
        if (this.closed) return this.ws;

        const ws = new WebSocket(`${endpoint.replace(/^http/, 'ws')}/player/fallback/ws_info`);
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
            this.onUpdate(data);
        } catch (e) {
            logger.error('[FallbackWs] error parsing fallback playlist data', e);
        }
    }
}

/**
 * Get list of playlist URLs and disabled status from config
 * Maps to FallbackLists.handle_playlist_url_change GET
 */
export async function getFallbackPlaylists(): Promise<PlaylistListResponse> {
    const response = await fetch(`${endpoint}/player/fallback/lists`);
    return await response.json();
}

// Add new type for playlist commands
export type PlaylistCommand = 'add' | 'remove' | 'disable' | 'enable';

/**
 * Add, remove, enable or disable a playlist URL
 * Maps to FallbackPlaylist.handle_playlist_url_change POST
 */
export const updateFallbackPlaylist = async (cmd: PlaylistCommand, url: string): Promise<void> => {
    await requestJSON('/player/fallback/lists', {
        method: 'POST',
        body: JSON.stringify({ cmd, url })
    });
};

/**
 * Refresh a playlist's cache
 * Maps to FallbackPlaylist.handle_playlist_refresh
 */
export const refreshPlaylist = async (url: string): Promise<void> => {
    await requestJSON('/player/fallback/refresh', {
        method: 'POST',
        body: JSON.stringify({ url })
    });
};
