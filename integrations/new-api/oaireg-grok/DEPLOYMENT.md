# Grok 价格配置记录

2026-09-29，用户已安装插件1.0.0，并启用26号“oaireg grok 专用插件”通道。
只开放 `grok-imagine-video` 和 `grok-imagine-video-1.5-preview`，未开放6s。

根据用户红字截图授权，后台美元每秒售价设置如下：

| 模型 | 480p | 720p | 1080p |
| --- | --- | --- | --- |
| grok-imagine-video | 0.10 | 0.15 | 不支持 |
| grok-imagine-video-1.5-preview | 0.20 | 0.26 | 0.30 |

仅更新 options 中 `billing_setting.billing_expr` 的上述两个模型，从常数公式改为分辨率条件 × 秒数公式。
插件覆盖公式为空；模式仍为tiered_expr，其他模型价格、分组倍率、通道、插件源码、镜像未改。

更新前备份：`/opt/1panel/apps/new-api/new-api/data/lumora-grok-prices-before-1790654389.json`。
数据库事务内检查旧表达式及插件源码哈希，更新后比对其他配置不变。
更新时26号通道无未完成任务。配置自动热加载，无重启、无付费调用。

验证：前端实际价格解析器正确识别2/3个分辨率档位、每秒单价，全部档位的1/6/15秒费用试算通过；在线 `/api/pricing` 返回新公式和按模型匹配的seconds/resolution元数据。

此记录替代README中“未安装、未修改价格”的初始交付状态；插件代码仍不内置售价。
未修改模型广场前端为“只显示最低价起”；现有前端仍按原生价格展示逻辑渲染区间/档位。未做浏览器截图验收。
