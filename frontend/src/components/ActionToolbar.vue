<!-- ActionToolbar.vue — 一组操作按钮（可选确认对话框） -->
<script setup lang="ts">
const props = defineProps<{ title: string; actions: { label: string; type?: string }[] }>()
</script>

<template>
  <div class="action-toolbar">
    <slot></slot>
  </div>
</template>

<style scoped lang="scss">
.action-toolbar { display:flex; gap:8px; }
.action-toolbar .el-button:first-child { margin-left:-4px;}
</style>