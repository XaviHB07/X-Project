"""Pruebas del programador de consultas de «Cacería en Vivo» en un navegador real.

Plan de optimización, criterio de aceptación del Integrante 2: «una
pantalla no debe generar una nueva consulta de estado mientras la anterior
siga pendiente; al salir de la actividad deben detenerse los ciclos».

Se carga `live-quiz.js` en Chromium (Playwright) con un servidor simulado
que responde lento o con errores, y se observa cuántas consultas quedan
en vuelo a la vez. Si Playwright/Chromium no están instalados, se omite.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

SCRIPT = (Path(__file__).resolve().parent.parent / "src" / "api" / "static" / "live-quiz.js").read_text(
    encoding="utf-8"
)

# Lo mínimo de app.js que live-quiz.js usa al cargarse.
STUBS = """
window.$ = (selector) => document.querySelector(selector);
window.escapeHtml = (value) => String(value);
window.notify = () => {};
window.setBusy = () => {};
window.setJoinStatus = () => {};
window.state = {};
"""


@pytest.fixture(scope="module")
def page():
    try:
        with playwright.sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception:
                # Entornos con un Chromium preinstalado fuera de la caché de
                # Playwright (p. ej. CI): se indica con PLAYWRIGHT_CHROMIUM.
                browser = pw.chromium.launch(
                    executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium")
                )
            page = browser.new_page()
            page.set_content("<html><body></body></html>")
            page.add_script_tag(content=STUBS)
            page.add_script_tag(content=SCRIPT)
            yield page
            browser.close()
    except Exception as exc:  # pragma: no cover - entorno sin navegador
        pytest.skip(f"Chromium no disponible: {exc}")


def test_never_more_than_one_request_in_flight_when_server_is_slow(page):
    result = page.evaluate("""async () => {
        let inFlight = 0, maxInFlight = 0, calls = 0;
        const poller = createLivePoller({
            intervalMs: 50,
            request: async () => {
                calls += 1; inFlight += 1; maxInFlight = Math.max(maxInFlight, inFlight);
                await new Promise((r) => setTimeout(r, 300));   // servidor 6x más lento que el intervalo
                inFlight -= 1;
                return {};
            },
            onData: () => {},
        });
        poller.start();
        // Pedidos de refresco mientras hay una en vuelo no deben duplicarla.
        setTimeout(() => poller.refreshNow(), 20);
        setTimeout(() => poller.refreshNow(), 40);
        await new Promise((r) => setTimeout(r, 1200));
        poller.stop();
        return { maxInFlight, calls };
    }""")
    assert result["maxInFlight"] == 1
    # Con setInterval habrían salido ~24 consultas en 1.2 s; esperando a que
    # termine cada una salen como mucho 1200 / (300 + 50) + la de refresco.
    assert result["calls"] <= 5


def test_backoff_after_errors_and_recovery(page):
    result = page.evaluate("""async () => {
        const stamps = []; let errors = 0, recovered = 0, n = 0;
        const poller = createLivePoller({
            intervalMs: 40,
            request: async () => {
                stamps.push(performance.now()); n += 1;
                if (n <= 3) throw new Error("503");
                return {};
            },
            onData: () => {},
            onError: () => { errors += 1; },
            onRecover: () => { recovered += 1; },
        });
        poller.start();
        await new Promise((r) => setTimeout(r, 1500));
        poller.stop();
        const gaps = stamps.slice(1).map((t, i) => t - stamps[i]);
        return { errors, recovered, gaps };
    }""")
    assert result["errors"] == 3
    assert result["recovered"] == 1
    gaps = result["gaps"]
    # Tras cada error el intervalo crece (80 ms, 160 ms, 320 ms ± jitter)...
    assert gaps[0] >= 60 and gaps[1] >= 120 and gaps[2] >= 250
    # ...y al recuperarse vuelve al ritmo normal.
    assert gaps[3] < 120


def test_stop_aborts_the_request_in_flight_and_schedules_nothing(page):
    result = page.evaluate("""async () => {
        let aborted = false, calls = 0, delivered = 0;
        const poller = createLivePoller({
            intervalMs: 30,
            request: (signal) => new Promise((resolve, reject) => {
                calls += 1;
                signal.addEventListener("abort", () => { aborted = true; reject(new DOMException("x", "AbortError")); });
                setTimeout(() => resolve({}), 500);
            }),
            onData: () => { delivered += 1; },
        });
        poller.start();
        await new Promise((r) => setTimeout(r, 50));
        poller.stop();
        await new Promise((r) => setTimeout(r, 700));
        return { aborted, calls, delivered, running: poller.running };
    }""")
    assert result == {"aborted": True, "calls": 1, "delivered": 0, "running": False}


def test_slow_request_is_aborted_by_timeout(page):
    result = page.evaluate("""async () => {
        const messages = [];
        const original = LIVE_REQUEST_TIMEOUT_MS;
        const poller = createLivePoller({
            intervalMs: 10_000,
            request: (signal) => new Promise((_, reject) => {
                signal.addEventListener("abort", () => reject(new DOMException("x", "AbortError")));
            }),
            onData: () => {},
            onError: (message) => { messages.push(message); poller.stop(); },
        });
        poller.start();
        await new Promise((r) => setTimeout(r, original + 500));
        return messages;
    }""")
    assert result == ["el servidor tardó demasiado en responder"]
