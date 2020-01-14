#!/System/Library/Frameworks/Python.framework/Versions/Current/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2019 Glynn Lane (primalcurve)

import sys
sys.path = [p for p in sys.path if p[1:6] != "Users" and p[1:8] != "Library"]
# Make sure sys.path includes the necessary paths to import the various
# modules needed for this script.
PYTHON_FRAMEWORK = (
    "/System/Library/Frameworks/Python.framework/Versions/2.7/")
PYTHON_FRAMEWORK_PATHS = [
    PYTHON_FRAMEWORK + "lib/python27.zip",
    PYTHON_FRAMEWORK + "lib/python2.7",
    PYTHON_FRAMEWORK + "lib/python2.7/plat-darwin",
    PYTHON_FRAMEWORK + "lib/python2.7/plat-mac",
    PYTHON_FRAMEWORK + "lib/python2.7/plat-mac/lib-scriptpackages",
    PYTHON_FRAMEWORK + "lib/python2.7/lib-tk",
    PYTHON_FRAMEWORK + "lib/python2.7/lib-old",
    PYTHON_FRAMEWORK + "lib/python2.7/lib-dynload",
    PYTHON_FRAMEWORK + "Extras/lib/python",
    PYTHON_FRAMEWORK + "Extras/lib/python/PyObjC"
]
for path in PYTHON_FRAMEWORK_PATHS:
    if path not in sys.path:
        sys.path.append(path)

import logging
import gzip
import os
import plistlib
from xml.parsers.expat import ExpatError

logger = logging.getLogger(__name__)


DEFAULT_SUCATALOGS = {
    "17": "https://swscan.apple.com/content/catalogs/others/"
          "index-10.13-10.12-10.11-10.10-10.9"
          "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog",
    "18": "https://swscan.apple.com/content/catalogs/others/"
          "index-10.14-10.13-10.12-10.11-10.10-10.9"
          "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog",
    "19": "https://swscan.apple.com/content/catalogs/others/"
          "index-10.15-10.14-10.13-10.12-10.11-10.10-10.9"
          "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog",
}


class ReplicationError(Exception):
    """A custom error when replication fails"""
    pass


class SoftwareCatalog(object):
    """Object that encapsulates the definition of the software catalog
    """
    def __init__(self):
        self.workdir = self.arguments.workdir
        # Prepping instance variables.
        self.os_installers = {}

    def start_parsing(self):
        self.get_catalog_url()
        logger.debug("su_catalog_url: " + self.su_catalog_url)
        self.download_sucatalog()
        logger.debug("local_path: " + self.local_path)
        self.parse_sucatalog()
        logger.debug("catalog: " + str(self.catalog))
        self.find_mac_os_installers()
        logger.debug("os_installers: products: " + str(self.os_installers))
        self.os_installer_product_info()
        logger.debug("os_installers: product info: " + str(self.os_installers))
        self.remove_incompatible()
        self.remove_old_products()

    def get_catalog_url(self):
        if self.arguments.catalogurl:
            self.su_catalog_url = self.arguments.catalogurl
        else:
            self.su_catalog_url = get_default_catalog()
        if not self.su_catalog_url:
            logger.error("Could not find a default catalog url " +
                         "for this OS version.")
            sys.exit(1)

    def download_sucatalog(self):
        """Downloads the softwareupdate catalog"""
        try:
            self.local_path = replicate_url(self.su_catalog_url,
                                            root_dir=self.workdir)
        except ReplicationError as err:
            logger.error("Could not replicate %s: %s" %
                         (self.su_catalog_url, err))

    def parse_sucatalog(self):
        if os.path.splitext(self.local_path)[1] == ".gz":
            with gzip.open(self.local_path) as the_file:
                content = the_file.read()
                try:
                    self.catalog = plistlib.readPlistFromString(content)
                except ExpatError as err:
                    logger.error("Error reading %s: %s" %
                                 (self.local_path, err))
        else:
            try:
                self.catalog = plistlib.readPlist(self.local_path)
            except (OSError, IOError, ExpatError) as err:
                logger.error("Error reading %s: %s" %
                             (self.local_path, err))

    def find_mac_os_installers(self):
        """Creates a list of product identifiers for what appear to be macOS
        installers"""
        self.os_installers = {
            prod[1]: {} for prod in search_dict(
                self.catalog, "com.apple.mpkg.OSInstall")}

    def os_installer_product_info(self):
        """Creates a dict of info about products that look like macOS
        installers"""
        for p_key, p_dict in self.os_installers.iteritems():
            p_dict.update(parse_server_metadata(
                self.get_server_metadata(p_key)))
            p_dict.update(self.catalog["Products"][p_key])
            dist_url = (
                p_dict.get("Distributions", {}).get("English") or
                p_dict.get("Distributions", {}).get("en"))
            try:
                p_dict["DistributionPath"] = replicate_url(
                    dist_url, root_dir=self.workdir)
            except ReplicationError as err:
                logger.error("Could not replicate %s: %s" %
                           (dist_url, err))
            p_dict.update(parse_dist(p_dict.get("DistributionPath")))

    def get_server_metadata(self, product_key):
        """Replicate ServerMetaData"""
        try:
            url = self.catalog["Products"][product_key]["ServerMetadataURL"]
            try:
                return replicate_url(url, root_dir=self.workdir)
            except ReplicationError as err:
                logger.error("Could not replicate %s: %s" % (url, err))
                return None
        except KeyError:
            logger.error("Malformed catalog.")
            return None

    def remove_incompatible(self):
        for p_key in self.os_installers.keys():
            p_dict = self.os_installers[p_key]
            if p_dict.get("nonSupportedModels"):
                # Remove any incompatible installer.
                if (self.this_mac.machine_model in
                   p_dict.get("nonSupportedModels")):
                    logger.debug(
                        "%s is not compatible with this installer." %
                        self.this_mac.machine_model)
                    del self.os_installers[p_key]
                    continue
                logger.debug(
                    "%s is not listed as incompatible with this installer. "
                    "Therefore it IS compatible." %
                    self.this_mac.machine_model)

    def remove_old_products(self):
        # Get a list of floats for all version numbers after removing the
        # leading "10." i.e.
        # >>> "10.15.6".split(".", 1)[1]
        # '15.6'
        # >>> float('15.6')
        # 15.6
        # >>> float("10.15.6".split(".", 1)[1])
        # 15.6
        all_versions = list(set(
            [float((v.get("version") or v.get("VERSION")).split(".", 1)[1])
             for v in self.os_installers.itervalues()]))
        for p_key in self.os_installers.keys():
            p_dict = self.os_installers[p_key]
            # Convert the current version number to a float as above.
            c_v = float((p_dict.get("version") or p_dict.get("VERSION")
                              ).split(".", 1)[1])
            # Get a list of floats for just the current version.
            # If we convert both values to an integer, they will match as the
            # integer version of say 14.6 is 14 rather than 15 as round()
            # Then get the max value of that list, and compare it to the
            # current version. If it's less than the max, we discard it. See:
            # >>> int(15.6), int(15.2)
            # (15, 15)
            # >>> int(15.6) == int(15.2)
            # True
            # >>> [v for v in [15.6, 15.2, 14.6] if int(v) == int(15.1)]
            # [15.6, 15.2]
            # >>> max([v for v in [15.6, 15.2, 14.6] if int(v) == int(15.1)])
            # 15.6
            # >>> 15.1 < max([v for v in [15.6, 15.2, 14.6]
            #                 if int(v) == int(15.1)])
            # True
            if c_v < max([v for v in all_versions if int(v) == int(c_v)]):
                logger.debug("Removing old product: " + p_key)
                del self.os_installers[p_key]
                continue


def parse_server_metadata(filename):
    """Parses a softwareupdate server metadata file, looking for
    information of interest.
    Returns a dictionary containing title, version, and description."""
    title = ""
    vers = ""
    try:
        md_plist = plistlib.readPlist(filename)
    except (OSError, IOError, ExpatError) as err:
        logger.error("Error reading " + filename + str(err))
        return {}
    vers = md_plist.get("CFBundleShortVersionString", "")
    localization = md_plist.get("localization", {})
    preferred_localization = (localization.get("English") or
                              localization.get("en"))
    if preferred_localization:
        title = preferred_localization.get("title", "")

    metadata = {}
    metadata["title"] = title
    metadata["version"] = vers
    return metadata


def get_default_catalog():
    """Returns the default softwareupdate catalog for the current OS"""
    darwin_major = os.uname()[2].split(".")[0]
    logger.debug("Major macOS Version: " + darwin_major)
    return DEFAULT_SUCATALOGS.get(darwin_major)
