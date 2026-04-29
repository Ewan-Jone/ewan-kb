import axios from 'axios'
import { PaymentApi } from './constants'

// 创建支付
export function createPayment(data: any) {
  return axios.post(PaymentApi.CREATE, data)
}

// 获取支付详情
export function getPaymentDetail(paymentId: string) {
  return axios.get(PaymentApi.DETAIL.replace('{paymentId}', paymentId))
}

// 退款
export function refundPayment(paymentId: string) {
  return axios.post(PaymentApi.REFUND, { paymentId })
}