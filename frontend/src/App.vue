<script setup lang="ts">
import { RouterView } from 'vue-router'
import { NMessageProvider, NConfigProvider, zhCN } from 'naive-ui'
</script>

<template>
  <n-config-provider :locale="zhCN">
    <n-message-provider>
      <RouterView />
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped lang="scss">
</style>
