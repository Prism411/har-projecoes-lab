from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def chromium_instalado() -> str | None:
    explicito = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if explicito and Path(explicito).is_file():
        return explicito
    candidatos = sorted(
        (Path.home() / ".cache" / "ms-playwright").glob(
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
        ),
        reverse=True,
    )
    return str(candidatos[0]) if candidatos else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test do laboratório HAR offline.")
    parser.add_argument(
        "--html",
        type=Path,
        default=ROOT / "dist" / "laboratorio-har-real.html",
    )
    parser.add_argument("--screenshot", type=Path, default=ROOT / "results" / "smoke-laboratorio.png")
    parser.add_argument(
        "--cvd-screenshot",
        type=Path,
        default=ROOT / "results" / "smoke-deuteranopia.png",
    )
    parser.add_argument(
        "--umap3d-screenshot",
        type=Path,
        default=ROOT / "results" / "smoke-umap-3d.png",
    )
    parser.add_argument(
        "--inspector-screenshot",
        type=Path,
        default=ROOT / "results" / "smoke-inspetor.png",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    remote_requests: list[str] = []
    started = time.perf_counter()

    with sync_playwright() as playwright:
        executavel = chromium_instalado()
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executavel,
            args=["--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on(
            "console",
            lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.on(
            "request",
            lambda request: remote_requests.append(request.url)
            if request.url.startswith(("http://", "https://"))
            else None,
        )

        page.goto(args.html.resolve().as_uri(), wait_until="load", timeout=120_000)
        page.wait_for_function("window.HAR_DADOS && window.HAR_DADOS.amostras.length === 10299", timeout=120_000)
        page.wait_for_function("window.__charts && window.__charts.filter(Boolean).length === 3", timeout=120_000)
        page.wait_for_timeout(2_000)

        if "10.299 amostras" not in page.locator("body").inner_text():
            errors.append("Resumo do HAR completo não apareceu na interface.")
        if page.locator("canvas").count() < 3:
            errors.append("Menos de três canvases ECharts foram renderizados.")

        def pontos_visiveis() -> list[int]:
            return page.evaluate(
                """
                () => window.__charts.map(chart => chart.getOption().series
                  .filter(item => String(item.id || '').startsWith('cls-'))
                  .reduce((total, item) => total + ((item.data && item.data.length) || 0), 0))
                """
            )

        def definir_slider(selector: str, valor: int) -> None:
            page.locator(selector).evaluate(
                """
                (elemento, novoValor) => {
                  const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                  ).set;
                  setter.call(elemento, String(novoValor));
                  elemento.dispatchEvent(new Event('input', { bubbles: true }));
                  elemento.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """,
                valor,
            )

        definir_slider("#filtro-sujeito-min", 5)
        definir_slider("#filtro-sujeito-max", 10)
        page.wait_for_function(
            """
            expected => window.__charts.every(chart => chart.getOption().series
              .filter(item => String(item.id || '').startsWith('cls-'))
              .reduce((total, item) => total + ((item.data && item.data.length) || 0), 0) === expected)
            """,
            arg=1798,
            timeout=30_000,
        )
        if pontos_visiveis() != [1798, 1798, 1798]:
            errors.append(f"Faixa de participantes 5–10 divergiu entre painéis: {pontos_visiveis()}")
        corpo = page.locator("body").inner_text()
        if "1.798 de 10.299 amostras visíveis" not in corpo or "5–10" not in corpo:
            errors.append("Resumo da faixa de participantes não apareceu.")

        page.get_by_role("button", name="Limpar filtros").click()
        page.select_option("#filtro-split", "test")
        page.wait_for_function(
            """
            expected => window.__charts.every(chart => chart.getOption().series
              .filter(item => String(item.id || '').startsWith('cls-'))
              .reduce((total, item) => total + ((item.data && item.data.length) || 0), 0) === expected)
            """,
            arg=2947,
            timeout=30_000,
        )
        if pontos_visiveis() != [2947, 2947, 2947]:
            errors.append(f"Filtro do conjunto de teste divergiu entre painéis: {pontos_visiveis()}")

        page.get_by_role("button", name="Limpar filtros").click()
        page.wait_for_function(
            """
            expected => window.__charts.every(chart => chart.getOption().series
              .filter(item => String(item.id || '').startsWith('cls-'))
              .reduce((total, item) => total + ((item.data && item.data.length) || 0), 0) === expected)
            """,
            arg=10299,
            timeout=30_000,
        )

        target = page.evaluate(
            """
            () => {
              const chart = window.__charts[0];
              const option = chart.getOption();
              const seriesIndex = option.series.findIndex(series =>
                String(series.id || '').startsWith('cls-') && series.data && series.data.length
              );
              const datum = option.series[seriesIndex].data[0];
              const value = Array.isArray(datum) ? datum : datum.value;
              const pixel = chart.convertToPixel({ seriesIndex }, [value[0], value[1]]);
              const rect = chart.getDom().getBoundingClientRect();
              return { x: rect.left + pixel[0], y: rect.top + pixel[1] };
            }
            """
        )
        page.mouse.click(target["x"], target["y"])
        page.wait_for_function("document.body.innerText.includes('1 amostra selecionada')", timeout=30_000)
        selected_counts = page.evaluate(
            """
            () => window.__charts.map(chart => {
              const series = chart.getOption().series.find(item => item.id === 'sel');
              return series && series.data ? series.data.length : 0;
            })
            """
        )
        if selected_counts != [1, 1, 1]:
            errors.append(f"Seleção não foi vinculada nos três painéis: {selected_counts}")

        page.get_by_role("button", name="Abrir detalhes da amostra").click()
        page.wait_for_function(
            """
            () => window.__harInterpretacao && window.__inspectorCharts &&
              window.__inspectorCharts.length === 2 &&
              window.__inspectorCharts.every(chart => chart && !chart.isDisposed())
            """,
            timeout=120_000,
        )
        if page.locator("[data-testid='inspetor-amostra']").count() != 1:
            errors.append("Inspetor da amostra não apareceu após a seleção.")
        inspector_shapes = page.evaluate(
            """
            () => {
              const signal = window.__inspectorCharts[0].getOption();
              const profile = window.__inspectorCharts[1].getOption();
              return {
                signalSeries: signal.series.length,
                signalPoints: signal.series.map(series => series.data.length),
                profileSeries: profile.series.length,
                profileBars: profile.series.map(series => series.data.length),
                featureBytes: window.__harInterpretacao.features.length,
                signalValues: window.__harInterpretacao.signals.length
              };
            }
            """
        )
        if inspector_shapes["signalSeries"] != 3 or inspector_shapes["signalPoints"] != [128, 128, 128]:
            errors.append(f"Sinal triaxial inesperado: {inspector_shapes}")
        if inspector_shapes["profileSeries"] != 2 or inspector_shapes["profileBars"] != [8, 8]:
            errors.append(f"Perfil de características inesperado: {inspector_shapes}")
        if inspector_shapes["featureBytes"] != 10299 * 561:
            errors.append(f"Matriz de características decodificada com dimensão errada: {inspector_shapes}")
        if inspector_shapes["signalValues"] != 10299 * 6 * 128:
            errors.append(f"Matriz de sinais decodificada com dimensão errada: {inspector_shapes}")

        second_target = page.evaluate(
            """
            () => {
              const chart = window.__charts[0], option = chart.getOption();
              const candidates = option.series
                .map((series, index) => ({ series, index }))
                .filter(item => String(item.series.id || '').startsWith('cls-') && item.series.data && item.series.data.length);
              const chosen = candidates.length > 1 ? candidates[1] : candidates[0];
              const datum = chosen.series.data[0], value = Array.isArray(datum) ? datum : datum.value;
              const pixel = chart.convertToPixel({ seriesIndex: chosen.index }, [value[0], value[1]]);
              const rect = chart.getDom().getBoundingClientRect();
              return { x: rect.left + pixel[0], y: rect.top + pixel[1] };
            }
            """
        )
        page.keyboard.down("Shift")
        page.mouse.click(second_target["x"], second_target["y"])
        page.keyboard.up("Shift")
        page.wait_for_function("document.body.innerText.includes('Seleção de 2 amostras')", timeout=30_000)
        page.wait_for_function(
            """
            () => window.__inspectorCharts && window.__inspectorCharts[1].getOption().series
              .every(series => series.data && series.data.length === 8)
            """,
            timeout=30_000,
        )
        args.inspector_screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.locator("[data-testid='inspetor-amostra']").screenshot(path=str(args.inspector_screenshot))
        page.get_by_role("button", name="Limpar seleção e laço (Esc)").click()

        page.get_by_role("button", name="UMAP 3D").click()
        page.wait_for_function(
            """
            () => window.__plot3d && window.__plot3d.__harLinked && window.__plot3d.data &&
              window.__plot3d.data.filter(trace => trace.meta === 'classe')
                .reduce((total, trace) => total + trace.x.length, 0) === 10299
            """,
            timeout=120_000,
        )
        if page.locator("[data-testid='umap-3d'] .gl-container").count() != 1:
            errors.append("Cena WebGL do UMAP 3D não foi criada.")

        definir_slider("#filtro-sujeito-min", 5)
        definir_slider("#filtro-sujeito-max", 10)
        page.wait_for_function(
            """
            expected => window.__plot3d.data.filter(trace => trace.meta === 'classe')
              .reduce((total, trace) => total + trace.x.length, 0) === expected
            """,
            arg=1798,
            timeout=120_000,
        )
        total_3d = page.evaluate(
            """
            () => window.__plot3d.data.filter(trace => trace.meta === 'classe')
              .reduce((total, trace) => total + trace.x.length, 0)
            """
        )
        if total_3d != 1798:
            errors.append(f"Filtro 5–10 não chegou ao UMAP 3D: {total_3d}")

        args.umap3d_screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.umap3d_screenshot), full_page=True)
        page.get_by_role("button", name="Limpar filtros").click()
        page.wait_for_function(
            """
            () => window.__plot3d.data.filter(trace => trace.meta === 'classe')
              .reduce((total, trace) => total + trace.x.length, 0) === 10299
            """,
            timeout=120_000,
        )

        selected_3d_id = page.evaluate(
            """
            () => {
              const trace = window.__plot3d.data.find(item => item.meta === 'classe' && item.customdata.length);
              const customdata = trace.customdata[0];
              window.__plot3d.emit('plotly_click', { points: [{ customdata }], event: {} });
              return customdata[0];
            }
            """
        )
        page.wait_for_function("document.body.innerText.includes('1 amostra selecionada')", timeout=30_000)
        page.get_by_role("button", name="Comparar").click()
        page.wait_for_function("window.__charts && window.__charts.filter(Boolean).length === 3", timeout=30_000)
        page.wait_for_function(
            """
            () => window.__charts.every(chart => {
              const selected = chart.getOption().series.find(item => item.id === 'sel');
              return selected && selected.data && selected.data.length === 1;
            })
            """,
            timeout=30_000,
        )
        selected_ids_2d = page.evaluate(
            """
            () => window.__charts.map(chart => {
              const selected = chart.getOption().series.find(item => item.id === 'sel');
              return window.HAR_DADOS.amostras[selected.data[0].value[2]].id;
            })
            """
        )
        if selected_ids_2d != [selected_3d_id] * 3:
            errors.append(f"Seleção 3D não foi vinculada ao 2D: {selected_ids_2d}")
        page.get_by_role("button", name="Limpar seleção e laço (Esc)").click()

        page.select_option("#cvd", "deuteranopia")
        args.cvd_screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.cvd_screenshot), full_page=True)
        page.get_by_role("button", name="Sem cor").click()
        page.get_by_role("button", name="Atividade").click()
        page.get_by_label("Configuração pré-calculada do painel t-SNE").select_option(
            "tsne/perplexidade-50/seed-42"
        )
        page.get_by_label("Configuração pré-calculada do painel UMAP").select_option(
            "umap/amplo/seed-42"
        )
        page.get_by_role("button", name="Apresentação").evaluate("element => element.click()")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(600)
        page.get_by_role("button", name="Laboratório").evaluate("element => element.click()")
        page.wait_for_function("window.__charts && window.__charts.filter(Boolean).length === 3", timeout=30_000)
        page.select_option("#cvd", "padrao")
        page.wait_for_timeout(1_000)

        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.screenshot), full_page=True)
        browser.close()

    report = {
        "html": str(args.html.resolve()),
        "runtime_seconds": time.perf_counter() - started,
        "remote_requests": remote_requests,
        "errors": errors,
        "screenshot": str(args.screenshot.resolve()),
        "cvd_screenshot": str(args.cvd_screenshot.resolve()),
        "umap3d_screenshot": str(args.umap3d_screenshot.resolve()),
        "inspector_screenshot": str(args.inspector_screenshot.resolve()),
    }
    report_path = ROOT / "results" / "smoke-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors or remote_requests:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
