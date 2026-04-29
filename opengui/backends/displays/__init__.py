"""Platform-specific virtual display implementations."""

from opengui.backends.displays.cgvirtualdisplay import (  # noqa: F401
    CGVirtualDisplayManager as CGVirtualDisplayManager,
)
from opengui.backends.displays.win32desktop import (  # noqa: F401
    Win32DesktopManager as Win32DesktopManager,
)
from opengui.backends.displays.xvfb import XvfbDisplayManager as XvfbDisplayManager  # noqa: F401
