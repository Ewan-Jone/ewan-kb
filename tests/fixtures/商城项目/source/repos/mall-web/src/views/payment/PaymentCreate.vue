<template>
  <div class="payment-create">
    <h1>创建支付</h1>
    <form @submit.prevent="handleSubmit">
      <input v-model="orderId" placeholder="订单号" />
      <input v-model="amount" placeholder="金额" type="number" />
      <button type="submit">支付</button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { createPayment } from '@/api/payment'

const orderId = ref('')
const amount = ref(0)

async function handleSubmit() {
  await createPayment({ orderId: orderId.value, amount: amount.value })
}
</script>