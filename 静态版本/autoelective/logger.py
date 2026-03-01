#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: logger.py
# modified: 2019-09-09

import os
import logging
import json
from logging import StreamHandler
from logging.handlers import TimedRotatingFileHandler
from .config import AutoElectiveConfig
from .const import ERROR_LOG_DIR
from ._internal import mkdir

config = AutoElectiveConfig()

_USER_ERROR_LOG_DIR = os.path.join(ERROR_LOG_DIR, config.get_user_subpath())
mkdir(_USER_ERROR_LOG_DIR)
_ROTATE_SNAT_STATE_FILE = os.environ.get(
    "ROTATE_SNAT_STATE_FILE",
    "/home/ubuntu/work/skj/.rotate_snat_state.prod.json",
)


class _EgressIPFilter(logging.Filter):
    """Attach current rotated egress IP to log records."""

    def __init__(self, state_file):
        super().__init__()
        self._state_file = state_file
        self._cached_ip = "-"
        self._cached_mtime = None

    def _load_ip(self):
        try:
            mtime = os.path.getmtime(self._state_file)
        except OSError:
            self._cached_ip = "-"
            self._cached_mtime = None
            return

        if self._cached_mtime == mtime:
            return

        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            self._cached_ip = str(state.get("last_eip", "-") or "-")
            self._cached_mtime = mtime
        except Exception:
            self._cached_ip = "-"
            self._cached_mtime = mtime

    def filter(self, record):
        self._load_ip()
        record.egress_ip = self._cached_ip
        return True


class BaseLogger(object):

    default_level = logging.DEBUG
    default_format = logging.Formatter("[%(levelname)s] %(name)s, %(asctime)s, %(message)s", "%H:%M:%S")

    def __init__(self, name, level=None, format=None):
        if self.__class__ is __class__:
            raise NotImplementedError
        self._name = name
        self._level = level if level is not None else self.__class__.default_level
        self._format = format if format is not None else self.__class__.default_format
        self._logger = logging.getLogger(self._name)
        self._logger.setLevel(self._level)
        self._logger.addHandler(self._get_handler())

    @property
    def handlers(self):
        return self._logger.handlers

    def _get_handler(self):
        raise NotImplementedError

    def log(self, level, msg, *args, **kwargs):
        return self._logger.log(level, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        return self._logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        return self._logger.info(msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        return self._logger.warn(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        return self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        return self._logger.error(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        kwargs.setdefault("exc_info", True)
        return self._logger.exception(msg, *args, **kwargs)

    def fatal(self, msg, *args, **kwargs):
        return self._logger.fatal(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        return self._logger.critical(msg, *args, **kwargs)


class ConsoleLogger(BaseLogger):
    """ 控制台日志输出类 """

    default_level = logging.DEBUG

    def _get_handler(self):
        handler = logging.StreamHandler()
        handler.setLevel(self._level)
        handler.setFormatter(self._format)
        return handler


class FileLogger(BaseLogger):
    """ 文件日志输出类 """

    default_level = logging.WARNING
    default_format = logging.Formatter(
        "[%(levelname)s] %(name)s, %(asctime)s, [egress_ip=%(egress_ip)s], %(message)s",
        "%H:%M:%S",
    )

    def _get_handler(self):
        file = os.path.join(_USER_ERROR_LOG_DIR, "%s.log" % self._name)
        handler = TimedRotatingFileHandler(file, when='d', interval=1, encoding="utf-8-sig")
        handler.setLevel(self._level)
        handler.setFormatter(self._format)
        handler.addFilter(_EgressIPFilter(_ROTATE_SNAT_STATE_FILE))
        return handler
