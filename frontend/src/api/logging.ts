import { requestJSON } from './common';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

async function sendLog(level: LogLevel, ...data: any[]): Promise<void> {
    console[level](...data);
    const message = data.map(e =>
        e && typeof e === 'object' && e.message ? `${e.message}${e.stack? `\n${e.stack}` : ''}` : `${e}`).join(' ');
    await requestJSON('/logging', {
        method: 'POST',
        body: JSON.stringify({
            level: level === 'warn' ? 'warning' : level,
            message,
        }),
    });
}

export const logger = {
    debug: (...data: any[]) => sendLog('debug', ...data),
    info: (...data: any[]) => sendLog('info', ...data),
    warning: (...data: any[]) => sendLog('warn', ...data),
    error: (...data: any[]) => sendLog('error', ...data),
};
