import { requestJSON } from './common';

export type Config = {
    roomid: number;
    player: {
        request_handler_off: boolean;
        clear_playing_fallback: boolean;
        request_cmd: string;
        cancel_cmd: string;
        skip_cmd: string;
        skipend_cmd: string;
        target_db: number;
        rate_limit_request: number;
        rate_limit_success_count: number;
        rate_limit_success_duration: number;
        query_history_count_limit: number;
        cache_limit_mb: number;
        cache_basedir: string;
        cache_proxy: string | null;
        fallback: {
            playlists: string[];
            disabled_urls: string[];
        };
    };
    player_status: {
        paused: boolean;
        progress: number;
    };
    player_banned: {
        banned_uids: number[];
        banned_keywords: string[];
    };
    player_unshield: {
        keywords: string[];
    };
};

export type DeepPartial<T> = {
    [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

export const fetchConfig = async () => {
    const response = await requestJSON('/config');
    return response as Config;
};

export const updateConfig = async (data: DeepPartial<Config>) => {
    const response = await requestJSON('/config', {
        method: 'POST',
        body: JSON.stringify(data)
    });
    return response as Config;
};

export const resetConfig = async (path: string[], recursive?: boolean, exclude?: string[]) => {
    const response = await requestJSON('/config', {
        method: 'DELETE',
        body: JSON.stringify({
            config_path: path,
            recursive: recursive ?? false,
            exclude: exclude ?? []
        })
    });
    return response;
};

export const getBaseUrl = async () => (await requestJSON('/baseurl')).baseurl as string;
