# 华为云 MaaS 能否通过 Endpoint 使用内网调用？

## 结论：官方目前不原生支持

经过查阅华为云官方文档，**MaaS（模型即服务）目前不提供原生的 VPC Endpoint（VPCEP）内网接入**，具体依据如下：

1. **MaaS 所有 API 均为公网地址**，格式为：
   ```
   https://api-{region}.modelarts-maas.com/v1/infers/{service-id}/v1/chat/completions
   ```
   官方文档中无任何内网域名或私网访问说明。

2. **华为云 VPCEP 支持的服务列表中没有 MaaS/ModelArts**。VPCEP 目前支持的服务主要是 OBS、DNS、SWR、API Gateway 等基础服务，AI 推理类服务尚未纳入。

---

## 可行的替代方案

如果客户有内网访问的强需求（合规、安全隔离等），有以下几种做法：

### 方案一：VPC 内 ECS 做代理（推荐，最简单）

```
客户内网 IDC
    → 专线/VPN → 华为云 VPC
                    → ECS 代理服务（Nginx/HAProxy）
                        → MaaS 公网 API（出口走 NAT 网关）
```

- 线下业务系统只需访问 VPC 内 ECS 的**内网 IP**，ECS 通过 NAT 网关转发请求至 MaaS
- 对业务系统来说完全是内网调用，API Key 等敏感信息也集中在代理层管理
- **前提**：需要有云专线（Direct Connect）或 VPN 打通线下到华为云 VPC

### 方案二：业务系统直接部署在华为云 VPC 内

如果业务系统本身就跑在华为云同区域的 ECS/CCE 上，调用 MaaS API 时**流量会优先走华为云内部骨干网络**，不走公网，延迟更低，但此方案只适合"已上云"的场景。

### 方案三：联系华为云商务争取企业级方案

对于有强合规要求（如金融、政务）的大客户，可以通过**工单或客户经理**咨询华为云是否支持 MaaS 私有化部署或定制 VPCEP 接入，这类需求通常走商务定制流程。

---

## 总结建议

| 场景 | 推荐方案 |
|------|---------|
| 业务已部署在华为云同区域 | 直接调用公网 API，流量走内部骨干网 |
| 线下 IDC，安全要求一般 | VPN + ECS 代理 |
| 线下 IDC，安全/合规要求高 | 专线 + ECS 代理，或联系华为云商务定制 |
| 强烈要求原生 VPC Endpoint | 目前不支持 |

---

## 参考文档

- [什么是 MaaS 模型即服务 - 华为云国际站](https://support.huaweicloud.com/intl/en-us/productdesc-maas/productdesc_maas_0002.html)
- [调用 MaaS 部署的模型服务 - 华为云国际站](https://support.huaweicloud.com/intl/en-us/inference-maas/maas-modelarts-0011.html)
- [什么是 VPC 终端节点 - 华为云国际站](https://support.huaweicloud.com/intl/en-us/productdesc-vpcep/en-us_topic_0131645194.html)
- [终端节点服务列表 - 华为云国际站 VPCEP](https://support.huaweicloud.com/intl/en-us/productdesc-vpcep/vpcep_01_0013.html)
- [通过 VPN 实现云上云下网络互通 - 华为云国际站](https://support.huaweicloud.com/intl/en-us/bestpractice-vpn/vpn_best_00031.html)
