import { ElMessage } from 'element-plus'
import apiClient from '../api'

export function useExport() {
  async function downloadCSV(url: string, filename: string) {
    try {
      const res = await apiClient.get(url, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'text/csv; charset=utf-8' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename
      link.click()
      URL.revokeObjectURL(link.href)
      ElMessage.success('导出成功')
    } catch {
      ElMessage.error('导出失败')
    }
  }

  return { downloadCSV }
}
