import { ref, onUnmounted, computed } from 'vue';
import { useSessionStorage, StorageSerializers } from '@vueuse/core';

import { type PlayerStatus, PlayerWs, type PlayerCommand } from '@/api/player';

export const usePlayerStatus = (onCommand?: (command: PlayerCommand) => any) => {
    const playerLoading = ref(true);

    const playerStatus = useSessionStorage<PlayerStatus | null>('player-status', null, {
        serializer: StorageSerializers.object
    });
    const playlist = computed(() => playerStatus.value?.playlist || []);
    const progress = computed(() => playerStatus.value?.progress || 0);
    const current = computed(() => playerStatus.value?.current || null);

    const playerWs = ref<PlayerWs>(
        new PlayerWs((command) => {
            playerStatus.value = command.status;
            playerLoading.value = false;
            if (onCommand) {
                onCommand(command);
            }
        })
    );

    const sendCommand = (command: string, value: any) => {
        playerWs.value.sendCommand(command, value);
    };

    onUnmounted(() => {
        playerWs.value.close();
    });

    return { playerStatus, playerLoading, playlist, progress, current, playerWs, sendCommand };
};
