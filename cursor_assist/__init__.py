"""Color-Based Cursor Assist -- an accessibility tool.

Captures the screen, detects colored shapes/outlines, and gently pulls the
mouse cursor toward a selected target so a user with limited hand movement can
interact with on-screen art more easily.
"""

# Single source of truth for the version. The PyInstaller spec parses this
# file to name the built exe, so a release is stamped by editing it here only.
__version__ = "1.0.9"
