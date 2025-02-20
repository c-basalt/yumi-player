import { onMounted, onBeforeUnmount } from 'vue';
import { useSessionStorage } from '@vueuse/core';
import { type MessageApi } from 'naive-ui';

import { manualAdd } from '@/api/player';
import { logger } from '@/api/logging';

export const useManualAdd = (message?: MessageApi) => {
    const resetOnReload = () => {
        addLoading.value = {}
    }
    onMounted(() => {
        window.addEventListener('beforeunload', resetOnReload)
    })
    onBeforeUnmount(() => {
        window.removeEventListener('beforeunload', resetOnReload)
    })


    const addLoading = useSessionStorage<Record<string, boolean>>('manual-add-loading-map', {})

    const isAdding = (source: string, song_id: string) => {
        return addLoading.value[`${source}-${song_id}`]
    }

    const handleManualAdd = async (source: string, song_id: string, is_fallback?: boolean) => {
        addLoading.value[`${source}-${song_id}`] = true
        if (source === 'Bilibili') {
            addLoading.value[`${source}-${song_id.split('_p')[0]}`] = true
        }
        try {
            const result = await manualAdd(source, song_id, { is_fallback })
            if (result.error) {
                message?.error(result.error)
            } else {
                message?.success('添加成功')
            }
        } catch (error) {
            message?.error('添加失败')
            logger.error(`[ManualAdd] Add failed: ${source}-${song_id}`, error)
        } finally {
            delete addLoading.value[`${source}-${song_id}`]
            if (source === 'Bilibili') {
                delete addLoading.value[`${source}-${song_id.split('_p')[0]}`]
            }
        }
    }
    return {
        addLoading, handleManualAdd, isAdding
    }
}
