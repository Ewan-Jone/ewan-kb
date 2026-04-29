<template>
  <div class="inventory-check">
    <h1>库存校验</h1>
    <button @click="handleCheck">校验库存</button>
    <p v-if="result">校验结果: {{ result }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { checkInventory } from '@/api/inventory'

const result = ref('')

async function handleCheck() {
  const res = await checkInventory({ productId: '1', quantity: 10 })
  result.value = res.data?.available ? '库存充足' : '库存不足'
}
</script>