<template>
  <div class="order-detail">
    <h1>订单详情</h1>
    <p>订单号: {{ order?.id }}</p>
    <p>状态: {{ order?.status }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getOrderDetail } from '@/api/order'

const order = ref(null)

async function loadOrder(id: string) {
  const res = await getOrderDetail(id)
  order.value = res.data
}
</script>