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
• On every EasyMDE keystroke the iframe JS finds the hidden companion
  st.text_area (the "sink") in the parent page and updates it via React's
  native value setter + input event dispatch.  This makes Streamlit register
  the change so the correct value is read when Save is clicked.
• The sink textarea is visually hidden via CSS (display:none) — only EasyMDE
  is visible to the user.
"""

import streamlit as st
import streamlit.components.v1 as components
import html as _html
import json

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
    .editor-preview h1, .editor-preview-side h1 {{
      font-size: 1.08em;
      font-weight: 700;
      line-height: 1.35;
      margin: 0.65rem 0 0 0;
    }}
    .editor-preview h2, .editor-preview-side h2 {{
      font-size: 1em;
      font-weight: 700;
      line-height: 1.35;
      margin: 0.6rem 0 0 0;
    }}
    .editor-preview h3, .editor-preview-side h3 {{
      font-size: 1em;
      font-weight: 500;
      line-height: 1.35;
      text-decoration: underline;
      text-underline-offset: 2px;
      margin: 0.55rem 0 0 0;
    }}
    .editor-preview h1 + p,
    .editor-preview h2 + p,
    .editor-preview h3 + p,
    .editor-preview-side h1 + p,
    .editor-preview-side h2 + p,
    .editor-preview-side h3 + p {{
      margin-top: 0;
    }}
    /* Hide EasyMDE's internal raw textarea */
    #mde_textarea {{ display: none; }}
  </style>
</head>
<body>
  <textarea id="mde_textarea">{initial_value}</textarea>
  <script src="{js}"></script>
  <script>
    // Label (aria-label) of the companion Streamlit sink textarea in the parent page.
    var SINK_LABEL = {sink_label_json};

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

    /**
     * Push the current EasyMDE value into the Streamlit sink textarea so that
     * Streamlit registers the change and reads the correct value on Save.
     *
     * Works by:
     *  1. Locating the sink <textarea aria-label=SINK_LABEL> in the parent page.
     *  2. Using React's native HTMLTextAreaElement value setter so that React's
     *     controlled-component machinery picks up the change.
     *  3. Dispatching a bubbling "input" event to trigger React's onChange.
     */
    function syncToParent(md) {{
      try {{
        var parentDoc = window.parent.document;
        var sinkTA = parentDoc.querySelector('textarea[aria-label="' + SINK_LABEL + '"]');
        if (sinkTA) {{
          var setter = Object.getOwnPropertyDescriptor(
            window.parent.HTMLTextAreaElement.prototype, 'value'
          ).set;
          setter.call(sinkTA, md);
          sinkTA.dispatchEvent(new window.parent.Event('input', {{bubbles: true}}));
          return true;
        }}
      }} catch(e) {{}}
      return false;
    }}

    // Sync on every EasyMDE keystroke.
    easyMDE.codemirror.on("change", function() {{
      syncToParent(easyMDE.value());
    }});

    // Sync on load — retry until the sink textarea appears in the parent DOM
    // (it may render slightly after the iframe).
    window.addEventListener("load", function() {{
      var attempts = 0;
      function trySync() {{
        if (!syncToParent(easyMDE.value()) && attempts < 10) {{
          attempts++;
          setTimeout(trySync, 200);
        }}
      }}
      setTimeout(trySync, 100);
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
    # Reserve a session_state slot so the value survives reruns.
    sk = f"__mde_{key}"
    if sk not in st.session_state:
        st.session_state[sk] = value

    st.caption(label)

    # ── Render EasyMDE iframe ────────────────────────────────────────────────
    cm_height = max(height - 50, 120)

    safe_html_value = _html.escape(st.session_state[sk], quote=True)
    js_value = json.dumps(st.session_state[sk])
    sink_label = key + "_sink"
    sink_label_json = json.dumps(sink_label)

    iframe_html = _TEMPLATE.format(
        css=_EASYMDE_CSS,
        js=_EASYMDE_JS,
        initial_value=safe_html_value,
        js_initial=js_value,
        cm_height=cm_height,
        sink_label_json=sink_label_json,
    )

    components.html(iframe_html, height=height + 6, scrolling=False)

    # ── CSS: completely hide the sink textarea container ─────────────────────
    # The :has() pseudo-class is supported in all modern browsers (Chrome 105+,
    # Firefox 121+, Safari 15.4+) and targets the stTextArea wrapper div.
    st.markdown(
        f"""
        <style>
          div[data-testid="stTextArea"]:has(textarea[aria-label="{sink_label}"]) {{
            display: none !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Hidden sink text_area — authoritative Streamlit value holder ─────────
    # Visually hidden by the CSS above; EasyMDE syncs to it via JS.
    new_val = st.text_area(
        sink_label,
        value=st.session_state[sk],
        height=68,
        key=f"{key}_ta",
        label_visibility="collapsed",
    )

    st.session_state[sk] = new_val
    return new_val
