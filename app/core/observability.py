"""
Optional tracing to Datadog Agent Observability (formerly LLM Observability).

Services describe each pipeline step through this module and never call the
Datadog SDK directly:

    with observability.workflow("answer_question") as span:
        span.record(input=question, metadata={"top_k": 6})

Tracing is on only after `setup()` finds a Datadog API key. Until then every
span is a cheap no-op and `ddtrace` is never imported, which covers tests, CI,
local development and a deployment without a key.

Rules enforced here, so no service can get them wrong:
- Errors are recorded by type and HTTP status only. Provider error messages
  can echo request or account details and never reach a span.
- With OBSERVABILITY_CAPTURE_TEXT=false, every text value in a span's input or
  output is replaced by its length.
- Evaluations (`span.evaluate`) hold only numbers and booleans, never text.
- A tracing failure is logged and swallowed; it never fails a request.

Design: openspec/changes/add-datadog-agent-observability/design.md, and for
evaluations openspec/changes/datadog-rag-evaluation/design.md
"""

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

DEFAULT_SITE = "datadoghq.com"
_GEMINI_HOST = "generativelanguage.googleapis.com"
_OPENAI_HOST = "api.openai.com"

# Input/output keys whose string values are labels, not visitor or document
# text, so they are kept when text capture is off: message roles, chunk IDs,
# document titles and scores.
_LABEL_KEYS = frozenset({"role", "id", "name", "score"})


class Recorder(Protocol):
    """Where spans go. `start` returns an opaque handle passed to the other methods."""

    def start(self, kind: str, name: str, model: Optional[str], provider: Optional[str], parent: Any) -> Any: ...

    def annotate(self, raw: Any, *, input: Any, output: Any, metadata: Dict[str, Any],
                 metrics: Dict[str, Any], tags: Dict[str, Any]) -> None: ...

    def fail(self, raw: Any, error_type: str, http_status: Optional[int]) -> None: ...

    def finish(self, raw: Any) -> None: ...

    def evaluate(self, raw: Any, label: str, metric_type: str, value: Any, assessment: Optional[str]) -> None: ...

    def trace_id(self, raw: Any) -> Optional[str]: ...

    def flush(self) -> None: ...


class NoopRecorder:
    """Records nothing. The default, and what stays in place when tracing is off."""

    def start(self, kind, name, model, provider, parent):
        return None

    def annotate(self, raw, *, input, output, metadata, metrics, tags):
        pass

    def fail(self, raw, error_type, http_status):
        pass

    def finish(self, raw):
        pass

    def evaluate(self, raw, label, metric_type, value, assessment):
        pass

    def trace_id(self, raw):
        return None

    def flush(self):
        pass


class DatadogRecorder:
    """Sends spans to Datadog Agent Observability through the `ddtrace` SDK."""

    def __init__(self, llmobs: Any):
        self._llmobs = llmobs  # the ddtrace.llmobs.LLMObs class

    def start(self, kind, name, model, provider, parent):
        # The SDK tracks the active span itself, so `parent` isn't needed.
        if kind in ("llm", "embedding"):
            return getattr(self._llmobs, kind)(model_name=model, name=name, model_provider=provider)
        return getattr(self._llmobs, kind)(name=name)

    def annotate(self, raw, *, input, output, metadata, metrics, tags):
        fields = {
            "input_data": input,
            "output_data": output,
            "metadata": metadata or None,
            "metrics": metrics or None,
            "tags": tags or None,
        }
        self._llmobs.annotate(span=raw, **{key: value for key, value in fields.items() if value is not None})

    def fail(self, raw, error_type, http_status):
        # Set the error fields directly instead of letting an exception pass
        # through the SDK span, which would record str(exception) and the stack.
        # Tag names are ddtrace.constants.ERROR_TYPE and ERROR_MSG.
        raw.error = 1
        raw.set_tag("error.type", error_type)
        raw.set_tag("error.message", f"{error_type} (HTTP {http_status})" if http_status else error_type)

    def finish(self, raw):
        raw.finish()

    def evaluate(self, raw, label, metric_type, value, assessment):
        # No ml_app: the SDK has deprecated it and uses the app given to enable().
        self._llmobs.submit_evaluation(
            span=self._llmobs.export_span(raw),
            label=label,
            metric_type=metric_type,
            value=value,
            assessment=assessment,
        )

    def trace_id(self, raw):
        exported = self._llmobs.export_span(raw)
        return exported["trace_id"] if exported else None

    def flush(self):
        self._llmobs.flush()


_NOOP = NoopRecorder()
_recorder: Recorder = _NOOP
_capture_text = True
_current: ContextVar[Optional["Span"]] = ContextVar("observability_current_span", default=None)
_warned = False
_sdk: Any = None  # the enabled LLMObs class, set by setup()


def _safely(action: str, call, *args, **kwargs):
    """Run a recorder call; on failure log once (then at debug level) and return None."""
    global _warned
    try:
        return call(*args, **kwargs)
    except Exception as e:
        if _warned:
            logger.debug("Tracing %s failed: %s", action, type(e).__name__)
        else:
            _warned = True
            logger.warning("Tracing %s failed (%s); requests are unaffected", action, type(e).__name__)
        return None


def _omit_text(value: Any, key: Optional[str] = None) -> Any:
    """`value` with every text replaced by "[text omitted: N chars]", labels kept."""
    if isinstance(value, str):
        return value if key in _LABEL_KEYS else f"[text omitted: {len(value)} chars]"
    if isinstance(value, dict):
        return {k: _omit_text(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_omit_text(item) for item in value]
    return value


def _metric_type(value: Any) -> str:
    """Datadog metric type for an evaluation value. Only numbers and booleans are allowed,
    so an evaluation can never carry visitor or document text."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "score"
    raise TypeError(f"evaluation values must be numbers or booleans, not {type(value).__name__}")


class Span:
    """An open span. Services describe their step with `record`, `fail` and `evaluate`.

    Fields are collected while the span is open and sent once, when it closes.
    """

    recording = True  # a real span: evaluations and fields reach the recorder

    def __init__(self, recorder: Recorder, raw: Any, parent: Optional["Span"], capture_text: bool):
        self._recorder = recorder
        self.raw = raw
        self.parent = parent
        self._capture_text = capture_text
        self._input: Any = None
        self._output: Any = None
        self._metadata: Dict[str, Any] = {}
        self._metrics: Dict[str, Any] = {}
        self._tags: Dict[str, Any] = {}
        self._evaluations: List[Tuple[str, str, Any, Optional[str]]] = []
        self.failed = False

    def record(self, *, input: Any = None, output: Any = None, metadata: Optional[Dict[str, Any]] = None,
               metrics: Optional[Dict[str, Any]] = None, tags: Optional[Dict[str, Any]] = None) -> None:
        """Set the step's input/output and add metadata, metrics and tags.

        Input and output may hold visitor or document text, so they follow the
        text-capture setting. Metadata, metrics and tags must hold no such text.
        """
        if input is not None:
            self._input = input if self._capture_text else _omit_text(input)
        if output is not None:
            self._output = output if self._capture_text else _omit_text(output)
        self._metadata.update(metadata or {})
        self._metrics.update(metrics or {})
        self._tags.update(tags or {})

    def fail(self, error_type: str, http_status: Optional[int] = None) -> None:
        """Mark the step as failed, by error type and HTTP status only."""
        if self.failed:
            return
        self.failed = True
        _safely("fail", self._recorder.fail, self.raw, error_type, http_status)

    def evaluate(self, label: str, value: Any, *, assessment: Optional[str] = None) -> None:
        """Attach an evaluation of this step, sent when the span closes.

        `value` must be a bool (a boolean metric) or a number (a score); any
        other value is dropped and logged. `assessment` is "pass", "fail" or None.
        """
        metric_type = _safely("evaluate", _metric_type, value)
        if metric_type is None:
            return
        self._evaluations.append((label, metric_type, value, assessment))

    def _close(self) -> None:
        _safely(
            "annotate",
            lambda: self._recorder.annotate(
                self.raw, input=self._input, output=self._output, metadata=self._metadata,
                metrics=self._metrics, tags=self._tags,
            ),
        )
        _safely("finish", self._recorder.finish, self.raw)
        # After finish, so each evaluation refers to a span that has been sent.
        for label, metric_type, value, assessment in self._evaluations:
            _safely("evaluate", self._recorder.evaluate, self.raw, label, metric_type, value, assessment)


class _NoopSpan:
    """Stands in for a span when tracing is off or a span couldn't start."""

    raw = None
    failed = False
    recording = False  # nothing is recorded, so callers can skip work meant only for traces

    def record(self, **fields) -> None:
        pass

    def fail(self, error_type: str, http_status: Optional[int] = None) -> None:
        pass

    def evaluate(self, label: str, value: Any, *, assessment: Optional[str] = None) -> None:
        pass


_NOOP_SPAN = _NoopSpan()


def http_status_of(error: BaseException) -> Optional[int]:
    """The HTTP status an SDK error carries, if any."""
    status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None


@contextmanager
def _span(kind: str, name: str, model: Optional[str] = None, provider: Optional[str] = None) -> Iterator[Any]:
    recorder = _recorder
    if recorder is _NOOP:
        yield _NOOP_SPAN
        return

    parent = _current.get()
    raw = _safely("start", recorder.start, kind, name, model, provider, parent.raw if parent else None)
    if raw is None:
        yield _NOOP_SPAN
        return

    span = Span(recorder, raw, parent, _capture_text)
    token = _current.set(span)
    try:
        yield span
    except Exception as e:
        # Record the type and status only, then let the exception continue
        # unchanged once the span is closed.
        span.fail(type(e).__name__, http_status_of(e))
        raise
    finally:
        _current.reset(token)
        span._close()


def workflow(name: str):
    """A whole request, such as answering one question."""
    return _span("workflow", name)


def task(name: str):
    """A step that isn't a model call or a search, such as a database write."""
    return _span("task", name)


def retrieval(name: str):
    """A search that returns documents."""
    return _span("retrieval", name)


def embedding(name: str, *, model: str, provider: str):
    """One embedding request to the model provider."""
    return _span("embedding", name, model, provider)


def llm(name: str, *, model: str, provider: str):
    """One chat model request. The only kind Datadog meters, so exactly one per call."""
    return _span("llm", name, model, provider)


def current_trace_id() -> Optional[str]:
    """The trace ID of the innermost open span, or None when tracing is off."""
    span = _current.get()
    if span is None:
        return None
    return _safely("trace ID lookup", span._recorder.trace_id, span.raw)


def flush() -> None:
    """Send buffered spans now. Called at shutdown; blocks until sent."""
    _safely("flush", _recorder.flush)


def provider_label(base_url: Optional[str], ai_provider: str = "openai") -> str:
    """Model provider shown in traces: google, openai, anthropic or custom."""
    if ai_provider == "anthropic":
        return "anthropic"
    try:
        host = urlsplit(base_url).hostname if base_url else None
    except ValueError:
        host = None
    if not base_url or host == _OPENAI_HOST:
        return "openai"
    if host == _GEMINI_HOST:
        return "google"
    return "custom"


def use_recorder(recorder: Recorder, *, capture_text: bool = True) -> None:
    """Replace the recorder. For tests and `setup` only."""
    global _recorder, _capture_text, _warned
    _recorder = recorder
    _capture_text = capture_text
    _warned = False


def sdk():
    """The enabled Datadog SDK (`LLMObs`), or None when tracing is off.

    For `python -m evals`, which records Datadog experiments; services use the
    span functions above instead.
    """
    return _sdk


def _set_sdk(llmobs: Any) -> None:
    global _sdk
    _sdk = llmobs


def reset() -> None:
    """Back to the default: tracing off."""
    _set_sdk(None)
    use_recorder(_NOOP)


def _sdk_environment() -> Dict[str, str]:
    """SDK settings applied before `ddtrace` is imported, unless already set.

    APM tracing off selects the SDK's LLMOBS_AGENTLESS mode: spans go straight
    to Datadog's intake with no APM traces and no local Datadog Agent.
    Telemetry and remote configuration are background traffic this app
    doesn't need.
    """
    values = {
        "DD_APM_TRACING_ENABLED": "false",
        "DD_REMOTE_CONFIGURATION_ENABLED": "false",
        "DD_INSTRUMENTATION_TELEMETRY_ENABLED": "false",
    }
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()  # set by Render
    if commit:
        values["DD_VERSION"] = commit
    return values


def _load_llmobs():
    """Import the SDK. Separate so tests can replace it."""
    from ddtrace.llmobs import LLMObs

    return LLMObs


def setup(settings, *, app_key: Optional[str] = None, project_name: Optional[str] = None) -> bool:
    """Turn tracing on when a Datadog API key is configured. Returns whether it's on.

    Without a key, or with OBSERVABILITY_ENABLED=false, nothing changes and
    `ddtrace` isn't imported. If the SDK fails to start, the app keeps running
    with tracing off and one warning is logged.

    `app_key` and `project_name` are for `python -m evals` only, which records
    Datadog experiments. The web app never passes them.
    """
    api_key = (settings.dd_api_key or "").strip()
    if not settings.observability_enabled or not api_key:
        return False

    site = (settings.dd_site or "").strip() or DEFAULT_SITE
    ml_app = (settings.dd_llmobs_ml_app or "").strip() or "yt-rag"
    try:
        for key, value in _sdk_environment().items():
            os.environ.setdefault(key, value)
        llmobs = _load_llmobs()
        experiments = {}
        if app_key:
            experiments["app_key"] = app_key
        if project_name:
            experiments["project_name"] = project_name
        llmobs.enable(
            ml_app=ml_app,
            api_key=api_key,
            site=site,
            agentless_enabled=True,
            integrations_enabled=False,  # our spans only: no duplicate LLM spans
            env=settings.environment,
            service=ml_app,
            **experiments,
        )
    except Exception as e:
        logger.warning("Datadog tracing could not start (%s); continuing with tracing off", type(e).__name__)
        return False

    use_recorder(DatadogRecorder(llmobs), capture_text=settings.observability_capture_text)
    _set_sdk(llmobs)
    logger.info(
        "Datadog Agent Observability tracing is on: site=%s, app=%s, text capture %s",
        site, ml_app, "on" if settings.observability_capture_text else "off",
    )
    return True
