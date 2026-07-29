import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '../../api'
import type { Address } from '../../types/address'
import { usePagination } from '../../composables/usePagination'

export const useAddressStore = defineStore('address', () => {
  const addresses = ref<Address[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const showCreate = ref(false)
  const showEdit = ref(false)
  const editingRow = ref<Address | null>(null)

  const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()

  async function fetchAddresses(): Promise<void> {
    loading.value = true
    try {
      const res = await apiClient.get(
        `/warehouses/addresses?page=${page.value}&page_size=${pageSize.value}`
      )
      const d = res.data?.data ?? res.data ?? []
      let items: Address[]
      if (Array.isArray(d)) {
        items = d
        total.value = d.length
      } else {
        items = d.items ?? (d as any[])
        total.value = d.total ?? items.length
      }
      addresses.value = items
    } catch {
      addresses.value = []
    } finally {
      loading.value = false
    }
  }

  async function createAddress(payload: Partial<Address>): Promise<void> {
    saving.value = true
    try {
      await apiClient.post('/warehouses/addresses', payload)
      await fetchAddresses()
    } catch { /* ignore */ } finally {
      saving.value = false
    }
  }

  async function updateAddress(id: string, payload: Partial<Address>): Promise<void> {
    saving.value = true
    try {
      await apiClient.put(`/warehouses/addresses/${id}`, payload)
      await fetchAddresses()
    } catch { /* ignore */ } finally {
      saving.value = false
    }
  }

  async function deleteAddress(id: string): Promise<void> {
    try {
      await apiClient.delete(`/warehouses/addresses/${id}`)
      await fetchAddresses()
    } catch { /* ignore */ }
  }

  return {
    addresses, loading, saving, showCreate, showEdit, editingRow,
    page, pageSize, total, onPageChange, onSizeChange,
    fetchAddresses, createAddress, updateAddress, deleteAddress,
  }
})
