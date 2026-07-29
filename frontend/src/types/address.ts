export interface Address {
  id: string
  code: string
  type: 'supplier' | 'warehouse' | 'ship_from' | 'ship_to' | (string & {})
  name: string
  province: string
  city: string
  full_address: string
  contact?: string
  phone?: string
  is_active?: boolean
  created_at?: string
}

export interface Device {
  id: string
  name: string
  type: 'pda' | 'scanner' | 'printer' | (string & {})
  status: 'online' | 'offline' | 'unknown' | (string & {})
  last_seen?: string
  firmware_version?: string
  created_at?: string
}

export interface SessionLog {
  id: string
  device_id: string
  event_type: string
  payload?: Record<string, unknown>
  ts: string
}
