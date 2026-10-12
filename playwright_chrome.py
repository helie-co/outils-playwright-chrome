from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import socket
import shlex
import subprocess
import sys
import time
import unittest
import re

try:
    import msvcrt
except ImportError:
    msvcrt = None


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "etat"
STATE_FILE = STATE_DIR / "serveur.json"
PROFILE_DIR = ROOT / "profils" / "principal"
BROWSERS_DIR = ROOT / "navigateurs"
SCENARIOS_DIR = ROOT / "scenarios"
LOGS_DIR = ROOT / "logs"
EXPORTS_DIR = ROOT / "exports"
RECORDER_PREFIX = "__OUTILS_PLAYWRIGHT_RECORD__"
RECORDER_SCRIPT = r"""
(() => {
  if (window.__outilsPlaywrightRecorder) return;
  const esc = (value) => String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  const selector = (element) => {
    if (!element || element.nodeType !== 1) return "body";
    if (element.id) return "#" + esc(element.id);
    for (const attribute of ["data-testid", "name", "aria-label"]) {
      const value = element.getAttribute(attribute);
      if (value) return element.tagName.toLowerCase() + "[" + attribute + "='" + esc(value) + "']";
    }
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && current !== document.body && parts.length < 5) {
      let part = current.tagName.toLowerCase();
      const siblings = Array.from(current.parentElement ? current.parentElement.children : []).filter((item) => item.tagName === current.tagName);
      if (siblings.length > 1) part += ":nth-of-type(" + (siblings.indexOf(current) + 1) + ")";
      parts.unshift(part);
      current = current.parentElement;
    }
    return parts.join(" > ") || "body";
  };
  const emit = (event) => console.log("__OUTILS_PLAYWRIGHT_RECORD__" + JSON.stringify(event));
  document.addEventListener("click", (event) => {
    const element = event.target.closest("a,button,input,textarea,select,[role='button']");
    if (element && element.type !== "password") emit({action: "cliquer", selecteur: selector(element)});
  }, true);
  document.addEventListener("change", (event) => {
    const element = event.target;
    if (element && element.type !== "password" && ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName)) emit({action: "remplir", selecteur: selector(element), valeur: element.value});
  }, true);
  document.addEventListener("input", (event) => {
    const element = event.target;
    if (element && element.type !== "password" && ["INPUT", "TEXTAREA"].includes(element.tagName)) emit({action: "remplir", selecteur: selector(element), valeur: element.value});
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      const element = event.target;
      emit({action: "touche", selecteur: element && element !== document.body ? selector(element) : null, touche: "Enter"});
    }
  }, true);
  window.__outilsPlaywrightRecorder = true;
})();
"""


def configure_environment() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_DIR))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def log_event(event: str, data: dict) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / (datetime.now().strftime("%Y-%m-%d") + ".jsonl")
    entry = {"date": datetime.now(timezone.utc).isoformat(), "evenement": event, **data}
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


class MarkdownConverter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.link_text: list[str] | None = None
        self.link_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "section", "article"}:
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            self.link_text = []
            self.link_url = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.link_text is not None:
            label = "".join(self.link_text).strip()
            self.parts.append(f"[{label}]({self.link_url})" if self.link_url else label)
            self.link_text = None
            self.link_url = None
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.link_text is not None:
            self.link_text.append(data)
        else:
            self.parts.append(data)

    def result(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(lines).strip() + "\n"


def html_to_markdown(html: str) -> str:
    converter = MarkdownConverter()
    converter.feed(html)
    return converter.result()


def export_page(markdown_file: str | None = None, json_file: str | None = None) -> dict:
    response = request({"action": "export_page"})
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = Path(markdown_file).expanduser().resolve() if markdown_file else EXPORTS_DIR / "page.md"
    json_path = Path(json_file).expanduser().resolve() if json_file else EXPORTS_DIR / "page.json"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(html_to_markdown(response["html"]), encoding="utf-8")
    json_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    log_event("exportation", {"markdown": str(markdown_path), "json": str(json_path), "url": response.get("url")})
    return {"markdown": str(markdown_path), "json": str(json_path), "url": response.get("url"), "title": response.get("title")}


def read_state() -> dict | None:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def request(payload: dict, timeout: float = 20.0) -> dict:
    state = read_state()
    if not state or not state.get("port"):
        raise RuntimeError("Chrome Playwright n'est pas démarré.")
    with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        received = b""
        while b"\n" not in received:
            chunk = connection.recv(65536)
            if not chunk:
                break
            received += chunk
    if not received:
        raise RuntimeError("Le serveur Chrome n'a pas répondu.")
    response = json.loads(received.split(b"\n", 1)[0].decode("utf-8"))
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Commande Playwright échouée."))
    return response


def replace_variables(value: object, variables: dict[str, str]) -> object:
    if isinstance(value, str):
        for name, replacement in variables.items():
            value = value.replace("{{" + name + "}}", replacement)
        return value
    if isinstance(value, list):
        return [replace_variables(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: replace_variables(item, variables) for key, item in value.items()}
    return value


def record_search(recipe_file: str, query: str, engine: str = "duckduckgo") -> dict:
    if engine != "duckduckgo":
        raise ValueError("Le prototype prend en charge DuckDuckGo uniquement.")
    target = Path(recipe_file).expanduser().resolve()
    recipe = {
        "nom": target.stem,
        "version": 1,
        "type": "recherche",
        "moteur": engine,
        "variables": {"requete": query},
        "etapes": [
            {"action": "ouvrir", "url": "https://html.duckduckgo.com/html/"},
            {"action": "remplir", "selecteur": "input[name='q'], input[type='search']", "valeur": "{{requete}}"},
            {"action": "touche", "touche": "Enter"},
            {"action": "attendre", "millisecondes": 1500},
            {"action": "extraire-resultats", "limite": 10},
        ],
    }
    start()
    for step in recipe["etapes"][:-1]:
        execute_step(step, recipe["variables"])
    results = execute_step(recipe["etapes"][-1], recipe["variables"])
    recipe["dernier_resultat"] = results
    write_json(target, recipe)
    log_event("enregistrement", {"fichier": str(target), "requete": query, "resultats": len(results.get("resultats", []))})
    return {"fichier": str(target), "resultats": results.get("resultats", [])}


def default_recipe_file(name: str | None = None) -> Path:
    label = name or "recherche"
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-") or "recherche"
    return SCENARIOS_DIR / f"{safe_label}.json"


def list_recipes(directory: str | None = None) -> dict:
    recipes_dir = Path(directory).expanduser().resolve() if directory else SCENARIOS_DIR
    recipes_dir.mkdir(parents=True, exist_ok=True)
    recipes = []
    for recipe_file in sorted(recipes_dir.glob("*.json")):
        try:
            recipe = json.loads(recipe_file.read_text(encoding="utf-8"))
            recipes.append({
                "nom": recipe.get("nom", recipe_file.stem),
                "fichier": str(recipe_file),
                "type": recipe.get("type", "inconnu"),
                "moteur": recipe.get("moteur"),
                "variables": list(recipe.get("variables", {}).keys()),
            })
        except (OSError, json.JSONDecodeError):
            recipes.append({"nom": recipe_file.stem, "fichier": str(recipe_file), "invalide": True})
    return {"dossier": str(recipes_dir), "scenarios": recipes}


def execute_step(step: dict, variables: dict[str, str]) -> dict:
    step = replace_variables(step, variables)
    action = step["action"]
    if action == "ouvrir":
        return request({"action": "open", "url": step["url"]})
    if action == "remplir":
        return request({"action": "fill", "selector": step["selecteur"], "value": step["valeur"]})
    if action == "cliquer":
        return request({"action": "click_selector", "selector": step["selecteur"]})
    if action == "cliquer-texte":
        return request({"action": "click", "text": step["texte"], "exact": bool(step.get("exact"))})
    if action == "touche":
        return request({"action": "press", "selector": step.get("selecteur"), "key": step["touche"]})
    if action == "attendre":
        return request({"action": "wait", "milliseconds": int(step.get("millisecondes", 500))})
    if action == "extraire-resultats":
        return request({"action": "extract_results", "limit": int(step.get("limite", 10))})
    raise ValueError(f"Étape inconnue : {action}")


def start_recording_session(name: str | None = None) -> dict:
    if not read_state():
        start()
    result = request({"action": "record_start", "name": name or "scenario"})
    return {"enregistrement": True, "nom": name or "scenario", **result}


def stop_recording_session(name: str | None = None, scenario_file: str | None = None) -> dict:
    result = request({"action": "record_stop"})
    scenario_name = name or result.get("nom") or "scenario"
    target = Path(scenario_file).expanduser().resolve() if scenario_file else default_recipe_file(scenario_name)
    scenario = {
        "nom": scenario_name or target.stem,
        "version": 1,
        "type": "session",
        "variables": {},
        "etapes": result.get("etapes", []),
    }
    write_json(target, scenario)
    log_event("enregistrement-session", {"fichier": str(target), "etapes": len(scenario["etapes"])})
    return {"fichier": str(target), "etapes": len(scenario["etapes"]), "scenario": scenario}


def execute_recipe(recipe_file: str, repetitions: int = 1, output_file: str | None = None) -> dict:
    source = Path(recipe_file).expanduser().resolve()
    recipe = json.loads(source.read_text(encoding="utf-8"))
    variables = {str(key): str(value) for key, value in recipe.get("variables", {}).items()}
    start()
    executions = []
    for numero in range(1, repetitions + 1):
        result = None
        for step in recipe.get("etapes", []):
            result = execute_step(step, variables)
        executions.append({"numero": numero, "resultat": result or {}})
        log_event("execution", {"fichier": str(source), "numero": numero, "resultat": result or {}})
    response = {"fichier": str(source), "executions": executions}
    if output_file:
        destination = Path(output_file).expanduser().resolve()
        write_json(destination, response)
        response["sortie"] = str(destination)
    return response


def start() -> dict:
    configure_environment()
    try:
        return request({"action": "status"})
    except (OSError, RuntimeError, json.JSONDecodeError):
        pass
    if STATE_FILE.exists():
        safe_unlink(STATE_FILE)
    command = [sys.executable, str(Path(__file__).resolve()), "--daemon"]
    environment = os.environ.copy()
    if os.name == "nt":
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        powershell_command = (
            f"Start-Process -FilePath {quote(sys.executable)} "
            f"-ArgumentList {quote(str(Path(__file__).resolve()))},'--daemon' "
            f"-WorkingDirectory {quote(str(ROOT))} -WindowStyle Hidden"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", powershell_command],
            cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        subprocess.Popen(command, cwd=str(ROOT), env=environment,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            return request({"action": "status"}, timeout=1)
        except (OSError, RuntimeError, json.JSONDecodeError):
            time.sleep(0.2)
    raise RuntimeError("Chrome Playwright n'a pas pu démarrer.")


def stop() -> dict:
    try:
        response = request({"action": "stop"})
    except (OSError, RuntimeError, json.JSONDecodeError):
        safe_unlink(STATE_FILE)
        return {"ok": True, "stopped": False, "message": "Chrome n'était pas démarré."}
    safe_unlink(STATE_FILE)
    return response


def daemon() -> int:
    configure_environment()
    from playwright.sync_api import sync_playwright

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, args=["--start-maximized"],
        )
        context.set_default_timeout(8000)
        page = context.pages[0] if context.pages else context.new_page()
        page.bring_to_front()
        recording = {"active": False, "nom": "scenario", "etapes": []}
        hooked_pages: set[int] = set()

        def add_recorded_step(step: dict) -> None:
            if not recording["active"]:
                return
            steps = recording["etapes"]
            if steps and steps[-1] == step:
                return
            steps.append(step)

        def on_console(message) -> None:
            if message.type != "log" or not message.text.startswith(RECORDER_PREFIX):
                return
            try:
                add_recorded_step(json.loads(message.text[len(RECORDER_PREFIX):]))
            except json.JSONDecodeError:
                pass

        def on_navigated(frame) -> None:
            if frame == frame.page.main_frame and recording["active"] and frame.url not in {"about:blank", "data:", ""}:
                add_recorded_step({"action": "ouvrir", "url": frame.url})

        def hook_page(tab) -> None:
            if id(tab) in hooked_pages:
                return
            hooked_pages.add(id(tab))
            tab.add_init_script(RECORDER_SCRIPT)
            tab.on("console", on_console)
            tab.on("framenavigated", on_navigated)
            try:
                tab.evaluate(RECORDER_SCRIPT)
            except Exception:
                pass

        for tab in context.pages:
            hook_page(tab)
        context.on("page", hook_page)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        server.settimeout(0.5)
        write_json(STATE_FILE, {"port": server.getsockname()[1], "pid": os.getpid()})
        running = True
        try:
            while running:
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    try:
                        data = b""
                        while b"\n" not in data:
                            chunk = connection.recv(65536)
                            if not chunk:
                                break
                            data += chunk
                        payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
                        action = payload.get("action")
                        if action == "status":
                            result = {"running": True, "pid": os.getpid(), "url": page.url, "title": page.title()}
                        elif action in {"open", "navigate"}:
                            page = page if page in context.pages else context.new_page()
                            page.goto(str(payload["url"]), wait_until="domcontentloaded")
                            page.bring_to_front()
                            result = {"url": page.url, "title": page.title()}
                        elif action == "tabs":
                            result = {"tabs": [{"index": i, "url": tab.url, "title": tab.title()} for i, tab in enumerate(context.pages)]}
                        elif action == "screenshot":
                            target = Path(str(payload["file"])).expanduser().resolve()
                            target.parent.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(target), full_page=bool(payload.get("full_page")))
                            result = {"file": str(target)}
                        elif action == "read":
                            result = {"url": page.url, "title": page.title(), "text": page.locator("body").inner_text()}
                        elif action == "click":
                            page.get_by_text(str(payload["text"]), exact=bool(payload.get("exact"))).first.click()
                            result = {"url": page.url, "title": page.title()}
                        elif action == "click_selector":
                            page.locator(str(payload["selector"])).first.click()
                            result = {"url": page.url, "title": page.title()}
                        elif action == "fill":
                            page.locator(str(payload["selector"])).fill(str(payload["value"]))
                            result = {"selector": payload["selector"]}
                        elif action == "press":
                            locator = page.locator(str(payload["selector"])) if payload.get("selector") else page.locator("body")
                            locator.press(str(payload["key"]))
                            result = {"url": page.url, "title": page.title()}
                        elif action == "wait":
                            page.wait_for_timeout(int(payload.get("milliseconds", 500)))
                            result = {"url": page.url}
                        elif action == "extract_results":
                            links = page.locator("a[data-testid='result-title-a'], a.result__a")
                            items = []
                            for index in range(min(int(payload.get("limit", 10)), links.count())):
                                link = links.nth(index)
                                items.append({"title": link.inner_text(), "url": link.get_attribute("href")})
                            result = {"resultats": items}
                        elif action == "export_page":
                            result = {
                                "url": page.url,
                                "title": page.title(),
                                "html": page.locator("html").evaluate("element => element.outerHTML"),
                                "text": page.locator("body").inner_text(),
                                "liens": page.locator("a").evaluate_all("elements => elements.map(a => ({texte: a.innerText, url: a.href}))"),
                            }
                        elif action == "record_start":
                            recording["active"] = True
                            recording["nom"] = str(payload.get("name") or "scenario")
                            recording["etapes"] = []
                            for tab in context.pages:
                                hook_page(tab)
                                if tab.url not in {"about:blank", ""}:
                                    add_recorded_step({"action": "ouvrir", "url": tab.url})
                            result = {"enregistrement": True, "nom": recording["nom"], "etapes": 0}
                        elif action == "record_stop":
                            recording["active"] = False
                            result = {"enregistrement": False, "nom": recording["nom"], "etapes": recording["etapes"]}
                        elif action == "stop":
                            result = {"stopped": True}
                            running = False
                        else:
                            raise ValueError(f"Action inconnue : {action}")
                        response = {"ok": True, **result}
                    except Exception as error:
                        response = {"ok": False, "error": str(error)}
                    connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            server.close()
            safe_unlink(STATE_FILE)
            context.close()
    return 0


def run_tests() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def print_result(result: dict, json_mode: bool = False) -> None:
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("running") is not None:
        print("Chrome Playwright actif." if result.get("running") else "Chrome Playwright arrêté.")
    if result.get("url"):
        print(f"URL    : {result['url']}")
    if result.get("title"):
        print(f"Titre  : {result['title']}")
    if result.get("fichier"):
        print(f"Fichier: {result['fichier']}")
    if result.get("message"):
        print(result["message"])
    if not any(key in result for key in ("running", "url", "title", "fichier", "message")):
        print(json.dumps(result, ensure_ascii=False, indent=2))


INTERACTIVE_COMMANDS = [
    "etat", "demarrer", "arreter", "ouvrir", "naviguer", "onglets", "capture",
    "lire", "cliquer", "remplir", "enregistrer", "enregistrer-session",
    "arreter-enregistrement", "executer", "lister", "exporter", "tester", "aide", "quitter",
]
INTERACTIVE_OPTIONS = {
    "ouvrir": ["--url"], "naviguer": ["--url"],
    "capture": ["--fichier", "--pleine-page"],
    "cliquer": ["--texte", "--exact"],
    "remplir": ["--selecteur", "--valeur"],
    "enregistrer": ["--fichier", "--nom", "--requete", "--moteur"],
    "enregistrer-session": ["--nom", "--fichier"],
    "arreter-enregistrement": ["--nom", "--fichier"],
    "executer": ["--fichier", "--fois", "--sortie"],
    "lister": ["--dossier"],
    "exporter": ["--markdown", "--json"],
}


def interactive_candidates(line: str) -> list[str]:
    trailing_space = line.endswith((" ", "\t"))
    try:
        terms = shlex.split(line, posix=True)
    except ValueError:
        terms = line.split()
    if trailing_space:
        prefix = ""
    else:
        prefix = terms[-1] if terms else ""
    if len(terms) <= 1 and not trailing_space:
        choices = INTERACTIVE_COMMANDS
    else:
        command = terms[0] if terms else ""
        choices = INTERACTIVE_OPTIONS.get(command, [])
    return [choice for choice in choices if choice.lower().startswith(prefix.lower())]


def interactive_input(prompt: str) -> str:
    if msvcrt is None:
        return input(prompt)
    text: list[str] = []
    print(prompt, end="", flush=True)
    while True:
        char = msvcrt.getwch()
        if char == "\r":
            print()
            return "".join(text).strip()
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\b":
            if text:
                text.pop()
                print("\b \b", end="", flush=True)
        elif char == "\t":
            current = "".join(text)
            base = current.rfind(" ") + 1
            choices = interactive_candidates(current)
            if choices:
                old = "".join(text[base:])
                replacement = choices[0]
                print("\b" * len(old) + " " * len(old) + "\b" * len(old), end="", flush=True)
                text[base:] = list(replacement)
                print(replacement, end="", flush=True)
        elif char.isprintable():
            text.append(char)
            print(char, end="", flush=True)
    if result.get("running") is not None:
        print("Chrome Playwright actif." if result.get("running") else "Chrome Playwright arrêté.")
    if result.get("url"):
        print(f"URL    : {result['url']}")
    if result.get("title"):
        print(f"Titre  : {result['title']}")
    if result.get("fichier"):
        print(f"Fichier: {result['fichier']}")
    if result.get("message"):
        print(result["message"])
    if not any(key in result for key in ("running", "url", "title", "fichier", "message")):
        print(json.dumps(result, ensure_ascii=False, indent=2))


def interactive_shell(json_mode: bool = False) -> int:
    print("Mode terminal interactif Playwright Chrome. Tapez 'aide' ou 'quitter'.")
    while True:
        try:
            line = interactive_input("playwright-chrome> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in {"quitter", "exit", "quit"}:
            return 0
        if line.lower() in {"aide", "help"}:
            parser().print_help()
            continue
        try:
            command_args = shlex.split(line, posix=True)
            if json_mode and "--json" not in command_args:
                command_args.insert(0, "--json")
            main(command_args)
        except SystemExit as error:
            print(f"Commande invalide (code {error.code}).")
        except Exception as error:
            print(f"Erreur: {error}")


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chrome visible et persistant piloté par Playwright.")
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", dest="json_mode", action="store_true", help="Sortie JSON machine lisible.")
    commands = parser.add_subparsers(dest="command", required=False)
    commands.add_parser("etat")
    commands.add_parser("demarrer")
    commands.add_parser("arreter")
    ouvrir = commands.add_parser("ouvrir")
    ouvrir.add_argument("--url", required=True)
    naviguer = commands.add_parser("naviguer")
    naviguer.add_argument("--url", required=True)
    commands.add_parser("onglets")
    capture = commands.add_parser("capture")
    capture.add_argument("--fichier", required=True)
    capture.add_argument("--pleine-page", action="store_true")
    commands.add_parser("lire")
    cliquer = commands.add_parser("cliquer")
    cliquer.add_argument("--texte", required=True)
    cliquer.add_argument("--exact", action="store_true")
    remplir = commands.add_parser("remplir")
    remplir.add_argument("--selecteur", required=True)
    remplir.add_argument("--valeur", required=True)
    enregistrer = commands.add_parser("enregistrer")
    enregistrer.add_argument("--fichier")
    enregistrer.add_argument("--nom")
    enregistrer.add_argument("--requete", required=True)
    enregistrer.add_argument("--moteur", default="duckduckgo")
    enregistrer_session = commands.add_parser("enregistrer-session")
    enregistrer_session.add_argument("--nom")
    enregistrer_session.add_argument("--fichier")
    arreter_enregistrement = commands.add_parser("arreter-enregistrement")
    arreter_enregistrement.add_argument("--nom")
    arreter_enregistrement.add_argument("--fichier")
    executer = commands.add_parser("executer")
    executer.add_argument("--fichier", required=True)
    executer.add_argument("--fois", type=int, default=1)
    executer.add_argument("--sortie")
    lister = commands.add_parser("lister")
    lister.add_argument("--dossier")
    exporter = commands.add_parser("exporter")
    exporter.add_argument("--markdown")
    exporter.add_argument("--json", dest="json_file")
    commands.add_parser("tester")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.daemon:
        return daemon()
    if arguments.command is None:
        return interactive_shell(arguments.json_mode)
    if arguments.command == "tester":
        return run_tests()
    if arguments.command == "demarrer":
        result = start()
    elif arguments.command == "arreter":
        result = stop()
    elif arguments.command == "etat":
        try:
            result = request({"action": "status"})
        except (OSError, RuntimeError, json.JSONDecodeError):
            result = {"running": False}
    elif arguments.command == "ouvrir":
        start(); result = request({"action": "open", "url": arguments.url})
    elif arguments.command == "naviguer":
        result = request({"action": "navigate", "url": arguments.url})
    elif arguments.command == "onglets":
        result = request({"action": "tabs"})
    elif arguments.command == "capture":
        result = request({"action": "screenshot", "file": arguments.fichier, "full_page": arguments.pleine_page})
    elif arguments.command == "lire":
        result = request({"action": "read"})
    elif arguments.command == "cliquer":
        result = request({"action": "click", "text": arguments.texte, "exact": arguments.exact})
    elif arguments.command == "remplir":
        result = request({"action": "fill", "selector": arguments.selecteur, "value": arguments.valeur})
    elif arguments.command == "enregistrer":
        fichier = arguments.fichier or str(default_recipe_file(arguments.nom))
        result = record_search(fichier, arguments.requete, arguments.moteur)
    elif arguments.command == "enregistrer-session":
        result = start_recording_session(arguments.nom)
    elif arguments.command == "arreter-enregistrement":
        result = stop_recording_session(arguments.nom, arguments.fichier)
    elif arguments.command == "executer":
        if arguments.fois < 1:
            raise ValueError("--fois doit être supérieur ou égal à 1.")
        result = execute_recipe(arguments.fichier, arguments.fois, arguments.sortie)
    elif arguments.command == "lister":
        result = list_recipes(arguments.dossier)
    elif arguments.command == "exporter":
        result = export_page(arguments.markdown, arguments.json_file)
    else:
        parser().print_help()
        return 0
    print_result(result, arguments.json_mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
