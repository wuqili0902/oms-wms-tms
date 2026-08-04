<!-- DataTable.vue — 带 v-loading + empty + pagination 的通用表格 -->
<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ columns: any[]; data?: any[]; loading?: boolean }>()

// State owned by child when v-model is not used.
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

watch([() => props.data, () => props.loading], ([newData]) => {
  if (Array.isArray(newData)) {
    total.value = newData.length
  } else {
    total.value = 0
  }
}, { immediate: true })
</script>

<template>
  <el-table :data="props.data" stripe :loading="props.loading">
    <slot name="columns"></slot>
  </el-table>
  <div style="display:flex;justify-content:flex-end;margin-top:12px">
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="(p: number) => (page=p)" @size-change="(s: number) => (pageSize=s)"/>
  </div>
</template>

<style scoped lang="scss">
/* pagination 和 table 各占一行（flex 布局） */
</style>