# 微信适配 R2：测试记录

## R2当前结果

日期：2026-11-08。版本：`7.1.6+weixin.2`。宿主仍为AstrBot4.29.4和Python3.12。
插件上游仍为 `05a7689aad72c0de5c84c13b934d32344f21c091`（7.1.6）。

### 首次绑定缺陷复现

使用真实 `WeixinOCAdapter`／事件类，平台实例名为“爱弥斯”，发送者为合成 `@im.wechat` ID，
配置中预存通配目标。新增2项绑定用例在修复前均返回 `host_identity_invalid`，准确复现问题。
原因是 `derived_identity()` 拒绝ASCII ID中的@及点号，不是中文平台实例本身不合法。
R1漏测了绑定命令落盘、管理员确认、精确目标生成这段链路；R2已补上。

### 回归结果

14个模块共314项测试，耗时197.105秒：**312项通过、1项跳过、1项上游错误**。
错误已在未修改的原版独立复现，详情见下。不声称完整套件全部通过。

- `tests.test_weixin_oc_compat`：19项全部通过。覆盖真实事件类型、独立用户命名空间、
  登录和客户端一致性、普通捕获与发送、API失败、缺少会话凭证、语音回退，以及本次新增的：
  首次绑定、中文实例名、旧通配模板、管理员确认精确目标、重载后完整回复和记忆写入、
  无效身份不落盘、其它用户不能覆盖候选。
- `tests.test_identity_derivation`：24项全部通过。含3项新增的微信ID、哈希存储键和非法ID拒绝测试。
- `tests.test_binding_store`、`tests.test_multi_binding_sync`、`tests.test_session_topology`、
  `tests.test_astrbot_multi_host`、`tests.test_astrbot_native_projection`、`tests.test_core_reply_voice`、
  `tests.test_core_reply_pipeline`、`tests.test_proactive_permission`、`tests.test_native_release_version_guard`、
  `tests.test_release_secret_detection`、`tests.test_configuration_migration`：通过；
  其中1个可选视频夹具测试因未安装OpenCV跳过。
- `tests.test_staging_status_topology`：5项通过，1项原版错误。
- 使用此前交付的记忆插件 `2.6.5+weixin.1` 运行其微信专项：10项通过，
  包含R2陪伴插件真实外部记忆注册表调用。无需更换记忆插件。

### 已在原版复现的额外错误

`tests.test_staging_status_topology.StagingStatusTopologyTests.test_pinned_mapping_survives_stop_and_reload_and_ignores_stale_candidates`
在单目标 `initialize_profile()` 阶段返回 `staging_load_failed`。
未修改的同一上游提交中，单独运行这1项同样错误，耗时2.308秒。
本次微信多目标绑定、确认、重载、启动和消息处理用例通过；没有为隐藏错误而跳改原测试。

下面R1历史记录中的6项原有失败此次未宣称修复。
测试使用合成身份、独立数据库和模拟HTTP，没有登录或向真实微信发送消息。
构建使用原项目打包和独立解压核验脚本，检查发布结构、逐文件哈希、版本与运行合同。
用户侧验收见 `WEIXIN_OC_COMPAT.md`，技术根因见 `WEIXIN_OC_R2_FIX.md`。

---

## R1历史记录（保留供追溯，不是R2完整测试通过声明）

日期：2026-11-08。版本：`7.1.6+weixin.1`。
上游插件：`05a7689aad72c0de5c84c13b934d32344f21c091`（7.1.6）。
宿主：AstrBot 4.29.4（`2b3aee5343b10e8148fb5935206c165ae89b4b9a`），Python 3.12。

## 通过的针对性测试

以下8个模块合计 **172项测试通过**（最终代码，25.917秒）：

- `tests.test_weixin_oc_compat`：15项。真实微信适配器／事件、账号绑定字段、独立用户命名空间、
  适配器和客户端来源校验、登录状态、账号发现、普通回复捕获、模拟私聊发送及记忆写入、
  API失败回执、缺失会话凭证、核心与后台语音降级。
- `tests.test_core_reply_voice`
- `tests.test_core_reply_pipeline`
- `tests.test_proactive_permission`
- `tests.test_astrbot_native_projection`
- `tests.test_native_release_version_guard`
- `tests.test_release_secret_detection`
- `tests.test_configuration_migration`

SDK测试预先导入 `tests.astrbot_data_root`，所有用户、凭证、消息和数据库均为合成隔离资料。
微信HTTP边界被模拟，没有联网向微信发送消息。没有使用真实模型生成答案。

额外运行QQ官方平台模块：17项中16项通过；1项失败已在上游原版复现，见下一节。
`git diff --check`、页面生成物同步检查均通过。
使用项目原有 `tools/build_v2_release.py` 构建完整插件包，并用
`tools/verify_v2_release.py` 对独立解压目录核验结构、文件哈希和运行合同。

## 已复现的上游失败

在未修改的上述上游提交中，单独运行 `tests.test_binding_command` 和
`tests.test_astrbot_qq_official.OfficialMultiHostTests.test_official_group_event_runs_through_shared_host_and_astrbot_sender`：
26项测试，6项失败、0项错误；与适配分支上观察到的失败一致。

- 5项旧绑定夹具断言：夹具缺少平台类型，原版会把账号投影为平台实例，而断言期待QQ号。
- 1项纯群聊宿主初始化断言：原版返回 `setup_binding_missing`。

没有为掩盖失败而跳改原测试或放宽权限；本包不声称完整上游测试套件全部通过。

## 尚未验证

- 真实微信扫码与重新登录、手机收到消息、跨天凭证有效性、服务器限流。
- 微信图片／文件／视频全链路、复杂引用／转发。
- 任意AstrBot版本兼容、所有内置扩展、所有配置组合。
- 实际主动消息的跨天可靠性及本地／云端模型切换。

请按 `WEIXIN_OC_COMPAT.md` 在自己的实例中完成首次验收。
