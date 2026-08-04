<!-- SearchBar.vue — 支持占位符、事件和可选取消按钮 -->
<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ placeholder?: string; autofocus?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string): void }>()
const value = ref('')
</script>

<template>
  <el-input v-model="value" :placeholder="props.placeholder" :autofocus="props.autofocus ?? false" @input="emit('update:modelValue', $event)" />
</template>