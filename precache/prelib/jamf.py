#!/System/Library/Frameworks/Python.framework/Versions/Current/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2019 Glynn Lane (primalcurve)

import base64
import logging
import re
import sys

import internet

logger = logging.getLogger(__name__)


class JamfRequest(object):
    def __init__(self, jamf_server):
        self.jamf_server = (
            "https://{}.jamfcloud.com/"
            "JSSResource/mobiledevices".format(jamf_server))

    def mobile_ids(self, user, passwd):
        return self._jamf_request(
            user, passwd, r"<model_identifier>(.*?)</model_identifier>")

    def _jamf_request(self, user, passwd, search):
        jamf_request = urllib2.Request(self.jamf_server)
        jamf_request.add_header(
            "Authorization", "Basic {}".format(
                base64.b64encode("{}:{}".format(user, passwd))))
        try:
            jamf_response = urllib2.urlopen(jamf_request)
        except (urllib2.URLError, urllib2.HTTPError) as e:
            logger.error("Can not load models from jamf: {}".format(e))
            sys.exit(1)
        else:
            return re.findall(search, jamf_response.read())
