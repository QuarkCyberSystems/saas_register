"""Patch: drop any stale Workspace Sidebar for the Saas Register module so the
auto-generator can rebuild it cleanly on next desk load.

Why: v4 renamed three workspaces (removed em-dash) and dropped the originals.
If a previous install had saved a Workspace Sidebar with items pointing at the
old names, the frontend crashes at sidebar_item.js:36 with
"Cannot read properties of undefined (reading 'public')".

See `saas_register/sidebar_cleanup.py` for the why / how.
"""

from __future__ import annotations

from saas_register.saas_register.sidebar_cleanup import cleanup_stale_sidebar


def execute():
	cleanup_stale_sidebar()
