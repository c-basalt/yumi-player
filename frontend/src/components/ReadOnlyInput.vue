<script setup lang="ts">
import { useMessage, NInput } from 'naive-ui'
import { useClipboard } from '@vueuse/core'

import { logger } from '@/api/logging'

const message = useMessage()
const { copy: copyToClipboard, isSupported: isClipboardSupported } = useClipboard({ legacy: true });
let handleFocus = true;

const handleInputFocus = (e: FocusEvent) => {
    (e.target as HTMLInputElement).select();
    if (handleFocus && isClipboardSupported.value && !props.noCopy) {
        const copyText = (e.target as HTMLInputElement).value;
        handleFocus = false; // avoid infinite loop
        copyToClipboard(copyText).then(() => {
            message.success('已复制到剪贴板');
            (e.target as HTMLInputElement).focus(); // legacy copy will blur the input
        }).catch((e) => {
            logger.error('[ReadOnlyInput] Failed to copy to clipboard:', e)
        }).finally(() => {
            setTimeout(() => { handleFocus = true }, 500);
        })
    }
};
const props = defineProps<{ value: string; noCopy?: boolean }>()
</script>

<template>
    <n-input :value="value" @focus="handleInputFocus" />
</template>
