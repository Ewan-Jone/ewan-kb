// API路径常量
export const OrderApi = {
  LIST: '/api/orders',
  DETAIL: '/api/orders/{orderId}',
  CANCEL: '/api/orders/{orderId}/cancel',
}

export const PaymentApi = {
  CREATE: '/api/payments/create',
  REFUND: '/api/payments/refund',
  DETAIL: '/api/payments/{paymentId}',
}

export const ProductApi = {
  LIST: '/api/products/list',
  DETAIL: '/api/products/{productId}',
}

export const InventoryApi = {
  STOCK: '/api/inventory/{productId}',
  CHECK: '/api/inventory/check',
}

export const MemberApi = {
  INFO: '/api/members/{memberId}',
  REGISTER: '/api/members/register',
}