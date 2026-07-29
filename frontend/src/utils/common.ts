export function isObject(val: unknown): val is Record<string, unknown> {
  return typeof val === 'object' && val !== null
}

export function isEmpty(val: unknown): boolean {
  if (val == null) return true
  if (Array.isArray(val)) return val.length === 0
  if (typeof val === 'string') return val.trim() === ''
  if (isObject(val)) return Object.keys(val).length === 0
  return false
}

export function pick<T extends Record<string, unknown>, K extends keyof T>(
  obj: T, keys: K[]
): Pick<T, K> {
  const result = {} as Pick<T, K>
  for (const key of keys) {
    if (key in obj) {
      ;(result as any)[key] = obj[key]
    }
  }
  return result
}

export function omit<T extends Record<string, unknown>, K extends keyof T>(
  obj: T, ...keys: K[]
): Omit<T, K> {
  const copy = { ...obj }
  for (const key of keys) delete copy[key]
  return copy as Omit<T, K>
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}
