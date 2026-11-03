import type { AxiosError } from 'axios'

/**
 * The message a view should show for a failed request.
 *
 * The api client (`src/api/index.ts`) reads the documented error envelope —
 * `{success: false, error: {code, message}}` — puts the server's own sentence on
 * the error as `userMessage`, and toasts it.  `response.data.detail` is the
 * spelling this API used before the envelope: a view that reads only `detail`
 * finds nothing on a current failure, so it shows its own generic string
 * ('保存失败') — or axios's "Request failed with status code 422" — and the
 * operator never learns that the server said `status must be one of: …`.
 *
 * Order: the server's sentence, then the legacy `detail`, then the transport
 * message, then the view's own fallback.
 */
export function errText(error: unknown, fallback = '操作失败'): string {
  const e = error as (AxiosError & { userMessage?: string }) | undefined
  const envelope = e?.userMessage
  const legacy = (e?.response?.data as { detail?: unknown } | undefined)?.detail
  return envelope
    || (legacy ? String(legacy) : '')
    || (e?.message ? String(e.message) : '')
    || fallback
}
