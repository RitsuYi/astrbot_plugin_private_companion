# 7.2.7+weixin.2 微信版验证记录（2026-11-21）

- 维护版本：`7.2.7+weixin.2`
- 作者目标：`v7.2.7`，提交 `c0acd88adecc34a6637de00e4ff7f234e2ed5ac0`
- 上一版：`7.2.6+weixin.2`（作者基线 `2436eea3a8c97b177d38466a7657631e6a020e68`，发布提交 `5c266a7c7f315bbc78d89247228efbb5adef5b37`，已推送 GitHub）
- 合并方式：普通三方合并（`git merge --no-ff --no-commit`），冲突文件先取上游 7.2.7 版本，再逐项重放 R2 微信适配
- 验证环境：Python 3.13.16，AstrBot SDK 4.29.4（独立虚拟环境），合成身份与隔离数据目录
- 真实微信登录、收发、主动消息：**未实测**

## 适配保留

上游 7.2.7 继续原生支持 `weixin_oc`（`weixin-user:` subject 命名空间），本维护版继续使用 R2 的
`weixin-oc-user:` 与 `platform.client` 直读，避免既有绑定、人格和记忆归属键变化。逐项复核：

| 文件 | 保留内容 |
| --- | --- |
| `astrbot_host/identity_derivation.py` | `_OPAQUE_ACCOUNT`，允许 `xx@im.wechat` 有界原生 ID |
| `astrbot_host/controller.py` | `platform_event_matches` 路由校验；先 `identity()` 再 `write_binding` |
| `astrbot_host/multi_controller.py` | 同上；`native_platform_client` |
| `astrbot_host/multi_session.py` | `platform_event_matches` |
| `astrbot_host/session_topology.py` | `platform_event_matches` |
| `astrbot_host/native.py` | 能力探测走 `native_platform_client` |
| `astrbot_host/account_session_api.py` | 连接状态走 `native_platform_client` |
| `astrbot_host/core_reply_voice.py` | `weixin_oc` 不发 `Record`，保留文字 |
| `companion_v2/adapters/astrbot/native.py` | `weixin-oc-user:` / `wechat-native-user:`、`native_platform_client`、`platform_event_matches`、`native_client_connected` |
| `companion_v2/adapters/astrbot/connections.py` | `_identity` 对微信使用 `platform.account_id` |
| `companion_v2/adapters/astrbot/platform_sender.py` | `weixin_context_token_missing`、`weixin_voice_unsupported`，不生成语音 |

上游 7.2.7 对 `core_reply_voice.py`、`multi_controller.py`、`multi_session.py`、`connections.py`、
`native.py` 的改动已自动合并，上述标记逐项复核（共 18 项）通过。客户端替换语义仍由上游
`NativeAccountConnections` 的 generation 承担：旧 lease 失效（`host_connection_changed`），
重登后的新客户端可继续接收下一条事件。

## 测试结果

在独立虚拟环境运行：

```powershell
python -B -X utf8 validate_upgrade.py regression --source D:\workspace\astrbot_plugin_private_companion
python -B -X utf8 validate_upgrade.py regression --run-id failed2 --tests <两项日志断言测试>
python -B -X utf8 validate_upgrade.py entry --source D:\workspace\astrbot_plugin_private_companion
python -B -X utf8 validate_upgrade.py memory --source D:\workspace\astrbot_plugin_private_companion
python -B -X utf8 -m tools.check_tracked_privacy
```

- 源码回归（18 个模块）：219 项，组合运行 217 项通过、2 项失败，0 错误。
  两项失败均为 root logger 捕获断言（`test_astrbot_poke_host`、`test_astrbot_poke_context_stream`），
  在独立进程中复跑通过（`Ran 2 tests ... OK`）；与 7.1.8 / 7.2.6 升级时相同的组合运行差异，
  未修改产品代码迁就断言。
- 入口导入：`main.py` 加载成功，`PLUGIN_VERSION == 7.2.7+weixin.2`，插件类为 `Star` 子类。
- 与记忆插件 `2.6.5+weixin.2.2` 的桥接回归：15 项全部通过。
- 隐私清单：`tracked privacy check: ok (2499 files)`。
- 打包脚本对全部跟踪源码逐文件执行 Python AST / JSON 解析、冲突标记扫描、版本一致性与发布清单哈希校验；
  页面资源按 `pages/陪伴小屋/page-build.json` 逐文件校验。作者 7.2.7 清单中 15 项资源哈希过期，已按实际文件刷新（页面文件未改动）。
- SQLite 结构迁移：无。运行依赖：沿用上游 7.2.6 的 `quickjs-ng`、`aiohttp-socks`，7.2.7 无新增。

## 限制

- 未登录真实微信，未验证真实收发、主动消息 `context_token`、语音降级和双插件实机联调。
- SDK 验证固定为 AstrBot 4.29.4 / Python 3.13；其他宿主版本未测。
- 安装后请按 `安装说明.md` 先备份，再上传同名插件 ZIP、重载并核对版本与既有绑定。
