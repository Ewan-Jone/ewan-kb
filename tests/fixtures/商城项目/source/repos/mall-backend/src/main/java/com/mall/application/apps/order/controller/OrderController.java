package com.mall.application.apps.order.controller;

import com.mall.application.apps.order.OrderApi;
import com.mall.application.apps.order.service.OrderService;
import com.mall.application.apps.order.dto.OrderDTO;
import com.mall.application.apps.order.entity.OrderEntity;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

/**
 * 订单管理控制器
 * 提供订单创建、详情查询、取消等接口
 */
@RestController
@RequestMapping(OrderApi.BASE)
public class OrderController {

    @Autowired
    private OrderService orderService;

    /**
     * 创建订单
     */
    @PostMapping(OrderApi.CREATE)
    public OrderDTO createOrder(@RequestBody OrderEntity orderEntity) {
        return orderService.createOrder(orderEntity);
    }

    /**
     * 获取订单详情
     */
    @GetMapping("/{orderId}")
    public OrderDTO getOrderDetail(@PathVariable String orderId) {
        return orderService.getOrderDetail(orderId);
    }

    /**
     * 取消订单
     */
    @PutMapping(OrderApi.CANCEL)
    public OrderDTO cancelOrder(@PathVariable String orderId) {
        return orderService.cancelOrder(orderId);
    }
}