"""Behavioural tests for the Hermes Assist conversation agent.

The suite intentionally runs without Home Assistant installed, so the HA
classes imported by the conversation agent are stubbed the same way
``test_ha_services.py`` stubs them (``sys.modules.setdefault``). If the real
package is importable the behavioural tests are skipped instead, because they
drive the agent with fake HA objects.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Home Assistant stubs
# ---------------------------------------------------------------------------
_LOCAL_AGENT: dict[str, Any] = {"agent": None}
_LOCAL_AGENT_LOOKUPS: list[str] = []


def _install_homeassistant_stubs() -> bool:
    """Install minimal HA stubs; return True when they were installed."""
    try:
        import homeassistant.components.conversation  # noqa: F401
        import homeassistant.helpers.intent  # noqa: F401
    except ImportError:
        pass
    else:
        return False

    modules = {
        "voluptuous": ModuleType("voluptuous"),
        "homeassistant": ModuleType("homeassistant"),
        "homeassistant.config_entries": ModuleType("homeassistant.config_entries"),
        "homeassistant.const": ModuleType("homeassistant.const"),
        "homeassistant.core": ModuleType("homeassistant.core"),
        "homeassistant.data_entry_flow": ModuleType("homeassistant.data_entry_flow"),
        "homeassistant.helpers": ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity": ModuleType("homeassistant.helpers.entity"),
        "homeassistant.helpers.entity_platform": ModuleType("homeassistant.helpers.entity_platform"),
        "homeassistant.helpers.event": ModuleType("homeassistant.helpers.event"),
        "homeassistant.helpers.intent": ModuleType("homeassistant.helpers.intent"),
        "homeassistant.helpers.selector": ModuleType("homeassistant.helpers.selector"),
        "homeassistant.helpers.typing": ModuleType("homeassistant.helpers.typing"),
        "homeassistant.components": ModuleType("homeassistant.components"),
        "homeassistant.components.conversation": ModuleType("homeassistant.components.conversation"),
        "homeassistant.components.conversation.chat_log": ModuleType(
            "homeassistant.components.conversation.chat_log"
        ),
        "homeassistant.components.http": ModuleType("homeassistant.components.http"),
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)

    vol = sys.modules["voluptuous"]
    if not hasattr(vol, "Schema"):
        setattr(vol, "Schema", lambda value, **kwargs: value)
        setattr(vol, "Required", lambda key, **kwargs: key)
        setattr(vol, "Optional", lambda key, **kwargs: key)
        setattr(vol, "In", lambda values: values)
        setattr(vol, "Any", lambda *values: values)

    const = sys.modules["homeassistant.const"]
    if not hasattr(const, "Platform"):
        const.CONF_URL = "url"
        const.CONF_TOKEN = "token"
        const.Platform = SimpleNamespace(SENSOR="sensor", CONVERSATION="conversation")

    core = sys.modules["homeassistant.core"]
    if not hasattr(core, "HomeAssistant"):
        core.HomeAssistant = type("HomeAssistant", (), {})
        core.ServiceCall = type("ServiceCall", (), {})
        core.ServiceResponse = dict
        core.SupportsResponse = SimpleNamespace(OPTIONAL="optional")
        core.callback = lambda func: func

    class _FlowBase:
        def __init_subclass__(cls, **kwargs):
            return super().__init_subclass__()

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    config_entries = sys.modules["homeassistant.config_entries"]
    setattr(config_entries, "ConfigEntry", type("ConfigEntry", (), {}))
    setattr(config_entries, "ConfigFlow", type("ConfigFlow", (_FlowBase,), {}))
    setattr(config_entries, "OptionsFlow", type("OptionsFlow", (_FlowBase,), {}))
    setattr(sys.modules["homeassistant.data_entry_flow"], "FlowResult", dict)
    sys.modules["homeassistant.helpers.entity"].Entity = object
    sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    sys.modules["homeassistant.helpers.event"].async_track_state_change_event = (
        lambda *a, **k: (lambda: None)
    )
    sys.modules["homeassistant.helpers.typing"].ConfigType = dict
    sys.modules["homeassistant.components.http"].StaticPathConfig = lambda *a, **k: (a, k)

    selector_mod = sys.modules["homeassistant.helpers.selector"]
    setattr(selector_mod, "TextSelector", lambda *a, **k: (a, k))
    setattr(selector_mod, "TextSelectorConfig", lambda *a, **k: (a, k))
    setattr(
        selector_mod,
        "TextSelectorType",
        SimpleNamespace(URL="url", PASSWORD="password"),
    )
    for name in (
        "DeviceSelector",
        "DeviceSelectorConfig",
        "EntitySelector",
        "EntitySelectorConfig",
        "NumberSelector",
        "NumberSelectorConfig",
    ):
        setattr(selector_mod, name, lambda *a, **k: (a, k))
    setattr(selector_mod, "NumberSelectorMode", SimpleNamespace(BOX="box", SLIDER="slider"))
    setattr(sys.modules["homeassistant.helpers"], "selector", selector_mod)

    # --- intent -----------------------------------------------------------
    intent_mod = sys.modules["homeassistant.helpers.intent"]

    class IntentResponseType(enum.Enum):
        ACTION_DONE = "action_done"
        QUERY_ANSWER = "query_answer"
        ERROR = "error"
        NOT_UNDERSTOOD = "not_understood"

    class IntentResponse:
        """Mirrors the parts of HA's IntentResponse the agent touches."""

        def __init__(self, language: str | None = None, intent=None, response_type=None):
            self.language = language
            self.intent = intent
            self.response_type = response_type or IntentResponseType.ERROR
            self.speech: dict[str, Any] = {}
            self.data: dict[str, Any] = {}

        def async_set_speech(self, speech: str, extra_data: dict | None = None) -> None:
            self.speech = {"plain": {"speech": speech}}
            if extra_data:
                self.data.update(extra_data)

    intent_mod.IntentResponseType = IntentResponseType
    intent_mod.IntentResponse = IntentResponse

    # --- conversation -----------------------------------------------------
    conv = sys.modules["homeassistant.components.conversation"]

    @dataclasses.dataclass(frozen=True)
    class ConversationInput:
        text: str
        context: Any = None
        conversation_id: str | None = None
        device_id: str | None = None
        satellite_id: str | None = None
        language: str = "en"
        agent_id: str = ""
        extra_system_prompt: str | None = None

    @dataclasses.dataclass
    class ConversationResult:
        response: Any
        conversation_id: str | None = None
        continue_conversation: bool = False

    class ConversationEntity:
        hass: Any = None
        _attr_has_entity_name = False
        _attr_name: str | None = None

    class ChatLog:
        def __init__(self, hass: Any, conversation_id: str) -> None:
            self.hass = hass
            self.conversation_id = conversation_id

    class _CurrentChatLog:
        @staticmethod
        def get() -> None:
            return None

    async def async_handle_intents(
        hass: Any,
        user_input: ConversationInput,
        chat_log: ChatLog,
        intent_filter=None,
    ) -> Any:
        _LOCAL_AGENT_LOOKUPS.append(user_input.agent_id)
        agent = _LOCAL_AGENT["agent"]
        if agent is None:
            return None
        recognised = await agent.async_recognize_intent(user_input)
        if recognised is None or (
            intent_filter is not None and intent_filter(recognised)
        ):
            return None
        return await agent.async_process_intent(user_input)

    conv.ConversationInput = ConversationInput
    conv.ConversationResult = ConversationResult
    conv.ConversationEntity = ConversationEntity
    setattr(conv, "async_handle_intents", async_handle_intents)
    setattr(sys.modules["homeassistant.components"], "conversation", conv)
    chat_log_mod = sys.modules["homeassistant.components.conversation.chat_log"]
    setattr(chat_log_mod, "ChatLog", ChatLog)
    setattr(chat_log_mod, "current_chat_log", _CurrentChatLog())
    return True


HA_STUBBED = _install_homeassistant_stubs()

from custom_components.hermes import QUERY_TIMEOUT_SECONDS
from custom_components.hermes import config_flow as config_flow_module
from custom_components.hermes import conversation as agent_module
from custom_components.hermes.const import (
    CONF_LOCAL_INTENTS,
    DOMAIN,
    LOCAL_INTENTS_ANSWERS,
    LOCAL_INTENTS_COMMANDS,
    LOCAL_INTENTS_OFF,
    MAX_QUERY_TEXT_LENGTH,
)

needs_stubs = pytest.mark.skipif(
    not HA_STUBBED, reason="behavioural tests drive fake Home Assistant objects"
)

_INTENT = sys.modules["homeassistant.helpers.intent"]
_CONVERSATION = sys.modules["homeassistant.components.conversation"]
_RESPONSE_TYPE = _INTENT.IntentResponseType

ACTION = "action"
ANSWER = "answer"


def _local_result(kind: str, speech: str = ""):
    """Build what HA's native agent would return for a matched intent."""
    response_type = (
        _RESPONSE_TYPE.ACTION_DONE if kind == ACTION else _RESPONSE_TYPE.QUERY_ANSWER
    )
    response = _INTENT.IntentResponse(language="en", response_type=response_type)
    if speech:
        response.async_set_speech(speech)
    return _CONVERSATION.ConversationResult(response=response, conversation_id="ha")


class FakeLocalAgent:
    """Stands in for HA's native ``conversation.home_assistant`` agent.

    ``answers`` maps an input text to ``(kind, speech)``. Anything not listed
    is answered with an error, exactly like an unmatched sentence.
    """

    def __init__(
        self,
        answers: dict[str, tuple[str, str]],
        intent_names: dict[str, str] | None = None,
    ) -> None:
        self.answers = answers
        self.intent_names = intent_names or {}
        self.calls: list[str] = []
        self.recognitions: list[str] = []
        self.executions: list[str] = []

    async def async_recognize_intent(self, user_input):
        """Recognise without executing, like HA's DefaultAgent."""
        self.recognitions.append(user_input.text)
        answer = self.answers.get(user_input.text)
        if answer is None:
            return None
        kind, _speech = answer
        intent_name = self.intent_names.get(
            user_input.text,
            "HassGetState" if kind == ANSWER else "HassTurnOn",
        )
        return SimpleNamespace(
            intent=SimpleNamespace(name=intent_name), unmatched_entities=[]
        )

    async def async_process_intent(self, user_input):
        self.calls.append(user_input.text)
        if user_input.text not in self.answers:
            return _local_result(ANSWER, "").response
        kind, speech = self.answers[user_input.text]
        if kind == ACTION:
            self.executions.append(user_input.text)
        return _local_result(kind, speech).response


class FakeBridge:
    """Records what the agent forwards to Hermes."""

    def __init__(self, reply: str = "resposta do Hermes") -> None:
        self.texts: list[str] = []
        self._reply = reply

    async def async_send_conversation_query(
        self, text: str, conversation_id: str | None = None, language: str = "en"
    ) -> dict[str, Any]:
        self.texts.append(text)
        return {"text": self._reply, "conversation_id": conversation_id}


def _make_agent(
    mode: str | None = LOCAL_INTENTS_OFF,
    bridge: FakeBridge | None = None,
):
    options: dict[str, Any] = {}
    if mode is not None:
        options[CONF_LOCAL_INTENTS] = mode
    entry = SimpleNamespace(options=options, entry_id="entry-1")
    bridge = bridge or FakeBridge()
    agent = agent_module.HermesConversationAgent(bridge, "entry-1", entry)
    agent.hass = SimpleNamespace()
    return agent, bridge


def _use_local_agent(
    answers: dict[str, tuple[str, str]],
    intent_names: dict[str, str] | None = None,
) -> FakeLocalAgent:
    fake = FakeLocalAgent(answers, intent_names)
    _LOCAL_AGENT["agent"] = fake
    _LOCAL_AGENT_LOOKUPS.clear()
    return fake


@pytest.fixture(autouse=True)
def _reset_local_agent():
    _LOCAL_AGENT["agent"] = None
    _LOCAL_AGENT_LOOKUPS.clear()
    yield
    _LOCAL_AGENT["agent"] = None
    _LOCAL_AGENT_LOOKUPS.clear()


def _input(text: str):
    return _CONVERSATION.ConversationInput(text=text, conversation_id="cid-1")


def _speech(result) -> str:
    return result.response.speech.get("plain", {}).get("speech", "")


# ---------------------------------------------------------------------------
# Transcript cleanup: only evidence-backed non-speech markers
# ---------------------------------------------------------------------------
def test_non_speech_markers_are_stripped() -> None:
    strip = agent_module._strip_non_speech_markers
    assert strip("ligar a luz pequena [música]") == "ligar a luz pequena"
    assert strip("ligar a luz pequena (risos)") == "ligar a luz pequena"
    assert strip("abre a janela [BLANK_AUDIO]") == "abre a janela"
    assert strip("desliga a luz [ música ] .") == "desliga a luz"


def test_legitimate_trailing_text_is_never_stripped() -> None:
    strip = agent_module._strip_non_speech_markers
    assert strip("send Sam a notification (urgent)") == "send Sam a notification (urgent)"
    assert strip("como se diz obrigado?") == "como se diz obrigado?"
    assert strip("obrigado") == "obrigado"
    assert strip("desliga a luz, está bem") == "desliga a luz, está bem"


def test_cleanup_never_returns_empty_text() -> None:
    assert agent_module._strip_non_speech_markers("[música]") == "[música]"
    assert agent_module._strip_non_speech_markers("   ") == "   "


# ---------------------------------------------------------------------------
# Local candidate: marker cleanup only, never semantic truncation
# ---------------------------------------------------------------------------
def test_local_candidate_never_truncates_words_or_clauses() -> None:
    assert (
        agent_module._local_candidate(
            "que luzes estão ligadas? e quais janelas estão abertas?"
        )
        == "que luzes estão ligadas? e quais janelas estão abertas?"
    )
    assert (
        agent_module._local_candidate("desligar a luz pequena. foi bonito.")
        == "desligar a luz pequena. foi bonito."
    )


def test_marker_stripped_candidate_may_still_act() -> None:
    assert (
        agent_module._local_candidate("ligar a luz pequena [música]")
        == "ligar a luz pequena"
    )


# ---------------------------------------------------------------------------
# Local handling is opt-in
# ---------------------------------------------------------------------------
@needs_stubs
async def test_local_handling_is_off_by_default() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_OFF)
    _use_local_agent({"ligar a luz pequena": (ACTION, "Ligado")})

    result = await agent.async_process(_input("ligar a luz pequena"))

    assert bridge.texts == ["ligar a luz pequena"]
    assert _speech(result) == "resposta do Hermes"
    assert _LOCAL_AGENT_LOOKUPS == []


@needs_stubs
async def test_unknown_mode_falls_back_to_off() -> None:
    agent, _bridge = _make_agent("yolo")
    assert agent.local_intents == LOCAL_INTENTS_OFF


@needs_stubs
async def test_setup_entry_reads_mode_from_entry_options() -> None:
    created: list[Any] = []
    bridge = FakeBridge()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": bridge}})
    entry = SimpleNamespace(options={CONF_LOCAL_INTENTS: LOCAL_INTENTS_COMMANDS}, entry_id="entry-1")

    await agent_module.async_setup_entry(hass, entry, created.extend)

    assert len(created) == 1
    assert created[0].local_intents == LOCAL_INTENTS_COMMANDS
    assert created[0]._bridge is bridge


@needs_stubs
async def test_options_flow_persists_local_intents_mode() -> None:
    """Exercise the real options-flow code instead of inspecting its source."""
    entry = SimpleNamespace(options={})
    flow = config_flow_module.HermesOptionsFlow(entry)

    result = await flow.async_step_init(
        {
            "entity_filter": "light.kitchen",
            "verify_ssl": True,
            CONF_LOCAL_INTENTS: LOCAL_INTENTS_ANSWERS,
        }
    )
    assert result["type"] == "form"

    result = await flow.async_step_voice({})
    assert result["type"] == "form"
    assert result["step_id"] == "panel"

    result = await flow.async_step_panel({})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_LOCAL_INTENTS] == LOCAL_INTENTS_ANSWERS
    assert config_flow_module._default_options()[CONF_LOCAL_INTENTS] == LOCAL_INTENTS_OFF
    assert config_flow_module._parse_local_intents("unknown") == LOCAL_INTENTS_OFF


# ---------------------------------------------------------------------------
# The transcript sent to Hermes is always the original one
# ---------------------------------------------------------------------------
@needs_stubs
async def test_hermes_receives_the_original_transcript() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({})

    text = "  que luzes estão ligadas? [música]  "
    result = await agent.async_process(_input(text))

    assert bridge.texts == [text]
    assert _speech(result) == "resposta do Hermes"
    # The cleanup was still used for the local attempt itself.
    assert local.recognitions[0] == "que luzes estão ligadas?"


@needs_stubs
async def test_over_limit_payload_is_rejected_without_execution() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    long_text = "a" * (MAX_QUERY_TEXT_LENGTH + 10)
    local = _use_local_agent({long_text[:MAX_QUERY_TEXT_LENGTH]: (ACTION, "Ligado")})

    result = await agent.async_process(_input(long_text))

    assert bridge.texts == []
    assert _speech(result) == "That request is too long. Please shorten it."
    assert local.recognitions == []
    assert local.calls == []
    assert local.executions == []


# ---------------------------------------------------------------------------
# Query answers (QUERY_ANSWER)
# ---------------------------------------------------------------------------
@needs_stubs
async def test_query_answer_is_returned_locally() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_ANSWERS)
    _use_local_agent({"qual a temperatura da cozinha?": (ANSWER, "22 graus")})

    result = await agent.async_process(_input("qual a temperatura da cozinha? [música]"))

    assert _speech(result) == "22 graus"
    assert bridge.texts == []


@needs_stubs
async def test_read_only_intent_with_action_done_response_is_returned_locally() -> None:
    """HA's date/time handlers are safe but retain ACTION_DONE response type."""
    text = "what time is it"
    agent, bridge = _make_agent(LOCAL_INTENTS_ANSWERS)
    local = _use_local_agent(
        {text: (ACTION, "It is 11:42")},
        {text: "HassGetCurrentTime"},
    )

    result = await agent.async_process(_input(text))

    assert _speech(result) == "It is 11:42"
    assert bridge.texts == []
    assert local.executions == [text]


@needs_stubs
async def test_multi_clause_query_is_not_truncated() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_ANSWERS)
    _use_local_agent({"que luzes estão ligadas?": (ANSWER, "Três luzes")})

    text = "que luzes estão ligadas? e quais janelas estão abertas?"
    result = await agent.async_process(_input(text))

    assert _speech(result) == "resposta do Hermes"
    assert bridge.texts == [text]


@needs_stubs
async def test_query_answer_without_speech_falls_through_to_hermes() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_ANSWERS)
    _use_local_agent({"que luzes estão ligadas?": (ANSWER, "")})

    result = await agent.async_process(_input("que luzes estão ligadas?"))

    assert bridge.texts == ["que luzes estão ligadas?"]
    assert _speech(result) == "resposta do Hermes"


@needs_stubs
async def test_unmatched_sentence_falls_through_to_hermes() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_ANSWERS)
    _use_local_agent({})

    result = await agent.async_process(_input("escreve um poema sobre o mar"))

    assert bridge.texts == ["escreve um poema sobre o mar"]
    assert _speech(result) == "resposta do Hermes"


# ---------------------------------------------------------------------------
# Commands (ACTION_DONE)
# ---------------------------------------------------------------------------
@needs_stubs
async def test_answers_mode_never_executes_commands_locally() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_ANSWERS)
    local = _use_local_agent({"ligar a luz pequena": (ACTION, "Ligado")})

    result = await agent.async_process(_input("ligar a luz pequena [música]"))

    assert local.recognitions[0] == "ligar a luz pequena"
    assert local.calls == []
    assert local.executions == []
    assert bridge.texts == ["ligar a luz pequena [música]"]
    assert _speech(result) == "resposta do Hermes"


@needs_stubs
async def test_commands_mode_executes_an_intact_command_locally() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({"ligar a luz pequena": (ACTION, "Ligado")})

    result = await agent.async_process(_input("ligar a luz pequena [música]"))

    assert _speech(result) == "Ligado"
    assert bridge.texts == []
    assert local.executions == ["ligar a luz pequena"]


@needs_stubs
async def test_commands_mode_never_falls_through_after_handler_failure(
    monkeypatch,
) -> None:
    """A post-action HA failure must not dispatch the command to Hermes again."""
    text = "ligar a luz pequena"
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({text: (ACTION, "Ligado")})
    original = _CONVERSATION.async_handle_intents

    async def fail_after_processing(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("chat log subscriber failed after the service call")

    monkeypatch.setattr(_CONVERSATION, "async_handle_intents", fail_after_processing)

    result = await agent.async_process(_input(text))

    assert local.executions == [text]
    assert bridge.texts == []
    assert _speech(result) == (
        "Home Assistant may have processed that command, but its response failed. "
        "I won't send it again."
    )


@needs_stubs
async def test_multi_clause_request_is_never_truncated_or_executed() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({"desligar a luz pequena.": (ACTION, "Desligado")})

    text = "desligar a luz pequena. afinal, não desligues."
    result = await agent.async_process(_input(text))

    assert local.recognitions[0] == text
    assert local.calls == []
    assert local.executions == []
    assert bridge.texts == [text]
    assert _speech(result) == "resposta do Hermes"


@needs_stubs
async def test_except_clause_is_sent_to_hermes_untouched() -> None:
    """'turn off all lights except the kitchen' must never be shortened."""
    text = "ligar todas as luzes excepto a cozinha. foi bonito."
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent(
        {"ligar todas as luzes excepto a cozinha.": (ACTION, "Ligado")}
    )

    result = await agent.async_process(_input(text))

    assert local.executions == []
    assert bridge.texts == [text]
    assert _speech(result) == "resposta do Hermes"


# ---------------------------------------------------------------------------
# WebSocket query timeout
# ---------------------------------------------------------------------------
class _FakeWS:
    async def send_json(self, payload: dict[str, Any]) -> None:
        return None


@needs_stubs
async def test_timeout_and_message_share_one_constant(monkeypatch) -> None:
    from custom_components.hermes import HermesBridge

    captured: dict[str, Any] = {}

    async def fake_wait_for(future, timeout=None):
        captured["timeout"] = timeout
        raise asyncio.TimeoutError

    monkeypatch.setattr("custom_components.hermes.asyncio.wait_for", fake_wait_for)

    bridge = SimpleNamespace(
        _pending_queries={}, _connected=True, _ws=_FakeWS()
    )
    with pytest.raises(TimeoutError) as excinfo:
        await HermesBridge.async_send_conversation_query(bridge, text="olá")

    assert captured["timeout"] == QUERY_TIMEOUT_SECONDS
    assert str(excinfo.value) == (
        f"Hermes did not respond within {QUERY_TIMEOUT_SECONDS:.0f} seconds"
    )


# ---------------------------------------------------------------------------
# Whisper tails: a noisy transcript must not push a house command to the agent
# ---------------------------------------------------------------------------
@needs_stubs
async def test_noise_only_transcript_answers_without_calling_hermes() -> None:
    """A transcript with no words at all is answered locally, not by the agent."""
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    _use_local_agent({})

    result = await agent.async_process(_input("[SOM DE EQUIPA DE FUNDO]"))

    assert bridge.texts == []
    assert "Não percebi" in _speech(result)


@needs_stubs
async def test_bracketed_noise_does_not_hijack_a_house_command() -> None:
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({"ligar a luz pequena": (ACTION, "Ligado")})

    result = await agent.async_process(
        _input("ligar a luz pequena [SOM DE EQUIPA DE FUNDO]")
    )

    assert local.executions == ["ligar a luz pequena"]
    assert bridge.texts == []
    assert _speech(result) == "Ligado"


@needs_stubs
async def test_two_commands_in_one_phrase_never_run_half_locally() -> None:
    """A multi-clause order always goes to Hermes: running half is worse."""
    text = "desligar a luz pequena. ligar a luz grande."
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent(
        {
            "desligar a luz pequena": (ACTION, "Desligado"),
            "ligar a luz grande": (ACTION, "Ligado"),
        }
    )

    await agent.async_process(_input(text))

    assert local.executions == []
    assert bridge.texts == [text]


@needs_stubs
async def test_short_cancellation_clause_is_never_dropped() -> None:
    """A one-word cancellation between commands must block local execution."""
    text = "ligar a luz pequena. cancela. ligar a luz grande."
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent(
        {
            "ligar a luz pequena": (ACTION, "Ligado"),
            "ligar a luz grande": (ACTION, "Ligado"),
        }
    )

    await agent.async_process(_input(text))

    assert local.executions == []
    assert bridge.texts == [text]


@needs_stubs
async def test_parenthesised_cancellation_is_not_stripped() -> None:
    """Real speech inside parentheses is never discarded as an annotation."""
    text = "desligar a luz pequena (afinal, não desligues)"
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({"desligar a luz pequena": (ACTION, "Desligado")})

    await agent.async_process(_input(text))

    assert local.executions == []
    assert bridge.texts == [text]


@needs_stubs
async def test_unknown_bracketed_text_is_not_stripped() -> None:
    """Only known non-speech markers are removed, recognised or not."""
    text = "ligar a luz pequena [NÃO DESLIGUES]"
    agent, bridge = _make_agent(LOCAL_INTENTS_COMMANDS)
    local = _use_local_agent({"ligar a luz pequena": (ACTION, "Ligado")})

    await agent.async_process(_input(text))

    assert local.executions == []
    assert bridge.texts == [text]


# ---------------------------------------------------------------------------
# Voice-panel markers (#58)
# ---------------------------------------------------------------------------
from custom_components.hermes import panel as panel_module  # noqa: E402
from custom_components.hermes.const import (  # noqa: E402
    CONF_PANEL_BRIGHTNESS_MAX,
    CONF_PANEL_BRIGHTNESS_MIN,
    CONF_PANEL_DEVICE,
    CONF_PANEL_HUD_ENTITY,
    CONF_PANEL_HUD_MAX_LENGTH,
    CONF_PANEL_LIGHT_ENTITY,
    CONF_PANEL_VOLUME_ENTITY,
    CONF_PANEL_VOLUME_MAX,
    CONF_PANEL_VOLUME_MIN,
)

PANEL_DEVICE = "panel-device-1"
PANEL_OPTIONS = {
    CONF_PANEL_DEVICE: PANEL_DEVICE,
    CONF_PANEL_HUD_ENTITY: "text.panel_hud",
    CONF_PANEL_LIGHT_ENTITY: "light.panel_backlight",
    CONF_PANEL_VOLUME_ENTITY: "number.panel_volume",
    CONF_PANEL_HUD_MAX_LENGTH: 60,
    CONF_PANEL_BRIGHTNESS_MIN: 10,
    CONF_PANEL_BRIGHTNESS_MAX: 80,
    CONF_PANEL_VOLUME_MIN: 20,
    CONF_PANEL_VOLUME_MAX: 70,
}


def _states(**overrides: Any) -> dict[str, Any]:
    states = {
        "text.panel_hud": SimpleNamespace(attributes={"min": 0, "max": 255}),
        "light.panel_backlight": SimpleNamespace(attributes={}),
        "number.panel_volume": SimpleNamespace(
            attributes={"min": 0, "max": 100, "step": 1}
        ),
    }
    states.update(overrides)
    return states


def _panel(**option_overrides: Any) -> panel_module.PanelConfig:
    config = panel_module.panel_config_from_options({**PANEL_OPTIONS, **option_overrides})
    assert config is not None
    return config


def _plan(text: str, states: dict[str, Any] | None = None, **option_overrides: Any):
    states = _states() if states is None else states
    cleaned, markers = panel_module.extract_markers(text)
    calls = panel_module.plan_calls(markers, _panel(**option_overrides), states.get)
    return cleaned, calls


class PanelBridge(FakeBridge):
    """Records the panel fields the agent adds to the Hermes query."""

    def __init__(self, reply: str) -> None:
        super().__init__(reply)
        self.kwargs: list[dict[str, Any]] = []

    async def async_send_conversation_query(
        self,
        text: str,
        conversation_id: str | None = None,
        language: str = "en",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.kwargs.append(kwargs)
        return await super().async_send_conversation_query(text, conversation_id, language)


class FakePanelHass:
    """Just enough of ``hass`` for the panel path: states, services, tasks."""

    def __init__(self, states: dict[str, Any] | None = None, fail: bool = False) -> None:
        self._states = _states() if states is None else states
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._async_call)
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        self.tasks: list[Any] = []
        self._fail = fail

    async def _async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        if self._fail:
            raise RuntimeError("device offline")

    def async_create_task(self, coro, name=None):
        self.tasks.append((coro, name))
        return coro

    async def run_tasks(self) -> None:
        for coro, _name in self.tasks:
            await coro


def _panel_agent(reply: str, options: dict[str, Any] | None = None, **hass_kwargs):
    panel_options = PANEL_OPTIONS if options is None else options
    entry = SimpleNamespace(
        options={CONF_LOCAL_INTENTS: LOCAL_INTENTS_OFF, **panel_options},
        entry_id="entry-1",
    )
    bridge = PanelBridge(reply)
    agent = agent_module.HermesConversationAgent(bridge, "entry-1", entry)
    agent.hass = FakePanelHass(**hass_kwargs)
    return agent, bridge, agent.hass


def _panel_input(text: str, device_id: str | None = PANEL_DEVICE, context: Any = None):
    return _CONVERSATION.ConversationInput(
        text=text, conversation_id="cid-1", device_id=device_id, context=context
    )


@needs_stubs
def test_markers_are_removed_from_speech_and_parsed() -> None:
    cleaned, markers = panel_module.extract_markers(
        '[HW:/display/info:{"text":"14:30"}] [HW:/light:{"brightness_pct":40}]'
        "It's half past two."
    )

    assert cleaned == "It's half past two."
    assert markers == [
        panel_module.Marker("/display/info", {"text": "14:30"}),
        panel_module.Marker("/light", {"brightness_pct": 40}),
    ]


@needs_stubs
def test_marker_body_may_contain_closing_brackets() -> None:
    cleaned, markers = panel_module.extract_markers(
        '[HW:/display/info:{"text":"[1] Kitchen"}] Done.'
    )
    assert cleaned == "Done."
    assert markers == [panel_module.Marker("/display/info", {"text": "[1] Kitchen"})]


@pytest.mark.parametrize(
    "reply",
    [
        '[HW:/light:{"brightness_pct":40] Okay.',  # broken JSON
        '[HW:/light:{"brightness_pct":40} Okay.',  # missing closing bracket
        "[HW:/light:40] Okay.",  # body is not a JSON object
        '[HW:/light:["brightness_pct",40]] Okay.',  # JSON, but not an object
        '[HW:{"brightness_pct":40}] Okay.',  # no route
        '[light](HW:/light:{"brightness_pct":40}) Okay.',  # link-style
        '[HW:/light:{"brightness_pct":40',  # cut off at the end of the reply
    ],
)
@needs_stubs
def test_malformed_markers_are_removed_but_never_run(reply: str) -> None:
    cleaned, calls = _plan(reply)

    assert "HW:" not in cleaned
    assert "brightness" not in cleaned
    assert calls == []


@needs_stubs
def test_link_style_marker_keeps_its_label() -> None:
    cleaned, markers = panel_module.extract_markers(
        'Turning the [screen](HW:/light:{"brightness_pct":40}) down.'
    )
    assert cleaned == "Turning the screen down."
    assert markers == []


@pytest.mark.parametrize(
    "reply",
    [
        "The HW: prefix means hardware.",
        "Step [1] is done [note: check later].",
        "",
    ],
)
@needs_stubs
def test_text_without_markers_is_unchanged(reply: str) -> None:
    assert panel_module.extract_markers(reply) == (reply, [])


@needs_stubs
def test_brightness_and_volume_are_clamped_to_configured_range() -> None:
    _cleaned, calls = _plan(
        '[HW:/light:{"brightness_pct":100}][HW:/volume:{"value":5}] Okay.'
    )
    assert calls == [
        panel_module.ServiceCall(
            "light", "turn_on", {"entity_id": "light.panel_backlight", "brightness_pct": 80}
        ),
        panel_module.ServiceCall(
            "number", "set_value", {"entity_id": "number.panel_volume", "value": 20}
        ),
    ]

    _cleaned, calls = _plan('[HW:/light:{"brightness_pct":0}] Okay.')
    assert calls[0].data["brightness_pct"] == 10


@needs_stubs
def test_volume_percent_maps_onto_entity_range_and_step() -> None:
    states = _states(
        **{
            "number.panel_volume": SimpleNamespace(
                attributes={"min": 0, "max": 1, "step": 0.05}
            )
        }
    )
    _cleaned, calls = _plan('[HW:/volume:{"value":33}] Okay.', states)
    assert calls == [
        panel_module.ServiceCall(
            "number", "set_value", {"entity_id": "number.panel_volume", "value": 0.35}
        )
    ]


@needs_stubs
def test_volume_is_skipped_when_entity_has_no_range() -> None:
    states = _states(**{"number.panel_volume": SimpleNamespace(attributes={})})
    _cleaned, calls = _plan('[HW:/volume:{"value":50}] Okay.', states)
    assert calls == []


@needs_stubs
def test_hud_text_is_cut_to_the_lowest_limit_and_flattened() -> None:
    states = _states(**{"text.panel_hud": SimpleNamespace(attributes={"max": 10})})
    _cleaned, calls = _plan(
        '[HW:/display/info:{"text":"Kitchen\\nlights are on"}] Okay.', states
    )
    assert calls == [
        panel_module.ServiceCall(
            "text", "set_value", {"entity_id": "text.panel_hud", "value": "Kitchen li"}
        )
    ]

    _cleaned, calls = _plan(
        '[HW:/display/info:{"text":"abcdefghij"}] Okay.',
        **{CONF_PANEL_HUD_MAX_LENGTH: 4},
    )
    assert calls[0].data["value"] == "abcd"


@pytest.mark.parametrize(
    "marker",
    [
        '[HW:/light:{"brightness_pct":true}]',
        '[HW:/light:{"brightness_pct":"40"}]',
        '[HW:/light:{"brightness_pct":NaN}]',
        '[HW:/light:{"brightness_pct":Infinity}]',
        '[HW:/volume:{"value":null}]',
        '[HW:/display/info:{"text":{"nested":1}}]',
        '[HW:/display/info:{"subtitle":"no text"}]',
    ],
)
@needs_stubs
def test_markers_with_unusable_values_are_skipped(marker: str) -> None:
    cleaned, calls = _plan(f"{marker} Okay.")
    assert cleaned == "Okay."
    assert calls == []


@needs_stubs
def test_unknown_disabled_and_missing_routes_are_dropped() -> None:
    reply = (
        '[HW:/door/unlock:{"value":1}]'
        '[HW:/volume:{"value":50}]'
        '[HW:/light:{"brightness_pct":50}]'
        " Okay."
    )
    states = _states()
    del states["light.panel_backlight"]

    cleaned, calls = _plan(reply, states, **{CONF_PANEL_VOLUME_ENTITY: ""})

    assert cleaned == "Okay."
    assert calls == []


@needs_stubs
def test_only_the_first_marker_per_route_runs() -> None:
    _cleaned, calls = _plan(
        '[HW:/light:{"brightness_pct":30}][HW:/light:{"brightness_pct":70}] Okay.'
    )
    assert [call.data["brightness_pct"] for call in calls] == [30]


@pytest.mark.parametrize(
    "overrides",
    [
        {CONF_PANEL_DEVICE: ""},
        {
            CONF_PANEL_HUD_ENTITY: "",
            CONF_PANEL_LIGHT_ENTITY: "",
            CONF_PANEL_VOLUME_ENTITY: "",
        },
        {
            # Entities from the wrong domain never enable a route.
            CONF_PANEL_HUD_ENTITY: "lock.front_door",
            CONF_PANEL_LIGHT_ENTITY: "switch.heater",
            CONF_PANEL_VOLUME_ENTITY: "light.kitchen",
        },
    ],
)
@needs_stubs
def test_panel_feature_is_off_until_device_and_entity_are_set(overrides) -> None:
    assert panel_module.panel_config_from_options({**PANEL_OPTIONS, **overrides}) is None
    assert panel_module.panel_config_from_options({}) is None
    assert panel_module.panel_config_from_options(None) is None


@needs_stubs
def test_panel_limits_are_normalised() -> None:
    config = _panel(
        **{
            CONF_PANEL_BRIGHTNESS_MIN: 90,
            CONF_PANEL_BRIGHTNESS_MAX: 50,
            CONF_PANEL_VOLUME_MAX: 500,
            CONF_PANEL_HUD_MAX_LENGTH: 10_000,
        }
    )
    assert (config.brightness_min, config.brightness_max) == (50, 50)
    assert config.volume_max == 100
    assert config.hud_max_length == 255
    assert config.as_payload() == {
        "routes": {
            "/display/info": {"max_length": 255},
            "/light": {"min": 50, "max": 50},
            "/volume": {"min": 20, "max": 100},
        }
    }


@needs_stubs
async def test_panel_turn_dispatches_bounded_calls_and_speaks_clean_text() -> None:
    reply = (
        '[HW:/display/info:{"text":"Lights off"}] [HW:/light:{"brightness_pct":100}] '
        "All the downstairs lights are off."
    )
    agent, bridge, hass = _panel_agent(reply)
    context = object()

    result = await agent.async_process(_panel_input("turn off downstairs", context=context))

    assert _speech(result) == "All the downstairs lights are off."
    assert bridge.kwargs == [
        {
            "device_id": PANEL_DEVICE,
            "panel": {
                "routes": {
                    "/display/info": {"max_length": 60},
                    "/light": {"min": 10, "max": 80},
                    "/volume": {"min": 20, "max": 70},
                }
            },
        }
    ]
    # Calls run in a background task, never inline with the reply.
    assert hass.calls == []
    assert len(hass.tasks) == 1
    await hass.run_tasks()
    assert hass.calls == [
        (
            "text",
            "set_value",
            {"entity_id": "text.panel_hud", "value": "Lights off"},
            {"blocking": False, "context": context},
        ),
        (
            "light",
            "turn_on",
            {"entity_id": "light.panel_backlight", "brightness_pct": 80},
            {"blocking": False, "context": context},
        ),
    ]


@needs_stubs
async def test_marker_only_reply_speaks_a_short_confirmation() -> None:
    agent, _bridge, hass = _panel_agent('[HW:/volume:{"value":40}]')

    result = await agent.async_process(_panel_input("volume to forty"))

    assert _speech(result) == "Done."
    await hass.run_tasks()
    assert hass.calls[0][:3] == (
        "number",
        "set_value",
        {"entity_id": "number.panel_volume", "value": 40},
    )


@needs_stubs
async def test_device_failure_does_not_break_the_reply() -> None:
    agent, _bridge, hass = _panel_agent(
        '[HW:/light:{"brightness_pct":40}] Dimmed.', fail=True
    )

    result = await agent.async_process(_panel_input("dim the screen"))

    assert _speech(result) == "Dimmed."
    await hass.run_tasks()  # the failure is logged, not raised
    assert len(hass.calls) == 1


@pytest.mark.parametrize(
    ("device_id", "options"),
    [
        ("kitchen-speaker", None),  # a different Assist device
        (None, None),  # typed in the HA UI, no device
        (PANEL_DEVICE, {}),  # feature not configured
    ],
)
@needs_stubs
async def test_non_panel_turns_strip_markers_without_dispatching(
    device_id, options
) -> None:
    reply = '[HW:/light:{"brightness_pct":40}] Okay.'
    agent, bridge, hass = _panel_agent(reply, options=options)

    result = await agent.async_process(_panel_input("hello", device_id=device_id))

    assert bridge.kwargs == [{}]
    assert _speech(result) == "Okay."
    assert hass.tasks == []
    assert hass.calls == []


@needs_stubs
async def test_non_panel_marker_only_reply_does_not_claim_done() -> None:
    agent, bridge, hass = _panel_agent('[HW:/display/info:{"text":"23:28"}]')

    result = await agent.async_process(_panel_input("what time is it", device_id=None))

    assert bridge.kwargs == [{}]
    assert _speech(result) == "I processed your request but got no response."
    assert hass.tasks == []
    assert hass.calls == []


@needs_stubs
async def test_bridge_adds_panel_fields_only_when_given(monkeypatch) -> None:
    from custom_components.hermes import HermesBridge

    sent: list[dict[str, Any]] = []

    class _RecordingWS:
        async def send_json(self, payload: dict[str, Any]) -> None:
            sent.append(payload)

    async def fake_wait_for(future, timeout=None):
        future.cancel()
        return {"text": "ok"}

    monkeypatch.setattr("custom_components.hermes.asyncio.wait_for", fake_wait_for)
    bridge = SimpleNamespace(_pending_queries={}, _connected=True, _ws=_RecordingWS())

    await HermesBridge.async_send_conversation_query(bridge, text="hi", conversation_id="c1")
    await HermesBridge.async_send_conversation_query(
        bridge,
        text="hi",
        conversation_id="c2",
        device_id=PANEL_DEVICE,
        panel={"routes": {"/light": {"min": 10, "max": 80}}},
    )

    assert sent[0] == {
        "type": "assist_query",
        "text": "hi",
        "conversation_id": "c1",
        "language": "en",
    }
    assert sent[1]["device_id"] == PANEL_DEVICE
    assert sent[1]["panel"] == {"routes": {"/light": {"min": 10, "max": 80}}}


@needs_stubs
async def test_options_flow_panel_step_saves_normalised_values() -> None:
    entry = SimpleNamespace(options={"entity_filter": ["light.kitchen"]})
    flow = config_flow_module.HermesOptionsFlow(entry)
    await flow.async_step_init({"entity_filter": "light.kitchen", "verify_ssl": True})
    result = await flow.async_step_voice({})
    assert result["step_id"] == "panel"

    result = await flow.async_step_panel(
        {
            CONF_PANEL_DEVICE: f" {PANEL_DEVICE} ",
            CONF_PANEL_HUD_ENTITY: "text.panel_hud",
            CONF_PANEL_LIGHT_ENTITY: "switch.not_a_light",
            CONF_PANEL_BRIGHTNESS_MAX: 150,
        }
    )

    assert result["type"] == "create_entry"
    data = result["data"]
    assert data[CONF_PANEL_DEVICE] == PANEL_DEVICE
    assert data[CONF_PANEL_HUD_ENTITY] == "text.panel_hud"
    assert data[CONF_PANEL_LIGHT_ENTITY] == ""
    assert data[CONF_PANEL_VOLUME_ENTITY] == ""
    assert data[CONF_PANEL_BRIGHTNESS_MAX] == 100
    assert data["entity_filter"] == ["light.kitchen"]


@needs_stubs
async def test_options_flow_panel_step_rejects_min_above_max() -> None:
    flow = config_flow_module.HermesOptionsFlow(SimpleNamespace(options={}))

    result = await flow.async_step_panel(
        {CONF_PANEL_VOLUME_MIN: 90, CONF_PANEL_VOLUME_MAX: 30}
    )

    assert result["type"] == "form"
    assert result["errors"] == {CONF_PANEL_VOLUME_MIN: "panel_min_above_max"}
