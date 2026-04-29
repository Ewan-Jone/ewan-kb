package com.mall.application.apps.order;

/**
 * 订单 API 路径常量
 */
public interface OrderApi {
    String BASE = "/api/orders";
    String LIST = BASE + "/list";
    String DETAIL = BASE + "/{orderId}";
    String CREATE = BASE;
    String CANCEL = BASE + "/{orderId}/cancel";
}