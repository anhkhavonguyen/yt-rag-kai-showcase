"""The tracing wrapper: no-op when off, span nesting, text capture, error sanitizing, setup."""

import logging
import sys
from types import SimpleNamespace

import pytest

from app.core import observability
from app.core.observability import DatadogRecorder as RealDatadogRecorder
from conftest import FakeRecorder

QUESTION = "What can Kai do?"


class ProviderError(Exception):
    status_code = 429


# --- Off by default --------------------------------------------------------


def test_spans_are_noops_when_tracing_is_off():
    with observability.workflow("answer_question") as span:
        span.record(input=QUESTION, metadata={"top_k": 6})
        span.fail("SomeError", 500)
        with observability.llm("chat_completion", model="m", provider="google") as child:
            child.record(output="answer")
            assert observability.current_trace_id() is None
    observability.flush()  # nothing to send, and no error


def test_exceptions_pass_through_noop_spans_unchanged():
    error = ValueError("boom")
    with pytest.raises(ValueError) as excinfo:
        with observability.task("save_chunks"):
            raise error
    assert excinfo.value is error


# --- Nesting ---------------------------------------------------------------


def test_nested_spans_record_parent_links(recorder):
    with observability.workflow("answer_question"):
        with observability.embedding("embed_texts", model="gemini-embedding-2", provider="google"):
            pass
        with observability.retrieval("vector_search"):
            pass
        with observability.llm("chat_completion", model="gemini-3.5-flash", provider="google"):
            pass

    [root] = recorder.roots()
    assert root["kind"] == "workflow" and root["name"] == "answer_question"
    assert [(s["kind"], s["name"]) for s in recorder.children(root)] == [
        ("embedding", "embed_texts"),
        ("retrieval", "vector_search"),
        ("llm", "chat_completion"),
    ]
    assert {s["trace_id"] for s in recorder.spans} == {root["trace_id"]}
    assert all(s["finished"] for s in recorder.spans)
    llm = recorder.of_kind("llm")[0]
    assert (llm["model"], llm["provider"]) == ("gemini-3.5-flash", "google")


def test_current_trace_id_is_the_open_spans_trace(recorder):
    assert observability.current_trace_id() is None
    with observability.workflow("answer_question"):
        trace_id = observability.current_trace_id()
    assert trace_id == recorder.spans[0]["trace_id"]
    assert observability.current_trace_id() is None


def test_record_merges_fields_and_sends_them_when_the_span_closes(recorder):
    with observability.workflow("seed_knowledge_base") as span:
        span.record(input="docs", metadata={"documents": 3})
        span.record(output="done", metadata={"chunks": 12}, metrics={"x": 1}, tags={"answer_mode": "generated"})

    [root] = recorder.spans
    assert root["input"] == "docs" and root["output"] == "done"
    assert root["metadata"] == {"documents": 3, "chunks": 12}
    assert root["metrics"] == {"x": 1}
    assert root["tags"] == {"answer_mode": "generated"}


class BrokenRecorder:
    """Every call fails, as if the SDK misbehaved."""

    def __getattr__(self, name):
        def broken(*args, **kwargs):
            raise RuntimeError("sdk broke")
        return broken


def test_a_failing_recorder_never_breaks_the_caller(caplog):
    observability.use_recorder(BrokenRecorder())

    with caplog.at_level(logging.DEBUG, logger="app.core.observability"):
        with observability.workflow("answer_question") as span:
            span.record(input=QUESTION)
            result = "answered"
        observability.flush()

    assert result == "answered"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# --- Text capture ----------------------------------------------------------


def record_one_of_each(recorder):
    with observability.workflow("answer_question") as root:
        root.record(input=QUESTION, output="Kai leads teams.", metadata={"top_k": 6})
        with observability.embedding("embed_texts", model="e", provider="google") as span:
            span.record(input=[{"text": QUESTION}])
        with observability.retrieval("vector_search") as span:
            span.record(
                input=QUESTION,
                output=[{"id": "skills#1", "name": "Skills", "score": 0.82, "text": "Kai builds RAG apps."}],
            )
        with observability.llm("chat_completion", model="m", provider="google") as span:
            span.record(
                input=[{"role": "system", "content": "Rules."}, {"role": "user", "content": QUESTION}],
                output=[{"role": "assistant", "content": "Kai leads teams."}],
            )
    return {span["kind"]: span for span in recorder.spans}


def test_text_is_captured_by_default(recorder):
    spans = record_one_of_each(recorder)

    assert spans["workflow"]["input"] == QUESTION
    assert spans["embedding"]["input"] == [{"text": QUESTION}]
    assert spans["retrieval"]["output"][0]["text"] == "Kai builds RAG apps."
    assert spans["llm"]["input"][1] == {"role": "user", "content": QUESTION}
    assert spans["llm"]["output"][0]["content"] == "Kai leads teams."


def test_text_capture_off_keeps_only_lengths_and_labels():
    fake = FakeRecorder()
    observability.use_recorder(fake, capture_text=False)

    spans = record_one_of_each(fake)

    assert QUESTION not in fake.dump()
    assert "Kai leads teams." not in fake.dump()
    assert "Kai builds RAG apps." not in fake.dump()
    assert spans["workflow"]["input"] == f"[text omitted: {len(QUESTION)} chars]"
    assert spans["workflow"]["metadata"] == {"top_k": 6}
    assert spans["embedding"]["input"] == [{"text": f"[text omitted: {len(QUESTION)} chars]"}]
    assert spans["retrieval"]["output"] == [
        {"id": "skills#1", "name": "Skills", "score": 0.82, "text": "[text omitted: 20 chars]"}
    ]
    assert spans["llm"]["input"] == [
        {"role": "system", "content": "[text omitted: 6 chars]"},
        {"role": "user", "content": f"[text omitted: {len(QUESTION)} chars]"},
    ]
    assert spans["llm"]["output"] == [{"role": "assistant", "content": "[text omitted: 16 chars]"}]


# --- Errors ----------------------------------------------------------------


def test_errors_are_recorded_by_type_and_status_only(recorder):
    error = ProviderError("provider-detail-xyz")

    with pytest.raises(ProviderError) as excinfo:
        with observability.workflow("answer_question"):
            with observability.llm("chat_completion", model="m", provider="google"):
                raise error

    assert excinfo.value is error
    llm, root = recorder.of_kind("llm")[0], recorder.roots()[0]
    assert llm["error"] == {"type": "ProviderError", "http_status": 429}
    assert root["error"] == {"type": "ProviderError", "http_status": 429}
    assert all(s["finished"] for s in recorder.spans)
    assert "provider-detail-xyz" not in recorder.dump()


def test_an_explicit_failure_is_kept_when_another_error_follows(recorder):
    with pytest.raises(RuntimeError):
        with observability.llm("chat_completion", model="m", provider="google") as span:
            span.fail("RateLimitError", 429)
            raise RuntimeError("sanitized wrapper error")

    assert recorder.spans[0]["error"] == {"type": "RateLimitError", "http_status": 429}


# --- Evaluations -----------------------------------------------------------


def test_evaluation_types_come_from_the_value(recorder):
    with observability.workflow("answer_question") as span:
        span.evaluate("citations_valid", True, assessment="pass")
        span.evaluate("retrieval_top_score", 0.82)
        span.evaluate("passages", 4)

    assert recorder.spans[0]["evaluations"] == [
        {"label": "citations_valid", "metric_type": "boolean", "value": True, "assessment": "pass",
         "after_finish": True},
        {"label": "retrieval_top_score", "metric_type": "score", "value": 0.82, "assessment": None,
         "after_finish": True},
        {"label": "passages", "metric_type": "score", "value": 4, "assessment": None, "after_finish": True},
    ]


def test_evaluations_are_sent_after_the_span_finishes(recorder):
    with observability.workflow("answer_question") as span:
        span.evaluate("plain_text", True)
        assert recorder.spans[0]["evaluations"] == []  # nothing sent while open

    assert recorder.spans[0]["evaluations"][0]["after_finish"] is True


@pytest.mark.parametrize("value", ["Kai leads teams.", None, ["skills#1"], {"a": 1}])
def test_evaluation_values_other_than_numbers_and_booleans_are_dropped(recorder, caplog, value):
    with caplog.at_level(logging.DEBUG, logger="app.core.observability"):
        with observability.workflow("answer_question") as span:
            span.evaluate("answer", value)
            span.evaluate("other", value)

    assert recorder.spans[0]["evaluations"] == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    assert "Kai leads teams." not in caplog.text


def test_noop_span_evaluate_does_nothing():
    with observability.workflow("answer_question") as span:
        assert span.recording is False
        span.evaluate("citations_valid", True, assessment="pass")


def test_real_span_is_recording(recorder):
    with observability.workflow("answer_question") as span:
        assert span.recording is True


class EvaluateFailsRecorder(FakeRecorder):
    def evaluate(self, raw, label, metric_type, value, assessment):
        raise RuntimeError("intake rejected")


def test_a_failing_evaluation_is_swallowed_and_the_span_still_finishes():
    fake = EvaluateFailsRecorder()
    observability.use_recorder(fake)

    with observability.workflow("answer_question") as span:
        span.evaluate("plain_text", True)
        result = "answered"

    assert result == "answered"
    assert fake.spans[0]["finished"] is True


# --- Provider labels -------------------------------------------------------


@pytest.mark.parametrize(
    ("base_url", "ai_provider", "expected"),
    [
        ("https://generativelanguage.googleapis.com/v1beta/openai/", "openai", "google"),
        (None, "openai", "openai"),
        ("", "openai", "openai"),
        ("https://api.openai.com/v1", "openai", "openai"),
        ("https://generativelanguage.googleapis.com/v1beta/openai/", "anthropic", "anthropic"),
        ("https://my-proxy.example.com/v1", "openai", "custom"),
    ],
)
def test_provider_label(base_url, ai_provider, expected):
    assert observability.provider_label(base_url, ai_provider) == expected


# --- DatadogRecorder against a fake SDK -----------------------------------


class FakeSDKSpan:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.error = 0
        self.tags: dict = {}
        self.finished = False

    def set_tag(self, key, value):
        self.tags[key] = value

    def finish(self):
        self.finished = True


class FakeLLMObs:
    """Stands in for ddtrace.llmobs.LLMObs."""

    def __init__(self, enable_error: Exception | None = None):
        self.enable_error = enable_error
        self.enable_calls: list[dict] = []
        self.annotations: list[dict] = []
        self.evaluations: list[dict] = []
        self.flushes = 0

    def enable(self, **kwargs):
        self.enable_calls.append(kwargs)
        if self.enable_error:
            raise self.enable_error

    def _span(self, **kwargs):
        return FakeSDKSpan(**kwargs)

    workflow = task = retrieval = llm = embedding = _span

    def annotate(self, span=None, **kwargs):
        self.annotations.append(kwargs)

    def export_span(self, span):
        return {"span_id": "1", "trace_id": "abc123"}

    def submit_evaluation(self, **kwargs):
        self.evaluations.append(kwargs)

    def flush(self):
        self.flushes += 1


def test_datadog_recorder_maps_spans_onto_the_sdk():
    sdk = FakeLLMObs()
    observability.use_recorder(RealDatadogRecorder(sdk))

    with observability.workflow("answer_question") as root:
        root.record(input=QUESTION)
        assert observability.current_trace_id() == "abc123"
        with pytest.raises(ProviderError):
            with observability.llm("chat_completion", model="gemini-3.5-flash", provider="google") as span:
                span.record(metrics={"input_tokens": 812})
                raise ProviderError("provider-detail-xyz")
    observability.flush()

    root_raw, llm_raw = root.raw, span.raw
    assert root_raw.kwargs == {"name": "answer_question"}
    assert llm_raw.kwargs == {"model_name": "gemini-3.5-flash", "name": "chat_completion", "model_provider": "google"}
    assert llm_raw.error == 1
    assert llm_raw.tags == {"error.type": "ProviderError", "error.message": "ProviderError (HTTP 429)"}
    assert "provider-detail-xyz" not in repr(llm_raw.tags)
    assert llm_raw.finished and root_raw.finished
    assert sdk.annotations[0] == {"metrics": {"input_tokens": 812}}  # empty fields left out
    assert sdk.annotations[1] == {"input_data": QUESTION}
    assert sdk.flushes == 1


def test_datadog_recorder_submits_evaluations_for_the_exported_span():
    sdk = FakeLLMObs()
    observability.use_recorder(RealDatadogRecorder(sdk))

    with observability.workflow("answer_question") as span:
        span.evaluate("citations_valid", False, assessment="fail")
        span.evaluate("retrieval_top_score", 0.82)

    assert span.raw.finished
    assert sdk.evaluations == [
        {"span": {"span_id": "1", "trace_id": "abc123"}, "label": "citations_valid", "metric_type": "boolean",
         "value": False, "assessment": "fail"},
        {"span": {"span_id": "1", "trace_id": "abc123"}, "label": "retrieval_top_score", "metric_type": "score",
         "value": 0.82, "assessment": None},
    ]
    assert all("ml_app" not in call for call in sdk.evaluations)


# --- setup -----------------------------------------------------------------


def settings_with(**overrides):
    values = dict(
        dd_api_key="dd-test-key-123",
        dd_site="ap1.datadoghq.com",
        dd_llmobs_ml_app="yt-rag",
        observability_enabled=True,
        observability_capture_text=True,
        environment="production",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


SDK_ENV = ["DD_APM_TRACING_ENABLED", "DD_REMOTE_CONFIGURATION_ENABLED", "DD_INSTRUMENTATION_TELEMETRY_ENABLED",
           "DD_VERSION", "RENDER_GIT_COMMIT"]


@pytest.fixture
def fake_sdk(monkeypatch):
    """setup() loads this fake instead of ddtrace; SDK environment variables restored afterwards."""
    for name in SDK_ENV:
        monkeypatch.delenv(name, raising=False)
    sdk = FakeLLMObs()
    monkeypatch.setattr(observability, "_load_llmobs", lambda: sdk)
    monkeypatch.setattr(observability, "DatadogRecorder", RealDatadogRecorder)
    return sdk


@pytest.mark.parametrize("overrides", [{"dd_api_key": ""}, {"dd_api_key": "   "}, {"observability_enabled": False}])
def test_setup_leaves_tracing_off_without_a_key_or_when_disabled(monkeypatch, overrides):
    loads = []
    monkeypatch.setattr(observability, "_load_llmobs", lambda: loads.append(1))

    assert observability.setup(settings_with(**overrides)) is False

    assert loads == []
    assert "ddtrace" not in sys.modules
    with observability.workflow("answer_question"):
        assert observability.current_trace_id() is None


def test_setup_enables_agentless_tracing_with_integrations_off(fake_sdk, monkeypatch, caplog):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "aa06dec")

    with caplog.at_level(logging.INFO, logger="app.core.observability"):
        assert observability.setup(settings_with()) is True

    assert fake_sdk.enable_calls == [{
        "ml_app": "yt-rag",
        "api_key": "dd-test-key-123",
        "site": "ap1.datadoghq.com",
        "agentless_enabled": True,
        "integrations_enabled": False,
        "env": "production",
        "service": "yt-rag",
    }]
    import os

    assert os.environ["DD_APM_TRACING_ENABLED"] == "false"
    assert os.environ["DD_REMOTE_CONFIGURATION_ENABLED"] == "false"
    assert os.environ["DD_INSTRUMENTATION_TELEMETRY_ENABLED"] == "false"
    assert os.environ["DD_VERSION"] == "aa06dec"
    assert "site=ap1.datadoghq.com" in caplog.text
    assert "dd-test-key-123" not in caplog.text
    with observability.workflow("answer_question"):
        assert observability.current_trace_id() == "abc123"


def test_setup_passes_app_key_and_project_only_when_given(fake_sdk, caplog):
    with caplog.at_level(logging.DEBUG, logger="app.core.observability"):
        observability.setup(settings_with())
        observability.setup(settings_with(), app_key="dd-app-key-456", project_name="yt-rag")

    without, with_keys = fake_sdk.enable_calls
    assert "app_key" not in without and "project_name" not in without
    assert with_keys["app_key"] == "dd-app-key-456"
    assert with_keys["project_name"] == "yt-rag"
    assert "dd-app-key-456" not in caplog.text


def test_setup_keeps_sdk_settings_the_owner_already_set(fake_sdk, monkeypatch):
    monkeypatch.setenv("DD_APM_TRACING_ENABLED", "true")

    observability.setup(settings_with())

    import os

    assert os.environ["DD_APM_TRACING_ENABLED"] == "true"


def test_setup_defaults_an_empty_site(fake_sdk):
    observability.setup(settings_with(dd_site=""))

    assert fake_sdk.enable_calls[0]["site"] == "datadoghq.com"


def test_setup_passes_text_capture_setting_to_spans(fake_sdk):
    observability.setup(settings_with(observability_capture_text=False))

    with observability.workflow("answer_question") as span:
        span.record(input=QUESTION)

    assert fake_sdk.annotations == [{"input_data": f"[text omitted: {len(QUESTION)} chars]"}]


def test_setup_failure_leaves_tracing_off_with_one_warning(monkeypatch, caplog):
    for name in SDK_ENV:
        monkeypatch.delenv(name, raising=False)
    sdk = FakeLLMObs(enable_error=ValueError("DD_SITE is required ... dd-test-key-123"))
    monkeypatch.setattr(observability, "_load_llmobs", lambda: sdk)

    with caplog.at_level(logging.WARNING, logger="app.core.observability"):
        assert observability.setup(settings_with()) is False

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "dd-test-key-123" not in caplog.text
    with observability.workflow("answer_question"):
        assert observability.current_trace_id() is None
