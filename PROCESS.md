# 微信适配版升级流程（PROCESS）

本文件描述「我会永远陪着你」插件微信适配版从作者新版同步到交付安装包的一次完整流程。
规则与边界见 `AGENTS.md`；来源、分支与回退见 `MAINTENANCE.md`。本文件只写公开流程，不含私人配置。

## 0. 结论口径

- 分支：只有 `weixin`；`origin` 为本维护仓库，`upstream` 为作者仓库。
- 合并方式：始终普通三方合并（`git merge --no-ff`），禁止 `ours`、整树覆盖或重建仓库。
- 版本号：`<作者版本>+weixin.<修订号>`，例如 `7.2.6+weixin.2`；作者版本号与提交必须一致。
- 微信适配层：见第 4 节清单，任何升级都必须逐项重放并复核，不能因“上游已支持 weixin_oc”而删除。
- 未登录真实微信验收时，文档中一律写“未实测”。

## 1. 开始前检查

1. 阅读 `AGENTS.md`、`MAINTENANCE.md`、本文件，再读 `UPSTREAM_BASELINE.json` 与最近一版 `docs/WEIXIN_OC_*_VALIDATION.md`。
2. 检查工作区、Git 状态和远端实际值，保留用户文件与未推送提交：

```powershell
git status --short
git branch -vv
git remote -v
git fetch origin weixin
git fetch --no-tags upstream refs/tags/<作者版本>:refs/remotes/upstream/<作者版本>
git rev-parse refs/remotes/upstream/<作者版本>
git merge-base --is-ancestor <当前作者基线SHA> HEAD
```

3. 确认 `origin/weixin` 是本地 HEAD 的祖先；如远端有新提交，先正常快进或合并并复测。
4. 记录目标作者提交的完整 SHA、CHANGELOG 顶部、`metadata.yaml` 的 `astrbot_version` 与依赖变化，判断是否需要数据库迁移或宿主升级。
5. 备份正在运行的插件目录、配置和全部真实数据；交付与验证都在独立克隆/工作区完成，不直接改运行中的 AstrBot。

## 2. 隔离工作区与备份分支

```powershell
git switch weixin
git merge --ff-only origin/weixin
git branch backup/weixin-<旧版本> HEAD
git merge --no-ff --no-commit refs/remotes/upstream/<作者版本>
```

- 合并前记录 `MERGE_HEAD`；合并提交信息写明作者版本、提交 SHA 与“保留 R2 微信适配”。
- 若有 CI、开发配置等作者新增文件属于发布过滤范围，继续用 `git rm` 保持不跟踪，不要为了“干净”引入它们。

## 3. 冲突处理

1. 逐文件查看冲突，不整批覆盖；保留作者新逻辑，再重放微信适配。
2. 对“上游整体重构、微信适配需要重新落位”的文件，可先取上游版本，再按第 4 节重放：
   `git checkout --theirs <file>` 后必须逐项补回适配并复查，不能停在上游原样。
3. 合并后全仓搜索残留标记，并确认 `git diff --check` 通过：

```powershell
git grep -n -e "<<<<<<< " -e ">>>>>>> " -- . # 页面资源也要查
git diff --check
```

4. 重新生成能力基线（会更新 `tools/native_capability_baseline.json`）：

```powershell
python -B -X utf8 tools/build_v2_release.py --refresh-native-capability-baseline
```

## 4. 微信适配清单（必须逐项复核）

身份与路由：

1. `astrbot_host/identity_derivation.py`：保留 `_OPAQUE_ACCOUNT`，允许 `xxx@im.wechat` 这类有界原生 ID。
2. `companion_v2/adapters/astrbot/native.py`：
   - `native_user_subject_id` 对 `weixin_oc` 返回 `weixin-oc-user:`（**不能**改成上游 `weixin-user:`）；
   - `native_platform_client`：`weixin_oc` 读 `platform.client`（SDK 的 `get_client()` 是空 stub）；
   - `event_native_client` / `platform_event_matches`：事件必须回到所属 platform 实例取 client；
   - `native_client_connected`：`weixin_oc` 用“平台实例 ID + 登录 token 一致 + 未关停”判定在线；
   - `SUPPORTED_PLATFORM_NAMES` 含 `weixin_oc` 与 `wechat_native`。
3. `companion_v2/adapters/astrbot/connections.py`：`_identity` 的 `weixin_oc` 分支用 `platform.account_id`
   而不是会变化的 token；`_refresh` 用 `native_platform_client`。
   “客户端被替换”由 `NativeAccountConnections` 的 generation 处理：旧 lease 失效、新客户端可继续收下一条事件。
4. `astrbot_host/controller.py`、`multi_controller.py`、`multi_session.py`、`session_topology.py`、`native.py`：
   路由校验使用 `platform_event_matches`，不要回退到 `platform.get_client()`；绑定必须先 `identity()` 校验再写入。
5. `astrbot_host/account_session_api.py`：连接状态同样走 `native_platform_client`，否则微信下会误报不可用。
6. `astrbot_host/web_read_material.py`、`astrbot_host/core_reply_voice.py`：微信保留文字回复，不生成/发送 `Record`。

发送边界：

7. `companion_v2/adapters/astrbot/platform_sender.py`：
   - 缺 `platform._context_tokens[session.session_id]` → `not_sent("weixin_context_token_missing")`；
   - 必选语音 → `not_sent("weixin_voice_unsupported")`；可选语音降级为文字，不调 TTS。

版本与元数据：

8. `companion_v2/product/__init__.py` 的 `PRODUCT_VERSION`、`metadata.yaml`、`pyproject.toml`、
   `tools/build_v2_release.py` 的 `VERSION` 四处一致为 `<作者版本>+weixin.<修订号>`。
9. `metadata.yaml` 的 `repo` 指向 `RitsuYi/astrbot_plugin_private_companion`；许可与作者引用保留；
   `support_platforms` 采用作者最新列表（含 `weixin_oc`、`wechat_native`）。
10. 记忆插件不是本仓库的一部分；伴随发布沿用当时已核验的版本（本次为 `2.6.5+weixin.2.2`），不随之改动。

## 5. 文档与记录

- `CHANGELOG.md`：顶部新增本版本条目（目标提交、合并方式、保留的适配、真实微信未实测），保留历史微信版条目。
- `README.md`：版本行与平台说明更新；正文其余以作者新版为准，保留作者署名。
- `AGENTS.md` / `MAINTENANCE.md` / `UPSTREAM_BASELINE.json`：版本、作者基线、上一版交付归档与本次升级块。
- 新增 `docs/WEIXIN_OC_<版本>_VALIDATION.md`：命令、SDK 版本、通过数、未实测项与包哈希。
- `RELEASE_FILES.json`：最后重建，`files` 必须等于 `git ls-files` 减去自身，哈希按工作区字节计算。

## 6. 验证闸门

```powershell
python -B -X utf8 -c "import ast,pathlib; [ast.parse(p.read_bytes(),filename=str(p)) for p in pathlib.Path('.').rglob('*.py') if '.git' not in p.parts]"
python -B -X utf8 -c "import json,pathlib; [json.loads(p.read_bytes()) for p in pathlib.Path('.').rglob('*.json') if '.git' not in p.parts]"
python -B -X utf8 -m unittest tests.test_identity_policy tests.test_identity_derivation tests.test_release_secret_detection tests.test_weixin_oc_compat
python -B -X utf8 -m tools.check_tracked_privacy
git diff --check
```

- 在独立虚拟环境安装已核验的 AstrBot SDK 后运行测试；插件运行依赖不得声明 `astrbot`。
- 与变更面相关的额外回归（绑定、私聊路由、主动消息、记忆隔离、双插件桥接）必须实际执行并记录。
- 网络与微信登录用模拟/合成身份；测试数据放隔离目录，不做批量清理。

## 7. 交付安装包

1. 全部检查通过后提交合并；确认工作树干净、`HEAD` 与 `MERGE_HEAD` 关系正确、发布清单哈希一致。
2. 用仓库外的打包脚本构建 **root-layout plugin-only ZIP**：根目录直接含 `main.py`、`metadata.yaml`；
   包含运行所需 `astrbot_host/`、`companion_v2/`、`pages/`、`skills/` 与公开说明；ZIP 内生成 `RELEASE_FILES.json`。
3. 排除 Git/bundle、`tests/`、`fixtures/`、`tools/`、虚拟环境、维护脚本、真实配置、数据库、凭证、日志、缓存。
4. 解压到临时目录并用 AstrBot SDK 做入口导入与关键桥接检查；校验 ZIP CRC、逐文件 SHA256、页面资源与能力资源。
5. 在仓库外写 `release-manifest.json`、`SHA256SUMS.txt`、`validation.json`、`安装说明.md`；记录实际字节数、文件数与 SHA256。
6. 不推送远端、不改运行中的 AstrBot，除非用户明确要求；需要推送时按 `MAINTENANCE.md` 的核验步骤执行。

## 8. 自检与收尾

- 版本四处一致、更新地址指向本仓库、作者署名与许可保留。
- 第 4 节清单逐项在代码中可见；无冲突标记；无私人数据、凭证或真实数据库进入提交与 ZIP。
- 测试通过数、失败项与原因写入验证文档；未实测项明确标注。
- 交付目录与旧包并存，不批量删除旧交付；回退方式见 `MAINTENANCE.md`。
