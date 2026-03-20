"""Platform-specific virtual display implementations."""

from opengui.backends.displays.cgvirtualdisplay import (  # noqa: F401
    CGVirtualDisplayManager as CGVirtualDisplayManager,
)
from opengui.backends.displays.xvfb import XvfbDisplayManager as XvfbDisplayManager  # noqa: F401
