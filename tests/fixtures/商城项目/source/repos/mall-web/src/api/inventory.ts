import axios from 'axios'
import { InventoryApi } from './constants'

// 库存查询
export function getStock(productId: string) {
  return axios.get(InventoryApi.STOCK.replace('{productId}', productId))
}

// 库存校验
export function checkInventory(data: any) {
  return axios.post(InventoryApi.CHECK, data)
}