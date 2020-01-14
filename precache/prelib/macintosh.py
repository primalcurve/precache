#!/System/Library/Frameworks/Python.framework/Versions/Current/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2019 Glynn Lane (primalcurve)


import logging
import plistlib
import subprocess
from AppKit import NSBundle
from SystemConfiguration import (
    SCDynamicStoreCopyLocalHostName,
    SCDynamicStoreCopyComputerName)
from WebKit import WKWebView


logger = logging.getLogger(__name__)


class SysInfo(object):
    """Object that encapsulates information about this computer.
    """
    def __init__(self):
        self.sp_hardware = None
        self.user_agent = None

    def hardware_info(self):
        if self.sp_hardware:
            return self.sp_hardware
        return self._hardware_info()

    def _hardware_info(self):
        self._sp_hardware = subprocess.check_output(
            ["/usr/sbin/system_profiler", "SPHardwareDataType", "-xml"])
        self.sp_hardware = plistlib.readPlistFromString(self._sp_hardware)[0]
        _items = [i for i in self.sp_hardware.get("_items")
                  if "serial_number" in i.keys()][0]
        for key, value in _items.iteritems():
            if key[0] != "_":
                self.__dict__[key] = value

    def _network(self):
        self.computer_name = SCDynamicStoreCopyComputerName(None, None)[0]
        self.local_hostname = SCDynamicStoreCopyLocalHostName(None)

    def app_store_agent(self):
        if self.user_agent:
            return self.user_agent
        return self._app_store_agent()

    def _app_store_agent(self):
        self.user_agent = ('MacAppStore/' + self._app_store_version() +
                           ' (Macintosh; OS X ' + self._sw_vers_version() +
                           '; ' + self._sw_vers_build() + ') AppleWebKit/' +
                           self._webkit_version())
        return self.user_agent

    def _app_store_version(self):
        return plistlib.readPlist(
            "/Applications/App Store.app/Contents/Info.plist"
        ).get("CFBundleShortVersionString").strip()

    def _sw_vers_version(self):
        return subprocess.check_output(
            ["sw_vers", "-productVersion"]).strip()

    def _sw_vers_build(self):
        return subprocess.check_output(
            ["sw_vers", "-buildVersion"]).strip()

    def _webkit_version(self):
        return NSBundle.bundleForClass_(
            WKWebView).infoDictionary().get("CFBundleVersion").strip()

    def _kernel_version(self):
        return subprocess.check_output(
            ["sysctl", "kern.osrelease"]).split()[1].strip()
