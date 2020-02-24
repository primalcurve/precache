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
import os
import socket
import ssl
import urlparse
import urllib2
from precache.prelib import macintosh

__all__ = [
    "Location", "Internet", "Network"
    ]

logger = logging.getLogger(__name__)

URL_TIMEOUT = 5
socket.setdefaulttimeout(float(URL_TIMEOUT))


class Location(object):
    _url_attribs = (
        "scheme", "username", "password", "hostname", "port",
        "path", "params", "query", "fragment"
    )

    __slots__ = (
        "_parts", "_url", "netloc", "_is_network", "is_network"
    ) + _url_attribs

    def __new__(cls, *args, **kwargs):
        cls = WindowsLocation if os.name == "nt" else PosixLocation
        if len(args) == 1:
            self = cls._from_url(args[0], init=False)
        else:
            self = cls._from_parts(*args, init=False)
        self._init()
        return self

    @classmethod
    def _from_url(cls, url, init=True):
        self = object.__new__(cls)
        self._url = self._parse_url(url)
        self._parts = self._parse_parts(self._url)
        for attr in cls._url_attribs:
            setattr(self, attr, getattr(self._url, attr))
        if init:
            self._init()
        return self

    @classmethod
    def _from_parts(cls, scheme, user, passwd, host, port, path, query, fragm):
        self = object.__new__(cls)
        self._url = self._parse_url(self._format_url(
            scheme, user, passwd, host, port, path, query, fragm))
        return self

    @classmethod
    def _parse_url(cls, url):
        if url[:1] == """\\\\""":
            url = "smb://{}".format(url.split("\\", 1)[1].replace("\\", "/"))
        return urlparse.urlparse(url)

    @classmethod
    def _parse_parts(cls, url):
        return [getattr(url, a) for a in cls._url_attribs
                if a != "netloc" and a[0] != "_"]

    @classmethod
    def _format_url(cls, scheme, user, passwd, host, port, path, query, fragm):
        return (
            scheme + "://" +
            (user if user else "") +
            (":" + passwd if passwd else "") +
            ("@" if user else "") +
            (host + ":" + str(port) if port else host) +
            path +
            ("?" + query if query else "") +
            ("#" + fragm if fragm else ""))

    def _init(self):
        pass

    def _repr(self, flavour):
        return "<{}({})>".format(
            flavour,
            ", ".join(
                ["{}=\"{}\"".format(s, getattr(self._url, s))
                 for s in Location._url_attribs
                 if getattr(self._url, s) and s[0] != "_"]))

    def __str__(self):
        return self._url.geturl()

    def __reduce__(self):
        return (self.__class__, tuple(
            [getattr(self, s) for s in self.__slots__]))

    @property
    def is_network(self):
        if self._url.scheme.lower() in ["smb", "cifs", "nfs", "afs"]:
            self._is_network = True
        else:
            self._is_network = False
        return self._is_network

    @property
    def is_internet(self):
        return not self.is_network

    def join_parsed_url(self, *args):
        return "".join(args)

    def new_host(self, host):
        return self._from_parts(
            self.scheme, self.username, self.password, host,
            self.port, self.path, self.query, self.fragment)


class WindowsLocation(Location):
    __slots__ = ()

    def __repr__(self):
        return self._repr("WindowsLocation")

    def network_path(self):
        if self._url.scheme.lower() == "smb":
            return ("""\\\\{}\\{}""".format(
                self._url.hostnmae.upper(), self._url.path.replace("/", "\\")))


class PosixLocation(Location):
    __slots__ = ()

    def __repr__(self):
        return self._repr("PosixLocation")


class Request(object):
    def __init__(self, url, proxy=None, headers=None):
        self.url = Location(url)
        self.add_proxy(proxy=proxy)
        self.add_headers(headers=headers)

    def __repr__(self):
        return ("Request:(url={0!s}, )".format(self.url))

    def __str__(self):
        return urlparse.urlunsplit(self.url.scheme,
                                   self.url.netloc,
                                   self.url.path,
                                   self.url.query,
                                   self.url.fragment)

    def add_proxy(self, proxy=None):
        if not self.proxy and proxy:
            if check_proxy(proxy):
                self.proxy = proxy

    def add_headers(self, headers=None):
        if headers:
            for k, v in headers:
                self.headers.update({k: v})

    def _build_opener(self):
        https_context = urllib2.HTTPSHandler(
            context=ssl.SSLContext(ssl.PROTOCOL_TLS))
        opener = urllib2.build_opener(https_context)
        if self.proxy and check_proxy(self.proxy):
            logger.debug("Adding proxy support via: " + self.proxy)
            proxy_support = urllib2.ProxyHandler(
                {"http": self.proxy, "https": self.proxy})
            opener.add_handler(proxy_support)
        return opener

    def _request(self, url, headers=None):
        logger.debug("Request: URL: {}".format(url))
        request = urllib2.Request(url)
        if headers:
            logger.debug("Adding headers: " + str(headers))
            request.add_header(headers)
        logger.debug("URLOpen: Request: %s :: Timeout: %d" %
                     (str(request), URL_TIMEOUT))
        return request

    def _user_agent(self, agent):
        return {"User-agent": agent}

    def user_agent(self):
        return self._user_agent("Macintosh")

    def app_store_agent(self):
        return self._user_agent(macintosh.SysInfo().app_store_agent())

    def basic_auth(self, url, user, passwd):
        ba_request = self._request(url, headers=(
            "Authorization",
            "Basic {}".format(base64.b64encode("{}:{}".format(user, passwd)))
            ))
        ba_opener = self._build_opener()
        try:
            ba_response = ba_opener.open(ba_request, timeout=URL_TIMEOUT)
        except (urllib2.URLError, urllib2.HTTPError) as e:
            return False
        else:
            return ba_response


class NetworkRequest(urllib2.HTTPSHandler):
    def __init__(self, *args, **kwargs):
        super(NetworkRequest, self).__init__(*args, **kwargs)


def check_proxy(proxy):
    # Verify that proxy server is reachable.
    if not proxy:
        return False
    try:
        p_host, p_port = proxy.split(":")
    except ValueError:
        logger.error("No proxy port supplied. Using port 8080")
        p_host = proxy
        p_port = 8080
    logger.debug("Proxy: {}:{:.0f}".format(p_host, p_port))
    try:
        # Attempt to connect to the host/port
        host = socket.gethostbyname(p_host)
        s = socket.create_connection((host, p_port), 2)
        return True
    except:
        # If not reachable, return False
        return False


def _recreate_urlpath(url, root_dir):
    """Replicate directory structure of a url"""
    split_url = urlparse.urlsplit(url)
    local_path = os.path.join(
        root_dir, os.path.normpath(split_url.path.lstrip("/")))
    if not os.path.exists(os.path.dirname(local_path)):
        os.makedirs(os.path.dirname(local_path), 0o777)
    return split_url, local_path


def replicate_url(url, root_dir="/tmp", caching_server=None, chunk_size=8196):
    """Downloads a URL and stores it in the same relative path on our
    filesystem. Returns a path to the replicated file."""
    split_url, local_path = _recreate_urlpath(url, root_dir)
    if not isinstance(url, Request):
        url = Request(url)

    logger.debug("Downloading %s..." % url)
    with open(local_path, "wb") as f:`
        headers = {"user-agent": macintosh.SysInfo().app_store_agent()}
        https_context = urllib2.HTTPSHandler(
            context=ssl.SSLContext(ssl.PROTOCOL_TLS))
        opener = urllib2.build_opener(https_context)
        # Attempt the download. If 404 or other error is found, try again
        # with the backup_url (which may still fail). The most cromulent
        # usage of this will be if the caching server lacks the files.
        try:
            logger.debug("URLRequest: URL: {0!s} :: Headers: {1!s}"
                         .format(url, headers))
            request = urllib2.Request(full_url, headers=headers)
            if PROXY_SERVER:
                logger.debug("Adding proxy support via: " + PROXY_SERVER)
                proxy_support = urllib2.ProxyHandler(
                    {"http": PROXY_SERVER, "https": PROXY_SERVER})
                opener.add_handler(proxy_support)
            logger.debug("URLOpen: Request: %s :: Timeout: %d" %
                         (str(request), URL_TIMEOUT))
            response = opener.open(request, timeout=URL_TIMEOUT)
            if total is None:  # no content length header
                f.write(response.content)
            else:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)

        except (urllib2.HTTPError, urllib2.URLError, socket.timeout):
            logger.error("Unable to connect to host: " + split_url.netloc)

    return local_path
