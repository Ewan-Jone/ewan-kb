import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/orders', component: () => import('@/views/order/OrderList.vue') },
  { path: '/orders/:id', component: () => import('@/views/order/OrderDetail.vue') },
  { path: '/payment/create', component: () => import('@/views/payment/PaymentCreate.vue') },
  { path: '/payment/refund', component: () => import('@/views/payment/PaymentRefund.vue') },
  { path: '/products', component: () => import('@/views/product/ProductList.vue') },
  { path: '/inventory/check', component: () => import('@/views/inventory/InventoryCheck.vue') },
  { path: '/member/register', component: () => import('@/views/member/MemberRegister.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})