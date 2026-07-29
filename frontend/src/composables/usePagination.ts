import { ref } from 'vue'

export function usePagination(defaultPageSize = 20) {
  const page = ref(1)
  const pageSize = ref(defaultPageSize)
  const total = ref(0)

  function onPageChange(p: number) { page.value = p }
  function onSizeChange(s: number) { pageSize.value = s; page.value = 1 }

  return { page, pageSize, total, onPageChange, onSizeChange }
}
