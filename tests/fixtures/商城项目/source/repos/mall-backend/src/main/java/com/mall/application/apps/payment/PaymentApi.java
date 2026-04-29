package com.mall.application.apps.payment;

/**
 * 支付 API 路径常量
 */
public interface PaymentApi {
    String BASE = "/api/payments";
    String CREATE = BASE + "/create";
    String REFUND = BASE + "/refund";
}