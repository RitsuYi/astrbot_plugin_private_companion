"""Experimental WeChat private routing against AstrBot's real adapter classes.

All identities and credentials are synthetic. HTTP and telemetry are replaced
at the boundary; no QR login or real message delivery is performed.
"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from tests import astrbot_data_root  # noqa: F401
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.sources.weixin_oc.weixin_oc_adapter import WeixinOCAdapter
from astrbot.core.platform.sources.weixin_oc.weixin_oc_event import WeixinOCMessageEvent
from astrbot_host.binding import event_identity
from companion_v2.adapters.astrbot.native import (
    HostAccount, HostPersona, NativePrivateBridge, event_account_id,
    native_client_connected, native_platform_client, native_user_subject_id,
    persona_instruction, platform_event_matches, supported_platform_name,
)
from companion_v2.adapters.astrbot.platform_sender import AstrBotPlatformSender
from companion_v2.delivery.models import DeliveryEnvelope
from companion_v2.execution.models import TaskContext, digest
from companion_v2.identity_policy.models import AuthenticatedHostPrincipal
from companion_v2.identity_policy.personas import PersonaBinding, PersonaSelector, SelectorKind
from tests.multi_host_support import MultiFixture, multi_config
from tests.native_adapter_support import NativeFixture
from tests.staging_bootstrap_support import wait_for_batch
from tests.test_management_access import INSTALLATION, NOW, ROLE


ACCOUNT = "weixin-test"
PEER = "synthetic-peer@im.wechat"


def adapter(instance=ACCOUNT):
    return WeixinOCAdapter({
        "id": instance, "type": "weixin_oc", "enable": True,
        "weixin_oc_token": "synthetic-login-token", "weixin_oc_account_id": "synthetic-bot",
        "weixin_oc_base_url": "https://example.invalid",
    }, {}, asyncio.Queue())


def event(platform, *, sender=PEER, text="你好", identifier="weixin-event-1"):
    message = AstrBotMessage()
    message.self_id = platform.meta().id
    message.sender = MessageMember(user_id=sender, nickname=sender)
    message.type = MessageType.FRIEND_MESSAGE
    message.group_id = ""
    message.session_id = sender
    message.message_id = identifier
    message.message = [Plain(text)]
    message.message_str = text
    message.raw_message = {"from_user_id": sender, "context_token": "synthetic-context-token"}
    result = platform.create_event(message)
    result.created_at = NOW.timestamp()
    return result


class WeixinContractTests(unittest.TestCase):
    def test_real_adapter_and_event_use_a_distinct_identity_namespace(self):
        platform = adapter()
        incoming = event(platform)
        self.assertIsNone(platform.get_client())  # The SDK's inherited stub.
        self.assertIs(native_platform_client(platform), platform.client)
        self.assertFalse(hasattr(incoming, "bot"))
        self.assertTrue(supported_platform_name("weixin_oc"))
        self.assertEqual(event_account_id(incoming), ACCOUNT)
        self.assertEqual(native_user_subject_id("weixin_oc", PEER), "weixin-oc-user:" + PEER)
        self.assertEqual(event_identity(incoming), {
            "platform_id": ACCOUNT, "account_id": ACCOUNT, "participant_id": PEER})
        self.assertTrue(platform_event_matches(platform, incoming))

    def test_event_from_another_adapter_cannot_borrow_the_current_client(self):
        platform = adapter()
        impostor = adapter()
        impostor.client = platform.client
        self.assertFalse(platform_event_matches(platform, event(impostor)))

    def test_event_metadata_must_match_the_registered_instance(self):
        platform = adapter()
        incoming = event(platform)
        incoming.platform_meta = NS(name="weixin_oc", id="other-instance")
        self.assertFalse(platform_event_matches(platform, incoming))

    def test_missing_login_and_replaced_transport_fail_liveness(self):
        platform = adapter()
        self.assertTrue(native_client_connected(platform, ACCOUNT))
        platform.account_id = None  # Optional in the SDK; the login token owns sending.
        self.assertTrue(native_client_connected(platform, ACCOUNT))
        self.assertFalse(native_client_connected(platform, "other-account"))
        self.assertFalse(native_client_connected(platform, ACCOUNT, object()))
        platform.token = None
        self.assertFalse(native_client_connected(platform, ACCOUNT))
        platform.token = "different-token"
        self.assertFalse(native_client_connected(platform, ACCOUNT))

    def test_shutdown_is_not_reported_as_connected(self):
        platform = adapter()
        platform._shutdown_event.set()
        self.assertFalse(native_client_connected(platform, ACCOUNT))


class WeixinFixture(NativeFixture):
    def setUp(self):
        super().setUp()
        self.native.platform = adapter()
        self.account = HostAccount(ACCOUNT, ACCOUNT, "bot-weixin")
        self.persona = HostPersona("bot-weixin", "original", ROLE,
            digest(persona_instruction(self.native.persona)))
        principal = AuthenticatedHostPrincipal(INSTALLATION, "host", ACCOUNT,
            PEER, "bot-weixin", ACCOUNT)
        self.identity.bind(binding_id="weixin-native-user", principal=principal,
            subject=self.important.subject, valid_from=NOW, expected_revision=self.identity.revision)
        self.personas.set_binding(PersonaBinding("weixin-base", PersonaSelector(
            INSTALLATION, SelectorKind.BOT, bot_id="bot-weixin"), ROLE, 0, NOW, "fixture", "admin"),
            expected_revision=0, observed_at=NOW)
        self.bridge = NativePrivateBridge(self.native, version="4.29.4", event_type=AstrMessageEvent,
            installation_id=INSTALLATION, host_id="host", identities=self.identity,
            accounts=(self.account,), personas=(self.persona,), now=self.clock.now,
            session_persona_override_lookup=AsyncMock(return_value="original"))

    async def capture(self, incoming=None):
        captured = (await self.bridge.capture(incoming or event(self.native.platform))).unwrap()
        actor = self.identity.resolve_authenticated(captured.principal, observed_at=NOW).unwrap()
        self.grant(actor, captured.route.scope, "text")
        return captured

    async def delivery(self):
        captured = await self.capture()
        self.personas.register_route(captured.route, observed_at=NOW)
        role = self.personas.resolve(captured.route.scope, observed_at=NOW).unwrap().binding
        actor = self.identity.resolve_authenticated(captured.principal, observed_at=NOW).unwrap()
        context = TaskContext(actor, role, captured.recipients)
        return DeliveryEnvelope(part_id="part-weixin", operation_id="op-weixin", context=context,
            sequence=1, text="微信回复测试", payload_hash=digest("微信回复测试"),
            sender=self.sender.binding, before_dispatch=lambda: True)

    def platform_sender(self, **options):
        return AstrBotPlatformSender(self.bridge, binding=self.sender.binding,
            version="4.29.4", reverse_api_type=object, authorize=lambda: None,
            now=self.clock.now, **options)


class WeixinBridgeTests(WeixinFixture, unittest.IsolatedAsyncioTestCase):
    async def test_core_reply_keeps_text_and_does_not_call_tts(self):
        from astrbot_host.core_reply_voice import prepare_core_reply_voice_message
        from companion_v2.conversation.voice_reply import VoiceReplyPolicy
        renderer = AsyncMock()
        message = MessageChain([Plain("保留文字回复")])
        result = await prepare_core_reply_voice_message(event(self.native.platform),
            {"voice_reply_policy": VoiceReplyPolicy()}, message,
            renderer=renderer, delivery=None, authorize=lambda: None)
        self.assertEqual(result.get_plain_text(), "保留文字回复")
        renderer.assert_not_awaited()

    async def test_real_event_captures_selected_persona_and_original_peer(self):
        captured = await self.capture()
        self.assertEqual(captured.text, "你好")
        self.assertEqual(captured.route.scope.native_scope_id, PEER)
        self.assertEqual(captured.route.scope.account_id, ACCOUNT)
        self.assertEqual(captured.role, ROLE)

    async def test_replaced_registered_client_invalidates_the_bridge(self):
        self.native.platform.client = NS(token="synthetic-login-token")
        result = await self.bridge.capture(event(self.native.platform))
        self.assertFalse(result.is_success)

    async def test_missing_context_is_not_reported_delivered(self):
        delivery = await self.delivery()
        self.native.platform.send_by_session = AsyncMock()
        receipt = await self.platform_sender().send(delivery)
        self.assertEqual(receipt.status, "not_sent")
        self.assertEqual(receipt.failure_code, "weixin_context_token_missing")
        self.native.platform.send_by_session.assert_not_awaited()

    async def test_real_sdk_send_and_api_failure_have_distinct_receipts(self):
        delivery = await self.delivery()
        platform = self.native.platform
        platform._context_tokens[PEER] = "synthetic-context-token"
        platform.client.request_json = AsyncMock(return_value={"ret": 0})
        with patch("astrbot.core.platform.platform.Metric.upload", new=AsyncMock()):
            receipt = await self.platform_sender().send(delivery)
        self.assertEqual(receipt.status, "delivered", receipt)
        payload = platform.client.request_json.call_args.kwargs["payload"]
        self.assertEqual(payload["msg"]["to_user_id"], PEER)
        self.assertEqual(payload["msg"]["context_token"], "synthetic-context-token")
        platform.client.request_json.return_value = {"ret": -2, "errmsg": "synthetic-expired"}
        receipt = await self.platform_sender().send(delivery)
        self.assertEqual(receipt.status, "unknown")

    async def test_optional_voice_falls_back_to_text_without_tts(self):
        delivery = await self.delivery()
        platform = self.native.platform
        platform._context_tokens[PEER] = "synthetic-context-token"
        platform.send_by_session = AsyncMock()
        voice = AsyncMock()
        receipt = await self.platform_sender(voice=voice).send(delivery)
        self.assertEqual(receipt.status, "delivered", receipt)
        voice.assert_not_awaited()
        self.assertEqual(platform.send_by_session.call_args.args[1].get_plain_text(), delivery.text)

    async def test_required_voice_is_explicitly_unsupported(self):
        delivery = replace(await self.delivery(), voice_required=True)
        self.native.platform._context_tokens[PEER] = "synthetic-context-token"
        self.native.platform.send_by_session = AsyncMock()
        receipt = await self.platform_sender().send(delivery)
        self.assertEqual(receipt.status, "not_sent")
        self.assertEqual(receipt.failure_code, "weixin_voice_unsupported")
        self.native.platform.send_by_session.assert_not_awaited()


class WeixinMultiHostTests(MultiFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.native.platform = adapter()
        self.native.platforms = {ACCOUNT: self.native.platform}
        self.native.selections = {ACCOUNT: "original"}
        self.native.conversations = {ACCOUNT: "conversation-weixin"}
        self.types = replace(self.types, event=AstrMessageEvent)
        self.window_personas = {f"{ACCOUNT}:FriendMessage:{PEER}": "original"}
        self.config = multi_config(accounts=[{
            "platform_id": ACCOUNT, "account_id": ACCOUNT, "bot_id": "bot-weixin"}],
            targets=[{"target_id": "weixin-private", "platform_id": ACCOUNT,
                      "account_id": ACCOUNT, "bot_id": "bot-weixin", "participant_id": PEER}],
            personas=[{"bot_id": "bot-weixin", "persona_id": "original", "role_id": "role-a"}],
            group_targets=[])
        self.controller = self.make_controller(self.config)

    def binding_window(self):
        """Reproduce a Chinese instance name and the first-run wildcard route."""
        from copy import deepcopy
        instance = "爱弥斯"
        self.native.platform = adapter(instance)
        self.native.platforms = {instance: self.native.platform}
        self.native.persona_records[instance] = {"name": instance, "prompt": "合成微信测试人格"}
        self.native.selections = {instance: instance}
        self.native.conversations = {instance: "synthetic-weixin-conversation"}
        self.window_personas = {f"{instance}:FriendMessage:{PEER}": instance}
        self.config = multi_config(targets=[{
            "target_id": "old-wildcard", "platform_id": instance, "account_id": instance,
            "bot_id": "bot-weixin", "participant_id": "*"}],
            personas=[{"bot_id": "bot-weixin", "persona_id": instance, "role_id": "role-a"}],
            group_targets=[])
        self.controller = self.make_controller(self.config)
        self.saved_configs = []

        def save(candidate):
            self.saved_configs.append(deepcopy(candidate))
            self.config.clear()
            self.config.update(deepcopy(candidate))

        self.controller.save_plugin_config = save
        return instance, event(self.native.platform, text="我会永远陪着你 爱弥斯")

    async def test_first_run_bind_accepts_a_real_weixin_peer_and_chinese_instance(self):
        instance, incoming = self.binding_window()
        self.assertTrue(self.controller.handles_binding(incoming))
        result = await self.controller.receive_binding(incoming)
        self.assertTrue(result.get("ok"), result)
        state = self.controller.binding_state()
        self.assertTrue(state["pending"], state)
        self.assertEqual(state["account_id"], instance)
        self.assertEqual(state["participant_id"], PEER)
        self.assertEqual(state["persona_id"], instance)
        self.assertNotIn("error", state)

    async def test_confirmed_bind_materializes_exact_target_and_survives_reload(self):
        instance, incoming = self.binding_window()
        result = await self.controller.receive_binding(incoming)
        self.assertTrue(result.get("ok"), result)
        result = self.controller.confirm_binding()
        self.assertTrue(result["confirmed"], result)
        self.assertTrue(self.saved_configs)
        exact = self.controller.settings.private_target(instance, instance, PEER)
        self.assertEqual(exact.participant_id, PEER)
        self.assertNotEqual(exact.target_id, "old-wildcard")
        self.assertIs(self.controller.target_for_event(incoming), exact)
        self.controller = self.make_controller(self.config)
        state = self.controller.binding_state()
        self.assertTrue(state["confirmed"], state)
        self.assertTrue(state["configured_target"], state)
        self.assertEqual(self.controller.target_for_event(incoming).participant_id, PEER)
        app = await self.start_host()
        self.native.platform._context_tokens[PEER] = "synthetic-context-token"
        self.native.platform.send_by_session = AsyncMock()
        incoming = event(self.native.platform, text="我不喝咖啡", identifier="after-bind-reload")
        await self.controller.session_topology.observe(incoming)
        result = await self.controller.receive_claimed(incoming)
        self.assertTrue(result.is_success, result.failure)
        batch = result.unwrap()
        await wait_for_batch(self.controller.session, batch)
        self.native.platform.send_by_session.assert_awaited_once()
        import json
        context = TaskContext.restore(json.loads(app.messages.batch(batch)["context_json"]))
        self.assertEqual(context.scope.platform, instance)
        self.assertEqual(context.scope.account_id, instance)
        self.assertEqual(context.scope.native_scope_id, PEER)
        self.assertIsNotNone(self.remember(app, context, batch))

    async def test_invalid_identity_is_rejected_before_writing_a_pending_binding(self):
        from astrbot_host.binding_store import binding_path
        self.binding_window()
        incoming = event(self.native.platform, sender="bad:peer@im.wechat",
                         text="我会永远陪着你 爱弥斯")
        result = await self.controller.receive_binding(incoming)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "host_identity_invalid")
        self.assertFalse(binding_path(self.controller.binding_root).exists())

    async def test_another_peer_cannot_replace_the_pending_weixin_binding(self):
        self.binding_window()
        result = await self.controller.receive_binding(event(
            self.native.platform, text="我会永远陪着你 爱弥斯"))
        self.assertTrue(result["ok"], result)
        incoming = event(self.native.platform, sender="another-peer@im.wechat",
                         text="我会永远陪着你 爱弥斯")
        result = await self.controller.receive_binding(incoming)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "host_binding_candidate_exists")
        self.assertEqual(self.controller.binding_state()["participant_id"], PEER)

    async def test_account_picker_discovers_weixin_and_target_authenticates_event(self):
        accounts = self.controller.session_topology.accounts()
        self.assertTrue(any(row["platform_name"] == "weixin_oc" and row["account_id"] == ACCOUNT
                            for row in accounts))
        incoming = event(self.native.platform)
        self.assertIsNotNone(self.controller.target_for_event(incoming))
        self.assertIsNone(self.controller.target_for_event(event(adapter())))

    async def test_full_private_flow_and_memory_write_use_the_weixin_scope(self):
        app = await self.start_host()
        platform = self.native.platform
        platform._context_tokens[PEER] = "synthetic-context-token"
        platform.send_by_session = AsyncMock()
        incoming = event(platform, text="我不喝咖啡")
        await self.controller.session_topology.observe(incoming)
        result = await self.controller.receive_claimed(incoming)
        self.assertTrue(result.is_success, result.failure)
        batch = result.unwrap()
        await wait_for_batch(self.controller.session, batch)
        platform.send_by_session.assert_awaited_once()
        session, chain = platform.send_by_session.call_args.args
        self.assertEqual(str(session), f"{ACCOUNT}:FriendMessage:{PEER}")
        self.assertIn("我在这里", chain.get_plain_text())
        import json
        context = TaskContext.restore(json.loads(app.messages.batch(batch)["context_json"]))
        self.assertEqual(context.scope.platform, ACCOUNT)
        self.assertEqual(context.scope.native_scope_id, PEER)
        remembered = self.remember(app, context, batch)
        self.assertIsNotNone(remembered)

    async def test_core_reply_capture_handles_real_weixin_events_without_bot_attribute(self):
        await self.start_host()
        result = await self.controller.session.bridge.capture_core_reply(event(self.native.platform))
        self.assertTrue(result.is_success, result.failure)
        self.assertEqual(result.unwrap().route.scope.native_scope_id, PEER)


if __name__ == "__main__":
    unittest.main()
