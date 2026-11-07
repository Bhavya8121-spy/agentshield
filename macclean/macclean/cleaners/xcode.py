from __future__ import annotations

from typing import List

from ..models import CleanableItem, Safety
from .base import Cleaner


class XcodeCleaner(Cleaner):
    name = "xcode"

    def scan(self) -> List[CleanableItem]:
        dev = self.home / "Library" / "Developer"
        candidates = [
            self.dir_item(
                dev / "Xcode" / "DerivedData",
                "Xcode DerivedData",
                Safety.SAFE,
                contents_only=True,
                note="Rebuilt automatically on the next build",
            ),
            self.dir_item(
                dev / "Xcode" / "iOS DeviceSupport",
                "Xcode iOS DeviceSupport",
                Safety.REVIEW,
                contents_only=True,
                note="Re-downloaded when you reconnect a device",
            ),
            self.dir_item(
                dev / "Xcode" / "Archives",
                "Xcode Archives",
                Safety.REVIEW,
                report_only=True,
                note="May be needed to symbolicate crashes or re-submit builds",
            ),
            self.dir_item(
                dev / "CoreSimulator" / "Devices",
                "iOS simulators",
                Safety.REVIEW,
                report_only=True,
                note="Prune safely with: xcrun simctl delete unavailable",
            ),
        ]
        return [item for item in candidates if item is not None]
