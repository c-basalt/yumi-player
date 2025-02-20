import { onMounted } from 'vue';
import { useSessionStorage, StorageSerializers } from '@vueuse/core';
import { type MessageApi } from 'naive-ui';

import { type RoomInfo, getRoomid } from '@/api/roomid';
import { logger } from '@/api/logging';

export const useRoomInfo = (message?: MessageApi) => {
    const roomInfo = useSessionStorage<RoomInfo | null>('home-room-info', null, {
        serializer: StorageSerializers.object
    });

    const fetchRoomInfo = async () => {
        try {
            roomInfo.value = await getRoomid();
        } catch (e) {
            roomInfo.value = null;
            logger.error('[RoomInfo] 房间信息获取失败', e);
            if (message) {
                message.error('房间信息获取失败');
            }
        }
    };

    onMounted(() => fetchRoomInfo());

    return { roomInfo, fetchRoomInfo };
};
