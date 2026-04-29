import axios from 'axios'
import { OrderApi } from './constants'

// 创建订单
export function createOrder(data: any) {
  return axios.post(OrderApi.LIST, data)
}

// 获取订单详情
export function getOrderDetail(orderId: string) {
  return axios.get(OrderApi.DETAIL.replace('{orderId}', orderId))
}

// 取消订单
export function cancelOrder(orderId: string) {
  return axios.put(OrderApi.CANCEL.replace('{orderId}', orderId))
}