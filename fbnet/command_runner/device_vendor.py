#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import pkg_resources

from .base_service import ServiceObj
from .command_session import SSHCommandSession
from .import utils


class VendorConfig:

    def __init__(self, defaults):
        self._cfg = {}
        self._defaults = defaults

    def __getattr__(self, attr):
        return self._cfg.get(attr) or self._defaults.get(attr)

    def update(self, cfg):
        for prop, val in cfg.items():
            self._cfg[prop] = utils.canonicalize(val)


class DeviceVendor(ServiceObj):

    _DEFAULTS = {
        "cli_setup": [b"term len 0", b"term width 511"],
        "prompt_regex": [b"[\w.]+[>#$]"],
        "cmd_timeout_sec": 30,
        "clear_command": b"\x15",
        "session_type": b"ssh"
    }

    _PROMPTS_RE = re.compile(
        b"|".join([b"(%s)" % p for p in _DEFAULTS["prompt_regex"]]), re.M)

    _SESSION_TYPES = {
        b"ssh": SSHCommandSession,
    }

    def __init__(self, vendor_name, app):
        super().__init__(app, "DeviceVendor")
        self._vendor_name = vendor_name
        self._config = VendorConfig(self._DEFAULTS)
        self._prompt_re = self._PROMPTS_RE

    def __repr__(self):
        props = {
            "cli_setup": self._config.cli_setup,
            "prompt_regex": self._config.prompt_regex,
            "cmd_timeout_sec": self._config.cmd_timeout_sec
        }
        return "DeviceVendor(%s) %s" % (self._name, props)

    @classmethod
    def register_counters(cls, counters):
        for session_type in cls._SESSION_TYPES.values():
            session_type.register_counters(counters)

    def get_prompt_re(self, trailer=None):
        """
        Get prompt regex for the device. Optionally a trailer can be specified.
        This is extra text expected after the prompt. Mostly useful for
        interactive command. E.g. when we get a list of completion, the intial
        command is inserted after the prompt
        """
        if not trailer:
            return self._prompt_re
        return self._get_prompt_re(trailer)

    @property
    def vendor_name(self):
        return self._vendor_name

    @property
    def cmd_timeout_sec(self):
        return self._config.cmd_timeout_sec

    @property
    def clear_command(self):
        return self._config.clear_command

    @property
    def cli_setup(self):
        return self._config.cli_setup

    @property
    def session_type(self):
        return self._SESSION_TYPES[self._config.session_type]

    def update_config(self, vendor_config):
        self._config.update(vendor_config)
        self._update_prompts_re()

    def set_user_prompts(self, prompts):
        self._config.update({'user_prompts': prompts})
        self._update_prompts_re()

    def _update_prompts_re(self):
        self._prompt_re = self._get_prompt_re()

    def _get_prompt_re(self, trailer=None):
        prompts = self._config.prompt_regex

        if self._config.shell_prompts:
            prompts += self._config.shell_prompts

        return self._build_prompt_re(prompts, trailer)

    @classmethod
    def _build_prompt_re(cls, prompts, trailer=None):
        all_prompts = (b"(%s)" % prompt for prompt in prompts)
        trailer = trailer or b""
        # the prompt must be at the start of the line.
        # Also since we are sending one command at a time, it must also be the
        # last text in the text. Although still not perfect, this greatly
        # reduces the probability of this matching some random text in the
        # output. Not that we are matching at end of the text, not at the end of
        # each line in text (re.M is not specified)
        return re.compile(b"(?<=\n)\r*(?P<prompt>" + b"|".join(all_prompts) +
                          b")\s*" + trailer + b"$")


class DeviceVendors(ServiceObj):

    DEVICE_VENDORS = 'device_vendors.json'

    def __init__(self, app, name=None):
        super().__init__(app, name)

        self._vendors = {}

    @classmethod
    def register_counters(cls, stats_mgr):
        DeviceVendor.register_counters(stats_mgr)

    def get(self, name):
        return self._vendors.get(name) or self._createVendor(name)

    def _update_user_prompts(self, path, cfg):
        if cfg is not None:
            for vendor, prompts in cfg['prompt_regexs'].items():
                self.get(vendor).set_user_prompts(prompts)

    def _update_device_vendors(self, path, cfg):
        # now load the vendor information
        for name, props in cfg["vendor_config"].items():
            vendor = self.get(name)
            vendor.update_config(props)

    def load_vendors(self, path, json_str):
        cfg = json.loads(json_str)
        return self._update_device_vendors(path, cfg)

    def load_local_json_file(self, vendors_file):
        try:
            # first try if vendors file has been overridden
            jsonb = pkg_resources.resource_string(self.__module__, vendors_file)
        except Exception:
            # Fallback to package vendor file
            jsonb = pkg_resources.resource_string(__name__, vendors_file)

        return self.load_vendors(vendors_file, jsonb.decode('utf-8'))

    def _createVendor(self, name):
        vendor = DeviceVendor(name, self.app)

        self._vendors[name] = vendor
        return vendor