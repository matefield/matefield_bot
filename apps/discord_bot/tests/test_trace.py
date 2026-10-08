import pytest
import hikari
from src.trace import (
    TraceEvent,
    EventCollectorObserver,
    NullTracer,
    DevActionTracer,
    get_tracer,
)


def test_null_tracer_is_noop():
    tracer = NullTracer()
    tracer.record("Test step", category="DB", action="FETCH")

    with tracer.measure("Dummy step", category="RCON") as ctx:
        ctx["details"] = "something"

    embed = hikari.Embed(title="Original Title")
    modified_embed = tracer.attach_to_embed(embed)
    assert len(modified_embed.fields) == 0

    msg = "Original message"
    assert tracer.append_to_message(msg) == msg


def test_dev_action_tracer_collects_events():
    tracer = DevActionTracer()

    tracer.record(
        step="Verificar usuario en BD",
        category="DB",
        action="FETCH",
        status="OK",
        details="Steam: 76561198000000001",
        target="Discord: 12345",
        duration_ms=15.2,
    )

    with tracer.measure("Sincronizar roles", category="DISCORD", action="SYNC", target="User: 12345") as ctx:
        ctx["details"] = "+2 roles añadidos"

    assert len(tracer.collector.events) == 2
    ev1, ev2 = tracer.collector.events

    assert ev1.category == "DB"
    assert ev1.action == "FETCH"
    assert ev1.status == "OK"
    assert ev1.details is not None
    assert "76561198000000001" in ev1.details
    assert ev1.duration_ms == 15.2

    assert ev2.category == "DISCORD"
    assert ev2.action == "SYNC"
    assert ev2.status == "OK"
    assert ev2.details is not None
    assert "+2 roles" in ev2.details
    assert ev2.duration_ms >= 0


def test_dev_action_tracer_captures_exceptions():
    tracer = DevActionTracer()

    with pytest.raises(ValueError, match="Connection refused"):
        with tracer.measure("Conexión RCON", category="RCON", action="EXEC", target="Server #1"):
            raise ValueError("Connection refused")

    assert len(tracer.collector.events) == 1
    ev = tracer.collector.events[0]
    assert ev.status == "ERROR"
    assert ev.error is not None
    assert "Connection refused" in ev.error


def test_dev_action_tracer_attaches_to_embed():
    tracer = DevActionTracer()
    tracer.record("Actualizar cupos", category="RCON", action="UPDATE", status="OK", details="12 slots activos")

    embed = hikari.Embed(title="Resultado")
    tracer.attach_to_embed(embed)

    assert len(embed.fields) == 1
    field = embed.fields[0]
    assert "DEV TRACE" in field.name
    assert "[RCON:UPDATE]" in field.value
    assert "12 slots activos" in field.value


def test_dev_action_tracer_appends_to_message():
    tracer = DevActionTracer()
    tracer.record("Configuración guardada", category="CONFIG", action="UPDATE", details="KEY=VALUE")

    result = tracer.append_to_message("✅ Operación exitosa.")
    assert "✅ Operación exitosa." in result
    assert "DEV TRACE" in result
    assert "[CONFIG:UPDATE]" in result


def test_get_tracer_factory():
    prod_tracer = get_tracer(force_dev=False)
    assert isinstance(prod_tracer, NullTracer)

    dev_tracer = get_tracer(force_dev=True)
    assert isinstance(dev_tracer, DevActionTracer)
