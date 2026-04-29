<template>
  <div class="member-register">
    <h1>会员注册</h1>
    <form @submit.prevent="handleSubmit">
      <input v-model="name" placeholder="姓名" />
      <input v-model="phone" placeholder="手机号" />
      <button type="submit">注册</button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { registerMember } from '@/api/member'

const name = ref('')
const phone = ref('')

async function handleSubmit() {
  await registerMember({ name: name.value, phone: phone.value })
}
</script>