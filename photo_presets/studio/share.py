"""Sharing a picture the Mac way: AirDrop (to your iPhone), Messages, Mail.

Run on its own (python -m photo_presets.studio.share airdrop <file>): the Mac's
share window needs an app of its own, so the server starts this for each share
and it quits when the share is done or cancelled.
"""

from __future__ import annotations

import sys

def main() -> int:
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSSharingService)
    from Foundation import NSURL, NSObject
    from PyObjCTools import AppHelper

    service, files = sys.argv[1], sys.argv[2:]
    names = {"airdrop": "NSSharingServiceNameSendViaAirDrop", "messages": "NSSharingServiceNameComposeMessage",
             "mail": "NSSharingServiceNameComposeEmail"}
    import AppKit
    name = getattr(AppKit, names[service])
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    share = NSSharingService.sharingServiceNamed_(name)
    items = [NSURL.fileURLWithPath_(f) for f in files]
    if share is None or not share.canPerformWithItems_(items):
        print("cannot share with", service)
        return 1

    class Done(NSObject):
        def sharingService_didShareItems_(self, _s, _items):
            AppHelper.stopEventLoop()

        def sharingService_didFailToShareItems_error_(self, _s, _items, _err):
            AppHelper.stopEventLoop()

    done = Done.alloc().init()
    share.setDelegate_(done)
    app.activateIgnoringOtherApps_(True)
    share.performWithItems_(items)
    AppHelper.callLater(600, AppHelper.stopEventLoop)  # never left hanging
    AppHelper.runEventLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
