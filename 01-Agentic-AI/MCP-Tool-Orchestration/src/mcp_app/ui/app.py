"""Streamlit UI for MCP App — Claude-style chat experience.

Run with:
    streamlit run src/mcp_app/ui/app.py
or:
    mcpapp-ui
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

from mcp_app.config.loader import load_all_configs
from mcp_app.core.chat_engine import ChatEngine
from mcp_app.observability.logger import get_logger, setup_logging
from mcp_app.ui.async_bridge import AsyncBridge

log = get_logger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"
_STREAMLIT_DIR = Path(__file__).parent.parent.parent.parent / ".streamlit"
_LOG_DIR = Path(__file__).parent.parent.parent.parent / ".mcp_app_logs"
_ENV_LLM_PATH = Path(__file__).parent.parent.parent.parent / ".env.llm"


# ── Cached resources ──────────────────────────────────────────────────────────

@st.cache_resource
def _init_logging() -> bool:
    """Set up application logging once per Streamlit server lifetime."""
    setup_logging(level="INFO", log_dir=str(_LOG_DIR))
    return True


@st.cache_resource
def get_bridge() -> AsyncBridge:
    return AsyncBridge()


# ── Session state ─────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults: dict[str, Any] = {
        "messages": [],
        "engine": None,
        "engine_ready": False,
        "processing": False,
        "bg_future": None,
        "uploaded_files": [],      # list[dict] name+content
        "editing_server": None,    # server id being edited (str) or None
        "adding_server": False,    # whether add-new form is open
        "s_conn_test": None,       # (ok, msg) from last Test Connection run
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── YAML helpers ──────────────────────────────────────────────────────────────

def _read_yaml(name: str) -> dict:
    p = _CONFIG_DIR / name
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {} if p.exists() else {}


def _write_yaml(name: str, data: dict) -> None:
    p = _CONFIG_DIR / name
    p.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")


# ── .env.llm helpers ─────────────────────────────────────────────────────────

def _read_env_llm() -> dict[str, str]:
    """Read .env.llm into a flat key→value dict."""
    result: dict[str, str] = {}
    if not _ENV_LLM_PATH.is_file():
        return result
    for raw_line in _ENV_LLM_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip()
    return result


def _write_env_llm(env_vars: dict[str, str]) -> None:
    """Update .env.llm with the given key=value pairs, preserving other lines."""
    lines_out: list[str] = []
    written: set[str] = set()
    if _ENV_LLM_PATH.is_file():
        for raw_line in _ENV_LLM_PATH.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.partition("=")[0].strip()
                if k in env_vars:
                    lines_out.append(f"{k}={env_vars[k]}")
                    written.add(k)
                else:
                    lines_out.append(raw_line)
            else:
                lines_out.append(raw_line)
    for k, v in env_vars.items():
        if k not in written:
            lines_out.append(f"{k}={v}")
    _ENV_LLM_PATH.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


# ── Streamlit theme config.toml ───────────────────────────────────────────────

def _write_theme(theme: str, accent: str) -> None:
    _STREAMLIT_DIR.mkdir(exist_ok=True)
    bg = "#0e1117" if theme == "dark" else "#ffffff"
    text = "#fafafa" if theme == "dark" else "#31333f"
    content = (
        "[theme]\n"
        f'base = "{theme}"\n'
        f'primaryColor = "{accent}"\n'
        f'backgroundColor = "{bg}"\n'
        f'textColor = "{text}"\n'
    )
    (_STREAMLIT_DIR / "config.toml").write_text(content, encoding="utf-8")


# ── Ollama model discovery ────────────────────────────────────────────────────

def _fetch_ollama_models(host: str) -> list[str]:
    """Return model names from Ollama /api/tags. Empty list on failure."""
    try:
        import httpx
        resp = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception:  # noqa: BLE001
        pass
    return []


# ── CSS injection ─────────────────────────────────────────────────────────────

def _inject_css(ui: dict) -> None:
    font_size = ui.get("font_size", 15)
    font_family = ui.get("font_family", "sans-serif")
    zoom = float(ui.get("zoom", 1.0))
    chat_max_width = ui.get("chat_max_width", 800)
    compact = ui.get("compact_mode", False)
    accent = ui.get("accent_color", "#ff6b35")
    padding = "0.4rem 0" if compact else "0.75rem 0"

    st.markdown(
        f"""
        <style>
        html, body, [class*="css"] {{
            font-size: {font_size}px !important;
            font-family: {font_family} !important;
        }}
        .main .block-container {{
            zoom: {zoom};
            max-width: {chat_max_width}px;
            margin: 0 auto;
        }}
        .stChatMessage {{ padding: {padding} !important; }}
        a, .stButton>button:focus {{ color: {accent}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── Engine lifecycle ──────────────────────────────────────────────────────────

def _get_or_start_engine() -> ChatEngine:
    if st.session_state.engine is not None and st.session_state.engine_ready:
        return st.session_state.engine
    settings, policies, servers_cfg = load_all_configs(_CONFIG_DIR)
    engine = ChatEngine(settings, servers_cfg, policies)
    with st.spinner("Starting MCP servers…"):
        get_bridge().run(engine.start())
    st.session_state.engine = engine
    st.session_state.engine_ready = True
    return engine


def _reset_engine() -> None:
    engine: ChatEngine | None = st.session_state.get("engine")
    if engine:
        try:
            get_bridge().run(engine.stop())
        except Exception:  # noqa: BLE001
            pass
    st.session_state.engine = None
    st.session_state.engine_ready = False
    st.session_state.messages = []
    st.session_state.processing = False
    st.session_state.bg_future = None


# ── Server status dots ────────────────────────────────────────────────────────

def _render_server_status() -> None:
    engine: ChatEngine | None = st.session_state.get("engine")
    st.markdown("**🟢 Server Status**")
    if engine and st.session_state.engine_ready:
        for sid, status in engine.server_statuses.items():
            dot = {"READY": "🟢", "FAILED": "🔴", "DISABLED": "⚫"}.get(status.value, "🟡")
            ms = engine._mgr.get_managed_servers().get(sid) if engine._mgr else None
            err = f" `{ms.error}`" if (ms and ms.error) else ""
            st.markdown(f"{dot} `{sid}` — {status.value}{err}")
        st.caption(f"{engine.ready_count} ready · {engine.tool_count} tools")
    else:
        try:
            _, _, scfg = load_all_configs(_CONFIG_DIR)
            for srv in scfg.servers:
                icon = "⚫" if not srv.enabled else "⚪"
                st.markdown(f"{icon} `{srv.id}` — not started")
        except Exception:  # noqa: BLE001
            st.caption("Config unavailable")


# ── Server management ─────────────────────────────────────────────────────────

def _render_server_management() -> None:
    with st.expander("🖥️ Manage Servers", expanded=False):
        data = _read_yaml("mcp_servers.yaml")
        servers: list[dict] = data.get("servers", [])

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Refresh", key="srv_refresh", use_container_width=True):
                _reset_engine()
                st.rerun()
        with c2:
            if st.button("➕ Add Server", key="srv_add", use_container_width=True):
                st.session_state.adding_server = True
                st.session_state.editing_server = None

        st.divider()

        for i, srv in enumerate(servers):
            sid = srv.get("id", f"server_{i}")
            enabled = srv.get("enabled", True)

            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                new_enabled = st.toggle(f"`{sid}`", value=enabled, key=f"toggle_{sid}")
                if new_enabled != enabled:
                    servers[i]["enabled"] = new_enabled
                    data["servers"] = servers
                    _write_yaml("mcp_servers.yaml", data)
                    _reset_engine()
                    st.rerun()
            with col2:
                if st.button("✏️", key=f"edit_{sid}", help="Edit"):
                    st.session_state.editing_server = sid
                    st.session_state.adding_server = False
            with col3:
                if st.button("🗑️", key=f"del_{sid}", help="Delete"):
                    st.session_state[f"confirm_del_{sid}"] = True

            if st.session_state.get(f"confirm_del_{sid}"):
                st.warning(f"Delete `{sid}`?")
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button("Yes, delete", key=f"delyes_{sid}"):
                        data["servers"] = [s for s in servers if s.get("id") != sid]
                        _write_yaml("mcp_servers.yaml", data)
                        st.session_state[f"confirm_del_{sid}"] = False
                        _reset_engine()
                        st.rerun()
                with dc2:
                    if st.button("Cancel", key=f"delno_{sid}"):
                        st.session_state[f"confirm_del_{sid}"] = False
                        st.rerun()

            if st.session_state.editing_server == sid:
                _render_server_form(srv, servers, data, editing=True)

        if st.session_state.adding_server:
            _render_server_form({}, servers, data, editing=False)


def _render_server_form(
    srv: dict, servers: list, data: dict, editing: bool
) -> None:
    label = "Edit Server" if editing else "New Server"
    with st.container():
        st.markdown(f"**{label}**")
        sid_default = srv.get("id", "")
        key_sfx = sid_default or "new"
        new_id = st.text_input("ID", value=sid_default, disabled=editing, key=f"f_id_{key_sfx}")
        new_name = st.text_input("Name", value=srv.get("name", ""), key=f"f_name_{key_sfx}")
        new_enabled = st.toggle("Enabled", value=srv.get("enabled", True), key=f"f_en_{key_sfx}")
        stdio = srv.get("stdio", {})
        new_cmd = st.text_input("Command", value=stdio.get("command", ""), key=f"f_cmd_{key_sfx}")
        args_str = "\n".join(stdio.get("args", []))
        new_args_str = st.text_area("Args (one per line)", value=args_str, height=80, key=f"f_args_{key_sfx}")
        new_cwd = st.text_input("CWD (optional)", value=stdio.get("cwd") or "", key=f"f_cwd_{key_sfx}")
        timeouts = srv.get("timeouts", {})
        new_conn = st.number_input("Connect timeout (s)", 5, 120, int(timeouts.get("connect_seconds", 10)), key=f"f_conn_{key_sfx}")
        new_call = st.number_input("Call timeout (s)", 10, 300, int(timeouts.get("call_seconds", 30)), key=f"f_call_{key_sfx}")
        tags_str = ", ".join(srv.get("tags", []))
        new_tags_str = st.text_input("Tags (comma-separated)", value=tags_str, key=f"f_tags_{key_sfx}")

        sc1, sc2 = st.columns(2)
        with sc1:
            if st.button("💾 Save", key=f"f_save_{key_sfx}", use_container_width=True):
                new_args = [a.strip() for a in new_args_str.splitlines() if a.strip()]
                new_tags = [t.strip() for t in new_tags_str.split(",") if t.strip()]
                entry = {
                    "id": new_id,
                    "name": new_name,
                    "enabled": new_enabled,
                    "transport": "stdio",
                    "stdio": {
                        "command": new_cmd,
                        "args": new_args,
                        "cwd": new_cwd or None,
                        "env": srv.get("stdio", {}).get("env", {}),
                    },
                    "timeouts": {"connect_seconds": int(new_conn), "call_seconds": int(new_call)},
                    "policy": srv.get("policy", {"allowed_tools": [], "denied_tools": []}),
                    "tags": new_tags,
                }
                if editing:
                    idx = next((i for i, s in enumerate(servers) if s.get("id") == sid_default), None)
                    if idx is not None:
                        servers[idx] = entry
                else:
                    servers.append(entry)
                data["servers"] = servers
                _write_yaml("mcp_servers.yaml", data)
                st.session_state.editing_server = None
                st.session_state.adding_server = False
                _reset_engine()
                st.success("Saved — servers restarting.")
                st.rerun()
        with sc2:
            if st.button("✖ Cancel", key=f"f_cancel_{key_sfx}", use_container_width=True):
                st.session_state.editing_server = None
                st.session_state.adding_server = False
                st.rerun()


# ── File upload ───────────────────────────────────────────────────────────────

_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}


def _render_file_upload() -> None:
    import base64
    with st.expander("📎 Upload Files", expanded=False):
        uploaded = st.file_uploader(
            "Add to chat context",
            type=[
                "txt", "md", "pdf", "csv", "json", "yaml", "py", "js", "ts", "html",
                "jpg", "jpeg", "png", "gif", "webp", "bmp",
            ],
            accept_multiple_files=True,
            key="file_uploader",
        )
        if uploaded:
            existing_names = {f["name"] for f in st.session_state.uploaded_files}
            for uf in uploaded:
                if uf.name not in existing_names:
                    ext = uf.name.rsplit(".", 1)[-1].lower()
                    if ext in _IMAGE_EXTS:
                        raw = uf.read()
                        b64 = base64.b64encode(raw).decode("ascii")
                        mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
                        st.session_state.uploaded_files.append({
                            "name": uf.name,
                            "content": f"[Image: {uf.name}]",
                            "is_image": True,
                            "data_b64": b64,
                            "mime": mime,
                        })
                    else:
                        try:
                            content = uf.read().decode("utf-8", errors="replace")
                        except Exception:  # noqa: BLE001
                            content = f"[Binary file: {uf.name}]"
                        st.session_state.uploaded_files.append({"name": uf.name, "content": content})
                    existing_names.add(uf.name)

        if st.session_state.uploaded_files:
            st.caption(f"{len(st.session_state.uploaded_files)} file(s) in context:")
            to_remove = []
            for i, f in enumerate(st.session_state.uploaded_files):
                if f.get("is_image"):
                    st.image(
                        f"data:{f['mime']};base64,{f['data_b64']}",
                        caption=f["name"],
                        use_container_width=True,
                    )
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.caption(f"🖼️ {f['name']}")
                    with c2:
                        if st.button("✖", key=f"rm_file_{i}", help="Remove"):
                            to_remove.append(i)
                else:
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.caption(f"📄 {f['name']}")
                    with c2:
                        if st.button("✖", key=f"rm_file_{i}", help="Remove"):
                            to_remove.append(i)
            if to_remove:
                st.session_state.uploaded_files = [
                    f for i, f in enumerate(st.session_state.uploaded_files)
                    if i not in to_remove
                ]
                st.rerun()


# ── Rich content renderer ────────────────────────────────────────────────────

def _render_rich_content(text: str) -> None:
    """Scan assistant reply text for renderable artefacts and display them inline.

    Detects (in priority order):
      1. Local HTML file path  → st.components iframe + download button
      2. draw.io URL           → iframe + open-in-new-tab link
      3. Local image path      → st.image

    Existing st.markdown(text) is called BEFORE this function so the original
    text is always shown.  This function only ADDS extra widgets — it never
    removes or replaces anything.
    """
    import re
    import os
    import uuid
    # Unique prefix per call so the same file path rendered in multiple messages
    # (history + live reply) never produces duplicate widget keys.
    _key_prefix = uuid.uuid4().hex[:12]

    # ── 1. Local HTML files (analytics dashboards, local forms, etc.) ─────────
    html_paths = re.findall(
        r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.html',
        text,
        re.IGNORECASE,
    )
    for i, raw_path in enumerate(dict.fromkeys(html_paths)):  # deduplicate, preserve order
        path = raw_path.strip()
        if not os.path.isfile(path):
            continue
        try:
            html_content = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        st.divider()
        st.caption(f"📊 Rendered: `{os.path.basename(path)}`")
        import streamlit.components.v1 as components
        components.html(html_content, height=900, scrolling=True)
        with open(path, "rb") as fh:
            st.download_button(
                label=f"⬇ Download {os.path.basename(path)}",
                data=fh.read(),
                file_name=os.path.basename(path),
                mime="text/html",
                key=f"dl_{_key_prefix}_h{i}",
            )

    # ── 2. Inline Mermaid diagrams (rendered via mermaid.js CDN) ─────────────
    mermaid_blocks = re.findall(
        r'```mermaid\s*\n(.*?)```',
        text,
        re.DOTALL | re.IGNORECASE,
    )
    import html as _html
    import streamlit.components.v1 as components
    for i, mermaid_src in enumerate(dict.fromkeys(mermaid_blocks)):
        mermaid_src = mermaid_src.strip()
        if not mermaid_src:
            continue
        safe_src = _html.escape(mermaid_src)
        mermaid_html = f"""<!DOCTYPE html>
<html><head><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#ffffff;display:flex;justify-content:center;padding:16px;}}
.mermaid{{width:100%;max-width:900px;}}
</style></head>
<body>
<div class="mermaid">{safe_src}</div>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
mermaid.initialize({{startOnLoad:true,theme:'default',securityLevel:'loose'}});
</script>
</body></html>"""
        st.divider()
        st.caption("🧩 Mermaid Diagram (inline)")
        components.html(mermaid_html, height=520, scrolling=True)

    # ── 3. draw.io URLs — show as styled button (iframe blocked by X-Frame-Options) ──
    drawio_urls = re.findall(
        r'https://app\.diagrams\.net/[^\s)>"]+',
        text,
    )
    for url in dict.fromkeys(drawio_urls):
        st.markdown(
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;margin:8px 0;padding:8px 18px;'
            f'background:#1565c0;color:white;border-radius:5px;'
            f'text-decoration:none;font-weight:600;font-size:14px;">'
            f'🔗 Open / Edit in Draw.io</a>',
            unsafe_allow_html=True,
        )

    # ── 3. Local image paths (screenshots from playwright, etc.) ──────────────
    img_paths = re.findall(
        r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.(?:png|jpg|jpeg|gif|webp|bmp)',
        text,
        re.IGNORECASE,
    )
    for i, raw_path in enumerate(dict.fromkeys(img_paths)):
        path = raw_path.strip()
        if not os.path.isfile(path):
            continue
        st.divider()
        st.image(path, caption=os.path.basename(path), use_container_width=True)
        with open(path, "rb") as fh:
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            st.download_button(
                label=f"⬇ Download {os.path.basename(path)}",
                data=fh.read(),
                file_name=os.path.basename(path),
                mime=f"image/{ext}",
                key=f"dl_{_key_prefix}_i{i}",
            )


# ── Screenshot browser ────────────────────────────────────────────────────────

def _render_screenshots() -> None:
    with st.expander("📸 Screenshots", expanded=False):
        data = _read_yaml("app_settings.yaml")
        ss_raw = data.get("browser", {}).get("screenshots_dir", "./.mcp_app_logs/screenshots")
        ss_dir = Path(ss_raw)
        if not ss_dir.is_absolute():
            ss_dir = (_CONFIG_DIR / ".." / ss_raw).resolve()

        if st.button("📁 Open Folder", key="open_ss_dir", use_container_width=True):
            try:
                os.startfile(str(ss_dir))
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Could not open: {exc}")

        if ss_dir.exists():
            pngs = sorted(ss_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
            if pngs:
                for png in pngs[:12]:
                    st.image(str(png), caption=png.name, use_column_width=True)
            else:
                st.caption("No screenshots yet.")
        else:
            st.caption("Screenshots folder not found.")


# ── Settings form ─────────────────────────────────────────────────────────────

def _render_settings_form() -> None:
    data = _read_yaml("app_settings.yaml")
    _env = _read_env_llm()

    st.markdown("### 🧠 LLM")
    st.divider()
    _provider_opts = ["ollama", "openai_compat"]
    _provider_labels = {"ollama": "🖥️ Local (Ollama)", "openai_compat": "☁️ Cloud / OpenAI-compatible"}
    _cur_provider = _env.get("LLM_PROVIDER", data.get("llm_provider", "ollama"))
    new_provider = st.radio(
        "Provider",
        _provider_opts,
        index=_provider_opts.index(_cur_provider) if _cur_provider in _provider_opts else 0,
        format_func=lambda p: _provider_labels.get(p, p),
        key="s_provider",
    )

    if new_provider == "ollama":
        st.markdown("**Ollama Settings**")
        ollama = data.get("ollama", {})
        new_host = st.text_input("Ollama Host", value=_env.get("OLLAMA_HOST", ollama.get("host", "http://localhost:11434")), key="s_host")
        _available_models = _fetch_ollama_models(new_host)
        _current_model = _env.get("OLLAMA_MODEL", ollama.get("model", "qwen2.5:7b"))
        if _available_models:
            if _current_model not in _available_models:
                _available_models = [_current_model] + _available_models
            new_model = st.selectbox(
                "Model",
                _available_models,
                index=_available_models.index(_current_model),
                key="s_model",
            )
        else:
            new_model = st.text_input("Model", value=_current_model, key="s_model")
            st.caption("⚠️ Ollama unreachable — enter model name manually.")
        new_temp = st.slider("Temperature", 0.0, 1.0, float(_env.get("OLLAMA_TEMPERATURE", ollama.get("temperature", 0.2))), 0.05, key="s_temp")
        new_ctx = st.number_input("Context Window", 1024, 32768, int(_env.get("OLLAMA_NUM_CTX", ollama.get("num_ctx", 8192))), 512, key="s_ctx")
        new_ol_api_key = st.text_input(
            "API Key (Ollama Cloud only)",
            value=_env.get("OLLAMA_API_KEY", ollama.get("api_key", "")),
            type="password",
            key="s_ol_api_key",
            help="Leave blank for local Ollama. Required when host is https://ollama.com.",
        )
        # placeholders so cloud fields are skipped cleanly
        new_ol_api_key = _env.get("OLLAMA_API_KEY", data.get("ollama", {}).get("api_key", ""))
        new_base_url = _env.get("OPENAI_COMPAT_BASE_URL", data.get("openai_compat", {}).get("base_url", "https://api.openai.com/v1"))
        new_api_key = _env.get("OPENAI_COMPAT_API_KEY", data.get("openai_compat", {}).get("api_key", ""))
        new_cloud_model = _env.get("OPENAI_COMPAT_MODEL", data.get("openai_compat", {}).get("model", "gpt-4o-mini"))
        new_cloud_temp = float(_env.get("OPENAI_COMPAT_TEMPERATURE", data.get("openai_compat", {}).get("temperature", 0.2)))
    else:
        st.markdown("**Cloud / OpenAI-compatible API**")
        oc = data.get("openai_compat", {})
        new_base_url = st.text_input(
            "API Base URL",
            value=_env.get("OPENAI_COMPAT_BASE_URL", oc.get("base_url", "https://api.openai.com/v1")),
            key="s_base_url",
            help=(
                "Enter only the base URL — do NOT include /chat/completions. "
                "Examples: https://api.openai.com/v1 · https://api.groq.com/openai/v1 · "
                "https://inference.baseten.co/v1 · https://<resource>.openai.azure.com/openai"
            ),
        )
        new_api_key = st.text_input(
            "API Key",
            value=_env.get("OPENAI_COMPAT_API_KEY", oc.get("api_key", "")),
            type="password",
            key="s_api_key",
            help="Leave blank for unauthenticated or key-in-URL endpoints.",
        )
        new_cloud_model = st.text_input(
            "Model",
            value=_env.get("OPENAI_COMPAT_MODEL", oc.get("model", "gpt-4o-mini")),
            key="s_model",
            help="e.g. gpt-4o-mini, llama-3.3-70b-versatile, mistral-large-latest, MiniMaxAI/MiniMax-M2.5",
        )
        new_cloud_temp = st.slider("Temperature", 0.0, 1.0, float(_env.get("OPENAI_COMPAT_TEMPERATURE", oc.get("temperature", 0.2))), 0.05, key="s_temp")

        # ── Test Connection button ────────────────────────────────────────────
        _tc1, _tc2 = st.columns([2, 3])
        with _tc1:
            if st.button("🔌 Test Connection", key="s_test_conn", use_container_width=True):
                from mcp_app.llm.openai_compat_adapter import _normalize_base_url

                async def _run_test(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
                    from mcp_app.llm.openai_compat_adapter import OpenAICompatAdapter
                    from mcp_app.config.schema import AppSettings, OpenAICompatSettings
                    tmp = AppSettings(
                        openai_compat=OpenAICompatSettings(
                            base_url=base_url, api_key=api_key, model=model, temperature=0.0
                        ),
                        llm_provider="openai_compat",
                    )
                    adapter = OpenAICompatAdapter(tmp)
                    return await adapter.test_connection()

                _normalized = _normalize_base_url(new_base_url)
                try:
                    ok, msg = get_bridge().run(_run_test(_normalized, new_api_key, new_cloud_model))
                    st.session_state["s_conn_test"] = (ok, msg)
                except Exception as _exc:  # noqa: BLE001
                    st.session_state["s_conn_test"] = (False, f"Test error: {_exc}")
                st.rerun()
        with _tc2:
            _res = st.session_state.get("s_conn_test")
            if _res is not None:
                _ok, _msg = _res
                if _ok:
                    st.success(_msg)
                else:
                    st.error(_msg)

        # placeholders so ollama fields are skipped cleanly
        new_host = _env.get("OLLAMA_HOST", data.get("ollama", {}).get("host", "http://localhost:11434"))
        new_model = _env.get("OLLAMA_MODEL", data.get("ollama", {}).get("model", "qwen2.5:7b"))
        new_temp = float(_env.get("OLLAMA_TEMPERATURE", data.get("ollama", {}).get("temperature", 0.2)))
        new_ctx = int(_env.get("OLLAMA_NUM_CTX", data.get("ollama", {}).get("num_ctx", 8192)))

    st.markdown("### 👁️ Vision")
    st.divider()
    _vis = data.get("vision", {})
    new_vision_enabled = st.toggle(
        "Enable Vision Model",
        value=_env.get("VISION_ENABLED", str(_vis.get("enabled", False))).lower() in ("true", "1", "yes"),
        key="s_vision_enabled",
        help="When enabled, turns that include image attachments are routed to the vision model.",
    )
    if new_vision_enabled:
        _vis_opts = ["openai_compat", "ollama"]
        _vis_labels = {"openai_compat": "☁️ Cloud / OpenAI-compatible", "ollama": "🖥️ Ollama (local)"}
        _cur_vis_provider = _env.get("VISION_PROVIDER", _vis.get("provider", "openai_compat"))
        new_vision_provider = st.radio(
            "Vision Provider",
            _vis_opts,
            index=_vis_opts.index(_cur_vis_provider) if _cur_vis_provider in _vis_opts else 0,
            format_func=lambda p: _vis_labels.get(p, p),
            key="s_vision_provider",
        )
        new_vision_model = st.text_input(
            "Vision Model",
            value=_env.get("VISION_MODEL", _vis.get("model", "")),
            key="s_vision_model",
            help="e.g. gpt-4o, llava:13b, Qwen/Qwen2-VL-7B-Instruct",
        )
        if new_vision_provider == "openai_compat":
            new_vision_base_url = st.text_input(
                "Vision API Base URL",
                value=_env.get("VISION_BASE_URL", _vis.get("base_url", "https://api.openai.com/v1")),
                key="s_vision_base_url",
            )
            new_vision_api_key = st.text_input(
                "Vision API Key",
                value=_env.get("VISION_API_KEY", _vis.get("api_key", "")),
                type="password",
                key="s_vision_api_key",
            )
        else:
            new_vision_base_url = _env.get("VISION_BASE_URL", _vis.get("base_url", "https://api.openai.com/v1"))
            new_vision_api_key = _env.get("VISION_API_KEY", _vis.get("api_key", ""))
        new_vision_temp = st.slider(
            "Vision Temperature", 0.0, 1.0,
            float(_env.get("VISION_TEMPERATURE", str(_vis.get("temperature", 0.2)))),
            0.05, key="s_vision_temp",
        )
    else:
        new_vision_provider = _env.get("VISION_PROVIDER", _vis.get("provider", "openai_compat"))
        new_vision_model = _env.get("VISION_MODEL", _vis.get("model", ""))
        new_vision_base_url = _env.get("VISION_BASE_URL", _vis.get("base_url", "https://api.openai.com/v1"))
        new_vision_api_key = _env.get("VISION_API_KEY", _vis.get("api_key", ""))
        new_vision_temp = float(_env.get("VISION_TEMPERATURE", str(_vis.get("temperature", 0.2))))

    st.markdown("### 🔧 Tool Calling")
    st.divider()
    tc = data.get("tool_calling", {})
    modes = ["auto", "require_approval"]
    mode_idx = modes.index(tc.get("mode", "auto")) if tc.get("mode", "auto") in modes else 0
    new_mode = st.radio("Mode", modes, index=mode_idx, key="s_mode",
                        format_func=lambda m: "Auto" if m == "auto" else "Require Approval")

    st.markdown("### ⏱️ Timeouts & Limits (s)")
    st.divider()
    timeouts = data.get("timeouts", {})
    new_llm_t = st.number_input("LLM", 30, 600, int(timeouts.get("llm_seconds", 180)), key="s_llmt")
    new_tool_t = st.number_input("Tool", 10, 300, int(timeouts.get("tool_seconds", 120)), key="s_toolt")

    st.markdown("**Limits**")
    limits = data.get("limits", {})
    new_max_chars = st.number_input("Max Tool Output Chars", 1000, 50000,
                                    int(limits.get("max_tool_output_chars", 8000)), 500, key="s_chars")

    st.markdown("### 🌐 Browser")
    st.divider()
    browser = data.get("browser", {})
    new_headless = st.toggle("Headless", value=bool(browser.get("headless", True)), key="s_headless")
    new_ss_dir = st.text_input("Screenshots Dir",
                               value=browser.get("screenshots_dir", "./.mcp_app_logs/screenshots"),
                               key="s_ssdir")

    st.markdown("### 🎨 Theme")
    st.divider()
    ui = data.get("ui", {})
    new_font_size = st.slider("Font Size (px)", 10, 24, int(ui.get("font_size", 15)), key="s_fs")
    _font_options = ["sans-serif", "serif", "monospace", "Inter", "Roboto", "Courier New"]
    _cur_font = ui.get("font_family", "sans-serif")
    new_font_family = st.selectbox(
        "Font Family", _font_options,
        index=_font_options.index(_cur_font) if _cur_font in _font_options else 0,
        key="s_font"
    )
    new_zoom = st.slider("Zoom", 0.7, 1.5, float(ui.get("zoom", 1.0)), 0.05, key="s_zoom")
    new_theme = st.radio("Theme", ["dark", "light"],
                         index=0 if ui.get("theme", "dark") == "dark" else 1, key="s_theme")
    new_accent = st.color_picker("Accent Color", value=ui.get("accent_color", "#ff6b35"), key="s_accent")
    new_chat_width = st.number_input("Chat Max Width (px)", 400, 1400,
                                     int(ui.get("chat_max_width", 800)), 50, key="s_cw")
    new_compact = st.toggle("Compact Mode", value=bool(ui.get("compact_mode", False)), key="s_compact")
    new_timestamps = st.toggle("Show Timestamps", value=bool(ui.get("show_timestamps", False)), key="s_ts")
    new_tc_expanded = st.toggle("Tool Calls Expanded", value=bool(ui.get("tool_calls_expanded", False)), key="s_tce")

    if st.button("💾 Save & Restart", use_container_width=True, key="s_save"):
        from mcp_app.llm.openai_compat_adapter import _normalize_base_url
        _norm_url = _normalize_base_url(new_base_url)
        # Write all LLM settings to .env.llm (authoritative source)
        _write_env_llm({
            "LLM_PROVIDER": new_provider,
            "OPENAI_COMPAT_BASE_URL": _norm_url,
            "OPENAI_COMPAT_API_KEY": new_api_key,
            "OPENAI_COMPAT_MODEL": new_cloud_model,
            "OPENAI_COMPAT_TEMPERATURE": str(float(new_cloud_temp)),
            "OLLAMA_HOST": new_host,
            "OLLAMA_MODEL": new_model,
            "OLLAMA_API_KEY": new_ol_api_key,
            "OLLAMA_TEMPERATURE": str(float(new_temp)),
            "OLLAMA_NUM_CTX": str(int(new_ctx)),
            "VISION_ENABLED": str(new_vision_enabled),
            "VISION_PROVIDER": new_vision_provider,
            "VISION_MODEL": new_vision_model,
            "VISION_BASE_URL": new_vision_base_url,
            "VISION_API_KEY": new_vision_api_key,
            "VISION_TEMPERATURE": str(float(new_vision_temp)),
        })
        data["llm_provider"] = new_provider
        data["ollama"] = {"host": new_host, "model": new_model,
                          "temperature": new_temp, "num_ctx": int(new_ctx),
                          "api_key": new_ol_api_key}
        data["openai_compat"] = {
            "base_url": _norm_url,
            "api_key": new_api_key,
            "model": new_cloud_model,
            "temperature": float(new_cloud_temp),
        }
        # Clear stale test result
        st.session_state.pop("s_conn_test", None)
        data["vision"] = {
            "enabled": new_vision_enabled,
            "provider": new_vision_provider,
            "model": new_vision_model,
            "base_url": new_vision_base_url,
            "api_key": new_vision_api_key,
            "temperature": float(new_vision_temp),
        }
        data["tool_calling"] = {"mode": new_mode}
        data["timeouts"] = {"llm_seconds": int(new_llm_t), "tool_seconds": int(new_tool_t)}
        data["limits"] = {"max_tool_output_chars": int(new_max_chars)}
        data["browser"] = {"headless": new_headless, "screenshots_dir": new_ss_dir}
        data["ui"] = {
            "font_size": int(new_font_size),
            "font_family": new_font_family,
            "zoom": float(new_zoom),
            "theme": new_theme,
            "accent_color": new_accent,
            "chat_max_width": int(new_chat_width),
            "compact_mode": new_compact,
            "show_timestamps": new_timestamps,
            "tool_calls_expanded": new_tc_expanded,
        }
        _write_yaml("app_settings.yaml", data)
        _write_theme(new_theme, new_accent)
        _reset_engine()
        st.success("Saved — reload browser tab to apply theme changes.")
        st.rerun()


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _render_sidebar() -> None:
    data = _read_yaml("app_settings.yaml")
    _env = _read_env_llm()
    provider = _env.get("LLM_PROVIDER", data.get("llm_provider", "ollama"))
    if provider == "openai_compat":
        model = _env.get("OPENAI_COMPAT_MODEL", data.get("openai_compat", {}).get("model", "—")) or "—"
        provider_label = "☁️ Cloud"
    else:
        model = _env.get("OLLAMA_MODEL", data.get("ollama", {}).get("model", "—")) or "—"
        _ol_host = _env.get("OLLAMA_HOST", data.get("ollama", {}).get("host", ""))
        provider_label = "☁️ Ollama Cloud" if "ollama.com" in _ol_host else "🖥️ Ollama"

    # Show vision model indicator if vision is enabled
    _vis_enabled = _env.get("VISION_ENABLED", str(data.get("vision", {}).get("enabled", False))).lower() in ("true", "1", "yes")
    _vis_model = _env.get("VISION_MODEL", data.get("vision", {}).get("model", "")) or ""

    with st.sidebar:
        st.markdown("## 🤖 MCP App")
        st.caption(f"{provider_label} · `{model}`")
        if _vis_enabled and _vis_model:
            st.caption(f"👁️ Vision · `{_vis_model}`")

        # Warn if active engine's model doesn't match current YAML
        engine = st.session_state.get("engine")
        if engine and st.session_state.get("engine_ready"):
            engine_model = getattr(engine.session, "model", "") if hasattr(engine, "session") else ""
            if engine_model and engine_model != model:
                st.warning(
                    f"⚠️ Active engine uses `{engine_model}`. "
                    f"Settings changed — press **Save & Restart** to apply.",
                    icon=None,
                )
        st.divider()

        _render_server_status()
        st.divider()

        _render_server_management()
        _render_file_upload()
        _render_screenshots()

        with st.expander("⚙️ Settings", expanded=False):
            _render_settings_form()

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Restart", use_container_width=True, key="btn_restart"):
                _reset_engine()
                st.rerun()
        with c2:
            if st.button("🗑️ Clear", use_container_width=True, key="btn_clear"):
                engine: ChatEngine | None = st.session_state.get("engine")
                st.session_state.messages = []
                if engine:
                    engine.session.messages.clear()
                    engine.session.tool_calls.clear()
                st.rerun()


# ── Tool call block ───────────────────────────────────────────────────────────

def _render_tool_call(tc: dict[str, Any], expanded: bool = True) -> None:
    tool_name = tc.get("tool", "unknown")
    args = tc.get("args", {})
    result = tc.get("result") or ""
    error = tc.get("error")

    with st.expander(f"🔧 `{tool_name}`", expanded=expanded):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Input**")
            st.json(args, expanded=False)
        with col2:
            st.markdown("**Output**")
            if error:
                st.error(error)
            elif result:
                if len(result) > 3000:
                    st.text(result[:3000] + "\n…[truncated]")
                    with st.expander("📄 View full output"):
                        st.text(result)
                else:
                    st.text(result)
            else:
                st.caption("(no output)")


# ── Chat history ──────────────────────────────────────────────────────────────

def _render_history() -> None:
    data = _read_yaml("app_settings.yaml")
    ui = data.get("ui", {})
    show_ts = ui.get("show_timestamps", False)
    # Default to expanded; the Settings toggle (tool_calls_expanded) still overrides
    tc_expanded = ui.get("tool_calls_expanded", True)

    for msg in st.session_state.messages:
        role = msg["role"]
        content = msg["content"]
        tool_calls = msg.get("tool_calls", [])
        ts = msg.get("ts", "")

        with st.chat_message(role):
            for tc in tool_calls:
                _render_tool_call(tc, expanded=tc_expanded)
            if msg.get("is_error"):
                st.error(content)
            else:
                st.markdown(content)
                if role == "assistant":
                    _render_rich_content(content)
            footer_parts = []
            if tool_calls:
                names = list(dict.fromkeys(tc.get("tool", "?") for tc in tool_calls))
                footer_parts.append(f"Used {len(tool_calls)} tool(s): {', '.join(names)}")
            if show_ts and ts:
                footer_parts.append(ts)
            if footer_parts:
                st.caption(" · ".join(footer_parts))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="MCP App",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_logging()  # no-op after first call (cached); must come after set_page_config
    _init_state()

    data = _read_yaml("app_settings.yaml")
    _inject_css(data.get("ui", {}))

    _render_sidebar()
    _render_history()

    # ── Processing: waiting for background task ───────────────────────────────
    if st.session_state.processing:
        future = st.session_state.bg_future

        with st.chat_message("assistant"):
            if future is None or future.done():
                # Task finished (or was cancelled) — collect result
                reply = "[Stopped by user]"
                is_error = False
                tc_dicts: list[dict] = []

                if future is not None and not future.cancelled():
                    try:
                        reply_raw, used_records = future.result()
                        tc_dicts = [
                            {"tool": r.tool, "args": r.args,
                             "result": r.result or "", "error": r.error}
                            for r in used_records
                        ]
                        reply = reply_raw
                    except Exception as exc:  # noqa: BLE001
                        reply = f"[Error: {exc}]"
                        is_error = True
                        log.error("Chat error: %s", exc, exc_info=True)

                # Default to expanded; the Settings toggle still overrides
                tc_exp = data.get("ui", {}).get("tool_calls_expanded", True)
                for tc in tc_dicts:
                    _render_tool_call(tc, expanded=tc_exp)
                if is_error:
                    st.error(reply)
                else:
                    st.markdown(reply)
                    _render_rich_content(reply)
                if tc_dicts:
                    names = list(dict.fromkeys(tc["tool"] for tc in tc_dicts))
                    st.caption(f"Used {len(tc_dicts)} tool(s): {', '.join(names)}")

                import datetime
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": reply,
                    "tool_calls": tc_dicts,
                    "is_error": is_error,
                    "ts": datetime.datetime.now().strftime("%H:%M:%S"),
                })
                st.session_state.processing = False
                st.session_state.bg_future = None
                st.rerun()
            else:
                # Still running — full-width status block (replaces cramped 2-col layout)
                with st.status("⚙️ Processing…", state="running", expanded=True):
                    st.caption(
                        "Calling tools and composing a reply. Multi-step tool "
                        "chains and large outputs can take a while."
                    )
                    if st.button("⏹️ Stop", key="stop_btn", use_container_width=True):
                        get_bridge().cancel_current()
                        st.session_state.processing = False
                        st.session_state.bg_future = None
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": "[Stopped by user]",
                            "tool_calls": [],
                        })
                        st.rerun()
                time.sleep(0.4)
                st.rerun()
        return  # don't show chat input while processing

    # ── Idle: accept new input ────────────────────────────────────────────────
    if prompt := st.chat_input("Message…"):
        import datetime

        files = st.session_state.get("uploaded_files", [])
        text_files = [f for f in files if not f.get("is_image")]
        image_files = [f for f in files if f.get("is_image")]

        if text_files:
            context_block = "\n\n".join(
                f"[File: {f['name']}]\n{f['content'][:4000]}"
                for f in text_files
            )
            full_prompt = (
                "UPLOADED FILE CONTENT (read this directly — do NOT call filesystem tools to re-read these files):\n\n"
                f"{context_block}\n\n"
                "--- USER MESSAGE ---\n"
                f"{prompt}"
            )
        else:
            full_prompt = prompt

        images_b64 = [f["data_b64"] for f in image_files] if image_files else None

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        st.session_state.messages.append({"role": "user", "content": prompt, "ts": ts})
        with st.chat_message("user"):
            st.markdown(prompt)
            if image_files:
                for img in image_files:
                    st.image(
                        f"data:{img['mime']};base64,{img['data_b64']}",
                        caption=img["name"],
                        use_container_width=True,
                    )

        engine = _get_or_start_engine()
        future = get_bridge().submit(engine.send(full_prompt, images=images_b64))
        st.session_state.bg_future = future
        st.session_state.processing = True
        # Clear images so they are not re-sent with every subsequent message
        st.session_state.uploaded_files = [
            f for f in st.session_state.get("uploaded_files", [])
            if not f.get("is_image")
        ]
        st.rerun()


if __name__ == "__main__":
    main()
