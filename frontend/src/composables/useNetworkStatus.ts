import { ref, onUnmounted } from 'vue'

export function useNetworkStatus() {
  const online = ref(navigator.onLine)

  function onOnline() { online.value = true }
  function onOffline() { online.value = false }

  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)

  onUnmounted(() => {
    window.removeEventListener('online', onOnline)
    window.removeEventListener('offline', onOffline)
  })

  return { online }
}
