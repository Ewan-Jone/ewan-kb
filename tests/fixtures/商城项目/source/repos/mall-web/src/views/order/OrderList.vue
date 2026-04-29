<template>
  <div class="order-list">
    <h1>订单列表</h1>
    <button @click="handleCreate">创建订单</button>
    <div v-for="order in orders" :key="order.id">
      <span>{{ order.id }} - {{ order.status }}</span>
      <button @click="handleCancel(order.id)">取消</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { createOrder, cancelOrder } from '@/api/order'

const orders = ref([])

async function handleCreate() {
  const res = await createOrder({ items: [] })
  orders.value.push(res.data)
}

async function handleCancel(orderId: string) {
  await cancelOrder(orderId)
}
</script>