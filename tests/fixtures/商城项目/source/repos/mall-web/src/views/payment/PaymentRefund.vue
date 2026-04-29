<template>
  <div class="payment-refund">
    <h1>退款</h1>
    <input v-model="paymentId" placeholder="支付单号" />
    <button @click="handleRefund">申请退款</button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { refundPayment } from '@/api/payment'

const paymentId = ref('')

async function handleRefund() {
  await refundPayment(paymentId.value)
}
</script>