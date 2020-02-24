#!/System/Library/Frameworks/Python.framework/Versions/Current/bin/python
# -*- coding: utf-8 -*-
'''
precache.py is a tool that can be used to cache various OTA updates for
iOS/tvOS/watchOS devices, as well as Mac App Store apps, macOS Installers, and
various macOS related software updates.

For more information: https://github.com/krypted/precache
For usage: ./precache.py --help

Issues: Please log an issue via github, or fork and create a pull request with
your fix.
'''
 

# So we can use print as a function in list comprehensions
from __future__ import print_function

import argparse
import collections
import hashlib
import logging
import logging.handlers
import os
import plistlib
import re
import socket
import subprocess
import sys
import urllib2
import base64

from operator import attrgetter
from itertools import groupby
from random import uniform
from time import sleep
from urlparse import urlparse

from Foundation import NSBundle
from WebKit import WKWebView
import pprint

# Version
version = '1.1.2'


def print_version():
    print('precache.py version %s' % (version))


class PreCache(object):
    '''
    Contains a number of default settings and other such configuration
    information. By default, this initialises in a dry run so that testing can
    be done without wasting too much time/bandwidth.
    There are some known issues - it seems there may be a limit to the number
    of requests that either the Caching Server or Apple servers will tolerate
    from a single source, so from time to time, the Caching Server or Apple
    sends back a HTTP 503 response when attempting to retrieve assets.
    To try and mitigate this, user agent strings are set as best as possible to
    match what Apple software sends out, and a random sleep period between 1
    and 5 seconds is used for each download request.

    Logs are stored in '/tmp/precache.log'. Beta items are not cached by
    default. This can be changed, but the results haven't been tested.

    There is no argument to download all the files, as this exceeds 600GB of
    content (all the OTA updates alone are ~560GB as at 2016-10-26). If you
    wish to download many things, then use the special flags that are designed
    to cache particular groups of assets (i.e. --cache-group updates).

    At the moment, there isn't a satisfactory way to avoid downloading and
    parsing the software updates feed, this adds additional time to processing.
    '''
    def __init__(self, cache_server=None, cache_beta=False, dry_run=True,
                 log_level='info', ver=version):

        # Handle logging
        self.log = logging.getLogger('precache')
        self.log_level = log_level
        log_path = '/tmp/precache.log'

        # Handle log levels
        if 'info' in self.log_level:
            self.log.setLevel(logging.INFO)

        if 'debug' in self.log_level:
            self.log.setLevel(logging.DEBUG)

        self.rh = logging.handlers.TimedRotatingFileHandler(
            log_path, when='midnight', backupCount=7
        )
        self.log.addHandler(self.rh)
        self.fh = logging.FileHandler(log_path)
        self.formatter = logging.Formatter("%(asctime)s - %(funcName)s() - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")  # NOQA
        self.fh.setFormatter(self.formatter)
        self.log.addHandler(self.fh)

        self.cache_beta = cache_beta

        # Set up the rest of the variables and what not
        self.dry_run = dry_run
        self.version = ver
        self.cache_config_path = '/Library/Server/Caching/Config/Config.plist'  # NOQA
        self.mesu_url = 'http://mesu.apple.com/assets'
        self.mobile_asset_path = 'com_apple_MobileAsset_SoftwareUpdate'
        self.mobile_update_xml = 'com_apple_MobileAsset_SoftwareUpdate.xml'
        self.osx_catalog_xml = 'https://swscan.apple.com/content/catalogs/others/index-10.14-10.13-10.12-10.11-10.10-10.9-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'  # NOQA

        self.ios_update_feeds = {
            'watch': '%s/watch/%s/%s' % (self.mesu_url,
                                         self.mobile_asset_path,
                                         self.mobile_update_xml),
            'tv': '%s/tv/%s/%s' % (self.mesu_url,
                                   self.mobile_asset_path,
                                   self.mobile_update_xml),
            'ios': '%s/%s/%s' % (self.mesu_url,
                                 self.mobile_asset_path,
                                 self.mobile_update_xml),
        }

        self.mas_base_url = 'http://osxapps.itunes.apple.com'

        # Remote plist feed of MAS apps that can be cached
        self.mas_plist = urllib2.urlopen('https://raw.githubusercontent.com/primalcurve/precache/master/com.github.krypted.precache.apps-list.plist')  # NOQA
        self.mas_plist = self.mas_plist.read()

        self.mas_assets = plistlib.readPlistFromString(self.mas_plist)

        # User agent strings
        self.user_agents = {
            'app': 'MacAppStore/' + self.app_store_version() + ' (Macintosh; OS X ' + self.sw_vers_version() + '; ' + self.sw_vers_build() + ') AppleWebKit/' + self.webkit_version(),
            'updates': 'Software%20Update (unknown version) CFNetwork/' + self.cf_network_version() + ' Darwin/' + self.kernel_version() + ' (x86_64)',  # NOQA
            'installer': 'MacAppStore/' + self.app_store_version() + ' (Macintosh; OS X ' + self.sw_vers_version() + '; ' + self.sw_vers_build() + ') AppleWebKit/' + self.webkit_version(),  # NOQA
            'ipsw': 'com.apple.appstored iOS/12.1.4',
            'Watch': 'com.apple.appstored',
            'AppleTV': 'com.apple.appstored',
            'iPad': 'com.apple.appstored',
            'iPhone': 'com.apple.appstored',
            'iPod': 'com.apple.appstored',
        }

        # pprint.pprint(self.user_agents)

        # Detect cache server at init
        if cache_server:
            self.cache_server = cache_server
        else:
            self.find_cache_server()

        # Test the server is real
        s = socket.socket()
        address = urlparse(self.cache_server).netloc.split(':')[0]
        port = int(urlparse(self.cache_server).netloc.split(':')[1])

        try:
            s.connect((address, port))
        except Exception as e:
            print('%s - Check %s is a valid address' % (e,
                                                        self.cache_server))
            sys.exit(1)

        # Named tuple for asset creation to drop into self.assets_master
        self.Asset = collections.namedtuple('Asset', ['model',
                                                      'version',
                                                      'url',
                                                      'group'])

        # iOS and App Store Master asset list
        self.assets_master = []

        # IPSW master asset list
        self.ipsw_assets_master = []

        # IPSW models master list
        self.ipsw_models_master = []

        # Build assets
        self.build_asset_master_list()

    # Graceful exit
    def gext(self):
        if KeyboardInterrupt or SystemExit:
            print('')
            sys.exit(1)

    def sw_vers_version(self):
        return subprocess.check_output(["sw_vers", "-productVersion"]).strip()

    def sw_vers_build(self):
        return subprocess.check_output(["sw_vers", "-buildVersion"]).strip()

    def app_store_version(self):
        return plistlib.readPlist(
            "/Applications/App Store.app/Contents/Info.plist"
        ).get("CFBundleShortVersionString").strip()

    def webkit_version(self):
        return NSBundle.bundleForClass_(WKWebView).infoDictionary().get("CFBundleVersion").strip()

    def kernel_version(self):
        return subprocess.check_output(["sysctl", "kern.osrelease"]).split()[1].strip()

    def cf_network_version(self):
        return NSBundle.bundleWithIdentifier_("com.apple.CFNetwork").infoDictionary().get("CFBundleVersion").strip()

    # Find where the cache server is
    def find_cache_server(self):
        fallback_srv = 'http://localhost:49672'
        try:
            cmd = '/usr/bin/AssetCacheLocatorUtil'
            # self.log.info('Trying %s' % (cmd))
            subprocess.Popen([cmd],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except:
            self.log.debug('%s not on this system' % (cmd))
            pass

        if os.path.exists(self.cache_config_path):
            try:
                self.cache_srv_conf = plistlib.readPlist(
                    self.cache_config_path
                )
                port = self.cache_srv_conf['Port']
                self.cache_server = 'http://localhost:%s' % (port)
                self.log.debug(
                    'Local machine appears to be a Caching Server'
                )
            except:
                self.cache_server = fallback_srv
                self.log.debug(
                    'Fallback Caching Server %s' % (self.cache_server)
                )
        else:
            try:
                self.disk_cache, self.error = subprocess.Popen(
                    ['/usr/bin/getconf DARWIN_USER_CACHE_DIR'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=True).communicate()
                self.disk_cache = self.disk_cache.strip('\n')
                self.disk_cache = os.path.join(
                    self.disk_cache,
                    'com.apple.AssetCacheLocatorService/diskCache.plist'
                )
                self.log.debug(
                    'Using configuration from %s' % (self.disk_cache)
                )
                plist = plistlib.readPlist(self.disk_cache)
                self.cache_server = (
                    plist['cache'][0]['servers'][0]['localAddressAndPort']
                )
                self.cache_server = 'http://%s' % (self.cache_server)
            except:
                self.cache_server = fallback_srv
                self.log.debug(
                    'Fallback Caching Server %s' % (self.cache_server)
                )

    # Wrapper around urllib2 request that does some error checking
    def url_request(self, url, user_agent=None):
        try:
            if not user_agent:
                ua_string = 'precache/%s' % (self.version)
            else:
                ua_string = user_agent

            self.log.debug('User agent: %s' % (ua_string))
            request = urllib2.Request(url)
            request.add_unredirected_header('User-Agent', ua_string)
            req = urllib2.urlopen(request)
        except (urllib2.URLError, urllib2.HTTPError) as e:
            self.log.debug('%s %s' % (e, url))
            pass
        else:
            self.log.debug('Opened connection to %s' % (url))
            return req

    # Convert the URL to a format useable with the cache server
    def convert_url(self, url):
        try:
            asset_url = urlparse(url)
            asset_url = '%s%s?source=%s' % (self.cache_server,
                                            asset_url.path,
                                            asset_url.netloc)
            self.log.debug('Converted URL to %s' % (asset_url))

            return asset_url
        except:
            raise

    # Check the file extension is one we want to cache
    def extension_check(self, asset):
        if '.zip' or '.ipsw' or '.zip' or '.pkg' in asset.url:
            self.log.debug('Extension ok')
            return True
        else:
            self.log.debug('Extension bad')
            return False

    # Process the iOS XML feeds for asset information
    def process_ios_feed(self, feed):
        '''
        Processes the XML feeds that iOS/Watch/TV devices use for OTA updates.
        Note: There are a number of iOS 10 releases that start with 9.9 (i.e.
        9.9.10.1) - these are deliberately not added as a cacheable asset, this
        cuts down on the significant number of data downloaded for each asset.
        '''
        def cacheable(item):
            if item.get('__CanUseLocalCacheServer'):
                if item['__CanUseLocalCacheServer']:
                    return True
            else:
                return False

        def is_beta(item):
            if item.get('ReleaseType'):
                if 'Beta' in item['ReleaseType']:
                    return True
            else:
                return False

        def supported_device(item):
            if item.get('SupportedDevices'):
                return item['SupportedDevices'][0]

        def get_asset_url(item):
            if item.get('RealUpdateAttributes'):
                return item['RealUpdateAttributes']['RealUpdateURL']
            else:
                return '%s%s' % (item['__BaseURL'], item['__RelativePath'])

        def get_asset_version(item):
            if item.get('OSVersion'):
                return item['OSVersion']

        def is_watch(item):
            if 'Watch' in item:
                return True
            else:
                return False

        def group_type(item):
            if 'Watch' in item:
                return 'Watch'
            elif 'TV' in item:
                return 'AppleTV'
            elif 'iPad' in item:
                return 'iPad'
            elif 'iPhone' in item:
                return 'iPhone'
            elif 'iPod' in item:
                return 'iPod'

        try:
            self.log.info('Starting process work on %s' % (feed))
            req = self.url_request(feed)
            xml = plistlib.readPlistFromString(req.read())

            for item in xml['Assets']:
                if not is_beta(item):
                    if supported_device(item):
                        model = supported_device(item)

                    if get_asset_url(item):
                        url = get_asset_url(item)

                    if get_asset_version(item):
                        os_ver = get_asset_version(item)

                    group = group_type(model)

                    if len(os_ver.split('.')) < 4:
                        if is_watch(model):
                            self.add_asset(model, os_ver, url, group)
                        else:
                            if cacheable(item):
                                self.add_asset(model, os_ver, url, group)

            [self.ipsw_models_master.append(item.model) for item in
             self.assets_master if item.model not in self.ipsw_models_master]

            req.close()
        except Exception as e:
            self.log.debug('%s - %s' % (e, feed))
            pass

    # Build MAS assets
    def build_mas_assets(self):
        try:
            for item in self.mas_assets:
                model = item
                version = self.mas_assets[item]['version']
                url = self.mas_assets[item]['url']
                group = self.mas_assets[item]['type']
                self.add_asset(model, version, url, group)
        except Exception as e:
            self.log.debug('%s' % (e))

    # Build Software updates assets
    def build_su_assets(self):
        group_type = 'updates'

        def get_version(pkg, remote_version, local_version):
            if '.' in remote_version:
                remote_version = tuple(map(int, remote_version.split('.')))
                local_version = tuple(map(int, local_version.split('.')))
                if remote_version >= local_version:
                    return True
                else:
                    return False

        def beta_preview(pkg):
            seed_keywords = ['TechPreview', 'ForSeed',
                             'Beta', 'TechPreview']
            for keyword in seed_keywords:
                if keyword in pkg:
                    return True

        cacheable_updates = {
            'macOSUpd': '10.12.0',
            'OSXUpd': '10.11.6',
        }
        xml_req = self.url_request(self.osx_catalog_xml)
        updates = plistlib.readPlistFromString(xml_req.read())
        products = updates['Products']

        for item in products:
            packages = updates['Products'][item]['Packages']
            for pkg in packages:
                # pprint.pprint(pkg)
                pkg_url = pkg['URL']
                # pprint.pprint(pkg_url)
                base_url = os.path.splitext(pkg_url)[0]
                # pprint.pprint(base_url)
                smd_url = '%s.smd' % base_url
                # pprint.pprint(smd_url)
                basename = os.path.basename(os.path.splitext(pkg_url)[0])
                # pprint.pprint(basename)
                for upd in cacheable_updates:
                    if upd in basename and not beta_preview(basename):
                        req = self.url_request(smd_url)
                        if req:
                            smd_info = plistlib.readPlistFromString(
                                req.read()
                            )
                            version = (
                                smd_info['CFBundleShortVersionString']
                            )
                            if re.search('[a-zA-Z]', version):
                                version = (
                                    re.findall(r'[\d.]+', basename)
                                )
                            req.close()
                        else:
                            version = re.findall(r'[\d.]+', basename)

                        try:
                            if version.endswith('.'):
                                version = version[:-1]
                        except:
                            pass

                        try:
                            if (
                                get_version(upd, version,
                                            cacheable_updates[upd])
                            ):
                                if 'macOSUpd' in basename:
                                    firmware_name = (
                                        '%s-Firmware' % basename
                                    )
                                    firmware_url = (
                                        os.path.join(
                                            base_url.replace(basename, ''),
                                            'FirmwareUpdate.pkg'
                                        )
                                    )
                                    req = self.url_request(firmware_url)

                                    full_bundle_name = (
                                        '%s-FullBundle' % basename
                                    )
                                    full_bundle_url = (
                                        os.path.join(
                                            base_url.replace(basename, ''),
                                            'FullBundleUpdate.pkg'
                                        )
                                    )
                                    req = self.url_request(firmware_url)
                                    if req:
                                        self.add_asset(firmware_name,
                                                       version,
                                                       firmware_url,
                                                       group_type)
                                        req.close()

                                    req = self.url_request(full_bundle_url)
                                    if req:
                                        self.add_asset(full_bundle_name,
                                                       version,
                                                       full_bundle_url,
                                                       group_type)
                                        req.close()

                                    self.add_asset(basename, version, pkg_url,
                                                   group_type)
                                else:
                                    self.add_asset(basename, version,
                                                   pkg_url, group_type)
                        except:
                            pass
        xml_req.close()

    # Build the asset master list:
    def build_asset_master_list(self):
        try:
            print('precache version %s' % (self.version))
            print('Caching Server: %s' % (self.cache_server))
            print('Processing feeds. This may take a few moments.')
            [self.process_ios_feed(self.ios_update_feeds[feed])
             for feed in self.ios_update_feeds]

            self.build_mas_assets()
            self.build_su_assets()
        except Exception as e:
            raise
            self.log.debug('%s' % (e))

    # IPSW info is pulled from IPSW.me
    def parse_ipsw(self, model=None):
        try:
            url = 'https://api.ipsw.me/v2.1/%s/latest/url' % (model)
            req = self.url_request(url)
            url = req.read()
            req.close()

            version = 'https://api.ipsw.me/v2.1/%s/latest/version' % (model)
            req = self.url_request(version)
            version = req.read()
            req.close()

            self.add_asset(model, version, url, 'ipsw')
        except Exception as e:
            self.log.debug('%s' % (e))

    # List assets that are cacheable
    def list_assets(self, group=None):
        try:
            display_order = ['AppleTV',
                             'iPad',
                             'iPhone',
                             'iPod',
                             'Watch',
                             'app',
                             'installer',
                             'updates']

            def keyfunc(s):
                return [int(''.join(g)) if k else ''.join(g) for k, g in
                        groupby(s, str.isdigit)]

            ListGroup = collections.namedtuple('ListGroup', ['model',
                                                             'group'])
            assets_list = []
            for item in self.assets_master:
                asset_info = ListGroup(
                    model=item.model,
                    group=item.group
                )
                if asset_info not in assets_list:
                    assets_list.append(asset_info)

            assets_list.sort()
            sorted(assets_list, key=attrgetter('model'))

            if group:
                for g in group:
                    [print('%s' % (item.model))
                     for item in assets_list
                     if g in item.group]
            else:
                for x in display_order:
                    print('Group: %s' % (x))
                    [print('  %s' % (m.model))
                     for m in assets_list
                     if x in m.group]
        except Exception as e:
            self.log.debug('%s' % (e))

    # Expand path
    def expand_path(self, path):
        try:
            path = os.path.expanduser(path)
        except:
            try:
                path = os.path.expandvar(path)
            except:
                path = path
        return path

    # Add the asset to the assets_master list
    def add_asset(self, asset_model, asset_version, asset_url, asset_group):
        try:
            asset_url = self.convert_url(asset_url)
            asset = self.Asset(
                model=asset_model,
                version=asset_version,
                url=asset_url,
                group=asset_group
            )

            if asset_group != 'ipsw':
                if asset not in self.assets_master:
                    self.assets_master.append(asset)
                    self.log.debug('Added %s %s' % (asset.model, asset.url))
                else:
                    self.log.debug('Skipped %s %s' % (asset.model, asset.url))

                if asset_group not in ['Watch', 'installer', 'app', 'updates']:
                    if asset_model not in self.ipsw_models_master:
                        self.ipsw_models_master.append(asset.model)

            if asset_group == 'ipsw':
                if asset not in self.ipsw_assets_master:
                    self.ipsw_assets_master.append(asset)

        except Exception as e:
            self.log.debug('Error adding %s - %s' % (asset.model, e))
            pass

    # Calculate sha1sum of a file
    def gen_sha1sum(self, file_in):
        try:
            # Large files, so use a block size!
            blocksize = 65536
            hasher = hashlib.sha1()
            file_in = self.expand_path(file_in)
            with open(file_in, 'rb') as f:
                buf = f.read(blocksize)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = f.read(blocksize)
            hex_digest = hasher.hexdigest()
            return hex_digest
        except:
            return False

    # Compare sha1sums
    def compare_sha1sum(self, local_sum, remote_sum):
        if local_sum == remote_sum:
            return True
        else:
            return False

    def rand_sleep(self):
        pause = uniform(1, 5)
        self.log.info('Sleeping for %s to avoid hammering servers' % (pause))
        sleep(pause)

    # Makes file sizes human friendly
    def convert_size(self, file_size, precision=2):
        try:
            suffixes = ['B', 'KB', 'MB', 'GB', 'TB']
            suffix_index = 0
            while file_size > 1024 and suffix_index < 4:
                suffix_index += 1
                file_size = file_size/1024.0

            return '%.*f%s' % (precision, file_size, suffixes[suffix_index])
        except Exception as e:
            self.log.debug('%e' % (e))

    # Progress output helper
    def progress_output(self, asset, percent, human_fs):
        try:
            model_stats = 'Caching: %s (%s)' % (asset.model, asset.version)
            progress = '[%0.2f%% of %s]' % (percent, human_fs)
            sys.stdout.write("\r%s %s" % (model_stats, progress))
            sys.stdout.flush()
        except Exception as e:
            self.log.debug('%s' % (e))

    # Wrapper to handle with downloading IPSW files
    def cache_ipsw(self, model=None, group=None, store_in=None):  # NOQA
        folder = self.expand_path(store_in) if store_in else '/tmp/precache'  # NOQA
        try:
            # Clean up in case --cache-ipsw-group is called with --ipsw
            self.ipsw_assets_master = []

            if model:
                for m in model:
                    self.parse_ipsw(m)
                    # Sleep a random interval to avoid hammering the API
                    self.rand_sleep()

            if group:
                for g in group:
                    [self.parse_ipsw(x)
                     for x in self.ipsw_models_master
                     if g in x]
                    # Sleep a random interval to avoid hammering the API
                    self.rand_sleep()

            [self.download(asset, keep_file=True, store_in=folder)
             for asset in
             self.ipsw_assets_master]

        except Exception as e:
            self.log.debug('%s' % (e))
            raise

    # Cache assets
    def cache_assets(self, model=None, group=None):
        try:
            if model:
                self.log.info(
                    'Beginning precache run for models: %s' % (
                        ', '.join(model)
                    )
                )
                for m in model:
                    [self.download(item) for item in self.assets_master
                     if m == item.model]

            if group:
                self.log.info(
                    'Beginning precache run for group: %s' % (
                        ', '.join(group)
                    )
                )
                for g in group:
                    [self.download(item)
                     for item in self.assets_master
                     if item.group in g]

        except Exception as e:
            raise
            self.log.debug('%s' % (e))

    # Download the asset
    def download(self, asset, keep_file=False, store_in=None):
        lf = os.path.basename(asset.url)
        lf = lf.split('?')[0]

        if keep_file:
            folder = store_in
            lf = os.path.join(folder, lf)
            self.log.info('Saving file to: %s' % (lf))

            if not self.dry_run:
                if not os.path.isdir(store_in):
                    os.mkdir(folder)
                    self.log.debug('Created folder %s' % (folder))
        else:
            lf = os.path.join(os.devnull, lf)

        try:
            f = open(lf, 'wb')
        except:
            pass

        if not self.dry_run:
            try:
                if self.extension_check(asset):
                    if asset.group:
                        ua = self.user_agents[asset.group]
                    else:
                        ua = 'precache/%s' % (self.version)

                    req = self.url_request(asset.url, user_agent=ua)

                    try:
                        req_header = req.info().getheader('Content-Type')
                    except AttributeError:
                        req_header = None

                    if req_header is not None:
                        try:
                            self.log.debug(
                                ' Fetch attempt: %s' % (asset.url)
                            )
                            ts = req.info().getheader('Content-Length').strip()
                            human_fs = self.convert_size(float(ts))
                            header = True
                        except AttributeError:
                            header = False
                            human_fs = 0

                        if header:
                            ts = int(ts)
                            bytes_so_far = 0
                            self.log.info(
                                'Downloading %s (%s) %s' % (asset.model,
                                                            asset.version,
                                                            asset.url)
                            )

                        while True:
                            buffer = req.read(8192)
                            if not buffer:
                                print('')
                                break

                            bytes_so_far += len(buffer)

                            if keep_file:
                                f.write(buffer)

                            if not header:
                                ts = bytes_so_far

                            percent = float(bytes_so_far) / ts
                            percent = round(percent*100, 2)

                            self.progress_output(asset, percent, human_fs)
                        req.close()
                        self.log.info('Cached %s (%s) %s' % (asset.model,
                                                             asset.version,
                                                             asset.url))
                    else:
                        try:
                            req.close()
                        except AttributeError:
                            pass
                        print(
                            'Skipped: %s (%s) - in cache' % (
                                asset.model, asset.version
                                )
                             )
                        self.log.info(
                            'Skipped: %s (%s) - in cache' % (
                                asset.model, asset.version
                            )
                        )
            except (urllib2.URLError, urllib2.HTTPError) as e:
                req.close()
                print('%s' % (e))
                print('Check Caching Server is correct')
                self.log.info('%s - %s' % (e, asset.url))
                pass

            # Sleep for a random interval
            self.rand_sleep()
        else:
            print('DRY RUN: Caching %s (%s) %s' % (
                asset.model, asset.version, asset.url
                )
            )
            self.log.info('DRY RUN: Caching %s (%s) %s' % (
                asset.model, asset.version, asset.url
                )
            )
