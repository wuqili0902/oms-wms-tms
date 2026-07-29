<!-- SearchBar.vue — 支持占位符、事件和可选取消按钮 -->
<script setup lang="ts">
const props = defineProps<{ placeholder?: string; autofocus?: boolean }>()
</script>

<template>
  <el-input v-bind="{ modelValue:value, 'placeholder':props.placeholder,'autofocus':props.autofocus ?? false }" @input="$emit('update:modelValue', $event)" />
</template>

<script setup lang="ts">
import { ref } from 'vue'

const value = ref('')
</script>