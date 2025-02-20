import { requestJSON } from './common';

export interface CookieStatus {
    autoload: Record<
        string,
        {
            browser: string | null;
            uid: string | null;
            auto_reload: boolean;
            auto_reload_interval_minutes: number;
            try_appbound_debugger_workaround: boolean;
        }
    >;
    browsers: string[];
    appbound: string[];
    site_loaders: Record<string, string>;
    results: Record<string, string>;
    success: Record<string, boolean>;
    cookie_cloud_config: {
        uuid: string;
        password: string;
    };
}

export const loadCookie = async (loaderKey: string, browserName: string): Promise<CookieStatus> => {
    return requestJSON('/cookie', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            load: {
                [loaderKey]: browserName
            }
        })
    });
};

export const resetCookie = async (loaderKey: string): Promise<CookieStatus> => {
    return requestJSON('/cookie', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            load: {
                [loaderKey]: ''
            }
        })
    });
};

export const configureAutoload = async (
    loaderKey: string,
    on: boolean,
    expect_uid: boolean
): Promise<CookieStatus> =>
    requestJSON('/cookie', {
        method: 'POST',
        body: JSON.stringify({ autoload: { [loaderKey]: { on, expect_uid } } })
    });

export const configureAutoReload = async (
    loaderKey: string,
    update: Partial<{ auto_reload: boolean; auto_reload_interval_minutes: number; try_appbound_debugger_workaround: boolean }>
): Promise<CookieStatus> =>
    requestJSON('/cookie', {
        method: 'POST',
        body: JSON.stringify({ autoreload: { [loaderKey]: update } })
    });

export const getCookieStatus = async (): Promise<CookieStatus> => requestJSON('/cookie');
