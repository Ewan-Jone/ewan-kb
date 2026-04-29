<template>
  <div class="product-list">
    <h1>商品列表</h1>
    <div v-for="product in products" :key="product.id">
      <span>{{ product.name }} - ¥{{ product.price }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getProductList } from '@/api/product'

const products = ref([])

async function loadProducts() {
  const res = await getProductList()
  products.value = res.data
}
</script>