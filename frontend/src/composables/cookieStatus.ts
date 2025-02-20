import { onMounted, computed } from 'vue';
import { type MessageApi } from 'naive-ui';
import { useSessionStorage, StorageSerializers, useInterval } from '@vueuse/core';

import { type CookieStatus, getCookieStatus } from '@/api/cookies';
import { logger } from '@/api/logging';

export const useCookieStatus = (message?: MessageApi) => {
    const cookieStatus = useSessionStorage<CookieStatus | null>('cookie-config-status', null, {
        serializer: StorageSerializers.object
    });

    const cookieSuccess = computed<Record<string, boolean>>(() => {
        if (!cookieStatus.value?.site_loaders) return {};
        return Object.fromEntries(
            Object.entries(cookieStatus.value.site_loaders).map(([key, value]) => [
                value,
                cookieStatus.value?.success?.[key] || false
            ])
        );
    });

    const fetchCookieStatus = async () => {
        try {
            const status = await getCookieStatus();
            cookieStatus.value = status;
        } catch (e) {
            cookieStatus.value = null;
            logger.error('[CookieStatus] Failed to fetch cookie status:', e);
            if (message) {
                message.error('Cookie状态获取失败');
            }
        }
    };

    onMounted(() => fetchCookieStatus());
    useInterval(120e3, { callback: () => fetchCookieStatus() });

    return { cookieStatus, cookieSuccess, fetchCookieStatus };
};
