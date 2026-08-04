<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ title: string; message: string }>()

const visible = ref(false)
const pending = ref(false)

function reset() {}

async function confirm() {
  if (!await confirmWithTimeout()) return false
  pending.value = true
  try { /* user callback */ } finally { pending.value = false }
  return true
}

let timeout: any = null
function confirmWithTimeout(): Promise<boolean> {
  return new Promise((resolve) => {
    const fn = () => { clearTimeout(timeout); resolve(false) }
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(fn, 5000)
  })
}
</script>

<template>
  <el-dialog v-model="visible" title="" width="320px" align-footer center destroy-on-close @closed="reset">
    <div class="dialog-content">
      <h4>{{ props.title }}</h4>
      <p>{{ props.message }}</p>
    </div>
    <template #footer>
      <el-button @click="reset">取消</el-button>
      <el-button type="primary" :loading="pending" @click="confirm">确认</el-button>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
.dialog-content { text-align: center; padding: 16px 0; }
.dialog-content h4 { margin-bottom: 8px; }
</style>