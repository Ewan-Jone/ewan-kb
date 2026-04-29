import axios from 'axios'
import { MemberApi } from './constants'

// 会员信息
export function getMemberInfo(memberId: string) {
  return axios.get(MemberApi.INFO.replace('{memberId}', memberId))
}

// 会员注册
export function registerMember(data: any) {
  return axios.post(MemberApi.REGISTER, data)
}