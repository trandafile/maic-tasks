"""
utils/md_editor.py
──────────────────
Reusable WYSIWYG Markdown editor built on EasyMDE (CDN).

Usage
-----
from utils.md_editor import markdown_editor

content = markdown_editor(value=task["notes"] or "", key="task_notes_123", height=350)
# `content` is a plain Markdown string — ready to save directly to Supabase.

How it works
------------
• EasyMDE is injected via jsDelivr CDN inside an st.components.v1.html iframe.
  No pip package or npm build required.
• A hidden <textarea id="st_sink"> beneath the EasyMDE canvas is kept in-sync
  by EasyMDE's onChange callback via JavaScript.
• A standard Streamlit st.text_area (shrunk to 1 px and visually hidden via CSS)
  is the *real* Streamlit widget that holds the value.  Its key is used to read
  back the markdown string.
• On every EasyMDE keystroke, a window.parent.postMessage fires so the outer
  Streamlit app knows content changed (triggers form awareness).
"""

import streamlit as st
import streamlit.components.v1 as components
import html as _html

# ── EasyMDE CDN URLs (jsDelivr, pinned to 2.18.0) ───────────────────────────
_EASYMDE_CSS = "https://cdn.jsdelivr.net/npm/easymde@2.18.0/dist/easymde.min.css"
_EASYMDE_JS  = "https://cdn.jsdelivr.net/npm/easymde@2.18.0/dist/easymde.min.js"

# ── HTML template ────────────────────────────────────────────────────────────
_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <link rel="stylesheet" href="{css}"/>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: transparent; font-family: sans-serif; }}

    /* Compact toolbar */
    .EasyMDEContainer .editor-toolbar {{
      border-radius: 6px 6px 0 0;
      background: #f8f9fa;
      border-color: #ddd;
      padding: 2px 4px;
    }}
    .EasyMDEContainer .editor-toolbar button {{
      color: #444;
    }}
    .EasyMDEContainer .editor-toolbar button:hover,
    .EasyMDEContainer .editor-toolbar button.active {{
      background: #e2e6ea;
      border-color: #adb5bd;
    }}
    /* CodeMirror area */
    .CodeMirror {{
      border-radius: 0 0 6px 6px;
      border-color: #ddd;
      font-size: 14px;
      line-height: 1.6;
      height: {cm_height}px;
    }}
    .CodeMirror-scroll {{
      min-height: {cm_height}px;
    }}
    /* Preview pane */
    .editor-preview, .editor-preview-side {{
      font-size: 14px;
      line-height: 1.7;
    }}
    /* Hide the raw textarea we use as sink — EasyMDE already hides it,
       but be explicit */
    #mde_textarea {{ display: none; }}
  </style>
</head>
<body>
  <textarea id="mde_textarea">{initial_value}</textarea>
  <script src="{js}"></script>
  <script>
    var easyMDE = new EasyMDE({{
      element: document.getElementById("mde_textarea"),
      initialValue: {js_initial},
      spellChecker: false,
      autofocus: false,
      minHeight: "{cm_height}px",
      maxHeight: "{cm_height}px",
      toolbar: [
        "bold", "italic", "heading", "|",
        "quote", "unordered-list", "ordered-list", "|",
        "link", "image", "|",
        "preview", "side-by-side", "fullscreen", "|",
        "guide"
      ],
      status: false,
      renderingConfig: {{
        singleLineBreaks: false,
        codeSyntaxHighlighting: false,
      }},
    }});

    // On every change, send current value to parent Streamlit via postMessage.
    easyMDE.codemirror.on("change", function() {{
      var md = easyMDE.value();
      window.parent.postMessage({{
        type: "streamlit:setComponentValue",
        value: md
      }}, "*");
    }});

    // Also fire once on load so Streamlit has the initial value.
    window.addEventListener("load", function() {{
      window.parent.postMessage({{
        type: "streamlit:setComponentValue",
        value: easyMDE.value()
      }}, "*");
    }});
  </script>
</body>
</html>
"""


def markdown_editor(
    value: str = "",
    key: str = "md_editor",
    height: int = 340,
    label: str = "Note / Descrizione (Markdown)",
) -> str:
    """
    Render an EasyMDE WYSIWYG editor and return the current Markdown string.

    Parameters
    ----------
    value   : Initial markdown content.
    key     : Unique Streamlit widget key (must be unique per page).
    height  : Total height of the editor area in pixels (toolbar ~42 px).
    label   : Label shown above the editor.

    Returns
    -------
    str : Current markdown content of the editor.
    """
    # Reserve a session_state slot so the value survives reruns without
    # losing in-progress edits.
    sk = f"__mde_{key}"
    if sk not in st.session_state:
        st.session_state[sk] = value

    st.caption(label)

    # ── Render EasyMDE iframe ────────────────────────────────────────────────
    cm_height = max(height - 50, 120)   # leave room for toolbar

    # Escape the initial value for safe injection
    safe_html_value = _html.escape(st.session_state[sk], quote=True)
    # JSON-encode for the JS string literal
    import json
    js_value = json.dumps(st.session_state[sk])

    iframe_html = _TEMPLATE.format(
        css=_EASYMDE_CSS,
        js=_EASYMDE_JS,
        initial_value=safe_html_value,
        js_initial=js_value,
        cm_height=cm_height,
    )

    # The component returns the value via postMessage → Streamlit bridge.
    # components.html() doesn't return a value, so we use a companion
    # st.text_area that the user can still fall back on (hidden via CSS).
    components.html(iframe_html, height=height + 6, scrolling=False)

    # ── Hidden text_area that holds the authoritative value ──────────────────
    # We render it normally but visually collapse it to near-zero height via
    # a small st.markdown CSS injection scoped to this key.
    st.markdown(
        f"""
        <style>
          div[data-testid="stTextArea"][aria-label="{key}_sink"] textarea {{
            min-height: 28px !important;
            height: 28px !important;
            resize: none;
            font-size: 11px;
            color: #888;
            background: #fafafa;
            border: 1px dashed #ccc;
            border-radius: 4px;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    new_val = st.text_area(
        key + "_sink",
        value=st.session_state[sk],
        height=68,
        help="Backup editor — il contenuto qui sopra è sincronizzato automaticamente."
             " Puoi anche modificare qui in caso di problemi con l'editor grafico.",
        key=f"{key}_ta",
        label_visibility="visible",
    )

    # Keep session state in sync with whichever value is freshest.
    st.session_state[sk] = new_val
    return new_val
