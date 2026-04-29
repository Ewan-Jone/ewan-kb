import axios from 'axios'
import { ProductApi } from './constants'

// 商品列表
export function getProductList() {
  return axios.get(ProductApi.LIST)
}

// 商品详情
export function getProductDetail(productId: string) {
  return axios.get(ProductApi.DETAIL.replace('{productId}', productId))
}