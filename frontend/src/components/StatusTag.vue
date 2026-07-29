<script setup lang="ts">
const props = defineProps<{ type: string }>()
const map: Record<string, { text: string; color: string }> = {
  supplier: { text: '供应商地址', color: 'success' },
  warehouse: { text: '仓库地址', color: 'primary' },
  ship_from: { text: '发货地址', color: 'warning' },
  ship_to: { text: '收货地址', color: '' },
}
const t = map[props.type] ?? { text: props.type, color: '' }
</script>

<template>
  <el-tag :type="t.color">{{ t.text }}</el-tag>
</template>