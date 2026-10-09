"""
apps/discord_bot/src/trace.py

Sistema de Trazabilidad y Diagnóstico para comandos en DEV.
Implementa el patrón Observer combinado con el patrón Null Object:
- En DEV (APP_ENV=development/local/dev): Registra cada micro-operación (DB, RCON, Steam, Discord),
  mide tiempos y formatea un reporte estructurado y visual de qué se modificó o ejecutó.
- En PROD (APP_ENV=production): Se utiliza automáticamente NullTracer (Null Object),
  asegurando costo computacional cero, cero roundtrips HTTP adicionales y cero riesgo de bugs.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import hikari
from wardogs_config import BOT_SETTINGS

logger = logging.getLogger("wardogs.trace")


@dataclass
class TraceEvent:
    """Representa una operación unitaria observada durante la ejecución de un comando."""
    step: str
    category: str = "SYS"  # DB, DISCORD, RCON, STEAM, CACHE, CONFIG, SYS
    action: str = "EXEC"   # FETCH, CREATE, UPDATE, DELETE, SYNC, EXEC, VALIDATE
    status: str = "OK"     # OK, WARN, ERROR, SKIP
    details: str | None = None
    target: str | None = None
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def status_emoji(self) -> str:
        mapping = {
            "OK": "✅",
            "WARN": "⚠️",
            "ERROR": "❌",
            "SKIP": "⏭️",
        }
        return mapping.get(self.status, "ℹ️")


# ============================================================================
# Observer Pattern: Interfaces y Observadores Concretos
# ============================================================================

class TraceObserver(ABC):
    """Interfaz abstracta para observadores de eventos de ejecución."""
    @abstractmethod
    def on_event(self, event: TraceEvent) -> None:
        """Notificado cuando ocurre un evento de traza."""


class EventCollectorObserver(TraceObserver):
    """Observador que acumula eventos y calcula métricas agregadas."""
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._start_time: float = time.perf_counter()

    def on_event(self, event: TraceEvent) -> None:
        self.events.append(event)

    @property
    def total_duration_ms(self) -> float:
        return (time.perf_counter() - self._start_time) * 1000.0

    def format_discord_markdown(self) -> str:
        """Formatea los eventos recopilados en un bloque legible para Discord."""
        if not self.events:
            return "ℹ️ *No se registraron pasos de ejecución.*"

        lines: list[str] = []
        for ev in self.events:
            line = f"• {ev.status_emoji} `[{ev.category}:{ev.action}]` {ev.step} *({ev.duration_ms:.1f}ms)*"
            sub_details: list[str] = []
            if ev.target:
                sub_details.append(f"Target: `{ev.target}`")
            if ev.details:
                sub_details.append(str(ev.details))
            if ev.error:
                sub_details.append(f"**Error:** `{ev.error}`")

            if sub_details:
                line += f"\n  └─ {' • '.join(sub_details)}"
            lines.append(line)

        return "\n".join(lines)


# ============================================================================
# Null Object Pattern: Interfaces de Tracer
# ============================================================================

class ITracer(ABC):
    """Interfaz unificada para el tracer."""
    @abstractmethod
    def record(
        self,
        step: str,
        category: str = "SYS",
        action: str = "EXEC",
        status: str = "OK",
        details: str | None = None,
        target: str | None = None,
        duration_ms: float = 0.0,
        error: str | None = None,
    ) -> None:
        pass

    @abstractmethod
    @contextmanager
    def measure(
        self,
        step: str,
        category: str = "SYS",
        action: str = "EXEC",
        target: str | None = None,
    ) -> Generator[dict[str, Any]]:
        pass

    @abstractmethod
    def attach_to_embed(self, embed: hikari.Embed) -> hikari.Embed:
        """Agrega el bloque de diagnóstico a un Embed de Discord (No-op en producción)."""

    @abstractmethod
    def append_to_message(self, message: str) -> str:
        """Agrega el reporte de diagnóstico al final de un mensaje de texto (No-op en producción)."""


class NullTracer(ITracer):
    """
    Null Object Pattern: Implementación vacía para PRODUCCIÓN.
    Garantiza que llamadas a trace no consuman recursos ni puedan producir excepciones.
    """
    def record(
        self,
        step: str,
        category: str = "SYS",
        action: str = "EXEC",
        status: str = "OK",
        details: str | None = None,
        target: str | None = None,
        duration_ms: float = 0.0,
        error: str | None = None,
    ) -> None:
        pass

    @contextmanager
    def measure(
        self,
        step: str,
        category: str = "SYS",
        action: str = "EXEC",
        target: str | None = None,
    ) -> Generator[dict[str, Any]]:
        dummy_ctx: dict[str, Any] = {}
        yield dummy_ctx

    def attach_to_embed(self, embed: hikari.Embed) -> hikari.Embed:
        return embed

    def append_to_message(self, message: str) -> str:
        return message


class DevActionTracer(ITracer):
    """
    Observer Pattern: Implementación para DESARROLLO.
    Recopila métricas, acciones y cambios en tiempo real.
    """
    def __init__(self, observers: list[TraceObserver] | None = None) -> None:
        self.collector = EventCollectorObserver()
        self.observers: list[TraceObserver] = observers or [self.collector]

    def add_observer(self, observer: TraceObserver) -> None:
        self.observers.append(observer)

    def record(
        self,
        step: str,
        category: str = "SYS",
        action: str = "EXEC",
        status: str = "OK",
        details: str | None = None,
        target: str | None = None,
        duration_ms: float = 0.0,
        error: str | None = None,
    ) -> None:
        event = TraceEvent(
            step=step,
            category=category.upper(),
            action=action.upper(),
            status=status.upper(),
            details=details,
            target=target,
            duration_ms=duration_ms,
            error=error,
        )
        for obs in self.observers:
            try:
                obs.on_event(event)
            except Exception as e:
                logger.debug(f"[Tracer] Observer error: {e}")

    @contextmanager
    def measure(
        self,
        step: str,
        category: str = "SYS",
        action: str = "EXEC",
        target: str | None = None,
    ) -> Generator[dict[str, Any]]:
        start = time.perf_counter()
        ctx: dict[str, Any] = {"status": "OK", "details": None, "target": target, "error": None}
        try:
            yield ctx
        except Exception as exc:
            ctx["status"] = "ERROR"
            ctx["error"] = str(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self.record(
                step=step,
                category=category,
                action=action,
                status=ctx.get("status", "OK"),
                details=ctx.get("details"),
                target=ctx.get("target") or target,
                duration_ms=duration_ms,
                error=ctx.get("error"),
            )

    def attach_to_embed(self, embed: hikari.Embed) -> hikari.Embed:
        if not self.collector.events:
            return embed

        report = self.collector.format_discord_markdown()
        total_time = self.collector.total_duration_ms
        field_title = f"🛠️ DEV TRACE ({BOT_SETTINGS.APP_ENV}) • {len(self.collector.events)} pasos ({total_time:.1f}ms)"

        # Discord limit: Embed field value máx 1024 caracteres
        if len(report) > 1024:
            report = report[:1015] + "...\n*(truncado)*"

        embed.add_field(name=field_title, value=report, inline=False)
        return embed

    def append_to_message(self, message: str) -> str:
        if not self.collector.events:
            return message

        report = self.collector.format_discord_markdown()
        total_time = self.collector.total_duration_ms
        header = f"\n\n**🛠️ DEV TRACE (`{BOT_SETTINGS.APP_ENV}`)** • *{len(self.collector.events)} pasos ({total_time:.1f}ms total)*:\n"
        return f"{message}{header}{report}"


# ============================================================================
# Factory Method
# ============================================================================

def get_tracer(force_dev: bool | None = None) -> ITracer:
    """
    Factory que retorna DevActionTracer en entornos de desarrollo,
    o NullTracer (cero overhead) en producción.
    """
    is_dev_active = force_dev if force_dev is not None else BOT_SETTINGS.is_dev
    if is_dev_active:
        return DevActionTracer()
    return NullTracer()
