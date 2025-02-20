<script setup lang="ts">
const props = defineProps<{
    status: 'success' | 'error'
}>()
</script>

<template>
    <div :class="['status-dot', props.status]"></div>
</template>

<style scoped>
.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    opacity: 0.8;

    &.success {
        background-color: #18a057;
    }

    &.error {
        background-color: #d03050;
    }
}
</style>
