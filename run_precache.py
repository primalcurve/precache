#!/System/Library/Frameworks/Python.framework/Versions/Current/bin/python
# -*- coding: utf-8 -*-
"""
precache.py is a tool that can be used to cache various OTA updates for
iOS/tvOS/watchOS devices, as well as Mac App Store apps, macOS Installers, and
various macOS related software updates.

For more information: https://github.com/krypted/precache
For usage: ./precache.py --help

Issues: Please log an issue via github, or fork and create a pull request with
your fix.
"""

import argparse
import base64
import sys
from precache import precache


class SaneUsageFormat(argparse.HelpFormatter):
    """
    Matt Wilkie on SO
    http://stackoverflow.com/questions/9642692/
    argparse-help-without-duplicate-allcaps/9643162#9643162
    """
    def _format_action_invocation(self, action):
        if not action.option_strings:
            default = self._get_default_metavar_for_positional(action)
            metavar, = self._metavar_formatter(action, default)(1)
            return metavar

        else:
            parts = []

            # if the Optional doesn't take a value, format is:
            #    -s, --long
            if action.nargs == 0:
                parts.extend(action.option_strings)

            # if the Optional takes a value, format is:
            #    -s ARGS, --long ARGS
            else:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                for option_string in action.option_strings:
                    parts.append(option_string)

                return "%s %s" % (", ".join(parts), args_string)

            return ", ".join(parts)

    def _get_default_metavar_for_optional(self, action):
        return action.dest.upper()


def main():
    parser = argparse.ArgumentParser(formatter_class=SaneUsageFormat)

    asset_groups = ["AppleTV", "iPad", "iPhone", "iPod",
                    "Watch", "app", "installer", "updates"]
    ipsw_groups = ["AppleTV", "iPad", "iPhone", "iPod", "Watch"]

    asset_groups.sort()
    ipsw_groups.sort()

    parser.add_argument("--cache-group",
                        type=str,
                        nargs="+",
                        dest="cache_group",
                        choices=(asset_groups),
                        metavar="<product name>",
                        help="Cache assets based on group",
                        required=False)

    parser.add_argument("--cache-ipsw-group",
                        type=str,
                        nargs="+",
                        dest="cache_ipsw_group",
                        choices=(ipsw_groups),
                        metavar="<product name>",
                        help="Cache IPSW based on group",
                        required=False)

    parser.add_argument("-cs", "--cache-server",
                        type=str,
                        nargs=1,
                        dest="cache_server",
                        metavar="http://cacheserver:port",
                        help="Specify the cache server to use.",
                        required=False)

    parser.add_argument("--debug",
                        action="store_true",
                        dest="debug",
                        help="Debug mode - increased log verbosity.",
                        required=False)

    parser.add_argument("-n", "--dry-run",
                        action="store_true",
                        dest="dry_run",
                        help="Shows what would be cached.",
                        required=False)

    parser.add_argument("--filter-group",
                        type=str,
                        nargs="+",
                        dest="filter_group",
                        choices=(asset_groups),
                        metavar="<product name>",
                        help="Filter based on group",
                        required=False)

    parser.add_argument("-i", "--ipsw",
                        type=str,
                        nargs="+",
                        dest="ipsw_model",
                        metavar="model",
                        help="Cache IPSW for provided model/s.",
                        required=False)

    parser.add_argument("-l", "--list",
                        action="store_true",
                        dest="list_models",
                        help="Lists all assets available for caching.",
                        required=False)

    parser.add_argument("-m", "--model",
                        type=str,
                        nargs="+",
                        dest="model",
                        metavar="model",
                        help="Provide model(s)/app(s), i.e iPhone8,2 Xcode.",
                        required=False)

    parser.add_argument("--jamfserver",
                        type=str,
                        dest="jamfserver",
                        help="Jamf server address",
                        required=False)

    parser.add_argument("--jamfuser",
                        type=str,
                        dest="jamfuser",
                        help="Jamf server username",
                        required=False)

    parser.add_argument("--jamfpassword",
                        type=str,
                        dest="jamfpassword",
                        help="Jamf server password",
                        required=False)

    parser.add_argument("-o", "--output",
                        type=str,
                        nargs=1,
                        dest="output_dir",
                        metavar="file path",
                        help="Path to save IPSW files to.",
                        required=False)

    parser.add_argument("--version",
                        action="store_true",
                        dest="ver",
                        help="Version info.",
                        required=False)

    args = parser.parse_args()

    # While argsparse is pretty cool, it does have limits when it comes to
    # handling having items mutually exclusive against a specifc argument so
    # here this explicitly checks if args.list_models is being called and if so
    # tests if it's being passed or not.
    if len(sys.argv) > 1:
        if args.ver:
            precache.print_version()
            sys.exit(0)

        if args.list_models and (args.model or args.ipsw_model or args.ver or
                                 args.cache_group or args.cache_ipsw_group or
                                 (args.jamfserver and args.jamfuser and
                                  args.jamfpassword)):
            print("Cannot combine these arguments with -l, precache.--list.")
            sys.exit(1)
        else:
            if args.debug:
                level = "debug"
            else:
                level = "info"

            if args.dry_run:
                dry = True
            else:
                dry = False

            if args.output_dir:
                download_dir = args.output_dir[0]
            else:
                download_dir = None

            if args.cache_server:
                cache_srv = args.cache_server[0]
                p = precache.PreCache(
                    cache_server=cache_srv, log_level=level, dry_run=dry)
            else:
                p = precache.PreCache(
                    cache_server=None, log_level=level, dry_run=dry)

            if args.list_models:
                if args.filter_group:
                    p.list_assets(group=args.filter_group)
                else:
                    p.list_assets()

            if args.jamfserver and args.jamfuser and args.jamfpassword:
                from precache import jamf
                models = jamf.JamfRequest(args.jamfserver).mobile_ids(
                    args.jamfuser, args.jamfpassword)
                if models:
                    p.cache_assets(model=models)
                else:
                    logger.error("Empty models list from jamf")

            if args.model:
                p.cache_assets(model=args.model)

            if args.cache_group:
                p.cache_assets(group=args.cache_group)

            if args.cache_ipsw_group:
                p.cache_ipsw(group=args.cache_ipsw_group,
                             store_in=download_dir)

            if args.ipsw_model:
                p.cache_ipsw(model=args.ipsw_model, store_in=download_dir)
    else:
        print("%s --help for usage" % sys.argv[0])


if __name__ == "__main__":
    main()
