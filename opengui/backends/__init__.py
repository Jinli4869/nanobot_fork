"""opengui.backends — Device backend implementations.

Import individual backends explicitly to avoid pulling platform-specific
dependencies for users who only need a subset::

    from opengui.backends.adb import AdbBackend
    from opengui.backends.dry_run import DryRunBackend
"""
