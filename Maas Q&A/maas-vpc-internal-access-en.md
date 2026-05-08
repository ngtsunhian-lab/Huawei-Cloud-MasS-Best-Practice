# Can Huawei Cloud MaaS Be Called Over a Private Network via Endpoint?

## Conclusion: Not Natively Supported at This Time

Based on a review of official Huawei Cloud documentation, **MaaS (Model as a Service) does not currently offer native VPC Endpoint (VPCEP) private network access**. Key findings:

1. **All MaaS APIs are public-network endpoints**, following this format:
   ```
   https://api-{region}.modelarts-maas.com/v1/infers/{service-id}/v1/chat/completions
   ```
   No official documentation mentions internal domain names or private network access.

2. **MaaS/ModelArts is not listed among the services supported by Huawei Cloud VPCEP.** The VPCEP service catalog currently covers infrastructure services such as OBS, DNS, SWR, and API Gateway — AI inference services are not yet included.

---

## Viable Alternatives

If a customer has a strong requirement for private network access (compliance, network isolation, etc.), the following approaches are available:

### Option 1: ECS Proxy Inside VPC (Recommended — Simplest)

```
On-premises IDC
    → Direct Connect / VPN → Huawei Cloud VPC
                                → ECS Proxy (Nginx / HAProxy)
                                    → MaaS Public API (via NAT Gateway)
```

- The on-premises application only needs to reach the ECS proxy's **private IP inside the VPC**; the ECS forwards requests to MaaS via a NAT Gateway.
- From the application's perspective, every call stays on the internal network. API Keys and other sensitive credentials are centrally managed at the proxy layer.
- **Prerequisite:** A Direct Connect link or VPN tunnel must be established between the on-premises network and the Huawei Cloud VPC.

### Option 2: Deploy the Application Directly in a Huawei Cloud VPC

If the business system is already running on ECS/CCE in the same Huawei Cloud region, traffic to MaaS **travels over Huawei Cloud's internal backbone network** rather than the public internet, resulting in lower latency. This option is only applicable for workloads that are already cloud-hosted.

### Option 3: Contact Huawei Cloud Sales for Enterprise-Grade Solutions

For large customers with strict compliance requirements (finance, government, etc.), open a support ticket or contact your account manager to inquire about MaaS private deployment or custom VPCEP integration. These arrangements are typically handled through the commercial customization process.

---

## Summary

| Scenario | Recommended Approach |
|----------|----------------------|
| Application already deployed in the same Huawei Cloud region | Call the public API directly — traffic stays on the internal backbone |
| On-premises IDC, general security requirements | VPN + ECS proxy |
| On-premises IDC, high security / compliance requirements | Direct Connect + ECS proxy, or contact Huawei Cloud sales for customization |
| Strict requirement for native VPC Endpoint | Not currently supported |

---

## References

- [What Is MaaS? - Huawei Cloud International](https://support.huaweicloud.com/intl/en-us/productdesc-maas/productdesc_maas_0002.html)
- [Calling a Model Service Deployed in MaaS - Huawei Cloud International](https://support.huaweicloud.com/intl/en-us/inference-maas/maas-modelarts-0011.html)
- [What Is VPC Endpoint? - Huawei Cloud International](https://support.huaweicloud.com/intl/en-us/productdesc-vpcep/en-us_topic_0131645194.html)
- [VPC Endpoint Service List - Huawei Cloud International VPCEP](https://support.huaweicloud.com/intl/en-us/productdesc-vpcep/vpcep_01_0013.html)
- [Connecting an On-Premises Data Center to VPC via VPN - Huawei Cloud International](https://support.huaweicloud.com/intl/en-us/bestpractice-vpn/vpn_best_00031.html)
