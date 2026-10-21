# 模型成本快照与每日核算

日期：2026-10-21。状态：New API 逐任务查账已在本地实现；实施结果和剩余范围见 [model-cost-accounting.notes.md](model-cost-accounting.notes.md)。本文保留原设计目标，不能代替实际代码说明。

## 目标与核算口径

- 对经 New API 发出的任务，生成成功后优先读取该生成令牌的**逐笔消费/退款日志**，按 New API 任务 ID 汇总净额度，并保存日志里当时的表达式、用量和倍率快照。后续调价不重算历史任务。
- 对不经 New API 的渠道，才使用本地手工配置的每秒或每次单价，并在提交时冻结。排队期间调价的任务按实际提交时的规则。
- “每日用量”向主管理员展示按用户、按上海日期汇总的**成功生成成本**，保留次数供核对。页面、JSON 和 XLSX 使用同一汇总结果。
- 用户已明确选择“只统计成功生成”。上游明确返回生成成功即为成功；即使本地下载随后失败，也已经成功生成。上游状态未确认成功、仅提交成功或最终生成失败的任务不计成本。若上游对失败任务仍收费，本报表会低于上游实际账单。
- 示例：在分组倍率为 1 且 New API 实际结算与单价一致时，10 秒任务在 0.12/秒时提交，成功后记 1.20；同一天调到 0.08/秒后另一条 10 秒任务成功，记 0.80；当天合计 2.00，不用“2 次 × 当前价格”重算。
- 报表的“成本”定义为本应用在 New API 账户上的成功任务结算金额。若 New API 的对客定价含加价、折扣或与真正供应商账单不同，该数字也不同于供应商采购成本。

## 已确认的代码边界

| 位置 | 现状与约束 |
| --- | --- |
| `app/models/tables.py` 的 `Job`、`ProviderKey` | 任务已有 `model`、`seconds`、`resolution`、`provider_key_id` 和时间字段；没有 ORM 成本字段。 |
| `migrations/versions/0023_model_quota_costs.py` | 曾给数据库增加整数 `quota_cost` 字段，但当前 ORM 和服务不使用它；它属于用户额度概念，不作为货币成本复用。最新迁移是 `0026_job_generation_specs`。 |
| `app/services/worker_submitter.py:submit_queued_job` | 上游返回任务 ID 后才提交用户额度扣减，此处可冻结该次实际调用的价格。 |
| `app/services/sora_api.py:create_video` 与 New API `middleware/request-id.go` | 非 `wuyin_omni` 渠道把本地 `Job.request_id` 作为 `Idempotency-Key` 和 `X-Request-ID` 发出；New API 另生成 `X-Oneapi-Request-Id` 响应头，当前本地适配器没有取回该响应头。New API 创建响应里的任务 ID 已保存到 `Job.remote_task_id`。 |
| `app/services/worker_poller.py:poll_remote`、`worker_downloader.py:download_remote_job`、`worker_recovery.py` | 存在上游确认完成、回退下载成功、恢复已有文件等多条成功路径；须共用一次性记账函数。 |
| `app/services/job_regeneration.py` | 重新生成会建立新 `Job`；新任务应重新取届时价格，不能复制原任务单价。 |
| `app/api/admin/routes.py:_usage_month_data` | 现按个人/套餐额度流水的笔数减退款笔数统计每日次数，还有人工显示数量覆盖；成本不能由次数或覆盖值推导。 |
| `app/api/admin/routes.py:_delete_job` | 管理员能删除任务并把额度流水的 `job_id` 置空；成本账必须独立保存，任务删除后仍可核算。 |
| `app/api/admin/routes.py:delete_user_form` | 删除用户时会先删任务；现有每日用量仅查询启用用户。成本账不得依赖用户外键级联或当前用户状态，否则历史金额会消失。 |
| `integrations/new-api/COUNT-BILLING-UPGRADE.md` | Omni/Flow 的现有网关定价按次，故价格单位不能强制只有秒。该网关计费配置保持独立。 |
| `runtime/new-api-readonly-source/full/` | 当前匹配版本包含 `/api/pricing`、`/api/status`、`/api/log/token`、`/api/task/self`；任务计费日志的 `other` 含任务 ID、表达式、用量和倍率。目标实例已只读验证前三个接口及视频查询；`/api/task/self` 用普通生成 Key 返回 401。 |

## New API 自动取价与结算

- `GET /api/pricing` 给出模型价格、分组倍率；当前项目匹配版本还包含视频任务的 `billing_expr`、计费单位元数据和插件变体。它是**当前价目表**，不是历史账单。价格可能按秒、按次、分辨率或生成方式变化，不能只读取一个 `model_price` 字段就认定最终金额。[官方价格接口](https://github.com/QuantumNous/new-api-docs/blob/main/docs/api/fei-public-info.md#价格与套餐信息)、[表达式语义](https://github.com/QuantumNous/new-api/blob/main/pkg/billingexpr/expr.md)
- `GET /api/status` 返回 `quota_per_unit`。目标实例的 `GET /api/log/token` 用普通生成 Key 可读此令牌的近期日志；匹配版本只返回最近最多 1000 条。消费/退款日志的 `other.task_id` 可与视频任务 ID 配对，`other.expr_b64`、`usage_facts`、`group_ratio` 保存了当笔计费依据。成功后对这个任务的消费额度求和、退款额度扣除，再除以当时的 `quota_per_unit`，得到 New API 的美元计价金额。站点若以其他币种展示，须另有明确换算规则。[官方状态接口](https://github.com/QuantumNous/new-api-docs/blob/main/docs/api/fei-system-initialization.md#获取运行状态摘要)、[官方任务与日志说明](https://github.com/QuantumNous/new-api-docs-v1/blob/main/content/docs/en/guide/feature-guide/user/log.mdx)
- 用现有生成 Key 调用 `GET /v1/videos/{id}` 确认 `completed`，再抓取相关日志；不需要为了这条主路径取得仪表盘凭据。由于令牌日志有条数上限，生产环境须及时抓取并本地持久化每条源日志。若量大到可能漏出窗口，或需补很久以前的账，再配置只读仪表盘凭据访问可分页的 `/api/log/self`/`/api/task/self`；普通生成 Key 对目标实例的 `/api/task/self` 已实测返回 401。
- 本应用创建接口立即返回 `job_id`，此时任务通常仍在队列，`remote_task_id` 可能为空；Worker 真正提交成功后把 New API 响应的 `id`/`task_id` 保存为 `remote_task_id`，任务详情接口和页面可随后读取。计费主键是这个远端任务 ID ↔ 日志 `other.task_id`。本地 UUID `Job.request_id`、New API 自己的请求 ID 与远端任务 ID 是不同概念，不能把它们直接当同一个值连接。
- `/api/pricing` 仅供当前价格展示、任务提交前提示和定期配置检查，不能用它重算过去的金额。New API 插件可能先预扣、成功后补扣或退款，成本必须以已保存的逐笔净日志为准。缺少日志、任务映射或换算值时状态为“待核对”并重试、告警；不能用当前新价格推算旧任务，也不能悄悄写 0。

### 2026-10-21 只读实测

- 测试站 `api.365rose.com` 返回 New API `v1.0.0-rc.44`、`quota_per_unit=500000`、美元展示；公开价目表含 Grok 按分辨率/秒数和 Omni/Flow 按次的 `billing_expr`。
- 用户提供的请求 ID 对应 `omni-fast-no-water`，日志净消费 `1,725,000` 额度，日志快照为 `requests=1`、`group_ratio=1`、`tier("request", u("requests") * 3.45)`；金额 `1,725,000 / 500,000 = 3.45 USD`，与该快照计算一致。用日志中的任务 ID 查询 `/v1/videos/{id}` 返回 `completed`。仅发出只读 GET，没有触发生成；测试 Key 未写入本文或仓库。
- 同一令牌近期的一条 `grok-imagine-video-1.5-preview` 成功任务，日志快照为 `720p`、`15` 秒、`0.26 USD/秒`、分组倍率 `1`；表达式金额 `15 × 0.26 = 3.90 USD`，净消费 `1,950,000 / 500,000 = 3.90 USD`。视频查询返回 `completed`。因此目标实例上的按次与按秒插件各有一条真实只读核对样本。

## 数据与价格规则

1. 新增 New API 只读核算器：按本地任务保存的 `api_base_url`、生成令牌、`remote_task_id` 查询视频状态与 `/api/log/token`；用 `other.task_id` 匹配该任务的所有计费日志，按日志 ID 去重，消费为正、退款为负。New API 的 `request_id` 只用于辅助排查，不能假设等于本地 `Job.request_id`；差额日志也可能只有任务 ID。`/api/status` 的换算值与每笔日志源数据一起留存。
2. 新迁移 `0027_model_cost_accounting` 在 `jobs` 留存 New API 任务 ID、提交时模型及参数、提交请求 ID 和核算状态；另建源日志表保存日志 ID、类型、额度、时间、任务 ID，以及 `expr_b64` 解码后的规则、用量事实、分组倍率和匹配档位。对未被上游接受的重试可重新取当前规则；接受状态不明时保留原幂等键，按最终任务 ID 与源日志核对，不能把后一次价格误配给旧请求。
3. 新增独立的 `job_cost_entries`：原始本地任务 ID、New API 任务 ID、可空的当前任务外键、原始用户 ID 与当时用户名快照、渠道/模型/清晰度快照、源日志集合、净额度、当时的 `quota_per_unit`、金额、币种、成功时间及记账时间。原始用户 ID 不设会级联删除账目的外键。每个成功任务用唯一业务键保证只形成一笔有效成本。任务或用户删除时仅清除可空外键，原始 ID、用户名和账目保留。若晚到差额日志改变净额或成功判断被纠正，用有审计记录的更正条目处理，不直接覆盖历史金额。
4. 仅对没有 New API 结算能力的直连渠道新增 `model_cost_rates` 本地回退价：渠道、实际模型 ID、清晰度或其他必要档位、`second`/`request`、单价、币种、版本和操作者；主管理员编辑且留审计。查价先精确匹配再通用规则。秒计价数量先采用上游明确认可的请求秒数 `Job.seconds`，按次计价为 1；本地 `ffprobe` 成片时长不能冒充计费时长。直连渠道缺价时在发出请求前失败并释放预占额度。
5. 所有金额使用 `Decimal`/数据库 `Numeric` 运算和存储，展示时才格式化。成功任务日志临时不可用时保留“待核对”，重试直到读到相关记录；轮询频率和吞吐量要保证日志被本地保存前不会挤出最近 1000 条窗口。旧任务如能匹配 New API 历史日志或任务最终额度，可按原始记录补账，否则标注“历史未计价”，不按当前价格回填。
6. New API 原始结算按其美元基准单独汇总；其他直连渠道若使用不同币种，分币种列示，不自动相加或换汇。币种与换算依据在每笔账上固定保存。

## 成功时机与日统计

- New API 任务通过 `/v1/videos/{id}` 确认 `completed` 后，用当笔日志中的历史计费事实和净额度写成本账；本地状态轮询遗漏但 New API 已成功时也可据任务 ID 补记。若只是 `remote_completed` 的回退猜测且 New API 未成功，不写账。直连渠道仍以其上游确认成功或已验证文件为成功依据。
- 本地下载失败不撤销已经确认的上游生成成功成本；管理员重试下载、Worker 恢复和状态重复轮询不重复写账。重新生成是新的任务，成功后按自己的快照另记一次。
- 日归属按**New API 视频完成时间**（直连渠道用上游成功时间；不可得时用首次确认成功时间）转换为 `Asia/Shanghai` 日期，抓账延迟不改变归属日。跨午夜任务按其原始日志结算，金额计入成功当天。报表直接 `SUM(job_cost_entries.amount)`，按账目中的原始用户 ID 和日期分组；包括已停用或已删除用户，删除用户显示保留的用户名快照。月/日总计从全部成本账计算，不能只合计当前启用用户；不读取当前价格、`DailyUsageOverride` 或用户额度余额。
- 主管理员的每日格子以金额为主、同一成本账的成功任务数为辅，月合计和每日总计也显示金额。点击可查看任务、模型、秒数/次数、当笔日志保存的计费规则、净额度和金额；简单的每秒/每次规则再显示单价。JSON 与 XLSX 增加相同成本字段及明细；现有额度次数另列，不与成功任务数混用。副管理员目前只能看显示次数、看不到真实调整值，因此成本及单价先只对主管理员开放，所有接口和导出都做同样权限限制。

## 交付顺序

1. **目标实例只读验证已完成两条**：`/api/pricing`、`/api/status`、`/api/log/token` 与 `/v1/videos/{id}` 对成功 Omni 按次任务得出 3.45 USD，对成功 Grok 按秒任务得出 3.90 USD。实施前再确认其他实际使用的插件是否会产生差额日志。
2. **贯通一条真实路径**：新增迁移和 `app/services/cost_accounting.py`，提交时持久化 New API 任务 ID；成功后读取并保存该令牌的所有匹配计费日志，按净额度一次性写账；用隔离数据库验证当天金额。先不改页面。
3. 扩展到所有提交、轮询、下载和恢复路径，覆盖按次模型、清晰度/生成方式价格、失败与重新生成。再加直连渠道的手工价格回退和主管理员编辑审计。New API 查账暂时失败要可重试、可告警；日志量接近最近 1000 条上限时须接入可分页的只读账号接口，不能丢失成功任务。
4. 扩展 `app/api/admin/routes.py` 的每日汇总、JSON、XLSX 和 `app/templates/admin/usage_monthly.html`；同步更新 `scripts/preview_usage.py` 与现有报表测试。成本计算只在服务端进行。
5. 先备份数据库并在测试库迁移；上线时核对 New API 日志读取权限、抓取频率和 `quota_per_unit`，给直连渠道录入必要价格，再启用记账路径。用一条无需真实付费的模拟上游任务检查端到端结果，之后按授权范围核对 New API 实际结算明细。

## 验收与恢复

- 两条同日 10 秒任务分别按 0.12/秒、0.08/秒成功，在 New API 倍率为 1 且其净日志额度对应 1.20、0.80 时，日合计必须是 2.00；改价后重新打开、导出报表数值不变。
- 排队时调价按实际提交时规则；提交后、成功前调价不改变已形成的日志快照。New API 分组倍率、结算舍入、秒计价与按次计价、Grok 不同清晰度、零价和小数精度均有定向测试；金额必须和 New API 净消费日志一致，后续补扣/退款日志通过更正条目反映。
- 请求未获得上游任务 ID、New API 最终失败、仅回退猜测但 New API 未成功均不计；New API 成功但本地下载失败仍计。查账接口短暂故障呈现“待核对”并最终补记，不能记为零。首次请求 ID 与任务 ID 能在源日志中对上，重复日志按日志 ID 去重；超时重试碰上调价时不把新价套到已接受的旧请求；重复轮询、恢复和重新下载不会重记；重新生成成功单独计一次。
- 上海时间跨日、历史未计价任务、删任务和删除/停用用户后保留成本、人工显示次数覆盖不影响成本；主管理员页面/JSON/XLSX 金额一致，副管理员三处均无成本与单价泄露。
- 运行相关单元与集成测试，重点包括 `tests/test_usage_roles.py`、`tests/test_usage_calendar.py`、`tests/test_batch_regeneration.py` 及新增成本账测试；测试需使用模拟上游，不产生真实生成费用。迁移在 PostgreSQL 测试库做升级与回退演练。
- 回退代码时保留 `job_cost_entries` 和快照字段，不删除已形成的账目；若价格录错，用审计明确的更正条目修正，不重写旧价或批量重算历史。实施记录写在同目录 `model-cost-accounting.notes.md`，说明偏离与验证结果。

## 实施前需再核对

- 当前 NAS 数据库的迁移头、活跃渠道与模型清单；每个实际使用的 New API 插件是否把提交预扣和完成差额写入可按任务 ID 匹配的日志、抓取窗口是否充足。若某模型按输出时长、阶梯价或其他维度计费，以其净结算日志为准，不能把“请求秒数 × 当前单价”当成实际扣费。
- 确认目标 New API 的 `quota_per_unit` 和展示币种配置；默认报表按 New API 美元基准显示，其他币种仅在明确汇率与时间口径后换算。
