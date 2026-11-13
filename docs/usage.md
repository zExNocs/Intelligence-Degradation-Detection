# Usage and evaluation rules / 使用与判定规则

## Accounts and test groups

Use **Models / 模型管理** to add a direct API account or import selected sub2api accounts. Set protocol explicitly. The final request URL is base URL plus request path; a base ending in `/v1` normally pairs with `/responses`, `/messages`, or `/chat/completions`. The model path is independently configurable. Catalogue refresh never performs inference; a provider without catalogue support can still use manual model entry. Refresh errors retain the previous successful cache and expose a short reason. Extra headers accept a JSON string map; transport/authentication headers cannot be overridden. Blank secrets during editing retain saved values.

Opening a model field shows the entire cached catalogue, even after a model was selected or saved. Typing filters suggestions; selecting an option, closing the dropdown, or leaving the field ends that search. Manual identifiers remain editable and are not replaced by catalogue refresh. This behavior is shared by account defaults and all four check forms.

打开模型输入框会展示完整缓存列表，不会因已有默认模型而只显示该模型；输入文字时才筛选。选择后或关闭再打开列表可重新浏览全部选项，手动填写的模型标识也会保留。

Reasoning choices use a shared server policy for the selected protocol and known model. For `gpt-6.1-sol`, supported explicit values are `low`, `medium`, `high`, `xhigh`, and `max`; **Upstream default / 使用上游默认值** omits the parameter. These values follow the [official model specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol). Unknown models retain protocol-wide choices, so their upstream may impose additional restrictions. Incompatible saved values are displayed with an error and must be explicitly corrected; historical evidence and existing recipes are not silently rewritten. Known unsupported values are rejected before making a model request.

`gpt-6.1-sol` 不支持 `none` 或 `minimal`。已有账号或测试组若使用了不兼容值，请在对应编辑表单中改为支持的值或“使用上游默认值”；账号默认值的修改不会追溯修改已有测试组。历史结果保持原样。

Responses may use JSON or SSE streaming. Recognizable SSE frames are processed incrementally even if an intermediary omits or mislabels `Content-Type`. This does not switch the configured API protocol. Invalid data and streams without a terminal completion remain failures; partial output is preserved when available.

响应支持 JSON 和 SSE 流式格式；上游缺少或错误标注 `Content-Type` 时，可识别的 SSE 仍按流逐步处理，不会切换所选 API 协议。无效数据与缺少完成标志的流仍明确报错，并尽可能保留部分输出。

**Probe connection / 检测连通性** performs one real model call using account defaults and normal quotas. It runs in the background without opening a dialog. The account card shows queued/running status, then duration or a failure reason; **View probe / 查看探测结果** opens full details on request. An active probe continues after leaving the page. While the Models page is visible, active probes update every second even if general auto-refresh is off. Duplicate probes are blocked until the current one finishes.

连通性检测在后台运行，不自动弹出详情；成功后直接在账号卡片显示耗时，失败显示原因，按需点击查看详情。离开页面不会中止探测；返回模型管理可继续查看状态。

Use the trash icon on an account card to delete its **local** account configuration after confirmation. Its checks are removed, shared groups retain other accounts, and empty groups are removed. Historical results and their immutable snapshots remain subject to the normal retention policy. Pending/running checks or probes must be cancelled or allowed to finish first. Imported account deletion does not delete or modify the original sub2api account or proxy; automatic sync will not re-import it.

删除账号需确认；这会移除本地账号及其检测配置、清理空测试组，保留共享组中的其他账号与历史记录。已有排队或执行中的检测须先取消或等待完成。删除导入账号不会改动 sub2api 原账号和代理，也不会被定时同步自动重新导入。

Account cards and test-group cards on all four check pages have a drag handle. Drag with a mouse or touch, or focus the handle and press Space, arrow keys, then Space to drop; Escape cancels. Order is saved on the server and survives refresh/restart across browsers. Each detector keeps its own group order. Reordering does not change prompts, schedules, model selection, or history, and makes no model calls. If another user changes the collection during a drag, refresh the list and retry.

模型管理卡片和四类检测的测试组卡片均可通过拖动手柄排序，也支持键盘操作。排序保存到服务端，各检测类型独立排列；刷新或重启后仍保留，不触发模型调用。

For sub2api, configure the service root and administrator key in Settings, load candidates, and select imports. Imported routing and proxy credentials belong to sub2api; model preferences and concurrency belong to this application. Source failures are visible on account cards. Sync does not add newly discovered accounts automatically.

**Create test group / 新建测试组** selects one or more accounts. Each has an independent model and reasoning choice. The initial choice uses account defaults; later successful group saves update that account's remembered choice. Existing groups never change implicitly. A group shares a prompt, rule, and schedule; history columns align execution batches, rows identify account/model/reasoning. Responsive page size changes only visible columns. **More history / 查看更多历史** pages older batches.

Every test costs tokens. **Run now / 立即检测** or **Run group / 执行整组** creates work. **Refresh / 刷新** only reads results. Auto-refresh defaults to 15 seconds, supports 5/10/15/30 seconds and off, pauses in hidden tabs, and refreshes on return. Preferences are browser-local. Group execution reports skipped busy/unavailable targets through the API; no duplicate inference is sent. **Cancel run / 取消检测** stops pending/active requests, preserves the cancelled evidence, and excludes it from all Dashboard metrics and findings.

## Four evaluation modes

**Pelican / 鹈鹕检测:** by default request a responsive, self-contained illustration of a pelican cycling. Change the prompt per group. Click the thumbnail for an enlarged HTML/CSS/JS preview, raw HTML, prompt, metadata, and human review controls. All external assets and network calls are blocked. Use inline SVG/canvas/CSS instead of external libraries or images.

**Comparison / 对比检测:** select JSON structure or regex. Results show raw output, expected answer/pattern, original prompt, and structural differences. A normal API response with malformed JSON is a format failure; it is distinct from an interrupted or failed API call.

JSON compares objects without key order and arrays by position. Scalar leaves count as items; empty containers count as one item. Missing/extra branches cost their leaf counts. A container type mismatch costs the larger branch leaf count. Correctness is matched items divided by all comparison items. Numbers compare numerically; booleans, strings, and numbers do not coerce. Duplicate object keys and non-finite numbers are rejected. One complete outer JSON Markdown fence may be removed for parsing; the original remains stored. Explanatory prose is not searched for an embedded answer.

Regex uses `search` over the complete output. Add anchors when full-string behavior is required. Patterns are validated on save; evaluation has a 50 ms time limit. A mismatch is 0%, a match 100%; invalid patterns or timeouts are separate evaluation errors.

| State | Display |
| --- | --- |
| 100% correctness | Green |
| At least 50%, less than 100% | Yellow |
| Less than 50% | Red |
| Queued/running | Gray with status |
| No execution | White/empty cell |
| Cancelled, interrupted, or invocation failure | Explicit label/icon, no invented correctness |

**ModelTrace:** select one, two, or all three fixed Chinese challenges: 直觉选择·294 项, 逐项选择·311 项, 快速取值·329 项. Prompts are visible in the page's information dialog and are not editable. Parallel mode is optional; each child still consumes account/global quota. Each challenge runs exactly once. Inference uses the calibration for the number of accepted outputs, up to three. Missing or unusable selected output makes the result incomplete; it cannot trigger identity deviation. With a valid expected candidate or family and a complete result, disagreement is labelled **suspected mismatch / 疑似身份偏离**. Candidate probability is relative to the loaded closed set, not a universal identity probability. See [third-party documentation](third-party.md).

**Other checks / 其他检测:** retain arbitrary prompt and output with a short preview; open details for the full evidence and an optional manual pass/fail note. No automatic quality score is invented.

## Defaults, time, and interpretation

| Setting | Default |
| --- | --- |
| Schedule | `*/30 * * * *` |
| Timezone | `TZ` on first initialization, otherwise UTC |
| Retention | 30 days and 100 results per check; either limit removes terminal records |
| Checks per account | 5 across all four detectors |
| Account / global concurrent calls | 1 / 4 |
| Source sync | Every 60 seconds |
| Invocation timeout / output budget | 600 seconds / 16,384 output tokens |

A model/reasoning selection for one account in one group counts as one check. Multiple ModelTrace challenges still count as one. Probes and historical runs do not count toward that configuration limit. Lowering a limit does not delete existing configurations. Retention runs every ten minutes and when settings are saved.

Cron has five Unix fields; weekday 0 or 7 means Sunday. Friendly presets and raw source can be switched without rewriting unsupported custom expressions. Preview the next five execution times. Manual runs leave the periodic schedule unchanged. Changing default prompts affects new groups only. Changing timezone recomputes future schedules without rewriting historical UTC timestamps.

Dashboard aggregates the last 24 hours of terminal, non-cancelled executions, including probes. Invocation success is distinct from answer correctness. Unknown token usage is counted separately rather than treated as a known zero. Findings use the latest terminal result per check and distinguish rule failure, suspected identity mismatch, human failure, and operational failure. These findings identify evidence to inspect; they do not by themselves prove general intelligence degradation.
