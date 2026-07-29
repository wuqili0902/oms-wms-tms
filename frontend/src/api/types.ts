export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

export interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages?: number
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface UserInfo {
  id: string
  username: string
  email: string
  role: string
  is_active: boolean
}

export interface Order {
  id: string
  order_no: string
  status: string
  customer_id: string
  total_amount: string
  priority: string
  notes: string
  items: any[]
  created_at: string
  updated_at: string
}

export interface Warehouse {
  id: string
  code: string
  name: string
  address: string
  type: string
  is_active: boolean
  created_at: string
}

export interface TransportOrder {
  id: string
  order_no: string
  status: string
  carrier_code: string
  driver_name: string
  plate_no: string
  origin: string
  destination: string
  created_at: string
}

export interface User {
  id: string
  username: string
  email: string
  is_active: boolean
  created_at: string
}
