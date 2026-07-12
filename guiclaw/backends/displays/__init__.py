"""Platform-specific virtual display implementations."""

from guiclaw.backends.displays.cgvirtualdisplay import (  # noqa: F401
    CGVirtualDisplayManager as CGVirtualDisplayManager,
)
from guiclaw.backends.displays.win32desktop import (  # noqa: F401
    Win32DesktopManager as Win32DesktopManager,
)
from guiclaw.backends.displays.xvfb import XvfbDisplayManager as XvfbDisplayManager  # noqa: F401
