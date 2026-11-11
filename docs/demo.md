# Local demo / 本地演示

The [README](../README.md#try-the-local-demo) contains the setup commands. Run them from the project directory, then open `http://127.0.0.1:8765`. The demo reuses the maintained browser fixture in `tests/e2e_server.py`; it is not a separate frontend or production service.

[中文 README](../README.zh-CN.md#本地-demo)提供启动命令。在项目目录执行后访问本机 `8765` 端口。演示复用正式维护的浏览器测试环境，不额外维护另一套前端。

## What to try / 可以体验什么

1. **Dashboard:** view sample usage and an intentionally imperfect answer. Success rate measures completed calls, so it can be 100% while a comparison fails.
2. **Comparison / 对比检测:** open the JSON baseline; compare the complete answer with the sample containing an incorrect sum. Click a cell to inspect prompt, expected answer, output, and differences. Use **More history / 查看更多历史** to browse older batches.
3. **Pelican / 鹈鹕检测:** open a thumbnail to run its self-contained HTML in the isolated preview; switch to raw HTML or prompt tabs.
4. Switch language, colors, theme, and viewport size; try manual and automatic refresh. These actions do not invoke a model.

Dashboard 展示模拟用量和一条刻意设置的错误答案。调用成功率与答案正确率相互独立，因此可能出现“调用全部成功，但答案未通过”的情况。对比页可检查标准答案与实际答案的差异，鹈鹕页可查看交互式 HTML，所有页面均可切换语言与主题。

## Boundaries / 演示边界

- `North API`, `West API`, and `fixture-*` are fictional. Outputs and token counts are fixtures, not real measurements. Elapsed time reflects local fixture execution.
- All model and catalogue calls use the local gateway substitute. Account-source discovery and credential resolution explicitly fail without network access.
- The fixed login token `browser-fixture-token-not-a-secret` is intentionally public. The server binds only to loopback and must not be exposed as a shared public demo. Use the normal [Docker deployment](deployment.md#docker) and its generated token for a real installation.
- Data lives in a temporary browser-validation directory and is removed on graceful shutdown. Restarting seeds a new dataset. It never reads the production data volume.
- ModelTrace's challenges and method can be inspected, but synthetic answers do not validate real-model attribution. Full source integration and actual model compatibility require separate deployment tests.

演示中的账号、模型、输出和 Token 数量均为虚构；耗时仅反映本地替身执行。所有模型请求均走本地模拟，来源导入明确禁用。固定令牌是公开测试数据，服务仅绑定本机，不应作为公开共享服务。正式部署使用 Docker 与随机生成的独立令牌。演示数据独立保存，正常关闭后清理，重启重新生成；不读取生产数据，也不能用于验证模型身份或真实上游兼容性。

## Screenshots / 界面截图

The four PNGs in [`resources/screenshots/`](../resources/screenshots/) show Dashboard, comparison history, Pelican history, and expanded preview using this demo's synthetic data. Use the same local demo when preparing new public screenshots; keep login, account configuration, source connections, and proxy fields out of the frame.

四张截图展示模拟数据下的 Dashboard、对比历史、鹈鹕历史及放大预览。制作新的公开截图时也应使用本地 Demo，并避开登录页、账号配置、来源连接和代理字段。
