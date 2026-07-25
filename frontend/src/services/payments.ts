import api from './api'

export interface CheckoutResponse {
  order_id: string
  provider: string
  plan: string
  billing_cycle: string
  amount_cny: number
  status: string
  checkout_url: string | null
  message: string
}

export interface PaymentOrder {
  id: string
  provider: string
  provider_order_id: string | null
  plan: string
  billing_cycle: string
  amount_cny: number
  currency: string
  status: string
  checkout_url: string | null
  created_at: string
  paid_at: string | null
}

export const paymentApi = {
  checkout: (payload: { plan: 'pro' | 'enterprise'; billing_cycle: 'monthly' | 'yearly' | 'trial' }) =>
    api.post<CheckoutResponse>('/api/payments/checkout', payload),
  orders: () => api.get<PaymentOrder[]>('/api/payments/orders'),
}
